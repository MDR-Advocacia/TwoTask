#!/bin/sh
set -eu

mkdir -p /app/data

python /app/scripts/run_migrations.py

# UVICORN_WORKERS permite overrride via painel do Coolify.
# Regra de bolso: 2-4 por vCPU, limitado pela RAM (cada worker replica o
# Python + engine do SQLAlchemy). Em EC2 com 4 vCPUs use 4; em 8, 6-8.
WORKERS="${UVICORN_WORKERS:-4}"

exec python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips="*"
