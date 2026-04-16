FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Playwright browsers cache (shared location)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN mkdir -p /app/data

# Base utilities needed to fetch Node and run Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 (LTS) via NodeSource — needed by the Playwright runner
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Layer de Playwright (cacheada) ───────────────────────────────
# Copia SÓ os arquivos de dependência do runner. Assim a instalação
# pesada do Chromium (5-8min) só roda de novo quando package*.json mudam,
# não em toda alteração de código Python.
COPY app/runners/legalone/package.json app/runners/legalone/package-lock.json /app/app/runners/legalone/
RUN cd /app/app/runners/legalone \
    && npm ci --omit=dev \
    && npx --yes playwright install --with-deps chromium

# ─── Código da aplicação (layer leve) ─────────────────────────────
COPY . .

RUN chmod +x /app/scripts/docker-api-start.sh

EXPOSE 8000

CMD ["/app/scripts/docker-api-start.sh"]
