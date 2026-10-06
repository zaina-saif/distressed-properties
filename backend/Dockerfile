# Production image for the FastAPI backend (Railway, Render, Fly.io, ...).
# Build from this directory: docker build -t sheriff-api backend
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# The API imports a few pipeline modules (parcel numbers, county lists); the
# scraped data under data/ stays out of the image.
COPY app ./app
COPY pipeline ./pipeline
COPY models ./models

RUN useradd --create-home api && chown -R api /app
USER api

# Hosts inject PORT; trust their proxy for the client's scheme and address.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
