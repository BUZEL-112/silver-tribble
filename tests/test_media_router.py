"""Unit and integration tests for MediaRouter, source selection, and provider fallback."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models.schemas import SentenceMediaPlacement, VisualAssetCreate
from src.repositories.asset_repository import AssetRepository
from src.services.brand_card_service import BrandCardService
from src.services.image_search_service import ImageSearchService
from src.services.media_inspector import MediaInspector
from src.services.media_router import MediaRouter
from src.services.storage_service import LocalStorageService


@pytest.fixture
def mock_storage(tmp_path: Path) -> LocalStorageService:
    """Sandbox storage fixture."""
    return LocalStorageService(base_dir=tmp_path / "storage")


def test_routing_source_selection() -> None:
    """Verify router selects appropriate source according to routing rules."""
    router = MediaRouter()

    # Rule 1: Named entity (Dario Amodei / Anthropic) -> google_search
    source, query = router.select_source("Dario Amodei announced a radical pace plan for AI.")
    assert source == "google_search"
    assert "anthropic" in query.lower() or "dario" in query.lower()

    # Rule 1: Company mention (OpenAI) -> google_search
    source, query = router.select_source("OpenAI unveiled their newest reasoning model today.")
    assert source == "google_search"
    assert "openai" in query.lower()

    # Rule 2: Skepticism / comedic beat -> giphy
    source, query = router.select_source(
        "Critics are rolling their eyes at the astronomical promises.",
        beat_info={"beat_type": "skepticism"},
    )
    assert source == "giphy"
    assert "skeptical" in query.lower() or "eye" in query.lower()

    # Rule 3: Infrastructure / hardware -> pexels_video
    source, query = router.select_source(
        "Thousands of server racks were connected inside the new datacenter facility.",
        beat_info={"beat_type": "technical_breakdown", "visual_direction": "server room"},
    )
    assert source == "pexels_video"
    assert query in ["datacenter", "server room", "server racks", "technology"]


def test_core_visual_noun_extraction() -> None:
    """Verify multi-word sentences are reduced to single concrete visual nouns (Rec A)."""
    router = MediaRouter()

    assert router.extract_core_visual_noun("The semiconductor chips are running hot") == "microchip"
    assert router.extract_core_visual_noun("Deep inside the quantum datacenter building") == "datacenter"
    assert router.extract_core_visual_noun("A new robotic arm was deployed on the assembly line") == "robot arm"


def test_brand_card_generation(tmp_path: Path) -> None:
    """Verify BrandCardService renders 9:16 portrait PNG cards for tech entities (Rec C)."""
    svc = BrandCardService()

    card_path = tmp_path / "anthropic_card.png"
    out = svc.generate_card("anthropic", card_path, custom_subtitle="Claude 3.7 Sonnet")

    assert out.exists()
    assert out.stat().st_size > 2000
    assert svc.detect_brand("Claude released by Anthropic") == "anthropic"
    assert svc.detect_brand("Nvidia revealed the Blackwell chip") == "nvidia"


def test_image_search_wikimedia() -> None:
    """Verify ImageSearchService finds public domain portraits for real tech leaders."""
    svc = ImageSearchService()

    result = svc.search_image("Dario Amodei")
    assert result is not None
    url, ext = result
    assert url.startswith("http")
    assert ext in ["jpg", "jpeg", "png", "webp"]


def test_router_route_and_fetch_with_inspector(tmp_path: Path) -> None:
    """Verify route_and_fetch runs candidates through MediaInspector and applies fallbacks."""
    mock_inspector = MagicMock(spec=MediaInspector)
    # Mock inspector to approve candidate
    mock_inspector.inspect_candidate.return_value = (True, "Approved by VLM")

    mock_search = MagicMock(spec=ImageSearchService)
    mock_search.search_image.return_value = ("https://example.com/dario.jpg", "jpg")

    router = MediaRouter(inspector=mock_inspector, image_search_service=mock_search)
    router.media_cache_dir = tmp_path / "cache"
    router.media_cache_dir.mkdir(parents=True, exist_ok=True)

    # Mock download helper
    fake_img = tmp_path / "cache" / "job_1_sent_0.jpg"
    fake_img.write_bytes(b"image_bytes")
    with patch.object(router, "_download", return_value=(True, fake_img)):
        placement = router.route_and_fetch(
            job_id=1,
            sentence_index=0,
            sentence_text="Dario Amodei spoke at Disrupt.",
            start_time=0.0,
            end_time=3.5,
            beat_info={"beat_type": "hook"},
            used_urls=set(),
        )

        assert placement.sentence_index == 0
        assert placement.provider == "google_search"
        assert placement.media_type == "image"
        assert placement.local_path == str(fake_img.resolve())
        mock_inspector.inspect_candidate.assert_called_once()


def test_router_progressive_photo_fallback(tmp_path: Path) -> None:
    """Verify router falls back to Pexels Photo when Pexels Video returns no results (Rec A)."""
    mock_media_svc = MagicMock()
    mock_media_svc.pexels_api_key = "fake_key"
    # Pexels Video returns None (0 portrait videos)
    mock_media_svc.search_pexels.side_effect = [
        None,                                              # Video search fails
        ("https://pexels.com/photo_datacenter.jpg", "jpg")  # Photo search succeeds
    ]

    mock_inspector = MagicMock(spec=MediaInspector)
    mock_inspector.inspect_candidate.return_value = (True, "Approved photo")

    fake_photo = tmp_path / "cache" / "job_2_sent_0.jpg"
    fake_photo.parent.mkdir(parents=True, exist_ok=True)
    fake_photo.write_bytes(b"photo_bytes")
    mock_media_svc.download_asset.return_value = (True, fake_photo)

    router = MediaRouter(inspector=mock_inspector)
    router.media_cache_dir = tmp_path / "cache"

    placement = router.route_and_fetch(
        job_id=2,
        sentence_index=0,
        sentence_text="The datacenter server architecture was expanded.",
        start_time=0.0,
        end_time=4.0,
        beat_info={"beat_type": "technical_breakdown", "visual_direction": "datacenter"},
        used_urls=set(),
        media_service_ref=mock_media_svc,
    )

    assert placement.sentence_index == 0
    assert placement.provider == "pexels"
    assert placement.media_type == "image"
    assert placement.source_url == "https://pexels.com/photo_datacenter.jpg"


def test_asset_library_reuse(tmp_path: Path, asset_repo: AssetRepository) -> None:
    """Verify router reuses existing visual asset from library before external API lookup."""
    fake_asset_file = tmp_path / "cache" / "reusable_server.mp4"
    fake_asset_file.parent.mkdir(parents=True, exist_ok=True)
    fake_asset_file.write_bytes(b"reusable_mp4_bytes")

    # Record verified asset into library
    asset_repo.record_asset(
        VisualAssetCreate(
            asset_hash="test_server_hash",
            source_url="https://example.com/server.mp4",
            local_path=str(fake_asset_file.resolve()),
            media_type="video",
            provider="pexels",
            query="server room",
            tags=["server room", "datacenter", "technology"],
            emotion_tags=["technical_focus"],
            aspect_ratio="9:16",
            vlm_score=9.0,
        )
    )

    router = MediaRouter(asset_repo=asset_repo)
    router.media_cache_dir = tmp_path / "cache"

    placement = router.route_and_fetch(
        job_id=3,
        sentence_index=0,
        sentence_text="The server room is filled with rows of computing racks.",
        start_time=0.0,
        end_time=5.0,
        beat_info={"beat_type": "technical_breakdown", "emotion": "technical_focus", "visual_direction": "server room"},
        used_urls=set(),
    )

    assert placement.provider == "asset_library"
    assert placement.local_path == str(fake_asset_file.resolve())
    assert placement.media_type == "video"


def test_pixabay_fallback(tmp_path: Path) -> None:
    """Verify router falls back to Pixabay when Pexels returns no results."""
    mock_media_svc = MagicMock()
    mock_media_svc.pexels_api_key = "fake_pexels_key"
    mock_media_svc.pixabay_api_key = "fake_pixabay_key"
    # Pexels video & photo return None
    mock_media_svc.search_pexels.return_value = None
    # Pixabay video returns valid URL
    mock_media_svc.search_pixabay.return_value = ("https://pixabay.com/video_robot.mp4", "mp4")

    fake_pixabay_vid = tmp_path / "cache" / "job_4_sent_0_pixabay.mp4"
    fake_pixabay_vid.parent.mkdir(parents=True, exist_ok=True)
    fake_pixabay_vid.write_bytes(b"pixabay_video_bytes")
    mock_media_svc.download_asset.return_value = (True, fake_pixabay_vid)

    mock_inspector = MagicMock(spec=MediaInspector)
    mock_inspector.inspect_candidate.return_value = (True, "Approved Pixabay")

    router = MediaRouter(inspector=mock_inspector)
    router.media_cache_dir = tmp_path / "cache"

    placement = router.route_and_fetch(
        job_id=4,
        sentence_index=0,
        sentence_text="The robotic arm operates seamlessly in the facility.",
        start_time=0.0,
        end_time=4.0,
        beat_info={"beat_type": "context", "visual_direction": "robot arm"},
        used_urls=set(),
        media_service_ref=mock_media_svc,
    )

    assert placement.provider == "pixabay"
    assert placement.media_type == "video"
    assert placement.source_url == "https://pixabay.com/video_robot.mp4"


def test_flux_image_generation_routing(tmp_path: Path) -> None:
    """Verify futuristic or abstract visual directions route to FLUX / AI generation."""
    router = MediaRouter()
    router.media_cache_dir = tmp_path / "cache"

    source, query = router.select_source(
        "A superintelligence singularity emerges inside the futuristic quantum core.",
        beat_info={"beat_type": "breakthrough", "emotion": "awe", "visual_direction": "futuristic quantum core"},
    )
    assert source == "ai_generated"
    assert "quantum" in query.lower() or "singularity" in query.lower()

    # Route and fetch invokes generator
    placement = router.route_and_fetch(
        job_id=5,
        sentence_index=0,
        sentence_text="A superintelligence singularity emerges inside the futuristic quantum core.",
        start_time=0.0,
        end_time=4.5,
        beat_info={"beat_type": "breakthrough", "emotion": "awe", "visual_direction": "futuristic quantum core"},
        used_urls=set(),
    )
    assert placement.provider == "flux_generation"
    assert Path(placement.local_path).exists()

