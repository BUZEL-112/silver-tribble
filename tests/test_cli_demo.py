"""Test suite validating zero-API-key sandbox demo CLI, service, and endpoints."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from src.cli import app
from src.core.database import get_session
from src.services.demo_service import DemoService
from src.services.render_service import RenderService
from src.web import app as fastapi_app

runner = CliRunner()


def test_cli_demo_dry_run() -> None:
    """Validate that 'demo --dry-run' completes successfully with exit code 0."""
    result = runner.invoke(app, ["demo", "--dry-run"])
    assert result.exit_code == 0
    assert "AI Video Studio Demo" in result.output
    assert "Stage 1: News Ingestion" in result.output
    assert "Stage 2: FastEmbed / Local Clustering" in result.output
    assert "Stage 3: 5-Beat Comedic Script" in result.output
    assert "Stage 4: Edge-TTS / Local Audio Synthesis" in result.output
    assert "Stage 5: Whisper / Synthetic Alignment" in result.output
    assert "Stage 6: Motion Graphics Rendering" in result.output
    assert "Demo Completed Successfully" in result.output


def test_cli_demo_json_output() -> None:
    """Validate that 'demo --dry-run --json' produces valid machine-readable JSON."""
    import json

    result = runner.invoke(app, ["demo", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output.strip())
    assert data["status"] == "success"
    assert data["beats_count"] == 5
    assert data["is_mock_render"] is True
    assert data["duration_seconds"] > 0
    assert Path(data["video_path"]).name.startswith("video_job_")


def test_web_endpoint_demo_get() -> None:
    """Validate GET /api/pipeline/demo endpoint returns 200 with completed job metadata."""
    client = TestClient(fastapi_app)
    response = client.get("/api/pipeline/demo?dry_run=true")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["beats_count"] == 5
    assert data["is_mock_render"] is True
    assert "job_id" in data
    assert "video_path" in data


def test_web_endpoint_demo_post() -> None:
    """Validate POST /api/pipeline/demo endpoint returns 200 with completed job metadata."""
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/pipeline/demo",
        json={"aspect_ratio": "16:9", "dry_run": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["beats_count"] == 5
    assert data["is_mock_render"] is True
    assert "stage_durations" in data


def test_demo_service_deterministic_fallback() -> None:
    """Validate DemoService audio synthesis fallback when Edge-TTS fails or is offline."""
    with get_session() as session:
        service = DemoService(session=session)
        # Force Edge-TTS failure to exercise deterministic local audio synthesis
        with patch(
            "src.services.tts_service.TtsService.synthesize_speech",
            side_effect=RuntimeError("Simulated Edge-TTS offline failure"),
        ):
            result = service.run_demo(dry_run=True)
            assert result.article_id > 0
            assert result.cluster_id > 0
            assert result.script_id > 0
            assert result.job_id > 0
            assert result.is_mock_render is True
            assert len(result.beats) == 5
            assert Path(result.audio_path).exists()


def test_render_service_chromium_headless_flags() -> None:
    """Validate RenderService provides correct flags for Linux or Docker environments."""
    with patch("platform.system", return_value="Linux"):
        flags = RenderService.get_chromium_headless_flags()
        assert "--no-sandbox" in flags
        assert "--disable-setuid-sandbox" in flags

    with patch("platform.system", return_value="Darwin"):
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                darwin_flags = RenderService.get_chromium_headless_flags()
                assert darwin_flags == []


def test_remotion_config_contains_sandbox_setting() -> None:
    """Validate remotion.config.ts contains Config.setChromiumSandbox(false)."""
    config_file = Path("remotion/remotion.config.ts")
    assert config_file.exists(), "remotion.config.ts must exist"
    content = config_file.read_text(encoding="utf-8")
    assert "Config.setChromiumSandbox(false)" in content
