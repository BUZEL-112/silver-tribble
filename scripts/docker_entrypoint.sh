#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo " Starting AI Video Production Studio in Container"
echo "=========================================================="

DATA_DIR="${DATA_DIR:-/data}"
CONFIG_FILE="${DATA_DIR}/config.yaml"

mkdir -p "${DATA_DIR}/assets" 2>/dev/null || true
mkdir -p "${DATA_DIR}/media" 2>/dev/null || true
mkdir -p "${DATA_DIR}/audio" 2>/dev/null || true
mkdir -p "${DATA_DIR}/captions" 2>/dev/null || true
mkdir -p "${DATA_DIR}/render_props" 2>/dev/null || true
mkdir -p "/app/output/videos" 2>/dev/null || true

# Seed default config.yaml if not present in mounted volume
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "No config.yaml found in ${DATA_DIR}. Seeding from config_example.yaml..."
    if [ -f "/app/config_example.yaml" ]; then
        cp "/app/config_example.yaml" "${CONFIG_FILE}" 2>/dev/null || true
    fi
fi

# Initialize database schema
echo "Initializing database schema..."
python -c "from src.core.database import init_db; init_db()" || {
    echo "Database initialization failed. Retrying in 3 seconds..."
    sleep 3
    python -c "from src.core.database import init_db; init_db()"
}

PORT="${PORT:-7860}"
echo "Database ready. Starting web server on port ${PORT}..."
RELOAD_FLAG=""
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
    RELOAD_FLAG="--reload --reload-dir /app/src"
fi
exec uvicorn src.web:app --host 0.0.0.0 --port "${PORT}" --workers 1 ${RELOAD_FLAG}
