"""Tests for video resolution conversion and beat generator configuration editing."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.render_service import RenderService
from src.services.script_service import ScriptService
from src.services.storage_service import LocalStorageService
from src.web import app


@pytest.fixture
def client():
    return TestClient(app)


def test_convert_resolution_vertical_mock(
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    """Test resolution conversion produces valid output for vertical 9:16 video."""
    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        output_dir=tmp_path / "videos",
    )

    source_file = tmp_path / "video_source.mp4"
    source_file.write_bytes(b"MOCK_MP4_VIDEO_CONTAINER_DATA_SOURCE")

    job = render_repo.create_job(script_id=1, aspect_ratio="9:16")
    render_repo.complete_job(job.id, str(source_file))

    out_360p = service.convert_resolution(job_id=job.id, resolution="360p")
    assert out_360p.exists()
    assert "360p" in out_360p.name

    out_720p = service.convert_resolution(job_id=job.id, resolution="720p")
    assert out_720p.exists()
    assert "720p" in out_720p.name


def test_convert_resolution_horizontal(
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    """Test resolution conversion for horizontal 16:9 video."""
    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        output_dir=tmp_path / "videos",
    )

    source_file = tmp_path / "video_horiz.mp4"
    source_file.write_bytes(b"MOCK_MP4_VIDEO_CONTAINER_DATA_HORIZONTAL")

    job = render_repo.create_job(script_id=2, aspect_ratio="16:9")
    render_repo.complete_job(job.id, str(source_file))

    out_480p = service.convert_resolution(job_id=job.id, resolution="480p")
    assert out_480p.exists()
    assert "480p" in out_480p.name


def test_convert_resolution_unsupported_resolution(
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    """Test ValueError is raised when resolution is invalid."""
    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        output_dir=tmp_path / "videos",
    )

    with pytest.raises(ValueError, match="Unsupported resolution"):
        service.convert_resolution(job_id=999, resolution="240p")


def test_convert_resolution_missing_job_or_file(
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    """Test exceptions on missing job or missing video file."""
    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        output_dir=tmp_path / "videos",
    )

    with pytest.raises(ValueError, match="not found"):
        service.convert_resolution(job_id=9999, resolution="720p")

    job = render_repo.create_job(script_id=3, aspect_ratio="9:16")
    with pytest.raises(FileNotFoundError, match="no completed video"):
        service.convert_resolution(job_id=job.id, resolution="720p")


def test_get_and_update_beat_generator_config(
    article_repo: ArticleRepository,
    script_repo: ScriptRepository,
    cost_repo: CostRepository,
    tmp_path: Path,
):
    """Test reading, updating, and listing beat generator YAML configs."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    beat_file = prompts_dir / "beat_sheet.yaml"
    initial_yaml = (
        "name: test_generator\n"
        "system_prompt: You are a producer.\n"
        'user_prompt_template: "Articles list"\n'
    )
    beat_file.write_text(initial_yaml, encoding="utf-8")

    service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
        prompts_dir=prompts_dir,
    )

    cfg = service.get_beat_generator_config("beat_sheet.yaml")
    assert cfg["filename"] == "beat_sheet.yaml"
    assert cfg["parsed"]["name"] == "test_generator"

    updated_yaml = (
        "name: updated_generator\n"
        "system_prompt: Updated producer prompt.\n"
        'user_prompt_template: "Updated template"\n'
    )
    res = service.update_beat_generator_config(
        content=updated_yaml,
        filename="beat_sheet.yaml",
    )
    assert res["parsed"]["name"] == "updated_generator"
    assert "updated_generator" in beat_file.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid YAML syntax"):
        service.update_beat_generator_config(content="foo: [bar: 1", filename="beat_sheet.yaml")

    with pytest.raises(ValueError, match="cannot be empty"):
        service.update_beat_generator_config(content="", filename="beat_sheet.yaml")

    with pytest.raises(ValueError, match="valid YAML dictionary"):
        service.update_beat_generator_config(content="just a string", filename="beat_sheet.yaml")

    files = service.list_beat_generator_configs()
    assert "beat_sheet.yaml" in files


def test_api_convert_resolution(client: TestClient, tmp_path: Path):
    """Test POST /api/jobs/{job_id}/convert-resolution."""
    from src.core.database import get_session

    res = client.post("/api/jobs/99999/convert-resolution", json={"resolution": "720p"})
    assert res.status_code == 404

    with get_session() as session:
        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=1, aspect_ratio="9:16")
        job_id = job.id

    # No video output path yet -> 400
    res = client.post(f"/api/jobs/{job_id}/convert-resolution", json={"resolution": "720p"})
    assert res.status_code == 400

    # With completed video output path -> 200
    dummy_mp4 = tmp_path / f"job_{job_id}.mp4"
    dummy_mp4.write_bytes(b"MOCK_MP4_DATA")
    with get_session() as session:
        render_repo = RenderRepository(session)
        render_repo.complete_job(job_id, str(dummy_mp4))

    res_ok = client.post(f"/api/jobs/{job_id}/convert-resolution", json={"resolution": "360p"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["status"] == "success"
    assert data["resolution"] == "360p"
    assert "360p" in data["output_video_path"]

    # Test streaming and downloading resolution variant
    stream_res = client.get(f"/api/jobs/{job_id}/video?resolution=360p")
    assert stream_res.status_code == 200

    download_res = client.get(f"/api/jobs/{job_id}/download?resolution=360p")
    assert download_res.status_code == 200


def test_api_beat_generator_config(client: TestClient):
    """Test GET and POST /api/config/beat-generator."""
    get_res = client.get("/api/config/beat-generator")
    assert get_res.status_code == 200
    data = get_res.json()
    assert "filename" in data
    assert "content" in data
    assert "available_files" in data
    original_content = data["content"]

    try:
        valid_yaml = (
            "name: beat_sheet_generator\n"
            "system_prompt: News prompt.\n"
            'user_prompt_template: "News items"\n'
        )
        post_res = client.post(
            "/api/config/beat-generator",
            json={"content": valid_yaml, "filename": "beat_sheet.yaml"},
        )
        assert post_res.status_code == 200
        assert post_res.json()["status"] == "success"

        invalid_res = client.post(
            "/api/config/beat-generator",
            json={"content": "foo: [bar: invalid", "filename": "beat_sheet.yaml"},
        )
        assert invalid_res.status_code == 400
    finally:
        client.post(
            "/api/config/beat-generator",
            json={"content": original_content, "filename": "beat_sheet.yaml"},
        )
