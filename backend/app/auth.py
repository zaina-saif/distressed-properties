"""Sign-in and plan checks for the API.

Users sign in with Supabase Auth in the browser and send the session's access
token as "Authorization: Bearer <token>". The token is verified against the
project's published signing keys (JWKS), so the API holds no Supabase secret.
Each user has a user_accounts row with a role, a plan and the plan's coverage:

  free     one county (coverage_state + coverage_county)
  starter  one state (coverage_state)
  pro      every state
  developer role: every state and the developer-only endpoints, whatever the plan
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from app.database.session import engine

ACTIVE_STATUSES = {"active", "trialing"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Access:
    user_id: str
    email: str
    role: str = "user"
    plan: str = "none"
    plan_status: str = "inactive"
    coverage_state: str | None = None
    coverage_county: str | None = None

    @property
    def is_developer(self) -> bool:
        return self.role == "developer"

    @property
    def has_plan(self) -> bool:
        if self.is_developer:
            return True
        if self.plan == "free":
            return self.plan_status == "active" and bool(self.coverage_state and self.coverage_county)
        if self.plan == "starter":
            return self.plan_status in ACTIVE_STATUSES and bool(self.coverage_state)
        return self.plan == "pro" and self.plan_status in ACTIVE_STATUSES

    @property
    def scope_state(self) -> str | None:
        """The one state this user may see, or None for every state."""
        if self.is_developer or self.plan == "pro":
            return None
        return (self.coverage_state or "").upper() or None

    @property
    def scope_county(self) -> str | None:
        """The one county this user may see, or None for every county in scope."""
        return self.coverage_county if self.plan == "free" and not self.is_developer else None

    def covers(self, state: str | None, county: str | None) -> bool:
        if self.scope_state and (state or "").upper() != self.scope_state:
            return False
        if self.scope_county and (county or "").lower() != self.scope_county.lower():
            return False
        return True


def supabase_url() -> str:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise HTTPException(status_code=503, detail="Sign-in is not configured on this server (SUPABASE_URL).")
    return url


@lru_cache(maxsize=1)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Your session is invalid or has expired. Sign in again.",
                         headers={"WWW-Authenticate": "Bearer"})


def _verify_locally(token: str, url: str) -> dict:
    key = _jwks_client(url).get_signing_key_from_jwt(token)
    return jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated", issuer=f"{url}/auth/v1")


# Tokens confirmed by the Auth server, kept until shortly before they expire.
_confirmed: dict[str, tuple[float, dict]] = {}


def _verify_with_auth_server(token: str, url: str) -> dict:
    """Ask Supabase Auth who the token belongs to. Used for tokens not signed with a
    published key (projects still signing with the legacy shared secret)."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    cached = _confirmed.get(digest)
    if cached and cached[0] > time.time():
        return cached[1]
    apikey = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not apikey:
        logger.warning("Token is not signed with a published key and SUPABASE_ANON_KEY is not set")
        raise _unauthorized()
    response = httpx.get(f"{url}/auth/v1/user", headers={"apikey": apikey, "Authorization": f"Bearer {token}"}, timeout=10)
    if response.status_code != 200:
        logger.warning("Auth server rejected a token: HTTP %s", response.status_code)
        raise _unauthorized()
    user = response.json()
    claims = {"sub": user["id"], "email": user.get("email") or ""}
    expires = jwt.decode(token, options={"verify_signature": False}).get("exp") or time.time() + 60
    if len(_confirmed) > 5000:
        _confirmed.clear()
    _confirmed[digest] = (min(expires, time.time() + 300), claims)
    return claims


def verify_token(token: str) -> dict:
    url = supabase_url()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc
    if header.get("alg") in ("ES256", "RS256"):
        try:
            return _verify_locally(token, url)
        except jwt.ExpiredSignatureError as exc:
            raise _unauthorized() from exc
        except jwt.PyJWTError as exc:
            logger.warning("Local token check failed (%s: %s); asking the Auth server", type(exc).__name__, exc)
    else:
        logger.debug("Token signed with %s; asking the Auth server", header.get("alg"))
    return _verify_with_auth_server(token, url)


def load_account(user_id: str, email: str) -> Access:
    """The user's account, created on first sign-in with no plan."""
    with engine.begin() as connection:
        row = connection.execute(text("""
            INSERT INTO user_accounts (user_id, email) VALUES (:user_id, :email)
            ON CONFLICT (user_id) DO UPDATE SET email = EXCLUDED.email
            RETURNING user_id::text, email, role, plan, plan_status, coverage_state, coverage_county
        """), {"user_id": user_id, "email": email}).mappings().one()
    return Access(**row)


def current_user(request: Request) -> Access:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    claims = verify_token(token.strip())
    return load_account(claims["sub"], claims.get("email") or "")


def require_access(access: Access = Depends(current_user)) -> Access:
    """A signed-in user with an active plan (or a developer)."""
    if not access.has_plan:
        raise HTTPException(status_code=402, detail="Choose a plan to see sale data.")
    return access


def require_developer(access: Access = Depends(current_user)) -> Access:
    if not access.is_developer:
        raise HTTPException(status_code=403, detail="Developer access is required.")
    return access


def assert_covers(access: Access, state: str | None, county: str | None) -> None:
    if not access.covers(state, county):
        raise HTTPException(status_code=403, detail="This property is outside your plan's coverage.")


def property_scope(property_id: str) -> tuple[str | None, str | None]:
    with engine.connect() as connection:
        row = connection.execute(text("SELECT state, county FROM properties WHERE id::text = :id"),
                                 {"id": property_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return row[0], row[1]


def require_property_access(property_id: str, access: Access = Depends(require_access)) -> Access:
    """For routes with a {property_id}: the property must be inside the user's coverage."""
    if access.scope_state:
        assert_covers(access, *property_scope(property_id))
    return access
