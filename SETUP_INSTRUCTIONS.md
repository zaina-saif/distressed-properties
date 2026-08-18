# Partner Setup Instructions

This guide explains how to run the sheriff-sale platform from a fresh clone and
identifies the local configuration, datasets, and trained model artifacts that
are intentionally excluded from Git.

## 1. Clone the repository

```bash
git clone git@github.com:zaina-saif/distressed-properties.git
cd distressed-properties
```

## 2. Backend setup

Create a virtual environment and install the Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
```

Create `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE
RENTCAST_API_KEY=your_rentcast_api_key
```

- `DATABASE_URL` is required by the backend and pipeline commands.
- `RENTCAST_API_KEY` is only required for RentCast valuation enrichment.
- Never commit real database credentials or API keys.
- A partner can use the existing hosted database if its connection string is
  shared through a password manager or another secure channel.

Start the backend from the `backend` directory:

```bash
cd backend
uvicorn app.main:app --reload
```

The default local backend URL is `http://127.0.0.1:8000`.

## 3. Database setup

If the partner is not connecting to the existing hosted database, create a new
PostgreSQL database and apply every SQL file in `backend/migrations` in numeric
order.

For example, from `backend`:

```bash
for migration in migrations/*.sql; do
  psql "postgresql://USER:PASSWORD@HOST:5432/DATABASE" -v ON_ERROR_STOP=1 -f "$migration"
done
```

The URI passed to `psql` uses `postgresql://`. The backend's SQLAlchemy
`DATABASE_URL` normally uses `postgresql+psycopg2://`.

An empty database will contain the schema but not the listings, lien results,
valuation results, property matches, or status history stored in the existing
database. Those records must be scraped, imported, or transferred separately.

## 4. Frontend setup

Install the frontend dependencies:

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

This file is optional for local development because the frontend already
defaults to `http://127.0.0.1:8000`. Set it to the deployed FastAPI URL when the
backend is hosted elsewhere.

Start the frontend:

```bash
npm run dev
```

Open `http://localhost:3000`.

## 5. Trained valuation model excluded from Git

The following local artifacts are ignored:

```text
backend/data/nj_property/models/
├── monmouth_avm_xgboost.joblib
└── monmouth_avm_metrics.json
```

The application can display valuations already saved in the shared database
without these files. The files are required to run local XGBoost prediction:

```bash
cd backend
python -m pipeline.predict_property_avm --save
```

There are two ways to obtain them:

1. Transfer both model files securely from the original development machine.
2. Rebuild them after loading the historical MOD-IV and SR-1A data:

   ```bash
   cd backend
   python -m pipeline.train_avm
   ```

Do not treat the model as a formal appraisal. It is a statistical prescreening
estimate and depends on the quality and recency of its training data.

## 6. Historical property data excluded from Git

The raw NJ property-history files are approximately 13 GB and are ignored:

```text
backend/data/nj_property/raw/
├── modiv/
│   ├── 2021/
│   ├── 2022/
│   ├── 2023/
│   ├── 2024/
│   ├── 2025/
│   └── 2026/
└── sr1a/
    ├── 2020/
    ├── 2021/
    ├── 2022/
    ├── 2023/
    ├── 2024/
    ├── 2025/
    └── 2026/
```

These MOD-IV property records and SR-1A sales files are needed only when
rebuilding the historical database tables or retraining the Monmouth AVM. They
are not necessary when using the existing shared database and transferred model
artifacts.

The filenames expected by the loader are defined in
`backend/pipeline/load_nj_property_history.py`. Preserve that directory and
filename structure when transferring or downloading the raw files.

## 7. Other files intentionally excluded

The repository also ignores:

- `backend/.env` and `frontend/.env.local`
- `.venv/` and `frontend/node_modules/`
- frontend `.next/`, build, coverage, and Vercel output
- `.idea/`, `.DS_Store`, Python caches, and test caches
- generated CivilView HTML and Monmouth scrape snapshots
- address and parcel manual-review JSON reports
- property-analysis import-failure reports
- local coverage reports

These are local secrets, reproducible dependencies, generated output, or
machine-specific metadata and should not be committed.

## 8. Verification

Run backend tests:

```bash
cd backend
python -m pytest -q
```

Run frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

## Recommended partner workflow

For the quickest setup, securely share access to the existing hosted database
and transfer the two trained model artifacts. This avoids copying the 13 GB raw
dataset or rebuilding the historical tables and valuation model. Each developer
should keep their own local `.env` files and should never exchange secrets in a
Git commit or public message.
