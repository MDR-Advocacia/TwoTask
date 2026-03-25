#!/bin/sh
set -eu

mkdir -p /app/data

python /app/scripts/run_migrations.py

exec python -m uvicorn main:app --host 0.0.0.0 --port 8000
