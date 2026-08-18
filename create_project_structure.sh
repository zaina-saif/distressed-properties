#!/bin/bash

set -e

mkdir -p backend/app/api
mkdir -p backend/app/database
mkdir -p backend/models
mkdir -p backend/pipeline
mkdir -p backend/tests

files=(
  "backend/app/__init__.py"
  "backend/app/main.py"
  "backend/app/config.py"
  "backend/app/api/__init__.py"
  "backend/app/api/properties.py"
  "backend/app/api/sheriff_sales.py"
  "backend/app/api/watchlists.py"
  "backend/app/database/__init__.py"
  "backend/app/database/session.py"
  "backend/app/database/models.py"
  "backend/models/__init__.py"
  "backend/pipeline/__init__.py"
  "backend/pipeline/scrape_civilview.py"
  "backend/pipeline/normalize.py"
  "backend/pipeline/enrich_valuation.py"
  "backend/pipeline/enrich_liens.py"
  "backend/pipeline/calculate_equity.py"
  "backend/pipeline/calculate_risk.py"
  "backend/pipeline/predict_sale.py"
  "backend/worker.py"
  "backend/requirements.txt"
  "backend/.env.example"
  "backend/.gitignore"
)

for file in "${files[@]}"; do
  touch "$file"
done

echo "Project structure created successfully."