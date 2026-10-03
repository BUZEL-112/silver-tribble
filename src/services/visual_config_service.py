"""Visual pipeline configuration and preset service."""

from pathlib import Path
from typing import Any

import yaml

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.models.schemas import VisualConfigSchema, VisualConfigUpdateRequest, VisualPresetInfo


class VisualConfigService:
    """Manages visual buttons configuration, profiles, and runtime hot-reloading."""

    PRESETS: dict[str, dict[str, Any]] = {
        "viral_shorts_9_16": {
            "name": "Viral Shorts (9:16)",
            "badge": "Mobile Vertical",
            "description": (
                "9:16 vertical format with kinetic Hormozi captions, 5 beats, "
                "balanced stock footage and reaction GIFs."
            ),
            "values": {
                "aspect_ratio": "9:16",
                "target_beats": 5,
                "time_limit_hours": 24,
                "max_clusters": 5,
                "tts_provider": "gemini",
                "tts_voice": "Puck",
                "caption_style": "hormozi",
                "caption_level": 30.0,
                "caption_font_size": 48,
                "caption_uppercase": True,
                "default_media_type_ratio": 0.5,
                "media_inspector_mode": "multimodal",
                "media_inspector_min_score": 6.0,
                "llm_planning_model": "gemini-2.0-flash",
                "llm_writing_model": "gemini-2.0-flash",
                "similarity_threshold": 0.82,
            },
        },
        "widescreen_documentary_16_9": {
            "name": "Widescreen Documentary (16:9)",
            "badge": "Desktop Horizontal",
            "description": (
                "16:9 widescreen format with deep authoritative narrator, 7 beats, "
                "and 85% stock footage."
            ),
            "values": {
                "aspect_ratio": "16:9",
                "target_beats": 7,
                "time_limit_hours": 48,
                "max_clusters": 4,
                "tts_provider": "gemini",
                "tts_voice": "Charon",
                "caption_style": "cinematic",
                "caption_level": 15.0,
                "caption_font_size": 36,
                "caption_uppercase": False,
                "default_media_type_ratio": 0.85,
                "media_inspector_mode": "multimodal",
                "media_inspector_min_score": 7.0,
                "llm_planning_model": "gemini-2.0-flash",
                "llm_writing_model": "gemini-2.0-flash",
                "similarity_threshold": 0.84,
            },
        },
        "high_retention_meme": {
            "name": "High-Retention Meme (9:16)",
            "badge": "Reaction Meme Focus",
            "description": (
                "9:16 vertical shorts powered by 80% reaction GIFs and punchy kinetic subtitles."
            ),
            "values": {
                "aspect_ratio": "9:16",
                "target_beats": 5,
                "time_limit_hours": 24,
                "max_clusters": 5,
                "tts_provider": "edge_tts",
                "tts_voice": "en-US-ChristopherNeural",
                "caption_style": "hormozi",
                "caption_level": 30.0,
                "caption_font_size": 52,
                "caption_uppercase": True,
                "default_media_type_ratio": 0.2,
                "media_inspector_mode": "off",
                "media_inspector_min_score": 5.0,
                "llm_planning_model": "gpt-4o-mini",
                "llm_writing_model": "deepseek-chat",
                "similarity_threshold": 0.80,
            },
        },
        "fast_draft_low_cost": {
            "name": "Fast Draft / Low-Cost",
            "badge": "Minimal Latency",
            "description": (
                "Rapid 3-beat outline with offline or edge speech synthesis "
                "and local asset prioritization."
            ),
            "values": {
                "aspect_ratio": "9:16",
                "target_beats": 3,
                "time_limit_hours": 12,
                "max_clusters": 3,
                "tts_provider": "edge_tts",
                "tts_voice": "en-US-ChristopherNeural",
                "caption_style": "minimal",
                "caption_level": 25.0,
                "caption_font_size": 40,
                "caption_uppercase": False,
                "default_media_type_ratio": 0.5,
                "media_inspector_mode": "off",
                "media_inspector_min_score": 5.0,
                "llm_planning_model": "gpt-4o-mini",
                "llm_writing_model": "gpt-4o-mini",
                "similarity_threshold": 0.82,
            },
        },
        "tech_journalist": {
            "name": "Tech Journalist & Analyst",
            "badge": "Serious Editorial",
            "description": (
                "Authoritative, analytical tech breakdown with rigorous skepticism "
                "and deep industry context."
            ),
            "values": {
                "aspect_ratio": "16:9",
                "target_beats": 6,
                "time_limit_hours": 48,
                "max_clusters": 4,
                "tts_provider": "gemini",
                "tts_voice": "Charon",
                "caption_style": "cinematic",
                "caption_level": 15.0,
                "caption_font_size": 36,
                "caption_uppercase": False,
                "default_media_type_ratio": 0.8,
                "media_inspector_mode": "multimodal",
                "media_inspector_min_score": 7.0,
                "llm_planning_model": "gemini-2.0-flash",
                "llm_writing_model": "gemini-2.0-flash",
                "similarity_threshold": 0.85,
            },
        },
    }

    def list_presets(self) -> list[VisualPresetInfo]:
        """Return metadata for all available visual configuration presets."""
        results: list[VisualPresetInfo] = []
        for pid, data in self.PRESETS.items():
            results.append(
                VisualPresetInfo(
                    id=pid,
                    name=data["name"],
                    badge=data["badge"],
                    description=data["description"],
                )
            )
        return results

    def get_visual_config(self) -> VisualConfigSchema:
        """Extract current visual configuration parameters from active runtime settings."""
        # Determine voice label
        current_voice = getattr(settings, "tts_voice", "Puck")
        if settings.tts_provider == "local" and getattr(settings, "local_tts_voice", None):
            current_voice = settings.local_tts_voice

        return VisualConfigSchema(
            aspect_ratio=settings.aspect_ratio,
            target_beats=settings.target_beats,
            max_clusters=settings.max_clusters,
            time_limit_hours=settings.time_limit_hours,
            tts_provider=settings.tts_provider,
            tts_voice=current_voice,
            caption_style=settings.caption_style,
            caption_level=settings.caption_level,
            caption_font_size=settings.caption_font_size,
            caption_uppercase=settings.caption_uppercase,
            default_media_type_ratio=settings.default_media_type_ratio,
            media_inspector_mode=settings.media_inspector_mode,
            media_inspector_min_score=settings.media_inspector_min_score,
            llm_planning_model=settings.llm_planning_model,
            llm_writing_model=settings.llm_writing_model,
            similarity_threshold=settings.similarity_threshold,
            active_preset=getattr(settings, "_active_preset", None),
        )

    def apply_preset(self, preset_id: str) -> VisualConfigSchema:
        """Apply a pre-configured pipeline preset and persist parameters to config.yaml."""
        if preset_id not in self.PRESETS:
            raise ValueError(f"Unknown preset identifier: {preset_id}")

        preset_info = self.PRESETS[preset_id]
        preset_data = dict(preset_info["values"])
        req = VisualConfigUpdateRequest.model_validate(preset_data)
        req.active_preset = preset_info["name"]

        updated_config = self.save_visual_config(req)
        setattr(settings, "_active_preset", preset_info["name"])
        return updated_config

    def save_visual_config(self, req: VisualConfigUpdateRequest) -> VisualConfigSchema:
        """Persist visual form controls into active YAML configuration and hot-reload."""
        config_path = find_yaml_config_path() or Path("config.yaml")
        if not config_path.exists():
            config_path.write_text("# Auto-generated visual config\n", encoding="utf-8")

        raw_text = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text) or {}
        if not isinstance(data, dict):
            data = {}

        # 1. Video and format section
        video_block = data.setdefault("video", {})
        if req.aspect_ratio is not None:
            video_block["aspect_ratio"] = req.aspect_ratio
            settings.aspect_ratio = req.aspect_ratio
        if req.target_beats is not None:
            video_block["target_beats"] = req.target_beats
            settings.target_beats = req.target_beats

        # 2. Clustering section
        clustering_block = data.setdefault("clustering", {})
        if req.max_clusters is not None:
            clustering_block["max_clusters"] = req.max_clusters
            settings.max_clusters = req.max_clusters
        if req.time_limit_hours is not None:
            clustering_block["time_limit_hours"] = req.time_limit_hours
            settings.time_limit_hours = req.time_limit_hours
        if req.similarity_threshold is not None:
            clustering_block["similarity_threshold"] = req.similarity_threshold
            settings.similarity_threshold = req.similarity_threshold

        # 3. TTS section
        tts_block = data.setdefault("tts", {})
        if req.tts_provider is not None:
            tts_block["provider"] = req.tts_provider
            settings.tts_provider = req.tts_provider
        if req.tts_voice is not None:
            tts_block["voice"] = req.tts_voice
            settings.tts_voice = req.tts_voice
            if req.tts_provider == "local" or settings.tts_provider == "local":
                settings.local_tts_voice = req.tts_voice

        # 4. Captions section
        captions_block = data.setdefault("captions", {})
        if req.caption_style is not None:
            captions_block["style"] = req.caption_style
            settings.caption_style = req.caption_style
        if req.caption_level is not None:
            captions_block["level"] = req.caption_level
            settings.caption_level = req.caption_level
        if req.caption_font_size is not None:
            captions_block["font_size"] = req.caption_font_size
            settings.caption_font_size = req.caption_font_size
        if req.caption_uppercase is not None:
            captions_block["uppercase"] = req.caption_uppercase
            settings.caption_uppercase = req.caption_uppercase

        # 5. Media and inspector section
        media_block = data.setdefault("media", {})
        if req.default_media_type_ratio is not None:
            media_block["ratio"] = req.default_media_type_ratio
            settings.default_media_type_ratio = req.default_media_type_ratio
        if req.media_inspector_mode is not None:
            media_block["inspector_mode"] = req.media_inspector_mode
            settings.media_inspector_mode = req.media_inspector_mode
        if req.media_inspector_min_score is not None:
            media_block["min_relevance_score"] = req.media_inspector_min_score
            settings.media_inspector_min_score = req.media_inspector_min_score

        # 6. Models section
        models_block = data.setdefault("models", {})
        if req.llm_planning_model is not None:
            models_block["planning"] = req.llm_planning_model
            settings.llm_planning_model = req.llm_planning_model
        if req.llm_writing_model is not None:
            models_block["writing"] = req.llm_writing_model
            settings.llm_writing_model = req.llm_writing_model

        # Write YAML and hot reload
        config_path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
        reload_settings(config_path)

        if req.active_preset is not None:
            setattr(settings, "_active_preset", req.active_preset)

        return self.get_visual_config()
