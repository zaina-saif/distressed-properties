# Deployment

The hosted site has four parts:

| Part | Host | Source |
|---|---|---|
| Frontend (Next.js) | Vercel | `frontend/` |
| API (FastAPI) | Railway (any Docker host works) | `backend/Dockerfile` |
| Operational database | Supabase (already running) | `DATABASE_URL` |
| Scheduled refreshes | GitHub Actions | `.github/workflows/` |

The warehouse database is self-hosted and unreachable from the hosted API, so production runs with `ENABLE_WAREHOUSE_API=0`. The dashboard and landing page only use Supabase.

## 1. API on Railway

1. New project → Deploy from GitHub repo → choose this repository.
2. Service settings → **Root Directory** `backend`. Railway reads `backend/railway.json` and builds `backend/Dockerfile`; the health check is `/health`.
3. Region: US East, the closest to the Supabase database (Canada).
4. Variables:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Supabase connection string (same as `backend/.env`) |
   | `GOOGLE_MAPS_API_KEY` | Street View key (restrict it to the Street View Static API) |
   | `CORS_ALLOWED_ORIGINS` | The site's origins, e.g. `https://www.example.com,https://example.com` |
   | `CORS_ALLOWED_ORIGIN_REGEX` | Optional, for Vercel previews: `https://.*-<team>\.vercel\.app` |
   | `ENABLE_WAREHOUSE_API` | `0` |

   Optional keys from `backend/.env.example` (`RENTCAST_API_KEY`, `REALIE_API_KEY`, ...) only if the API uses them. `APIFY_API_TOKEN` is not needed by the API.
5. Settings → Networking → **Generate Domain**, or add a custom domain such as `api.example.com`. Check `https://<api-domain>/health` returns `{"status":"healthy"}`.

Local check of the image: `docker build -t sheriff-api backend && docker run --env-file backend/.env -e PORT=8000 -p 8000:8000 sheriff-api`.

## 2. Frontend on Vercel

1. Add New → Project → import this repository.
2. **Root Directory** `frontend`; the framework is detected as Next.js.
3. Environment variables (Production and Preview):

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | The API's public URL, e.g. `https://api.example.com` (no trailing slash) |
   | `NEXT_PUBLIC_GEOAPIFY_API_KEY` | Optional basemap key, restricted to the site's domains |

   The build fails on purpose if `NEXT_PUBLIC_API_URL` is missing. Variables starting with `NEXT_PUBLIC_` are baked in at build time, so redeploy after changing them.
4. Commercial use needs a Vercel Pro plan.

## 3. Domain

1. Add the domain in Vercel (Settings → Domains) and set the DNS records it shows (apex `A` record and `www` `CNAME`).
2. Add `api.<domain>` in Railway and create the `CNAME` it shows.
3. Put both site origins in Railway's `CORS_ALLOWED_ORIGINS` and the API URL in Vercel's `NEXT_PUBLIC_API_URL`, then redeploy both.

## 4. Scheduled refreshes (GitHub Actions)

Repository Settings → Secrets and variables → Actions → add `DATABASE_URL` and `APIFY_API_TOKEN`.

- `nj-sale-refresh.yml`: NJ, on the 1st and 15th of each month.
- `multistate-sale-refresh.yml`: OH, FL, PA, IL, SC, DE every Monday (`pipeline.multistate_refresh`), at most 600 paid Zillow lookups per run.

Both can be run by hand from the Actions tab, with or without the paid Zillow stage. Each run's summary shows counts per state; the detailed log stays on the runner because it contains addresses. If a source starts blocking GitHub's servers, its step fails and the previous data is kept; run that scraper from the operator's machine instead. Operator-assisted collectors (CAPTCHA sources) always run locally.

## Before going public

- There is no real sign-in yet: the sign-in page lets anyone through and the API is open, so anyone with the link sees all data.
- Add rate limiting to the API, at least on the Excel export and photo endpoints.
- Confirm the landing-page testimonial, set real prices on `/pricing`, and add Terms and Privacy pages.
