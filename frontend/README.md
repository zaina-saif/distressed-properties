# Sheriff Sale Dashboard

The Next.js frontend for the NJ Sheriff Sale Platform. See the repository-root
README for full setup, architecture, and pipeline instructions.

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

`NEXT_PUBLIC_API_URL` points to the FastAPI backend. Add an optional,
domain-restricted `NEXT_PUBLIC_GEOAPIFY_API_KEY` to enable Geoapify tiles and
place search; without it the property map uses MapLibre's demo basemap and the
database search remains fully available.

Available checks:

```bash
npm run lint
npm run build
```
