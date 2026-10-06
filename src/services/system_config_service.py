"""System configuration and model registry management service."""

import logging
import time
from pathlib import Path
from typing import Any

import yaml

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.core.security import mask_secret
from src.models.schemas import (
    ModelDefinition,
    ModelDefinitionResponse,
    ModelTestResponse,
    RoleFallbacksUpdateRequest,
    RoleMappingsConfig,
    SystemConfigResponse,
    SystemConfigUpdateRequest,
)
from src.services.model_registry_service import ModelRegistryService

logger = logging.getLogger(__name__)


class SystemConfigService:
    """Manages system configuration, model registry catalog, and role fallback chains."""

    def __init__(
        self,
        model_registry_service: ModelRegistryService | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.model_registry_service = model_registry_service or ModelRegistryService()
        self._custom_config_path = config_path

    def _resolve_config_path(self) -> Path:
        """Resolve current active YAML configuration file path."""
        if self._custom_config_path:
            return self._custom_config_path
        return find_yaml_config_path() or Path("config.yaml")

    def _read_yaml_data(self) -> tuple[Path, dict[str, Any]]:
        """Read and parse raw dictionary from the active YAML configuration file."""
        target = self._resolve_config_path()
        if not target.exists():
            return target, {}
        try:
            content = target.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return target, data
            return target, {}
        except Exception as exc:
            logger.warning("Failed to parse YAML file %s: %s", target, exc)
            return target, {}

    def _write_yaml_data(self, target: Path, data: dict[str, Any]) -> None:
        """Persist dictionary to YAML and hot-reload runtime configuration."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
        reload_settings(target)

    def list_models(self) -> list[ModelDefinitionResponse]:
        """Return full catalog of registered models with masked secrets and status."""
        results: list[ModelDefinitionResponse] = []
        for item in settings.model_registry:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            model_name = str(item.get("model_name", name))
            raw_key = item.get("api_key")
            base_url = item.get("base_url")

            # Determine whether key is explicitly configured or inherited from provider
            is_configured = bool(raw_key)
            if not is_configured:
                fallback_key = settings._resolve_fallback_api_key(model_name, base_url)
                is_configured = bool(fallback_key)

            results.append(
                ModelDefinitionResponse(
                    name=name,
                    model_name=model_name,
                    base_url=base_url,
                    api_key_masked=mask_secret(str(raw_key)) if raw_key else None,
                    is_configured=is_configured,
                    api_format=item.get("api_format", "openai"),
                    endpoint_type=item.get("endpoint_type", "chat"),
                    timeout=float(item.get("timeout", 30.0)),
                    extra_headers=item.get("extra_headers") or {},
                )
            )
        return results

    def get_model(self, name: str) -> ModelDefinitionResponse | None:
        """Retrieve a specific registered model by friendly alias."""
        for m in self.list_models():
            if m.name == name:
                return m
        return None

    def add_or_update_model(self, model_def: ModelDefinition) -> ModelDefinitionResponse:
        """Register a new model definition or update an existing one in config.yaml."""
        target, data = self._read_yaml_data()
        registry = data.setdefault("model_registry", [])
        if not isinstance(registry, list):
            registry = []
            data["model_registry"] = registry

        new_entry: dict[str, Any] = {
            "name": model_def.name,
            "model_name": model_def.model_name,
            "base_url": model_def.base_url,
            "api_key": model_def.api_key,
            "api_format": model_def.api_format,
            "endpoint_type": model_def.endpoint_type,
            "timeout": model_def.timeout,
        }
        if model_def.extra_headers:
            new_entry["extra_headers"] = model_def.extra_headers

        # Check if already exists in registry
        found_idx = -1
        for idx, item in enumerate(registry):
            if isinstance(item, dict) and item.get("name") == model_def.name:
                found_idx = idx
                break

        if found_idx >= 0:
            # Preserve existing api_key if update did not supply one
            if not new_entry["api_key"] and registry[found_idx].get("api_key"):
                new_entry["api_key"] = registry[found_idx]["api_key"]
            registry[found_idx] = new_entry
        else:
            registry.append(new_entry)

        self._write_yaml_data(target, data)
        model_resp = self.get_model(model_def.name)
        if model_resp is None:
            return ModelDefinitionResponse(
                name=model_def.name,
                model_name=model_def.model_name,
                base_url=model_def.base_url,
                api_key_masked=mask_secret(model_def.api_key),
                is_configured=bool(model_def.api_key),
                api_format=model_def.api_format,
                endpoint_type=model_def.endpoint_type,
                timeout=model_def.timeout,
                extra_headers=model_def.extra_headers,
            )
        return model_resp

    def delete_model(self, name: str) -> bool:
        """Remove a model from model_registry and clean up references in role chains."""
        target, data = self._read_yaml_data()
        registry = data.get("model_registry", [])
        if not isinstance(registry, list):
            return False

        original_count = len(registry)
        data["model_registry"] = [
            item for item in registry if not (isinstance(item, dict) and item.get("name") == name)
        ]

        # Clean up any role references
        roles = data.get("roles", {})
        if isinstance(roles, dict):
            for role_name, chain in roles.items():
                if isinstance(chain, list):
                    roles[role_name] = [x for x in chain if str(x) != name]

        if len(data["model_registry"]) != original_count:
            self._write_yaml_data(target, data)
            return True
        return False

    def get_role_mappings(self) -> RoleMappingsConfig:
        """Return configured model fallback chains for all pipeline roles."""
        return RoleMappingsConfig(
            planning=list(settings.roles.get("planning", [])),
            writing=list(settings.roles.get("writing", [])),
            embedding=list(settings.roles.get("embedding", [])),
            vlm_inspector=list(settings.roles.get("vlm_inspector", [])),
        )

    def update_role_mappings(self, req: RoleFallbacksUpdateRequest) -> RoleMappingsConfig:
        """Update ordered model fallback chains in YAML and reload runtime settings."""
        target, data = self._read_yaml_data()
        roles_block = data.setdefault("roles", {})
        if not isinstance(roles_block, dict):
            roles_block = {}
            data["roles"] = roles_block

        if req.planning is not None:
            roles_block["planning"] = req.planning
            # Also sync legacy models.planning to top of chain
            if req.planning:
                models_block = data.setdefault("models", {})
                if isinstance(models_block, dict):
                    models_block["planning"] = req.planning[0]

        if req.writing is not None:
            roles_block["writing"] = req.writing
            if req.writing:
                models_block = data.setdefault("models", {})
                if isinstance(models_block, dict):
                    models_block["writing"] = req.writing[0]

        if req.embedding is not None:
            roles_block["embedding"] = req.embedding
            if req.embedding:
                models_block = data.setdefault("models", {})
                if isinstance(models_block, dict):
                    models_block["embedding"] = req.embedding[0]

        if req.vlm_inspector is not None:
            roles_block["vlm_inspector"] = req.vlm_inspector
            if req.vlm_inspector:
                media_block = data.setdefault("media", {})
                if isinstance(media_block, dict):
                    media_block["multimodal_model"] = req.vlm_inspector

        self._write_yaml_data(target, data)
        return self.get_role_mappings()

    def test_model_connection(
        self,
        model_name: str,
        prompt: str | None = None,
    ) -> ModelTestResponse:
        """Execute a connectivity test against a configured model endpoint."""
        start_time = time.perf_counter()
        try:
            model_def = settings.get_model_definition_by_name(model_name)
            test_prompt = prompt or "Respond with 'ok' to verify connectivity."

            if model_def.endpoint_type == "chat":
                content, usage = self.model_registry_service.call_chat_completion(
                    model_def=model_def,
                    messages=[{"role": "user", "content": test_prompt}],
                    max_tokens=10,
                )
                latency = round((time.perf_counter() - start_time) * 1000, 1)
                short_reply = content.strip().replace("\n", " ")[:60]
                return ModelTestResponse(
                    model_name=model_name,
                    status="success",
                    latency_ms=latency,
                    message=f"Endpoint responded successfully: {short_reply}",
                )

            if model_def.endpoint_type == "embedding":
                vectors = self.model_registry_service.call_embedding(
                    model_def=model_def,
                    texts=[test_prompt],
                )
                latency = round((time.perf_counter() - start_time) * 1000, 1)
                dim = len(vectors[0]) if vectors and len(vectors) > 0 else 0
                return ModelTestResponse(
                    model_name=model_name,
                    status="success",
                    latency_ms=latency,
                    message=f"Embedding generated with vector dimension {dim}",
                )

            if model_def.endpoint_type == "multimodal":
                # For multimodal, verify client instantiation and credential presence
                if not model_def.api_key:
                    raise ValueError(f"No API key resolved for model '{model_name}'")
                latency = round((time.perf_counter() - start_time) * 1000, 1)
                return ModelTestResponse(
                    model_name=model_name,
                    status="success",
                    latency_ms=latency,
                    message="Multimodal credentials and client configuration validated",
                )

            latency = round((time.perf_counter() - start_time) * 1000, 1)
            return ModelTestResponse(
                model_name=model_name,
                status="success",
                latency_ms=latency,
                message="Endpoint definition is valid",
            )
        except Exception as exc:
            latency = round((time.perf_counter() - start_time) * 1000, 1)
            return ModelTestResponse(
                model_name=model_name,
                status="error",
                latency_ms=latency,
                message=str(exc),
            )

    def get_system_config(self) -> SystemConfigResponse:
        """Extract full system configuration state structured per application config."""
        yaml_path = self._resolve_config_path()
        db_raw = settings.database_url
        masked_db = db_raw.split("@")[-1] if "@" in db_raw else db_raw

        return SystemConfigResponse(
            database={
                "url": masked_db,
                "engine": "sqlite" if "sqlite" in db_raw else "postgresql",
            },
            litellm={
                "base_url": settings.litellm_base_url,
                "api_key_configured": bool(settings.litellm_api_key),
            },
            model_registry=self.list_models(),
            roles=self.get_role_mappings(),
            providers={
                "openai_configured": bool(settings.openai_api_key),
                "deepseek_configured": bool(settings.deepseek_api_key),
                "gemini_configured": bool(settings.gemini_api_key),
                "pexels_configured": bool(settings.pexels_api_key),
                "pixabay_configured": bool(settings.pixabay_api_key),
                "giphy_configured": bool(settings.giphy_api_key),
                "flux_configured": bool(settings.flux_api_key),
                "flux_endpoint": settings.flux_endpoint,
                "image_generation_provider": settings.image_generation_provider,
            },
            tts={
                "provider": settings.tts_provider,
                "endpoint": settings.local_tts_endpoint,
                "path": settings.local_tts_path,
                "model": settings.local_tts_model,
                "voice": settings.local_tts_voice or settings.tts_voice,
                "timeout": settings.local_tts_timeout,
            },
            storage={
                "backend": settings.storage_backend,
                "local_dir": str(settings.storage_local_dir),
                "r2_configured": bool(settings.r2_bucket_name),
                "r2_bucket": settings.r2_bucket_name,
            },
            whisper={
                "model_size": settings.whisper_model_size,
                "device": settings.whisper_device,
            },
            remotion={
                "project_dir": str(settings.remotion_project_dir),
                "output_dir": str(settings.remotion_output_dir),
            },
            clustering={
                "similarity_threshold": settings.similarity_threshold,
                "time_limit_hours": settings.time_limit_hours,
                "max_clusters": settings.max_clusters,
            },
            video={
                "aspect_ratio": settings.aspect_ratio,
                "target_beats": settings.target_beats,
            },
            media={
                "cache_dir": str(settings.media_cache_dir),
                "ratio": settings.default_media_type_ratio,
                "inspector_mode": settings.media_inspector_mode,
                "multimodal_model": settings.media_inspector_model,
                "min_relevance_score": settings.media_inspector_min_score,
                "provider_priority": settings.provider_priority,
                "enabled_providers": settings.enabled_providers,
            },
            timing={
                "intro_delay_seconds": settings.intro_delay_seconds,
                "outro_duration_seconds": settings.outro_duration_seconds,
                "cluster_review_timeout_seconds": settings.cluster_review_timeout_seconds,
            },
            budget={
                "daily_budget_usd": settings.cost_daily_budget_usd,
                "monthly_budget_usd": settings.cost_monthly_budget_usd,
            },
            security={
                "auth_enabled": bool(settings.api_auth_token),
                "admin_password_set": bool(settings.admin_password),
            },
            youtube={
                "configured": bool(settings.youtube_client_id and settings.youtube_refresh_token),
            },
            rss_feeds=settings.rss_feeds,
            config_source=settings.config_source_label,
            config_path=str(yaml_path.resolve()) if yaml_path.exists() else None,
        )

    def update_system_config(self, req: SystemConfigUpdateRequest) -> SystemConfigResponse:
        """Apply modular updates to configuration sections in YAML and reload settings."""
        target, data = self._read_yaml_data()

        # Update LiteLLM
        if req.litellm is not None:
            lt_block = data.setdefault("litellm", {})
            if isinstance(lt_block, dict):
                for k, v in req.litellm.items():
                    if v is not None:
                        lt_block[k] = v

        # Update Providers
        if req.providers is not None:
            p_block = data.setdefault("providers", {})
            if isinstance(p_block, dict):
                for k, v in req.providers.items():
                    if v is not None:
                        p_block[k] = v

        # Update TTS
        if req.tts is not None:
            t_block = data.setdefault("tts", {})
            if isinstance(t_block, dict):
                for k, v in req.tts.items():
                    if v is not None:
                        t_block[k] = v

        # Update Storage
        if req.storage is not None:
            s_block = data.setdefault("storage", {})
            if isinstance(s_block, dict):
                for k, v in req.storage.items():
                    if v is not None:
                        s_block[k] = v

        # Update Whisper
        if req.whisper is not None:
            w_block = data.setdefault("whisper", {})
            if isinstance(w_block, dict):
                for k, v in req.whisper.items():
                    if v is not None:
                        w_block[k] = v

        # Update Remotion
        if req.remotion is not None:
            r_block = data.setdefault("remotion", {})
            if isinstance(r_block, dict):
                for k, v in req.remotion.items():
                    if v is not None:
                        r_block[k] = v

        # Update Clustering
        if req.clustering is not None:
            c_block = data.setdefault("clustering", {})
            if isinstance(c_block, dict):
                for k, v in req.clustering.items():
                    if v is not None:
                        c_block[k] = v

        # Update Video
        if req.video is not None:
            v_block = data.setdefault("video", {})
            if isinstance(v_block, dict):
                for k, v in req.video.items():
                    if v is not None:
                        v_block[k] = v

        # Update Media
        if req.media is not None:
            m_block = data.setdefault("media", {})
            if isinstance(m_block, dict):
                for k, v in req.media.items():
                    if v is not None:
                        m_block[k] = v

        # Update Timing
        if req.timing is not None:
            tm_block = data.setdefault("timing", {})
            if isinstance(tm_block, dict):
                for k, v in req.timing.items():
                    if v is not None:
                        tm_block[k] = v

        # Update Budget
        if req.budget is not None:
            bg_block = data.setdefault("budget", {})
            if isinstance(bg_block, dict):
                for k, v in req.budget.items():
                    if v is not None:
                        bg_block[k] = v
                        if k == "daily_budget_usd":
                            bg_block["daily_usd"] = v
                        elif k == "monthly_budget_usd":
                            bg_block["monthly_usd"] = v

        # Update Security
        if req.security is not None:
            sec_block = data.setdefault("security", {})
            if isinstance(sec_block, dict):
                for k, v in req.security.items():
                    if v is not None:
                        sec_block[k] = v

        self._write_yaml_data(target, data)
        return self.get_system_config()
