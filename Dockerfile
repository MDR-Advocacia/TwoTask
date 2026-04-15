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

COPY . .

# Install the Playwright runner dependencies and the Chromium browser
# (with its OS-level dependencies). Doing this in the image avoids
# runtime downloads and keeps cold-start fast.
RUN cd /app/app/runners/legalone \
    && npm ci --omit=dev \
    && npx --yes playwright install --with-deps chromium

RUN chmod +x /app/scripts/docker-api-start.sh

EXPOSE 8000

CMD ["/app/scripts/docker-api-start.sh"]
