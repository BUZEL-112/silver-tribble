"""Modal deployment specification for the AI Video Production Platform.

Provides a serverless container environment with FastAPI, Remotion,
Node.js 22, FFmpeg, and persistent storage on Modal.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Container Image Specification
# ---------------------------------------------------------------------------
# Defines a Debian 12 container environment containing Python 3.12, Node.js 22 LTS,
# FFmpeg, and the shared libraries required for headless Chromium video rendering.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(
        "ffmpeg",
        "git",
        "curl",
        "ca-certificates",
        "fonts-liberation",
        "libnss3",
        "libatk1.0-0",
        "libatk-bridge2.0-0",
        "libcups2",
        "libdrm2",
        "libxcomposite1",
        "libxdamage1",
        "libxfixes3",
        "libxrandr2",
        "libgbm1",
        "libxkbcommon0",
        "libpango-1.0-0",
        "libcairo2",
        "libasound2",
        "libxshmfence1",
        "libglu1-mesa",
    )
    .run_commands(
        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
        "apt-get install -y --no-install-recommends nodejs",
    )
    .pip_install_from_pyproject("pyproject.toml")
    .env(
        {
            "PYTHONPATH": "/app",
            "DATA_DIR": "/data",
            "APP_CONFIG_FILE": "/data/config.yaml",
            "API_ONLY_MODE": "true",
        }
    )
    .workdir("/app")
    .add_local_dir("remotion", remote_path="/app/remotion", copy=True)
    .run_commands(
        "cd /app/remotion && (npm ci --prefer-offline --no-audit || npm install --no-audit)"
    )
    .add_local_dir("prompts", remote_path="/app/prompts")
    .add_local_file("config_example.yaml", remote_path="/app/config_example.yaml")
    .add_local_file("index.html", remote_path="/app/index.html")
    .add_local_dir("src", remote_path="/app/src")
)

# ---------------------------------------------------------------------------
# Modal Application and Persistent Storage
# ---------------------------------------------------------------------------
app = modal.App("ai-video-pipeline", image=image)

# Persistent volume mounted at /data for configuration, media cache, and state
data_volume = modal.Volume.from_name("ai-video-pipeline-data", create_if_missing=True)


def _bootstrap_environment() -> None:
    """Prepare required filesystem directories, links, and seeded configuration."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    data_dir = Path("/data")
    app_data_dir = Path("/app/data")

    # Ensure required volume subdirectories exist
    for sub in ["assets", "media", "audio", "captions", "render_props"]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    Path("/app/output/videos").mkdir(parents=True, exist_ok=True)
    Path("/app/artifacts/media").mkdir(parents=True, exist_ok=True)

    # Link /app/data to /data for relative path compatibility
    if not app_data_dir.exists():
        try:
            app_data_dir.symlink_to(data_dir)
        except OSError:
            pass

    # Seed config.yaml from example template if not yet present in volume
    config_file = data_dir / "config.yaml"
    template_config = Path("/app/config_example.yaml")
    if not config_file.exists() and template_config.exists():
        shutil.copyfile(template_config, config_file)


# ---------------------------------------------------------------------------
# ASGI Web Endpoint
# ---------------------------------------------------------------------------
@app.function(
    volumes={"/data": data_volume},
    secrets=[modal.Secret.from_name("ai-video-secrets")],
    cpu=2.0,
    memory=2048,
    timeout=900,
    scaledown_window=60,
)
@modal.asgi_app()
def web() -> Any:
    """Mount the FastAPI web application on a public Modal ASGI endpoint."""
    _bootstrap_environment()

    from src.core.database import init_db
    from src.web import app as fastapi_app

    init_db()
    return fastapi_app


# ---------------------------------------------------------------------------
# Health Diagnostic Entrypoint
# ---------------------------------------------------------------------------
@app.function(
    volumes={"/data": data_volume},
    secrets=[modal.Secret.from_name("ai-video-secrets")],
    timeout=120,
)
def check_health() -> dict[str, Any]:
    """Execute comprehensive system diagnostics against database, storage, and tools."""
    _bootstrap_environment()

    from src.core.database import init_db
    from src.services.health_service import HealthService

    init_db()
    health_svc = HealthService()
    report = health_svc.run_health_check()
    return report.model_dump()


@app.local_entrypoint()
def main() -> None:
    """Run remote health check diagnostics from the CLI."""
    import json

    print("Executing remote health check on Modal...")
    result = check_health.remote()
    print(json.dumps(result, indent=2))
