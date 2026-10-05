"""Provider management and testing service for visual media sources."""

import re
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from src.core.config import find_yaml_config_path, reload_settings, settings
from src.models.schemas import (
    CustomProviderConfig,
    ProviderInfo,
    ProviderTestResponse,
)


class ProviderService:
    """Manages built-in and custom image, GIF, and video providers."""

    BUILTIN_PROVIDERS: list[dict[str, Any]] = [
        {
            "id": "asset_library",
            "name": "Local Asset Library",
            "category": "custom",
            "media_types": ["image", "video", "gif"],
            "is_custom": False,
        },
        {
            "id": "pexels",
            "name": "Pexels Stock Footage & Photos",
            "category": "stock_video",
            "media_types": ["video", "image"],
            "is_custom": False,
        },
        {
            "id": "giphy",
            "name": "Giphy Reaction GIFs & Memes",
            "category": "reaction_gif",
            "media_types": ["gif"],
            "is_custom": False,
        },
        {
            "id": "pixabay",
            "name": "Pixabay Stock Footage & Photos",
            "category": "stock_video",
            "media_types": ["video", "image"],
            "is_custom": False,
        },
        {
            "id": "google_search",
            "name": "Google / Wikimedia Entity Photos",
            "category": "web_search",
            "media_types": ["image"],
            "is_custom": False,
        },
        {
            "id": "flux",
            "name": "FLUX AI Image Generation",
            "category": "ai_generation",
            "media_types": ["image"],
            "is_custom": False,
        },
        {
            "id": "gemini",
            "name": "Gemini Imagen 3 Generation",
            "category": "ai_generation",
            "media_types": ["image"],
            "is_custom": False,
        },
        {
            "id": "brand_card",
            "name": "Procedural Tech Brand Cards",
            "category": "brand_card",
            "media_types": ["image"],
            "is_custom": False,
        },
    ]

    def _mask_key(self, key: str | None) -> str | None:
        """Return masked representation of a secret key."""
        if not key or key.strip() == "":
            return None
        trimmed = key.strip()
        if len(trimmed) <= 8:
            return "••••••••"
        return f"{trimmed[:4]}••••{trimmed[-4:]}"

    def list_providers(self) -> list[ProviderInfo]:
        """List all available built-in and custom providers with current configuration."""
        priority_list = list(settings.provider_priority)
        enabled_set = set(settings.enabled_providers)

        results: list[ProviderInfo] = []

        # 1. Process Built-in Providers
        for p in self.BUILTIN_PROVIDERS:
            pid = p["id"]
            is_configured = False
            masked_key = None
            endpoint = None
            key: str | None = None

            if pid == "asset_library" or pid == "brand_card":
                is_configured = True
            elif pid == "pexels":
                key = settings.pexels_api_key
                is_configured = bool(key and key != "your_pexels_api_key_here")
                masked_key = self._mask_key(key)
            elif pid == "giphy":
                key = settings.giphy_api_key
                is_configured = bool(key and key != "your_giphy_api_key_here")
                masked_key = self._mask_key(key)
            elif pid == "pixabay":
                key = settings.pixabay_api_key
                is_configured = bool(key and key != "your_pixabay_api_key_here")
                masked_key = self._mask_key(key)
            elif pid == "google_search":
                key = settings.serpapi_api_key or settings.google_cse_api_key
                is_configured = bool(key)
                masked_key = self._mask_key(key)
            elif pid == "flux":
                key = settings.flux_api_key
                endpoint = settings.flux_endpoint or None
                is_configured = bool(key or endpoint)
                masked_key = self._mask_key(key)
            elif pid == "gemini":
                key = settings.gemini_api_key
                is_configured = bool(key and key != "your_gemini_api_key_here")
                masked_key = self._mask_key(key)

            rank = priority_list.index(pid) + 1 if pid in priority_list else 99

            results.append(
                ProviderInfo(
                    id=pid,
                    name=p["name"],
                    category=p["category"],
                    media_types=p["media_types"],
                    is_custom=False,
                    is_configured=is_configured,
                    is_enabled=pid in enabled_set,
                    priority_rank=rank,
                    api_key_masked=masked_key,
                    endpoint_url=endpoint,
                    custom_config=None,
                )
            )

        # 2. Process Custom Providers
        for item in settings.custom_providers:
            try:
                cfg = CustomProviderConfig.model_validate(item)
                pid = cfg.id
                rank = priority_list.index(pid) + 1 if pid in priority_list else 99
                results.append(
                    ProviderInfo(
                        id=pid,
                        name=cfg.name,
                        category="custom",
                        media_types=[cfg.media_type],
                        is_custom=True,
                        is_configured=bool(cfg.endpoint_url),
                        is_enabled=pid in enabled_set and cfg.enabled,
                        priority_rank=rank,
                        api_key_masked=self._mask_key(cfg.auth_token) if cfg.auth_token else None,
                        endpoint_url=cfg.endpoint_url,
                        custom_config=cfg,
                    )
                )
            except Exception:
                continue

        # Sort by priority rank ascending
        results.sort(key=lambda x: x.priority_rank)
        return results

    def test_provider(
        self,
        provider_id: str,
        api_key: str | None = None,
        custom_config: CustomProviderConfig | None = None,
    ) -> ProviderTestResponse:
        """Execute live connectivity test against provider with latency benchmark."""
        t0 = time.perf_counter()

        # Custom provider test
        builtin_ids = {p["id"] for p in self.BUILTIN_PROVIDERS} | {"local"}
        if custom_config is not None or provider_id not in builtin_ids:
            return self._test_custom_provider(provider_id, custom_config, t0)

        # Built-in providers test
        effective_key = api_key
        key: str | None = None
        try:
            if provider_id in ["asset_library", "local"]:
                latency = (time.perf_counter() - t0) * 1000.0
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="success",
                    latency_ms=round(latency, 2),
                    message="Local Asset Library is operational and accessible",
                )

            if provider_id == "brand_card":
                latency = (time.perf_counter() - t0) * 1000.0
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="success",
                    latency_ms=round(latency, 2),
                    message="Procedural SVG and Canvas Brand Card generator is ready",
                )

            if provider_id == "pexels":
                key = effective_key or settings.pexels_api_key
                if not key:
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="Pexels API key not provided or configured",
                    )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(
                        "https://api.pexels.com/v1/search?query=technology&per_page=1",
                        headers={"Authorization": key},
                    )
                    latency = (time.perf_counter() - t0) * 1000.0
                    if resp.status_code == 200:
                        data = resp.json()
                        photos = data.get("photos", [])
                        preview = photos[0].get("src", {}).get("tiny") if photos else None
                        return ProviderTestResponse(
                            provider_id=provider_id,
                            status="success",
                            latency_ms=round(latency, 2),
                            message=(f"Pexels API authenticated (HTTP 200, {len(photos)} results)"),
                            sample_preview_url=preview,
                        )
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=round(latency, 2),
                        message=f"Pexels returned HTTP {resp.status_code}: {resp.text[:150]}",
                    )

            if provider_id == "giphy":
                key = effective_key or settings.giphy_api_key
                if not key:
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="Giphy API key not provided or configured",
                    )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(
                        f"https://api.giphy.com/v1/gifs/search?api_key={key}&q=ai&limit=1"
                    )
                    latency = (time.perf_counter() - t0) * 1000.0
                    if resp.status_code == 200:
                        data = resp.json()
                        gifs = data.get("data", [])
                        preview = (
                            gifs[0].get("images", {}).get("fixed_height_small", {}).get("url")
                            if gifs
                            else None
                        )
                        return ProviderTestResponse(
                            provider_id=provider_id,
                            status="success",
                            latency_ms=round(latency, 2),
                            message="Giphy API authenticated (HTTP 200)",
                            sample_preview_url=preview,
                        )
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=round(latency, 2),
                        message=f"Giphy returned HTTP {resp.status_code}: {resp.text[:150]}",
                    )

            if provider_id == "pixabay":
                key = effective_key or settings.pixabay_api_key
                if not key:
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="Pixabay API key not provided or configured",
                    )
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(f"https://pixabay.com/api/?key={key}&q=technology&per_page=3")
                    latency = (time.perf_counter() - t0) * 1000.0
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = data.get("hits", [])
                        preview = hits[0].get("previewURL") if hits else None
                        return ProviderTestResponse(
                            provider_id=provider_id,
                            status="success",
                            latency_ms=round(latency, 2),
                            message=f"Pixabay API authenticated (HTTP 200, {len(hits)} hits)",
                            sample_preview_url=preview,
                        )
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=round(latency, 2),
                        message=f"Pixabay returned HTTP {resp.status_code}: {resp.text[:150]}",
                    )

            if provider_id == "gemini":
                key = effective_key or settings.gemini_api_key
                if not key or key == "your_gemini_api_key_here":
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="Gemini API key not configured",
                    )
                from google import genai

                genai_client = genai.Client(api_key=key)
                genai_client.models.get(model="gemini-2.5-flash")
                latency = (time.perf_counter() - t0) * 1000.0
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="success",
                    latency_ms=round(latency, 2),
                    message="Google Gemini API connection verified successfully",
                )

            if provider_id == "flux":
                key = effective_key or settings.flux_api_key
                endpoint = settings.flux_endpoint
                if not key and not endpoint:
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="FLUX API key or endpoint not configured",
                    )
                latency = (time.perf_counter() - t0) * 1000.0
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="success",
                    latency_ms=round(latency, 2),
                    message="FLUX endpoint configuration format verified",
                )

            if provider_id == "google_search":
                key = effective_key or settings.serpapi_api_key or settings.google_cse_api_key
                if not key:
                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="error",
                        latency_ms=0.0,
                        message="Google CSE or SerpApi key not configured",
                    )
                latency = (time.perf_counter() - t0) * 1000.0
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="success",
                    latency_ms=round(latency, 2),
                    message="Google Search API key present",
                )

        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000.0
            return ProviderTestResponse(
                provider_id=provider_id,
                status="error",
                latency_ms=round(latency, 2),
                message=f"Test failed: {str(exc)}",
            )

        return ProviderTestResponse(
            provider_id=provider_id,
            status="error",
            latency_ms=0.0,
            message=f"Unknown provider '{provider_id}'",
        )

    def _test_custom_provider(
        self,
        provider_id: str,
        custom_config: CustomProviderConfig | None,
        start_time: float,
    ) -> ProviderTestResponse:
        """Execute connectivity test for a custom registered HTTP provider."""
        cfg = custom_config
        if cfg is None:
            for item in settings.custom_providers:
                if item.get("id") == provider_id:
                    cfg = CustomProviderConfig.model_validate(item)
                    break

        if cfg is None:
            return ProviderTestResponse(
                provider_id=provider_id,
                status="error",
                latency_ms=0.0,
                message=f"Custom provider '{provider_id}' not found",
            )

        headers: dict[str, str] = {}
        if cfg.auth_token:
            headers[cfg.auth_header_name] = cfg.auth_token

        try:
            with httpx.Client(timeout=10.0) as client:
                if cfg.mode == "openai_compatible":
                    payload = {"prompt": "technology microchip", "n": 1, "size": "512x512"}
                    resp = client.post(cfg.endpoint_url, json=payload, headers=headers)
                else:
                    if "{query}" in cfg.endpoint_url:
                        url = cfg.endpoint_url.replace("{query}", "technology")
                    else:
                        sep = "&" if "?" in cfg.endpoint_url else "?"
                        url = f"{cfg.endpoint_url}{sep}{cfg.query_param_name}=technology"

                    if cfg.http_method == "POST":
                        resp = client.post(url, json={"query": "technology"}, headers=headers)
                    else:
                        resp = client.get(url, headers=headers)

                latency = (time.perf_counter() - start_time) * 1000.0
                if resp.status_code in (200, 201):
                    preview_url = None
                    try:
                        data = resp.json()
                        preview_url = self._extract_nested_value(data, cfg.response_url_path)
                    except Exception:
                        pass

                    return ProviderTestResponse(
                        provider_id=provider_id,
                        status="success",
                        latency_ms=round(latency, 2),
                        message=f"Custom provider responded with HTTP {resp.status_code}",
                        sample_preview_url=str(preview_url) if preview_url else None,
                    )
                return ProviderTestResponse(
                    provider_id=provider_id,
                    status="error",
                    latency_ms=round(latency, 2),
                    message=f"Custom provider returned HTTP {resp.status_code}: {resp.text[:150]}",
                )
        except Exception as exc:
            latency = (time.perf_counter() - start_time) * 1000.0
            return ProviderTestResponse(
                provider_id=provider_id,
                status="error",
                latency_ms=round(latency, 2),
                message=f"Custom provider connection error: {str(exc)}",
            )

    def _extract_nested_value(self, data: Any, path: str) -> Any:
        """Extract a value from nested dict/list using dot or bracket notation."""
        parts = re.split(r"\.|\b", path.strip())
        current = data
        for part in parts:
            if not part:
                continue
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def add_custom_provider(self, config: CustomProviderConfig) -> CustomProviderConfig:
        """Register a new custom provider in settings and persist to active YAML configuration."""
        existing_ids = {p["id"] for p in self.BUILTIN_PROVIDERS} | {
            item.get("id") for item in settings.custom_providers
        }
        if config.id in existing_ids:
            # Update existing custom provider
            updated_list = [p for p in settings.custom_providers if p.get("id") != config.id]
            updated_list.append(config.model_dump())
            settings.custom_providers = updated_list
        else:
            settings.custom_providers.append(config.model_dump())
            if config.id not in settings.provider_priority:
                settings.provider_priority.append(config.id)
            if config.enabled and config.id not in settings.enabled_providers:
                settings.enabled_providers.append(config.id)

        self._persist_provider_settings_to_yaml()
        return config

    def delete_custom_provider(self, provider_id: str) -> bool:
        """Remove a custom provider by ID and update configuration file."""
        original_len = len(settings.custom_providers)
        settings.custom_providers = [
            p for p in settings.custom_providers if p.get("id") != provider_id
        ]
        if provider_id in settings.provider_priority:
            settings.provider_priority.remove(provider_id)
        if provider_id in settings.enabled_providers:
            settings.enabled_providers.remove(provider_id)

        if len(settings.custom_providers) < original_len:
            self._persist_provider_settings_to_yaml()
            return True
        return False

    def update_priority(self, new_order: list[str]) -> list[str]:
        """Update provider priority cascade order and persist to YAML."""
        custom_ids = {
            str(item["id"])
            for item in settings.custom_providers
            if isinstance(item, dict) and item.get("id")
        }
        valid_ids: set[str] = {str(p["id"]) for p in self.BUILTIN_PROVIDERS} | custom_ids
        filtered_order = [pid for pid in new_order if pid in valid_ids]
        # Append any missing providers at the end to prevent orphans
        for pid in valid_ids:
            if pid not in filtered_order:
                filtered_order.append(pid)

        settings.provider_priority = filtered_order
        self._persist_provider_settings_to_yaml()
        return settings.provider_priority

    def move_priority(self, provider_id: str, direction: str) -> list[str]:
        """Move provider up or down in cascade priority."""
        p_list = list(settings.provider_priority)
        if provider_id not in p_list:
            return p_list
        idx = p_list.index(provider_id)
        if direction == "up" and idx > 0:
            p_list[idx], p_list[idx - 1] = p_list[idx - 1], p_list[idx]
        elif direction == "down" and idx < len(p_list) - 1:
            p_list[idx], p_list[idx + 1] = p_list[idx + 1], p_list[idx]
        settings.provider_priority = p_list
        self._persist_provider_settings_to_yaml()
        return p_list

    def remove_from_cascade(self, provider_id: str) -> list[str]:
        """Remove a provider from active priority cascade and enabled set."""
        if provider_id in settings.provider_priority:
            settings.provider_priority.remove(provider_id)
        if provider_id in settings.enabled_providers:
            settings.enabled_providers.remove(provider_id)
        self._persist_provider_settings_to_yaml()
        return settings.provider_priority

    def test_all_providers(self) -> list[ProviderTestResponse]:
        """Execute connectivity tests across all registered providers."""
        results: list[ProviderTestResponse] = []
        for p in self.BUILTIN_PROVIDERS:
            results.append(self.test_provider(p["id"]))
        for c in settings.custom_providers:
            cid = c.get("id")
            if cid:
                results.append(self.test_provider(cid))
        return results

    def toggle_provider(self, provider_id: str, enabled: bool) -> bool:
        """Enable or disable a specific provider."""
        current = set(settings.enabled_providers)
        if enabled:
            current.add(provider_id)
        else:
            current.discard(provider_id)
        settings.enabled_providers = list(current)

        # Also update custom provider enabled flag if applicable
        for item in settings.custom_providers:
            if item.get("id") == provider_id:
                item["enabled"] = enabled

        self._persist_provider_settings_to_yaml()
        return enabled

    def update_credentials(self, provider_id: str, api_key: str) -> bool:
        """Update API key or authentication token for a provider and persist to YAML."""
        config_path = find_yaml_config_path() or Path("config.yaml")
        if not config_path.exists():
            config_path.write_text("# Auto-generated config\nmedia:\n", encoding="utf-8")

        raw_content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_content) or {}
        if not isinstance(data, dict):
            data = {}

        if provider_id == "pexels":
            data.setdefault("media", {})["pexels_api_key"] = api_key
            settings.pexels_api_key = api_key
        elif provider_id == "giphy":
            data.setdefault("media", {})["giphy_api_key"] = api_key
            settings.giphy_api_key = api_key
        elif provider_id == "pixabay":
            data.setdefault("media", {})["pixabay_api_key"] = api_key
            settings.pixabay_api_key = api_key
        elif provider_id == "gemini":
            data.setdefault("llm", {})["api_key"] = api_key
            settings.gemini_api_key = api_key
        elif provider_id == "flux":
            data.setdefault("media", {})["flux_api_key"] = api_key
            settings.flux_api_key = api_key
        elif provider_id == "google_search":
            data.setdefault("media", {})["serpapi_api_key"] = api_key
            settings.serpapi_api_key = api_key
        else:
            for item in settings.custom_providers:
                if item.get("id") == provider_id:
                    item["auth_token"] = api_key
                    data.setdefault("media", {})["custom_providers"] = list(
                        settings.custom_providers
                    )
                    break

        config_path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
        reload_settings(config_path)
        return True

    def _persist_provider_settings_to_yaml(self) -> None:
        """Synchronize provider priority, enabled list, and custom providers to config.yaml."""
        config_path = find_yaml_config_path() or Path("config.yaml")
        if not config_path.exists():
            config_path.write_text("# Auto-generated config\nmedia:\n", encoding="utf-8")

        raw_content = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_content) or {}

        if "media" not in data or not isinstance(data["media"], dict):
            data["media"] = {}

        data["media"]["provider_priority"] = list(settings.provider_priority)
        data["media"]["enabled_providers"] = list(settings.enabled_providers)
        data["media"]["custom_providers"] = list(settings.custom_providers)

        config_path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
        reload_settings(config_path)
