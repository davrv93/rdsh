#!/usr/bin/env bash
# Arranque local sin Docker (alternativa a `docker compose up --build`).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

# Sin Docker no hay almacén: se corre en modo demo sobre DuckDB.
[ -f .env ] || cp .env.example .env
export OPTIMIZA_SOURCE_MODE="${OPTIMIZA_SOURCE_MODE:-demo}"
export SYNC_ON_START="${SYNC_ON_START:-false}"
.venv/bin/python -m backend.app.seed.generate_seed
exec .venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port "${OPTIMIZA_PORT:-8000}" --reload
