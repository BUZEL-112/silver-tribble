"""Unit tests for MediaService, keyword extraction, and asset retrieval."""

from pathlib import Path

from src.models.schemas import WordCaption
from src.repositories.cost_repository import CostRepository
from src.services.media_service import MediaService
from src.services.storage_service import LocalStorageService


def test_keyword_extraction(tmp_path: Path, cost_repo: CostRepository) -> None:
    """Verify keyword extraction strips stop words and punctuation."""
    storage = LocalStorageService(base_dir=tmp_path / "assets")
    svc = MediaService(
        storage_service=storage,
        cost_repo=cost_repo,
        media_cache_dir=tmp_path / "media",
    )

    text = "The quick brown fox is jumping over the lazy dog in artificial intelligence!"
    keywords = svc.extract_keywords(text, max_keywords=3)

    assert len(keywords) <= 3
    assert len(keywords) >= 1
    # Check that common stopwords were eliminated
    assert "the" not in keywords
    assert "is" not in keywords
    assert "in" not in keywords


def test_caption_sentence_grouping(tmp_path: Path, cost_repo: CostRepository) -> None:
    """Verify word captions are grouped into sentences with valid timestamps."""
    storage = LocalStorageService(base_dir=tmp_path / "assets")
    svc = MediaService(
        storage_service=storage,
        cost_repo=cost_repo,
        media_cache_dir=tmp_path / "media",
    )

    captions = [
        WordCaption(word="OpenAI", start=0.0, end=0.5),
        WordCaption(word="released", start=0.6, end=1.0),
        WordCaption(word="GPT-5.", start=1.1, end=1.8),
        WordCaption(word="It", start=2.5, end=2.8),
        WordCaption(word="is", start=2.9, end=3.1),
        WordCaption(word="superfast!", start=3.2, end=3.9),
    ]

    sentences = svc.group_captions_into_sentences(captions)
    assert len(sentences) == 2

    assert sentences[0]["start_time"] == 0.0
    assert sentences[0]["end_time"] == 1.8
    assert "OpenAI released GPT-5." in sentences[0]["text"]

    assert sentences[1]["start_time"] == 2.5
    assert sentences[1]["end_time"] == 3.9
    assert "It is superfast!" in sentences[1]["text"]


def test_media_service_graceful_fallback(tmp_path: Path, cost_repo: CostRepository) -> None:
    """Verify MediaService returns fallback provider without error when no keys are provided."""
    storage = LocalStorageService(base_dir=tmp_path / "assets")
    svc = MediaService(
        storage_service=storage,
        cost_repo=cost_repo,
        pexels_api_key="",
        giphy_api_key="",
        media_cache_dir=tmp_path / "media",
    )

    captions = [
        WordCaption(word="Robots", start=0.0, end=0.8),
        WordCaption(word="are", start=0.9, end=1.2),
        WordCaption(word="everywhere.", start=1.3, end=2.0),
    ]

    placements = svc.process_media_for_job(job_id=10, captions=captions)

    assert len(placements) == 1
    assert placements[0].provider == "fallback"
    assert placements[0].local_path == "" or Path(placements[0].local_path).exists()
    assert placements[0].sentence_index == 0
    assert placements[0].start_time == 0.0
    assert placements[0].end_time == 2.0
    assert len(placements[0].keywords) > 0
