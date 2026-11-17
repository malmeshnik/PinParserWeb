FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .
# libatomic1 потрібна Node-драйверу Playwright (без неї: libatomic.so.1 not found)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /app/staticfiles /app/media
