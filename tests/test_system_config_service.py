"""Tests for SystemConfigService and system configuration endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core.config import settings
from src.models.schemas import (
    ModelDefinition,
    RoleFallbacksUpdateRequest,
    SystemConfigUpdateRequest,
)
from src.services.system_config_service import SystemConfigService
from src.web import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_config_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a dedicated test configuration YAML file for each test."""
    test_yaml_content = """database:
  url: "sqlite:///./data/test_db.db"
litellm:
  base_url: "http://localhost:4000"
  api_key: "sk-litellm-test"
model_registry:
  - name: "test-gemini"
    model_name: "gemini-3.5-flash-lite"
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key: "test-key-gemini"
    api_format: "openai"
    endpoint_type: "chat"
    timeout: 30.0
  - name: "test-deepseek"
    model_name: "deepseek-chat"
    base_url: "https://api.deepseek.com/v1"
    api_key: "test-key-deepseek"
    api_format: "openai"
    endpoint_type: "chat"
    timeout: 30.0
  - name: "test-embed"
    model_name: "gemini-embedding-2"
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    api_key: "test-key-embed"
    api_format: "openai"
    endpoint_type: "embedding"
    timeout: 30.0
roles:
  planning:
    - "test-gemini"
    - "test-deepseek"
  writing:
    - "test-deepseek"
    - "test-gemini"
  embedding:
    - "test-embed"
  vlm_inspector:
    - "test-gemini"
providers:
  openai_api_key: null
  gemini_api_key: "test-gemini-key"
tts:
  provider: "auto"
  endpoint: "http://localhost:8880/v1/audio/speech"
  model: "kokoro"
  voice: "af_heart"
storage:
  backend: "local"
  local_dir: "./data/assets"
clustering:
  similarity_threshold: 0.82
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(test_yaml_content, encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_FILE", str(cfg_file))

    from src.core.config import reload_settings

    reload_settings(cfg_file)
    yield


def test_list_and_get_models() -> None:
    """Verify listing and retrieving model definitions with masked secrets."""
    service = SystemConfigService()
    models = service.list_models()

    assert len(models) >= 3
    aliases = [m.name for m in models]
    assert "test-gemini" in aliases
    assert "test-deepseek" in aliases

    gemini_model = service.get_model("test-gemini")
    assert gemini_model is not None
    assert gemini_model.model_name == "gemini-3.5-flash-lite"
    assert gemini_model.endpoint_type == "chat"
    assert gemini_model.is_configured is True
    # Masked key should not expose full plaintext
    assert gemini_model.api_key_masked != "test-key-gemini"


def test_add_and_delete_model() -> None:
    """Verify registering a new model definition and removing it from catalog."""
    service = SystemConfigService()
    new_model = ModelDefinition(
        name="custom-claude",
        model_name="claude-3-5-sonnet-20241022",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-test-key",
        api_format="anthropic",
        endpoint_type="chat",
        timeout=45.0,
    )

    created = service.add_or_update_model(new_model)
    assert created.name == "custom-claude"
    assert created.api_format == "anthropic"

    # Verify present in settings
    retrieved = service.get_model("custom-claude")
    assert retrieved is not None
    assert retrieved.model_name == "claude-3-5-sonnet-20241022"

    # Now delete model
    deleted = service.delete_model("custom-claude")
    assert deleted is True
    assert service.get_model("custom-claude") is None


def test_role_mappings_update() -> None:
    """Verify updating fallback priority lists for pipeline roles."""
    service = SystemConfigService()
    updated = service.update_role_mappings(
        RoleFallbacksUpdateRequest(
            planning=["test-deepseek", "test-gemini"],
            writing=["test-gemini"],
        )
    )

    assert updated.planning == ["test-deepseek", "test-gemini"]
    assert updated.writing == ["test-gemini"]
    assert settings.roles.get("planning") == ["test-deepseek", "test-gemini"]


def test_get_and_update_system_config() -> None:
    """Verify extracting and updating modular system configuration sections."""
    service = SystemConfigService()
    cfg = service.get_system_config()

    assert cfg.database["engine"] == "sqlite"
    assert cfg.litellm["base_url"] == "http://localhost:4000"
    assert len(cfg.model_registry) >= 3
    assert "planning" in cfg.roles.model_dump()
    assert cfg.tts["provider"] == "auto"

    # Update sections
    updated = service.update_system_config(
        SystemConfigUpdateRequest(
            tts={"provider": "local", "voice": "en_US-lessac"},
            clustering={"similarity_threshold": 0.88},
            budget={"daily_budget_usd": 15.0},
        )
    )

    assert updated.tts["provider"] == "local"
    assert updated.tts["voice"] == "en_US-lessac"
    assert updated.clustering["similarity_threshold"] == 0.88
    assert updated.budget["daily_budget_usd"] == 15.0


def test_system_config_api_endpoints() -> None:
    """Verify FastAPI routes for system configuration and model registry."""
    # 1. Get system config
    res_sys = client.get("/api/config/system")
    assert res_sys.status_code == 200
    data_sys = res_sys.json()
    assert "model_registry" in data_sys
    assert "roles" in data_sys
    assert "tts" in data_sys

    # 2. Get models
    res_models = client.get("/api/config/models")
    assert res_models.status_code == 200
    models_list = res_models.json()
    assert len(models_list) >= 3

    # 3. Add model via API
    res_add = client.post(
        "/api/config/models",
        json={
            "name": "api-model-test",
            "model_name": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-key",
            "api_format": "openai",
            "endpoint_type": "chat",
            "timeout": 25.0,
        },
    )
    assert res_add.status_code == 200
    assert res_add.json()["name"] == "api-model-test"

    # 4. Get and update roles via API
    res_roles = client.get("/api/config/roles")
    assert res_roles.status_code == 200

    res_up_roles = client.post(
        "/api/config/roles",
        json={"planning": ["api-model-test", "test-gemini"]},
    )
    assert res_up_roles.status_code == 200
    assert res_up_roles.json()["planning"] == ["api-model-test", "test-gemini"]

    # 5. Delete model via API
    res_del = client.delete("/api/config/models/api-model-test")
    assert res_del.status_code == 200

    # 6. Update system config via API
    res_up_sys = client.post(
        "/api/config/system",
        json={"tts": {"provider": "edge_tts"}},
    )
    assert res_up_sys.status_code == 200
    assert res_up_sys.json()["tts"]["provider"] == "edge_tts"
