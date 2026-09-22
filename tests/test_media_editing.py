"""Tests for sentence-level indexed media editing, swapping, and re-rendering."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from src.cli import app as cli_app
from src.core.config import settings
from src.core.database import get_session, init_db
from src.models.entities import ScriptRecord, StoryCluster
from src.models.schemas import SentenceMediaPlacement, WordCaption
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.storage_service import LocalStorageService
from src.web import app as fastapi_app

client = TestClient(fastapi_app)
runner = CliRunner()


@pytest.fixture
def mock_storage(tmp_path: Path) -> LocalStorageService:
    """Provide local storage sandbox for test artifacts."""
    return LocalStorageService(base_dir=tmp_path / "storage")


@pytest.fixture
def mock_cost_repo() -> CostRepository:
    """Mock cost tracking repository."""
    return MagicMock(spec=CostRepository)


def test_generate_visual_query_concrete_keywords(
    mock_storage: LocalStorageService,
    mock_cost_repo: CostRepository,
) -> None:
    """Verify visual query generator filters metaphors and prioritizes concrete hardware terms."""
    service = MediaService(storage_service=mock_storage, cost_repo=mock_cost_repo)

    # Technical sentence with server and compute
    tech_sentence = (
        "Anthropic deployed thousands of clusters inside their high security data center."
    )
    query, keywords, media_type = service.generate_visual_query(
        sentence_text=tech_sentence,
        beat_info={
            "beat_type": "technical_breakdown",
            "visual_direction": "server racks and cables glowing in dark room",
        },
    )
    assert media_type == "video"
    assert any(term in query for term in ["server", "data center", "rack", "cable", "computer"])

    # Skepticism beat should map to reaction gif
    skeptic_sentence = "Critics are rolling their eyes at the astronomical valuation promises."
    s_query, s_keywords, s_media_type = service.generate_visual_query(
        sentence_text=skeptic_sentence,
        beat_info={
            "beat_type": "skepticism",
            "visual_direction": "person looking skeptical or raising eyebrow",
        },
    )
    assert s_media_type == "gif"
    assert any(term in s_query for term in ["skeptical", "doubt", "eye roll", "reaction"])


def test_get_and_save_job_placements(
    mock_storage: LocalStorageService,
    mock_cost_repo: CostRepository,
    tmp_path: Path,
) -> None:
    """Verify loading and persisting indexed placements on disk."""
    service = MediaService(storage_service=mock_storage, cost_repo=mock_cost_repo)
    test_placements = [
        SentenceMediaPlacement(
            sentence_index=0,
            start_time=0.0,
            end_time=3.5,
            keywords=["supercomputer", "ai"],
            media_type="video",
            local_path="/path/to/vid0.mp4",
            source_url="https://example.com/vid0.mp4",
            provider="pexels",
            text="First sentence intro.",
            query="supercomputer data center",
        ),
        SentenceMediaPlacement(
            sentence_index=1,
            start_time=3.5,
            end_time=7.0,
            keywords=["reaction"],
            media_type="image",
            local_path="/path/to/gif1.gif",
            source_url="https://example.com/gif1.gif",
            provider="giphy",
            text="Second sentence skepticism.",
            query="skeptical reaction",
        ),
    ]

    job_id = 9999
    service.save_job_placements(job_id, test_placements)

    loaded = service.get_job_placements(job_id)
    assert len(loaded) == 2
    assert loaded[0].sentence_index == 0
    assert loaded[0].query == "supercomputer data center"
    assert loaded[1].sentence_index == 1
    assert loaded[1].provider == "giphy"


def test_update_placement_media(
    mock_storage: LocalStorageService,
    mock_cost_repo: CostRepository,
    tmp_path: Path,
) -> None:
    """Verify updating a specific indexed placement with custom file or URL."""
    service = MediaService(storage_service=mock_storage, cost_repo=mock_cost_repo)
    job_id = 9998
    initial_placements = [
        SentenceMediaPlacement(
            sentence_index=0,
            start_time=0.0,
            end_time=4.0,
            keywords=["test"],
            media_type="video",
            local_path=str(tmp_path / "old.mp4"),
            source_url="https://old.url",
            provider="pexels",
            text="Initial line",
            query="initial query",
        )
    ]
    service.save_job_placements(job_id, initial_placements)

    new_file = tmp_path / "replacement.mp4"
    new_file.write_bytes(b"dummy_video_bytes")

    updated = service.update_placement_media(
        job_id=job_id,
        sentence_index=0,
        new_media_path_or_url=str(new_file),
        provider="custom",
    )

    assert updated.sentence_index == 0
    assert updated.provider == "custom"
    assert updated.media_type == "video"
    assert Path(updated.local_path).exists()
    assert "job_9998_sent_0_custom.mp4" in updated.local_path

    persisted = service.get_job_placements(job_id)
    assert persisted[0].provider == "custom"
    assert "job_9998_sent_0_custom.mp4" in persisted[0].local_path


def test_search_and_replace_placement(
    mock_storage: LocalStorageService,
    mock_cost_repo: CostRepository,
    tmp_path: Path,
) -> None:
    """Verify search and replace for a placement index against Pexels/Giphy provider."""
    service = MediaService(storage_service=mock_storage, cost_repo=mock_cost_repo)
    job_id = 9997
    initial_placements = [
        SentenceMediaPlacement(
            sentence_index=0,
            start_time=0.0,
            end_time=4.0,
            keywords=["old"],
            media_type="video",
            local_path=str(tmp_path / "old.mp4"),
            source_url="https://old.url",
            provider="pexels",
            text="Original line",
            query="old query",
        )
    ]
    service.save_job_placements(job_id, initial_placements)

    mock_downloaded = tmp_path / "downloaded_new.mp4"
    mock_downloaded.write_bytes(b"mp4_content")

    with (
        patch.object(
            service, "search_pexels", return_value=("https://pexels.com/new_video.mp4", "mp4")
        ),
        patch.object(service, "download_asset", return_value=(True, mock_downloaded)),
    ):
        updated = service.search_and_replace_placement(
            job_id=job_id,
            sentence_index=0,
            query="quantum computing processor",
            provider="pexels",
            media_type="video",
            aspect_ratio="9:16",
        )

        assert updated.sentence_index == 0
        assert updated.query == "quantum computing processor"
        assert updated.local_path == str(mock_downloaded)
        assert updated.source_url == "https://pexels.com/new_video.mp4"


def test_re_render_job_review_mode(
    mock_storage: LocalStorageService,
    mock_cost_repo: CostRepository,
    tmp_path: Path,
) -> None:
    """Verify re_render_job passes show_material_indices into render props."""
    init_db()
    test_uid = uuid.uuid4().hex[:8]

    # Create dummy audio file in mock storage
    audio_file = tmp_path / "storage" / "dummy_audio.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy_mp3_data")

    with get_session() as session:
        render_repo = RenderRepository(session)
        cluster = StoryCluster(
            cluster_hash=f"hash_{test_uid}",
            title="Test Cluster",
            summary="Summary",
            article_ids=[],
            article_count=0,
            status="ready",
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="Test Script for Re-Render",
            aspect_ratio="9:16",
            beats=[{"beat_type": "hook", "visual_direction": "server room"}],
            full_narration="Testing re-render functionality.",
        )
        session.add(script)
        session.flush()

        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
        job.duration_seconds = 5.0
        job.audio_path = "dummy_audio.mp3"
        session.flush()
        job_id = job.id

        media_svc = MediaService(storage_service=mock_storage, cost_repo=mock_cost_repo)
        placements = [
            SentenceMediaPlacement(
                sentence_index=0,
                start_time=0.0,
                end_time=5.0,
                keywords=["test"],
                media_type="video",
                local_path=str(tmp_path / "mock.mp4"),
                source_url="https://example.com/test.mp4",
                provider="custom",
                text="Testing re-render functionality.",
                query="test query",
            )
        ]
        media_svc.save_job_placements(job_id, placements)

        captions = [
            WordCaption(word="Testing", start=0.0, end=0.8),
            WordCaption(word="re-render", start=0.8, end=1.5),
            WordCaption(word="functionality", start=1.5, end=2.5),
        ]

        render_svc = RenderService(render_repo, mock_cost_repo, mock_storage)
        output_path = render_svc.re_render_job(
            job_id=job_id,
            dry_run=True,
            show_material_indices=True,
            script=script,
            captions=captions,
        )

    assert output_path.exists()
    props_path = tmp_path / "storage" / "render_props" / f"props_job_{job_id}.json"
    assert props_path.exists()
    props_data = json.loads(props_path.read_text(encoding="utf-8"))
    assert props_data["showMaterialIndices"] is True
    assert len(props_data["mediaPlacements"]) == 1
    assert props_data["mediaPlacements"][0]["sentence_index"] == 0


def test_web_api_job_media_and_re_render(tmp_path: Path) -> None:
    """Verify REST API endpoints for GET /media, PUT /media/{index}, and POST /re-render."""
    init_db()
    test_uid = uuid.uuid4().hex[:8]

    # Create dummy audio file in local storage
    audio_file = settings.storage_local_dir / "audio" / f"audio_{test_uid}.mp3"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_bytes(b"dummy_mp3_data")

    with get_session() as session:
        render_repo = RenderRepository(session)
        cluster = StoryCluster(
            cluster_hash=f"hash_api_{test_uid}",
            title="Test Cluster API",
            summary="Summary",
            article_ids=[],
            article_count=0,
            status="ready",
        )
        session.add(cluster)
        session.flush()

        script = ScriptRecord(
            cluster_id=cluster.id,
            title="API Script",
            aspect_ratio="9:16",
            beats=[{"beat_type": "hook", "visual_direction": "lab"}],
            full_narration="API test narration sentence.",
        )
        session.add(script)
        session.flush()

        job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
        job.duration_seconds = 4.0
        job.audio_path = str(audio_file)
        session.flush()
        job_id = job.id

    p_file = settings.media_cache_dir / f"placements_job_{job_id}.json"
    p_file.parent.mkdir(parents=True, exist_ok=True)
    p_data = [
        {
            "sentence_index": 0,
            "start_time": 0.0,
            "end_time": 4.0,
            "keywords": ["api", "test"],
            "media_type": "video",
            "local_path": "/fake/path/scene0.mp4",
            "source_url": "https://fake.url/scene0.mp4",
            "provider": "pexels",
            "text": "API test narration sentence.",
            "query": "artificial intelligence lab",
        }
    ]
    p_file.write_text(json.dumps(p_data), encoding="utf-8")

    # Test GET /api/jobs/{job_id}/media
    res_get = client.get(f"/api/jobs/{job_id}/media")
    assert res_get.status_code == 200
    media_list = res_get.json()
    assert len(media_list) == 1
    assert media_list[0]["sentence_index"] == 0
    assert media_list[0]["query"] == "artificial intelligence lab"

    # Test PUT /api/jobs/{job_id}/media/{sentence_index} with a custom local file
    custom_clip = tmp_path / "custom_clip.mp4"
    custom_clip.write_bytes(b"dummy_clip_bytes")

    res_put = client.put(
        f"/api/jobs/{job_id}/media/0",
        json={"file_path": str(custom_clip)},
    )
    assert res_put.status_code == 200
    put_data = res_put.json()
    assert put_data["status"] == "success"
    assert put_data["placement"]["provider"] == "custom"
    assert "custom.mp4" in put_data["placement"]["local_path"]

    # Test POST /api/jobs/{job_id}/re-render
    res_render = client.post(
        f"/api/jobs/{job_id}/re-render",
        json={"dry_run": True, "show_material_indices": True},
    )
    assert res_render.status_code == 200
    render_resp = res_render.json()
    assert render_resp["status"] == "success"
    assert "output_video_path" in render_resp


def test_cli_edit_media_commands(tmp_path: Path) -> None:
    """Verify typer CLI edit-media command with --list and --dry-run."""
    init_db()
    with get_session() as session:
        render_repo = RenderRepository(session)
        job = render_repo.create_job(script_id=1, aspect_ratio="9:16")
        session.flush()
        test_job_id = job.id

    p_file = settings.media_cache_dir / f"placements_job_{test_job_id}.json"
    p_file.parent.mkdir(parents=True, exist_ok=True)
    p_data = [
        {
            "sentence_index": 0,
            "start_time": 0.0,
            "end_time": 3.0,
            "keywords": ["cli"],
            "media_type": "video",
            "local_path": "/fake/cli.mp4",
            "source_url": "https://fake.url/cli.mp4",
            "provider": "pexels",
            "text": "CLI test line.",
            "query": "supercomputer",
        }
    ]
    p_file.write_text(json.dumps(p_data), encoding="utf-8")

    result_list = runner.invoke(
        cli_app, ["edit-media", "--job-id", str(test_job_id), "--list", "--json"]
    )
    assert result_list.exit_code == 0
    parsed = json.loads(result_list.stdout)
    assert parsed["status"] == "success"
    assert parsed["media_count"] == 1
    assert parsed["placements"][0]["sentence_index"] == 0

    fake_asset = tmp_path / "custom_asset.mp4"
    fake_asset.write_bytes(b"content")

    result_edit = runner.invoke(
        cli_app,
        [
            "edit-media",
            "--job-id",
            str(test_job_id),
            "--index",
            "0",
            "--file",
            str(fake_asset),
            "--json",
        ],
    )
    assert result_edit.exit_code == 0
    edit_parsed = json.loads(result_edit.stdout)
    assert edit_parsed["status"] == "success"
    assert edit_parsed["updated_index"] == 0
    assert edit_parsed["updated_placement"]["provider"] == "custom"
