# Deployment

| Part | Host | Source |
|---|---|---|
| Frontend (Next.js) | Vercel | `frontend/` |
| API (FastAPI) | Railway (any Docker host works) | `backend/Dockerfile` |
| Database and sign-in | Supabase (already running) | `DATABASE_URL`, Supabase Auth |
| Payments | Stripe | Checkout, customer portal, webhook |
| Scheduled refreshes | GitHub Actions | `.github/workflows/` |

## How access works

- People sign in with Supabase Auth (email and password). The browser sends the session token to the API, which verifies it against the project's public signing keys.
- Every data request needs an active plan, and the API only returns data inside the plan's coverage: Free one county, Starter one state, Pro everything. Starter and Pro are paid through Stripe Checkout; a Stripe webhook turns access on and off.
- Developer accounts (`role = developer`) see every state and the developer-only endpoints (data imports, parcel review, lien jobs, warehouse).
- The landing and pricing pages stay public; they only use aggregate counts.
- Migration 034 turns on row-level security for every table and removes the public Supabase roles' access, so the publishable key in the browser cannot read data directly. **New tables must keep RLS on** (default privileges already exclude the public roles).

## 1. Database (once)

Apply the migration that creates accounts and locks down Supabase's REST API:

```bash
cd backend
psql "$DATABASE_URL" -f migrations/034_auth_accounts_and_lockdown.sql
```

(`DATABASE_URL` without the `+psycopg2` part if psql rejects it.)

## 2. Supabase Auth settings

In the Supabase dashboard:

1. **Project Settings → API**: copy the Project URL and the publishable (anon) key. Keep the service-role key private; it is only for creating developer logins.
2. **Authentication → Sign In / Providers → Email**: enabled; keep "Confirm email" on.
3. **Authentication → URL Configuration**: Site URL = `https://www.<your-domain>`; Redirect URLs = `https://www.<your-domain>/**` and `http://localhost:3000/**`.
4. **Authentication → Emails → SMTP**: before launch, add your own SMTP sender (Supabase's built-in sender is rate-limited and meant for testing).

## 3. Stripe

1. Create products **Starter** and **Pro**, each with a monthly and a yearly recurring price (the pricing page shows $39 and $69 a month, 10% off yearly). Copy the four price IDs (`price_...`).
2. **Developers → API keys**: copy the secret key.
3. **Developers → Webhooks → Add endpoint**: URL `https://api.<your-domain>/api/v1/billing/webhook`, events `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`. Copy the signing secret (`whsec_...`).
4. **Settings → Billing → Customer portal**: turn it on and allow cancelling and updating payment methods.

Use test mode first; switch the keys and price IDs to live mode at launch.

## 4. API on Railway

1. New project → Deploy from GitHub repo → this repository. **Root Directory** `backend`. Railway builds `backend/Dockerfile`; the health check is `/health`. Region: US East.
2. Variables:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Supabase connection string |
   | `SUPABASE_URL` | `https://<project>.supabase.co` |
   | `SUPABASE_ANON_KEY` | The publishable key (lets the API confirm sessions signed with Supabase's legacy secret) |
   | `GOOGLE_MAPS_API_KEY` | Street View key (restricted to the Street View Static API) |
   | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | From step 3 |
   | `STRIPE_PRICE_STARTER_MONTH`, `STRIPE_PRICE_STARTER_YEAR`, `STRIPE_PRICE_PRO_MONTH`, `STRIPE_PRICE_PRO_YEAR` | From step 3 |
   | `FRONTEND_URL` | `https://www.<your-domain>` |
   | `CORS_ALLOWED_ORIGINS` | `https://www.<your-domain>,https://<your-domain>` |
   | `CORS_ALLOWED_ORIGIN_REGEX` | Optional, for Vercel previews: `https://.*-<team>\.vercel\.app` |
   | `ENABLE_WAREHOUSE_API` | `0` |

   Do **not** add `SUPABASE_SERVICE_ROLE_KEY` or `APIFY_API_TOKEN`; the API does not use them.
3. Settings → Networking: add `api.<your-domain>`. Check `https://api.<your-domain>/health`.

## 5. Frontend on Vercel

1. Add New → Project → this repository. **Root Directory** `frontend`.
2. Environment variables (Production and Preview):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://api.<your-domain>` |
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://<project>.supabase.co` |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The publishable (anon) key |
   | `NEXT_PUBLIC_GEOAPIFY_API_KEY` | Optional, restricted to your domains |

   Builds fail on purpose if the first three are missing. `NEXT_PUBLIC_` values are baked in at build time, so redeploy after changing them. Commercial use needs Vercel Pro.

## 6. Domain

Add the domain in Vercel (apex `A` record, `www` `CNAME`) and `api.<your-domain>` in Railway (`CNAME`). Then make sure `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, the Supabase Site URL and redirect URLs, and the Stripe webhook URL all use the final domain, and redeploy both.

## 7. Developer login

On a trusted machine, with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `backend/.env`:

```bash
cd backend
python -m app.create_developer --email you@yourcompany.com
```

It prints a generated password once. Run it again with `--reset-password` to issue a new one. The account has every state and the developer-only endpoints, whatever its plan.

## 8. Scheduled refreshes (GitHub Actions)

Repository Settings → Secrets and variables → Actions → add `DATABASE_URL` and `APIFY_API_TOKEN`.

- `nj-sale-refresh.yml`: NJ on the 1st and 15th of each month.
- `multistate-sale-refresh.yml`: OH, FL, PA, IL, SC, DE every Monday, at most 600 paid Zillow lookups per run.

## 9. Test before launch (Stripe test mode)

1. Sign up with a new email, confirm it, choose **Free** and a county: the dashboard shows only that county.
2. Choose **Starter** with card `4242 4242 4242 4242`: after checkout the account page shows the plan active and the dashboard shows only that state.
3. Cancel from **Manage billing**: when the subscription ends, the dashboard sends you back to choose a plan.
4. Log in with the developer account: every state is available.
5. Signed out, open `https://api.<your-domain>/api/v1/properties`: it must answer 401.

## Still open before going public

- Rate limiting on the API (Excel export and photo endpoints first).
- Confirm the landing-page testimonial, final prices, and Terms and Privacy pages.
- The pricing page's per-plan limits beyond coverage (10 reports a month on Free, Excel export only on Pro) are not enforced yet.
