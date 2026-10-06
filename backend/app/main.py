import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.account import router as account_router
from app.api.properties import router as properties_router
from app.api.liens import jobs_router as lien_jobs_router
from app.api.liens import router as liens_router
from app.api.pa_data import router as pa_data_router
from app.api.sale_page import router as sale_page_router
from app.api.warehouse_valuations import router as warehouse_valuations_router
from app.auth import require_developer, require_property_access


app = FastAPI(
    title="NJ Sheriff Sale API",
    version="1.0.0",
)

# Browser origins allowed to call the API. Production sets CORS_ALLOWED_ORIGINS
# to the site's domains (comma-separated) and may set CORS_ALLOWED_ORIGIN_REGEX
# for preview deployments, e.g. https://.*-your-team\.vercel\.app
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=os.getenv("CORS_ALLOWED_ORIGIN_REGEX") or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Access rules: the properties and sale-page routers check sign-in, plan and
# coverage per route (their aggregate facets stay public for the landing page);
# lien details need the property inside the plan; data-maintenance and
# warehouse routes are developer-only. Billing and account routes sign users in.
app.include_router(account_router)
app.include_router(properties_router)
app.include_router(liens_router, dependencies=[Depends(require_property_access)])
app.include_router(lien_jobs_router, dependencies=[Depends(require_developer)])
app.include_router(pa_data_router, dependencies=[Depends(require_developer)])
# The warehouse is a self-hosted database a hosted API cannot reach; production
# sets ENABLE_WAREHOUSE_API=0 instead of letting these routes fall back to Supabase.
if os.getenv("ENABLE_WAREHOUSE_API", "1") != "0":
    app.include_router(warehouse_valuations_router, dependencies=[Depends(require_developer)])
app.include_router(sale_page_router)


@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {
        "message": "NJ Sheriff Sale API is running"
    }
