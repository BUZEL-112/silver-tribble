"""Tests for YouTubeUploadService: token refresh, upload initiation, and publishing flow."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.database import get_session
from src.models.entities import ScriptRecord, StoryCluster
from src.models.schemas import YouTubeUploadRequest
from src.repositories.render_repository import RenderRepository
from src.services.storage_service import LocalStorageService
from src.services.youtube_upload_service import YouTubeUploadService


@pytest.fixture
def yt_service(tmp_path: Path) -> YouTubeUploadService:
    storage = LocalStorageService(base_dir=tmp_path)
    return YouTubeUploadService(
        storage_service=storage,
        client_id="test_client_id",
        client_secret="test_client_secret",
        refresh_token="test_refresh_token",
    )


def test_is_configured(yt_service: YouTubeUploadService) -> None:
    """Verify configuration check validates all three OAuth attributes."""
    assert yt_service.is_configured() is True

    unconfigured = YouTubeUploadService(client_id=None, client_secret=None, refresh_token=None)
    assert unconfigured.is_configured() is False


def test_refresh_access_token_success(yt_service: YouTubeUploadService) -> None:
    """Verify successful access token retrieval from Google OAuth endpoint."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "mock_ya29_token_123"}
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        token = yt_service.refresh_access_token()
        assert token == "mock_ya29_token_123"


def test_upload_video_for_job(yt_service: YouTubeUploadService, tmp_path: Path) -> None:
    """Verify video upload process from initiation to completion."""
    video_file = tmp_path / "test_render.mp4"
    video_file.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"A" * 1024)

    import uuid

    with get_session() as session:
        cluster = StoryCluster(
            cluster_hash=f"yt_hash_{uuid.uuid4().hex[:8]}",
            title="YouTube Upload News",
            summary="A big update in AI video publishing.",
            article_ids=[],
            article_count=1,
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="How AI Uploads to YouTube",
            full_narration="Here is the full narration for YouTube upload test.",
            beats=[{"beat_number": 1, "on_screen_text": "Intro", "target_duration_seconds": 10.0}],
        )
        session.add(script)
        session.flush()

        repo = RenderRepository(session)
        job = repo.create_job(script_id=script.id, aspect_ratio="9:16")
        job.output_video_path = str(video_file)
        job.duration_seconds = 10.0
        job.status = "completed"
        session.commit()
        job_id = job.id

    # Mock access token refresh
    init_resp = MagicMock()
    init_resp.headers = {"Location": "https://upload.youtube.com/resumable_upload_session"}
    init_resp.raise_for_status.return_value = None

    upload_resp = MagicMock()
    upload_resp.json.return_value = {"id": "dQw4w9WgXcQ"}
    upload_resp.raise_for_status.return_value = None

    with patch.object(yt_service, "refresh_access_token", return_value="mock_token"):
        with patch("httpx.Client.post", return_value=init_resp):
            with patch("httpx.Client.put", return_value=upload_resp):
                req = YouTubeUploadRequest(
                    job_id=job_id,
                    privacy_status="unlisted",
                )
                result = yt_service.upload_video_for_job(req)

                assert result.video_id == "dQw4w9WgXcQ"
                assert result.video_url == "https://youtu.be/dQw4w9WgXcQ"
                assert result.privacy_status == "unlisted"
