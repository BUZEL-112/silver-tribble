"""Unit and integration tests for ModelRegistryService and role fallback chains."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.config import Settings, flatten_yaml_data
from src.models.schemas import ModelDefinition
from src.services.clustering_service import ClusteringService
from src.services.model_registry_service import ModelRegistryService
from src.services.script_service import ScriptService


@pytest.mark.unit
def test_normalize_embedding_url() -> None:
    """Verify conversational endpoint paths are stripped for embedding endpoints."""
    service = ModelRegistryService()

    # Conversational suffixes should be stripped
    assert (
        service.normalize_embedding_url("http://localhost:8000/v1/chat/completions")
        == "http://localhost:8000/v1"
    )
    assert (
        service.normalize_embedding_url("http://localhost:8000/v1/chat")
        == "http://localhost:8000/v1"
    )
    assert (
        service.normalize_embedding_url("http://localhost:8000/v1/completions")
        == "http://localhost:8000/v1"
    )

    # Google endpoint formatting
    assert (
        service.normalize_embedding_url("https://generativelanguage.googleapis.com/v1beta/openai")
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )

    # Bare host defaults to /v1
    assert service.normalize_embedding_url("http://localhost:11434") == "http://localhost:11434/v1"


@pytest.mark.unit
def test_flatten_yaml_data_model_registry_and_roles() -> None:
    """Verify flatten_yaml_data correctly parses model_registry and roles lists."""
    raw_data = {
        "model_registry": [
            {
                "name": "primary-gemini",
                "model_name": "gemini-3.5-flash-lite",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key": "test-key-1",
                "api_format": "openai",
                "endpoint_type": "chat",
            },
            {
                "name": "backup-claude",
                "model_name": "claude-3-5-sonnet-20241022",
                "base_url": "https://api.anthropic.com/v1",
                "api_key": "test-key-2",
                "api_format": "anthropic",
                "endpoint_type": "chat",
            },
        ],
        "roles": {
            "planning": ["primary-gemini", "backup-claude"],
            "writing": ["backup-claude"],
            "embedding": ["local-embed"],
        },
    }

    flat = flatten_yaml_data(raw_data)
    assert len(flat["model_registry"]) == 2
    assert flat["roles"]["planning"] == ["primary-gemini", "backup-claude"]
    assert flat["roles"]["writing"] == ["backup-claude"]
    assert flat["roles"]["embedding"] == ["local-embed"]


@pytest.mark.unit
def test_backward_compatibility_legacy_config() -> None:
    """Verify legacy scalar models auto-adapt to fallback roles without crashing."""
    legacy_data = {
        "models": {
            "planning": "gpt-4o-mini",
            "writing": "deepseek-chat",
            "embedding": "text-embedding-3-small",
        }
    }
    flat = flatten_yaml_data(legacy_data)
    assert flat["llm_planning_model"] == "gpt-4o-mini"
    assert flat["roles"]["planning"] == ["gpt-4o-mini"]
    assert flat["roles"]["writing"] == ["deepseek-chat"]
    assert flat["roles"]["embedding"] == ["text-embedding-3-small"]


@pytest.mark.unit
def test_fallback_chain_success_on_second_model(action_repo) -> None:
    """Verify first model failure falls back to second model and logs a warning."""
    service = ModelRegistryService(action_log_repo=action_repo)

    model1 = ModelDefinition(
        name="failing-model",
        model_name="fail-gpt",
        base_url="http://localhost:9999/v1",
        api_key="bad-key",
    )
    model2 = ModelDefinition(
        name="working-model",
        model_name="success-gpt",
        base_url="http://localhost:8000/v1",
        api_key="good-key",
    )

    with patch.object(service, "call_chat_completion") as mock_call:
        mock_call.side_effect = [
            RuntimeError("Connection refused on primary model"),
            ('{"title": "Valid Script"}', {"total_tokens": 150}),
        ]

        with patch.object(
            Settings, "get_model_definitions_for_role", return_value=[model1, model2]
        ):
            content, model_name, chosen_def, usage = service.execute_role_fallback_chat(
                role="planning",
                messages=[{"role": "user", "content": "Test prompt"}],
                job_id=42,
            )

            assert content == '{"title": "Valid Script"}'
            assert model_name == "success-gpt"
            assert chosen_def.name == "working-model"
            assert usage["total_tokens"] == 150

    # Verify an action log entry was saved recording the fallback warning
    recent_logs = action_repo.get_recent_logs(stage="planning_fallback")
    assert len(recent_logs) >= 1
    assert recent_logs[0].status == "warning"
    assert "failing-model" in recent_logs[0].message
    assert recent_logs[0].job_id == 42


@pytest.mark.unit
def test_all_models_fail_raises_runtime_error() -> None:
    """Verify that when all models in the fallback chain fail, a RuntimeError is raised."""
    service = ModelRegistryService()

    model1 = ModelDefinition(name="fail1", model_name="m1")
    model2 = ModelDefinition(name="fail2", model_name="m2")

    with patch.object(service, "call_chat_completion") as mock_call:
        mock_call.side_effect = [
            RuntimeError("Server error 500"),
            RuntimeError("Rate limit 429"),
        ]

        with patch.object(
            Settings, "get_model_definitions_for_role", return_value=[model1, model2]
        ):
            with pytest.raises(RuntimeError) as exc_info:
                service.execute_role_fallback_chat(
                    role="planning",
                    messages=[{"role": "user", "content": "Test prompt"}],
                )

            assert "All 2 configured models failed for role 'planning'" in str(exc_info.value)
            assert "Server error 500" in str(exc_info.value)
            assert "Rate limit 429" in str(exc_info.value)


@pytest.mark.unit
def test_anthropic_format_dispatch() -> None:
    """Verify Anthropic Messages API format formats payload and parses text correctly."""
    service = ModelRegistryService()
    claude_def = ModelDefinition(
        name="claude-model",
        model_name="claude-3-5-haiku-20241022",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-test-key",
        api_format="anthropic",
        extra_headers={"x-custom-header": "test-val"},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": "Anthropic response message"}],
        "usage": {"input_tokens": 40, "output_tokens": 15},
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        content, usage = service.call_chat_completion(
            model_def=claude_def,
            messages=[
                {"role": "system", "content": "System directive"},
                {"role": "user", "content": "Hello Claude"},
            ],
            temperature=0.5,
        )

        assert content == "Anthropic response message"
        assert usage["prompt_tokens"] == 40
        assert usage["completion_tokens"] == 15
        assert usage["total_tokens"] == 55

        mock_post.assert_called_once()
        called_url, called_kwargs = mock_post.call_args
        assert called_url[0] == "https://api.anthropic.com/v1/messages"
        assert called_kwargs["headers"]["x-api-key"] == "sk-ant-test-key"
        assert called_kwargs["headers"]["x-custom-header"] == "test-val"
        assert called_kwargs["json"]["system"] == "System directive"
        assert called_kwargs["json"]["messages"] == [{"role": "user", "content": "Hello Claude"}]


@pytest.mark.unit
def test_model_override_prepends_chain() -> None:
    """Verify model_override flag puts requested model at front of the execution chain."""
    service = ModelRegistryService()

    primary = ModelDefinition(name="default-planning", model_name="p1")
    override = ModelDefinition(name="override-model", model_name="o1")

    with (
        patch.object(Settings, "get_model_definitions_for_role", return_value=[primary]),
        patch.object(Settings, "get_model_definition_by_name", return_value=override),
    ):
        with patch.object(service, "call_chat_completion") as mock_call:
            mock_call.return_value = ("Success", {"total_tokens": 10})

            _, model_name, chosen_def, _ = service.execute_role_fallback_chat(
                role="planning",
                messages=[{"role": "user", "content": "Prompt"}],
                model_override="override-model",
            )

            assert chosen_def.name == "override-model"
            assert model_name == "o1"


@pytest.mark.unit
def test_script_service_generate_beat_sheet_fallback(article_repo, script_repo, cost_repo) -> None:
    """Verify ScriptService uses ModelRegistryService and records costs."""
    cluster = article_repo.save_story_cluster(
        cluster_hash="hash123",
        title="AI News Breakthrough",
        summary="A major AI model was released.",
        article_ids=[],
    )

    mock_registry_service = MagicMock()
    mock_model_def = ModelDefinition(name="gemini-flash", model_name="gemini-3.5-flash-lite")
    valid_beat_json = """
    {
        "title": "AI Breakthrough",
        "beats": [
            {
                "beat_number": 1,
                "beat_type": "hook",
                "core_point": "New model drops today",
                "visual_direction": "Fast zoom on logo",
                "on_screen_text": "AI MODEL RELEASE",
                "target_duration_seconds": 5.0
            },
            {
                "beat_number": 2,
                "beat_type": "outro",
                "core_point": "Subscribe for updates",
                "visual_direction": "Host signoff card",
                "on_screen_text": "SUBSCRIBE",
                "target_duration_seconds": 5.0
            }
        ]
    }
    """
    mock_registry_service.execute_role_fallback_chat.return_value = (
        valid_beat_json,
        "gemini-3.5-flash-lite",
        mock_model_def,
        {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180},
    )

    service = ScriptService(
        article_repo=article_repo,
        script_repo=script_repo,
        cost_repo=cost_repo,
        model_registry_service=mock_registry_service,
    )

    result = service.generate_beat_sheet(cluster_id=cluster.id)
    assert result.title == "AI Breakthrough"
    assert len(result.beats) == 2
    mock_registry_service.execute_role_fallback_chat.assert_called_once()
    assert mock_registry_service.execute_role_fallback_chat.call_args[1]["role"] == "planning"

    # Verify cost log entry
    total_spend = cost_repo.get_total_spend()
    assert total_spend > 0.0


@pytest.mark.unit
def test_clustering_service_generate_embeddings_fallback(article_repo, cost_repo) -> None:
    """Verify ClusteringService uses ModelRegistryService for embedding generation."""
    from src.models.schemas import FeedItem

    article_repo.save_feed_items(
        [
            FeedItem(
                title="Google Announces New Model",
                link="https://techcrunch.com/google-announces",
                summary="Details on the new Gemini release.",
                source="TechCrunch",
            )
        ]
    )

    mock_registry_service = MagicMock()
    mock_model_def = ModelDefinition(name="gemini-embed", model_name="gemini-embedding-2")
    dummy_vec = [0.1] * 1536
    mock_registry_service.execute_role_fallback_embedding.return_value = (
        [dummy_vec],
        "gemini-embedding-2",
        mock_model_def,
    )

    service = ClusteringService(
        article_repo=article_repo,
        cost_repo=cost_repo,
        model_registry_service=mock_registry_service,
    )

    count = service.generate_embeddings_for_new_articles()
    assert count == 1
    mock_registry_service.execute_role_fallback_embedding.assert_called_once()

    embedded = article_repo.get_all_embedded_articles()
    assert len(embedded) == 1
    assert len(embedded[0].embedding) == 1536
