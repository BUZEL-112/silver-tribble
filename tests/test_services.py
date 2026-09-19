"""Integration and unit tests for services: CaptionService and RssService."""

from pathlib import Path
from unittest.mock import MagicMock

from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.services.caption_service import CaptionService
from src.services.rss_service import RssService
from src.services.storage_service import LocalStorageService


def test_caption_service_fallback(
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    service = CaptionService(
        storage_service=temp_storage,
        cost_repo=cost_repo,
    )
    # Mock model that returns very few words
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], None)
    service._model = mock_model

    dummy_audio = tmp_path / "dummy.wav"
    dummy_audio.write_bytes(b"DUMMY_AUDIO")
    audio_path = temp_storage.save_file(dummy_audio, "audio/test.wav")

    reference_text = "This is a five word sentence."
    json_path, captions = service.generate_captions(
        audio_path_or_url=audio_path,
        job_id=99,
        reference_text=reference_text,
        total_duration=10.0,
    )

    assert len(captions) == 6
    assert [c.word for c in captions] == ["This", "is", "a", "five", "word", "sentence."]
    assert captions[0].start == 0.0
    assert captions[-1].end <= 10.0
    assert Path(json_path).exists()


def test_caption_service_sparse_whisper_triggers_fallback(
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    service = CaptionService(
        storage_service=temp_storage,
        cost_repo=cost_repo,
    )
    # Simulate Whisper returning only 1 hallucinated word for a 10-word sentence
    mock_word = MagicMock()
    mock_word.word = "hallucination"
    mock_word.start = 1.0
    mock_word.end = 2.0
    mock_word.probability = 0.2
    mock_segment = MagicMock()
    mock_segment.words = [mock_word]

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], None)
    service._model = mock_model

    dummy_audio = tmp_path / "dummy2.wav"
    dummy_audio.write_bytes(b"DUMMY_AUDIO")
    audio_path = temp_storage.save_file(dummy_audio, "audio/test2.wav")

    reference_text = "OpenAI releases new reasoning model with advanced coding benchmarks."
    _json_path, captions = service.generate_captions(
        audio_path_or_url=audio_path,
        job_id=100,
        reference_text=reference_text,
        total_duration=8.0,
    )

    # Since 1 word < 9 words * 0.4, it should fallback to all 9 reference words
    assert len(captions) == 9
    assert captions[0].word == "OpenAI"
    assert captions[-1].word == "benchmarks."


def test_rss_service_clean_html():
    service = RssService()
    html_input = (
        "<p>Breaking <strong>AI</strong> news! <a href='https://example.com'>Read more</a></p>"
    )
    cleaned = service.clean_html(html_input)
    assert cleaned == "Breaking AI news! Read more"


def test_rss_service_feed_initialization_and_normalization():
    custom_feeds = [
        {"name": "Hacker News AI", "url": "https://hnrss.org/newest?q=AI"},
        "https://news.ycombinator.com/rss",
    ]
    service = RssService(feeds=custom_feeds)
    assert len(service.feeds) == 2
    assert service.feeds[0]["name"] == "Hacker News AI"
    assert service.feeds[1] == "https://news.ycombinator.com/rss"


def test_flatten_yaml_data_rss_feeds_normalization():
    from src.core.config import flatten_yaml_data

    yaml_dict = {
        "rss_feeds": [
            {"name": "Custom Source", "url": "https://example.com/rss"},
            "https://news.ycombinator.com/rss",
        ]
    }
    flat = flatten_yaml_data(yaml_dict)
    assert len(flat["rss_feeds"]) == 2
    assert flat["rss_feeds"][0] == {"name": "Custom Source", "url": "https://example.com/rss"}
    assert flat["rss_feeds"][1]["name"] == "news.ycombinator.com"
    assert flat["rss_feeds"][1]["url"] == "https://news.ycombinator.com/rss"


def test_article_repository_cluster_status(article_repo: ArticleRepository):
    cluster = article_repo.save_story_cluster(
        cluster_hash="hash_123",
        title="Test Cluster",
        summary="Summary text",
        article_ids=[1, 2],
    )
    assert cluster.status == "pending"

    article_repo.update_cluster_status(cluster.id, "scripted")
    fetched = article_repo.get_cluster_by_id(cluster.id)
    assert fetched is not None
    assert fetched.status == "scripted"


def test_script_service_client_resolution(
    article_repo: ArticleRepository,
    cost_repo: CostRepository,
):
    from src.repositories.script_repository import ScriptRepository
    from src.services.script_service import ScriptService

    script_repo = MagicMock(spec=ScriptRepository)
    service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
        openai_key="sk-openai-test-key",
        deepseek_key="sk-deepseek-test-key",
    )

    # gpt-4o-mini should route to OpenAI
    openai_client = service._resolve_client("gpt-4o-mini")
    assert "api.openai.com" in str(openai_client.base_url)
    assert openai_client.api_key == "sk-openai-test-key"

    # deepseek-chat should route to DeepSeek
    deepseek_client = service._resolve_client("deepseek-chat")
    assert "api.deepseek.com" in str(deepseek_client.base_url)
    assert deepseek_client.api_key == "sk-deepseek-test-key"

    # Explicit base URL overrides model routing
    proxy_service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-v1-test",
    )
    custom_client = proxy_service._resolve_client("deepseek-chat")
    assert "openrouter.ai" in str(custom_client.base_url)
    assert custom_client.api_key == "sk-or-v1-test"


def test_clustering_service_local_and_byok(
    article_repo: ArticleRepository,
    cost_repo: CostRepository,
):
    from src.services.clustering_service import ClusteringService

    # Verify local model detection
    assert ClusteringService.is_local_model("local") is True
    assert ClusteringService.is_local_model("local:BAAI/bge-small-en-v1.5") is True
    assert ClusteringService.is_local_model("BAAI/bge-small-en-v1.5") is True
    assert ClusteringService.is_local_model("text-embedding-3-small") is False

    # Verify custom BYOK endpoint resolution
    byok_service = ClusteringService(
        article_repo=article_repo,
        cost_repo=cost_repo,
        embedding_base_url="http://localhost:11434/v1",
        embedding_api_key="ollama-key",
    )
    ollama_client = byok_service._resolve_client("nomic-embed-text")
    assert "localhost:11434" in str(ollama_client.base_url)
    assert ollama_client.api_key == "ollama-key"

    # Verify Google AI Studio embedding model routing
    assert ClusteringService.is_google_embedding_model("text-embedding-004") is True
    google_service = ClusteringService(
        article_repo=article_repo,
        cost_repo=cost_repo,
        gemini_key="AIzaSyGoogleTestKey",
    )
    google_client = google_service._resolve_client("text-embedding-004")
    assert "googleapis.com" in str(google_client.base_url)
    assert google_client.api_key == "AIzaSyGoogleTestKey"
