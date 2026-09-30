"""Tests for VisualConfigService: preset definitions, visual configuration reading, preset application, and persistence."""

from pathlib import Path
import pytest
from src.core.config import settings
from src.models.schemas import VisualConfigUpdateRequest
from src.services.visual_config_service import VisualConfigService


@pytest.fixture(autouse=True)
def restore_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create a temporary test config.yaml and restore settings after test."""
    orig_aspect = settings.aspect_ratio
    orig_beats = settings.target_beats
    orig_time_limit = settings.time_limit_hours
    orig_max_clusters = settings.max_clusters
    orig_voice = getattr(settings, "tts_voice", "Puck")
    orig_tts_provider = settings.tts_provider
    orig_caption_style = settings.caption_style

    test_yaml = tmp_path / "test_config.yaml"
    test_yaml.write_text("aspect_ratio: '9:16'\ntarget_beats: 5\n", encoding="utf-8")
    monkeypatch.setenv("APP_CONFIG_FILE", str(test_yaml))

    yield

    settings.aspect_ratio = orig_aspect
    settings.target_beats = orig_beats
    settings.time_limit_hours = orig_time_limit
    settings.max_clusters = orig_max_clusters
    settings.tts_voice = orig_voice
    settings.tts_provider = orig_tts_provider
    settings.caption_style = orig_caption_style


def test_list_presets() -> None:
    """Verify catalog of one-click visual configuration presets."""
    svc = VisualConfigService()
    presets = svc.list_presets()
    preset_ids = [p.id for p in presets]

    assert "viral_shorts_9_16" in preset_ids
    assert "widescreen_documentary_16_9" in preset_ids
    assert "high_retention_meme" in preset_ids
    assert "fast_draft_low_cost" in preset_ids


def test_get_visual_config() -> None:
    """Verify reading active visual configuration from settings."""
    svc = VisualConfigService()
    config = svc.get_visual_config()

    assert config.aspect_ratio in ["9:16", "16:9"]
    assert 1 <= config.max_clusters <= 20
    assert 3 <= config.target_beats <= 9
    assert config.tts_provider in ["gemini", "edge_tts", "local", "auto"]


def test_apply_widescreen_preset() -> None:
    """Verify applying widescreen preset updates configuration and active preset identifier."""
    svc = VisualConfigService()
    updated = svc.apply_preset("widescreen_documentary_16_9")

    assert updated.aspect_ratio == "16:9"
    assert updated.target_beats == 7
    assert updated.tts_voice == "Charon"
    assert updated.default_media_type_ratio == 0.85
    assert updated.caption_style == "cinematic"
    assert updated.active_preset == "Widescreen Documentary (16:9)"

    # Verify settings reflection
    assert settings.aspect_ratio == "16:9"
    assert settings.target_beats == 7
    assert settings.tts_voice == "Charon"


def test_apply_high_retention_meme_preset() -> None:
    """Verify applying high-retention meme preset configures 9:16 aspect and GIF dominance."""
    svc = VisualConfigService()
    updated = svc.apply_preset("high_retention_meme")

    assert updated.aspect_ratio == "9:16"
    assert updated.caption_style == "hormozi"
    assert updated.default_media_type_ratio == 0.20
    assert updated.active_preset == "High-Retention Meme (9:16)"


def test_apply_unknown_preset_raises_value_error() -> None:
    """Verify attempting to apply an unknown preset raises ValueError."""
    svc = VisualConfigService()
    with pytest.raises(ValueError, match="Unknown preset"):
        svc.apply_preset("nonexistent_preset_123")


def test_save_visual_config_updates_yaml_and_settings() -> None:
    """Verify saving custom visual configuration updates backing file and runtime settings."""
    svc = VisualConfigService()
    req = VisualConfigUpdateRequest(
        aspect_ratio="16:9",
        target_beats=7,
        max_clusters=8,
        tts_provider="edge_tts",
        tts_voice="en-US-GuyNeural",
        caption_style="karaoke",
        default_media_type_ratio=0.75,
        media_inspector_mode="hil",
        media_inspector_min_score=7.5,
    )

    updated = svc.save_visual_config(req)

    assert updated.aspect_ratio == "16:9"
    assert updated.target_beats == 7
    assert updated.max_clusters == 8
    assert updated.tts_voice == "en-US-GuyNeural"
    assert updated.caption_style == "karaoke"
    assert updated.default_media_type_ratio == 0.75
    assert updated.media_inspector_mode == "hil"
    assert updated.media_inspector_min_score == 7.5

    # Check persistence in backing YAML
    from src.core.config import find_yaml_config_path
    cfg_file = find_yaml_config_path() or Path("config.yaml")
    backing_yaml = cfg_file.read_text(encoding="utf-8")
    assert "16:9" in backing_yaml
    assert "en-US-GuyNeural" in backing_yaml
