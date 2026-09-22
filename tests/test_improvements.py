"""Comprehensive test suite for the top 10 platform improvements."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.core.database import get_session, init_db
from src.models.entities import Article, RenderJob, ScriptRecord, StoryCluster, VisualAsset
from src.models.schemas import WordCaption
from src.repositories.article_repository import ArticleRepository
from src.repositories.asset_repository import AssetRepository
from src.services.cache_pruning_service import CachePruningService
from src.services.health_service import HealthService
from src.services.rss_service import RssService
from src.services.script_auditor_service import ScriptAuditorService
from src.services.subtitle_service import SubtitleService
from src.services.webhook_service import WebhookService
from src.services.youtube_metadata_service import YouTubeMetadataService
from src.web import app


@pytest.fixture
def clean_db() -> Generator[None, None, None]:
    """Provide a clean database state for each test."""
    init_db()
    with get_session() as session:
        session.query(VisualAsset).delete()
        session.query(RenderJob).delete()
        session.query(ScriptRecord).delete()
        session.query(StoryCluster).delete()
        session.query(Article).delete()
        session.commit()
    yield


# ---------------------------------------------------------------------------
# 1. YouTube Metadata Service Tests
# ---------------------------------------------------------------------------


def test_youtube_metadata_generation() -> None:
    service = YouTubeMetadataService()
    beats = [
        {"timestamp": 0.0, "header": "The Breakthrough", "narration": "OpenAI drops a bomb."},
        {
            "timestamp": 12.5,
            "header": "Industry Reactions",
            "narration": "Competitors are panicking.",
        },
    ]
    captions = [
        WordCaption(word="OpenAI", start=0.0, end=0.6, confidence=0.98),
        WordCaption(word="drops", start=0.7, end=1.1, confidence=0.95),
        WordCaption(word="bombshell", start=1.2, end=1.8, confidence=0.99),
    ]

    meta = service.generate_metadata(
        title="OpenAI Stuns the World With GPT-5",
        full_narration="OpenAI drops a bombshell today. Competitors are in utter panic.",
        beats=beats,
        captions=captions,
        duration_seconds=35.0,
    )

    assert len(meta.title_options) >= 3
    assert any("OpenAI" in opt for opt in meta.title_options)
    assert len(meta.chapters) == 2
    assert meta.chapters[0].title == "The Breakthrough"
    assert meta.chapters[0].timestamp == "00:00"
    assert "Chapters:" in meta.description
    assert len(meta.tags) > 0
    assert any("ai" in tag.lower() for tag in meta.tags)
    assert len(meta.hashtags) > 0


def test_youtube_metadata_fallback_without_beats() -> None:
    service = YouTubeMetadataService()
    meta = service.generate_metadata(
        title="Quick AI News",
        full_narration="Short single segment news update.",
        beats=None,
        captions=[],
        duration_seconds=15.0,
    )
    assert len(meta.chapters) >= 1
    assert meta.chapters[0].timestamp == "00:00"


# ---------------------------------------------------------------------------
# 2. Subtitle Service Tests (SRT and WebVTT)
# ---------------------------------------------------------------------------


def test_subtitle_formatting_and_cues(tmp_path: Path) -> None:
    service = SubtitleService()
    captions = [
        WordCaption(word="Welcome", start=0.0, end=0.4),
        WordCaption(word="back", start=0.45, end=0.7),
        WordCaption(word="to", start=0.75, end=0.9),
        WordCaption(word="AI", start=0.95, end=1.2),
        WordCaption(word="Daily.", start=1.25, end=1.6),
        WordCaption(word="Here", start=2.5, end=2.8),
        WordCaption(word="is", start=2.85, end=3.0),
        WordCaption(word="today's", start=3.05, end=3.4),
        WordCaption(word="lead.", start=3.45, end=3.8),
    ]

    srt = service.generate_srt(captions)
    vtt = service.generate_vtt(captions)

    assert "00:00:00,000 -->" in srt
    assert "Welcome back to AI Daily." in srt

    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 -->" in vtt

    exported = service.export_subtitles(captions, job_id=999, output_dir=tmp_path)
    assert exported["srt"].exists()
    assert exported["vtt"].exists()
    assert exported["srt"].stat().st_size > 0
    assert exported["vtt"].stat().st_size > 0


# ---------------------------------------------------------------------------
# 3. Health Check Service Tests
# ---------------------------------------------------------------------------


def test_health_check_service() -> None:
    service = HealthService()
    status = service.run_health_check()

    assert status.status in ("healthy", "degraded", "unhealthy")
    assert status.total_checks >= 4
    names = [c.name for c in status.components]
    assert "database" in names
    assert "storage" in names
    assert "ffmpeg" in names
    assert "remotion" in names
    assert "providers" in names


# ---------------------------------------------------------------------------
# 4. Webhook Dispatch Service Tests
# ---------------------------------------------------------------------------


def test_webhook_service_signature_and_dispatch() -> None:
    service = WebhookService(
        webhook_url="https://example.com/webhook", webhook_secret="supersecret123"
    )
    signature = service.compute_signature(b'{"test": 1}')
    assert len(signature) == 64

    # Unconfigured URL returns False gracefully
    noop_service = WebhookService(webhook_url=None)
    assert noop_service.dispatch_event("test.event", {"foo": "bar"}) is False

    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, is_success=True)
        success = service.dispatch_event("pipeline.completed", {"job_id": 42})
        assert success is True
        assert mock_post.called


# ---------------------------------------------------------------------------
# 5. RSS URL Canonicalization Tests
# ---------------------------------------------------------------------------


def test_rss_url_canonicalization() -> None:
    service = RssService()
    raw_url = "https://techcrunch.com/2026/09/20/ai-model/?utm_source=twitter&utm_medium=social&utm_campaign=launch&fbclid=12345#overview"
    canonical = service.canonicalize_url(raw_url)
    assert canonical == "https://techcrunch.com/2026/09/20/ai-model"

    # Preserves legitimate parameters
    query_url = "https://example.com/article?id=500&category=tech&utm_content=button"
    canonical_query = service.canonicalize_url(query_url)
    assert "id=500" in canonical_query
    assert "category=tech" in canonical_query
    assert "utm_content" not in canonical_query


# ---------------------------------------------------------------------------
# 6. Trending Clusters Velocity Ranking Tests
# ---------------------------------------------------------------------------


def test_trending_clusters_ranking(clean_db: None) -> None:
    with get_session() as session:
        repo = ArticleRepository(session)
        art1 = Article(title="Story 1", link="https://a.com/1", source="Source A")
        art2 = Article(title="Story 2", link="https://a.com/2", source="Source B")
        art3 = Article(title="Story 3", link="https://a.com/3", source="Source C")
        session.add_all([art1, art2, art3])
        session.flush()

        # Cluster A has 3 articles from 3 diverse sources
        cluster_a = StoryCluster(
            cluster_hash="hash_a",
            title="High Velocity Multi-Source Event",
            summary="Huge breaking news",
            article_ids=[art1.id, art2.id, art3.id],
            article_count=3,
            status="pending",
        )
        # Cluster B has 1 article
        cluster_b = StoryCluster(
            cluster_hash="hash_b",
            title="Single Source Update",
            summary="Small news",
            article_ids=[art1.id],
            article_count=1,
            status="pending",
        )
        session.add_all([cluster_a, cluster_b])
        session.commit()

        trending = repo.get_trending_clusters(limit=5, hours_back=48)
        assert len(trending) >= 2
        # Cluster A should rank higher than Cluster B due to volume and source diversity
        top_cluster, top_score = trending[0]
        second_cluster, second_score = trending[1]
        assert top_cluster.id == cluster_a.id
        assert top_score > second_score


# ---------------------------------------------------------------------------
# 7. Asset Library Multi-Factor Scoring Tests
# ---------------------------------------------------------------------------


def test_asset_library_multi_factor_scoring(clean_db: None, tmp_path: Path) -> None:
    f1 = tmp_path / "robot1.jpg"
    f1.write_text("robot1", encoding="utf-8")
    f2 = tmp_path / "robot2.jpg"
    f2.write_text("robot2", encoding="utf-8")

    with get_session() as session:
        repo = AssetRepository(session)
        # Asset 1: High VLM score, matching emotion, low usage
        asset1 = VisualAsset(
            asset_hash="hash_robot_1",
            query="futuristic artificial intelligence robot",
            provider="pexels",
            media_type="image",
            local_path=str(f1),
            emotion_tags=["dramatic", "technological"],
            tags=["robot", "ai", "future"],
            aspect_ratio="9:16",
            vlm_score=9.5,
            vlm_reason="High quality sharp render",
            usage_count=0,
        )
        # Asset 2: High usage count penalty
        asset2 = VisualAsset(
            asset_hash="hash_robot_2",
            query="futuristic artificial intelligence robot",
            provider="pexels",
            media_type="image",
            local_path=str(f2),
            emotion_tags=["dramatic"],
            tags=["robot"],
            aspect_ratio="9:16",
            vlm_score=6.0,
            vlm_reason="Acceptable shot",
            usage_count=10,
        )
        session.add_all([asset1, asset2])
        session.commit()

        best = repo.find_matching_asset(
            query="futuristic artificial intelligence robot",
            emotion="dramatic",
            media_type="image",
            aspect_ratio="9:16",
        )
        assert best is not None
        assert best.id == asset1.id


# ---------------------------------------------------------------------------
# 8. Script Retention and Pacing Auditor Tests
# ---------------------------------------------------------------------------


def test_script_auditor_analysis() -> None:
    auditor = ScriptAuditorService()
    narration = (
        "Breaking news: Did OpenAI just change software engineering forever? "
        "Today they announced an agent capable of solving complex architecture problems. "
        "Engineers around the world are questioning what comes next."
    )
    beats = [
        {"header": "The Hook", "narration": "Breaking news: Did OpenAI change software forever?"},
        {"header": "Details", "narration": "Today they announced an autonomous agent."},
    ]

    report = auditor.audit_script(
        title="OpenAI Breakthrough Changes Everything",
        full_narration=narration,
        beats=beats,
    )

    assert report.word_count > 10
    assert report.words_per_minute > 0
    assert report.pacing_rating in ("optimal", "too_fast", "too_slow")
    assert report.has_question_hook is True
    assert report.has_breaking_trigger is True
    assert report.hook_score >= 0.7


# ---------------------------------------------------------------------------
# 9. Cache Pruning Service Tests
# ---------------------------------------------------------------------------


def test_cache_pruning_protects_assets_and_removes_unindexed(
    clean_db: None, tmp_path: Path
) -> None:
    protected_file = tmp_path / "protected_asset.jpg"
    protected_file.write_text("image-bytes", encoding="utf-8")

    stale_temp = tmp_path / "stale_temp_file.part"
    stale_temp.write_text("chunk-data", encoding="utf-8")

    with get_session() as session:
        repo = AssetRepository(session)
        asset = VisualAsset(
            asset_hash="hash_protected_asset",
            query="test",
            provider="pexels",
            media_type="image",
            local_path=str(protected_file),
            usage_count=1,
        )
        session.add(asset)
        session.commit()

        service = CachePruningService(asset_repo=repo)

        # Test dry-run: files are identified but not removed
        dry_result = service.prune_cache(retention_hours=0.0, target_dir=tmp_path, dry_run=True)
        assert dry_result.files_deleted >= 1
        assert stale_temp.exists()
        assert protected_file.exists()

        # Real prune: stale temp deleted, protected file remains
        real_result = service.prune_cache(retention_hours=0.0, target_dir=tmp_path, dry_run=False)
        assert real_result.files_deleted >= 1
        assert not stale_temp.exists()
        assert protected_file.exists()


# ---------------------------------------------------------------------------
# 10. Web API Endpoints for Improvements Tests
# ---------------------------------------------------------------------------


def test_web_api_improvement_endpoints(clean_db: None, tmp_path: Path) -> None:
    client = TestClient(app)

    # 1. /api/health
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "components" in data

    # 2. /api/clusters/trending
    resp = client.get("/api/clusters/trending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Create script and job for detailed endpoint tests
    video_file = tmp_path / "test_out.mp4"
    video_file.write_bytes(b"dummy-mp4-data")
    captions_file = tmp_path / "test_caps.json"
    captions_file.write_text(
        json.dumps([{"word": "Hello", "start": 0.0, "end": 0.5, "confidence": 1.0}]),
        encoding="utf-8",
    )

    with get_session() as session:
        script = ScriptRecord(
            cluster_id=1,
            title="Breaking: AI Model Beats Human Programmers",
            aspect_ratio="9:16",
            full_narration="Did AI just replace coders? Today marks the turning point.",
            beats=[
                {"timestamp": 0.0, "header": "Intro", "narration": "Did AI just replace coders?"}
            ],
        )
        session.add(script)
        session.flush()

        job = RenderJob(
            script_id=script.id,
            aspect_ratio="9:16",
            status="completed",
            duration_seconds=12.0,
            captions_path=str(captions_file),
            output_video_path=str(video_file),
        )
        session.add(job)
        session.commit()
        script_id = script.id
        job_id = job.id

    # 3. /api/scripts/{id}/audit
    audit_resp = client.get(f"/api/scripts/{script_id}/audit")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert "pacing_rating" in audit_data
    assert "hook_score" in audit_data

    # 4. /api/jobs/{id}/video
    video_resp = client.get(f"/api/jobs/{job_id}/video")
    assert video_resp.status_code == 200
    assert video_resp.headers["content-type"] == "video/mp4"

    # 5. /api/jobs/{id}/download
    download_resp = client.get(f"/api/jobs/{job_id}/download")
    assert download_resp.status_code == 200
    assert "attachment" in download_resp.headers["content-disposition"]

    # 6. /api/jobs/{id}/subtitles (SRT and VTT)
    sub_srt = client.get(f"/api/jobs/{job_id}/subtitles?format=srt")
    assert sub_srt.status_code == 200
    assert "00:00:00,000 -->" in sub_srt.json()["content"]

    sub_vtt = client.get(f"/api/jobs/{job_id}/subtitles?format=vtt")
    assert sub_vtt.status_code == 200
    assert "WEBVTT" in sub_vtt.json()["content"]

    # 7. /api/jobs/{id}/youtube-metadata
    yt_resp = client.get(f"/api/jobs/{job_id}/youtube-metadata")
    assert yt_resp.status_code == 200
    yt_data = yt_resp.json()
    assert len(yt_data["title_options"]) > 0
    assert len(yt_data["chapters"]) > 0

    # 8. /api/system/prune
    prune_resp = client.post("/api/system/prune?retention_hours=24")
    assert prune_resp.status_code == 200
    prune_data = prune_resp.json()
    assert "files_scanned" in prune_data
    assert "files_deleted" in prune_data
