#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo " Starting AI Video Production Studio in Container"
echo "=========================================================="

DATA_DIR="${DATA_DIR:-/data}"
CONFIG_FILE="${DATA_DIR}/config.yaml"

mkdir -p "${DATA_DIR}/assets"
mkdir -p "${DATA_DIR}/media"
mkdir -p "${DATA_DIR}/audio"
mkdir -p "${DATA_DIR}/captions"
mkdir -p "${DATA_DIR}/render_props"
mkdir -p "/app/output/videos"

# Seed default config.yaml if not present in mounted volume
if [ ! -f "${CONFIG_FILE}" ]; then
    echo "No config.yaml found in ${DATA_DIR}. Seeding from config_example.yaml..."
    if [ -f "/app/config_example.yaml" ]; then
        cp "/app/config_example.yaml" "${CONFIG_FILE}"
    fi
fi

# Initialize database schema
echo "Initializing database schema..."
python -c "from src.core.database import init_db; init_db()" || {
    echo "Database initialization failed. Retrying in 3 seconds..."
    sleep 3
    python -c "from src.core.database import init_db; init_db()"
}

echo "Database ready. Starting web server on port 8000..."
exec uvicorn src.web:app --host 0.0.0.0 --port 8000 --workers 1
