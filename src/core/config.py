"""Application configuration and environment settings."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from src.models.schemas import ModelDefinition

DEFAULT_RSS_FEEDS: list[dict[str, str]] = [
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "name": "MIT Technology Review AI",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    },
    {
        "name": "ArXiv AI Recent",
        "url": "https://rss.arxiv.org/rss/cs.AI",
    },
    {
        "name": "Hacker News AI",
        "url": "https://hnrss.org/newest?q=AI",
    },
]


def find_yaml_config_path() -> Path | None:
    """Detect active config.yaml file if present in workspace or environment."""
    env_path = os.environ.get("APP_CONFIG_FILE")
    if env_path:
        p = Path(env_path)
        if p.exists() and p.is_file():
            return p
    for candidate in [
        Path("/data/config.yaml"),
        Path("config.yaml"),
        Path("config/config.yaml"),
    ]:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def flatten_yaml_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize nested or flat YAML configuration dictionary into Settings fields."""
    if not isinstance(data, dict):
        return {}
    flat: dict[str, Any] = {}

    # 1. Direct top-level scalar copies
    for k, v in data.items():
        if not isinstance(v, (dict, list)):
            flat[k] = v

    # 2. Database section
    if "database" in data and isinstance(data["database"], dict):
        db = data["database"]
        if "url" in db:
            flat["database_url"] = db["url"]

    # 3. LiteLLM section
    if "litellm" in data and isinstance(data["litellm"], dict):
        lt = data["litellm"]
        if "base_url" in lt:
            flat["litellm_base_url"] = lt["base_url"]
        if "api_key" in lt:
            flat["litellm_api_key"] = lt["api_key"]

    # 3.1 Model Registry section
    if "model_registry" in data and isinstance(data["model_registry"], list):
        flat["model_registry"] = data["model_registry"]
    elif "models_registry" in data and isinstance(data["models_registry"], list):
        flat["model_registry"] = data["models_registry"]

    # 3.2 Roles section
    roles_map: dict[str, list[str]] = {}
    if "roles" in data and isinstance(data["roles"], dict):
        for r_name, r_val in data["roles"].items():
            if isinstance(r_val, list):
                roles_map[str(r_name)] = [str(x) for x in r_val]
            elif isinstance(r_val, str):
                roles_map[str(r_name)] = [r_val]
    elif "model_roles" in data and isinstance(data["model_roles"], dict):
        for r_name, r_val in data["model_roles"].items():
            if isinstance(r_val, list):
                roles_map[str(r_name)] = [str(x) for x in r_val]
            elif isinstance(r_val, str):
                roles_map[str(r_name)] = [r_val]

    # 4. Models section (backward compatibility & list fallback support)
    if "models" in data and isinstance(data["models"], dict):
        m = data["models"]
        for role_key, flat_field in [
            ("planning", "llm_planning_model"),
            ("writing", "llm_writing_model"),
            ("embedding", "llm_embedding_model"),
        ]:
            if role_key in m:
                val = m[role_key]
                if isinstance(val, list):
                    if val:
                        flat[flat_field] = str(val[0])
                    if role_key not in roles_map:
                        roles_map[role_key] = [str(x) for x in val]
                elif isinstance(val, str):
                    flat[flat_field] = val
                    if role_key not in roles_map:
                        roles_map[role_key] = [val]

        if "embedding_base_url" in m:
            flat["embedding_base_url"] = m["embedding_base_url"]
        if "embedding_api_key" in m:
            flat["embedding_api_key"] = m["embedding_api_key"]

    if (
        "multimodal_model" in data.get("media", {})
        if isinstance(data.get("media"), dict)
        else False
    ):
        med_val = data["media"]["multimodal_model"]
        if isinstance(med_val, list):
            if med_val:
                flat["media_inspector_model"] = str(med_val[0])
            if "vlm_inspector" not in roles_map:
                roles_map["vlm_inspector"] = [str(x) for x in med_val]
        elif isinstance(med_val, str):
            flat["media_inspector_model"] = med_val
            if "vlm_inspector" not in roles_map:
                roles_map["vlm_inspector"] = [med_val]

    if roles_map:
        flat["roles"] = roles_map

    # 5. Providers section
    if "providers" in data and isinstance(data["providers"], dict):
        p = data["providers"]
        for k in [
            "openai_api_key",
            "deepseek_api_key",
            "gemini_api_key",
            "pexels_api_key",
            "pixabay_api_key",
            "giphy_api_key",
            "flux_api_key",
            "flux_endpoint",
            "local_tts_endpoint",
            "local_tts_path",
            "local_tts_model",
            "local_tts_voice",
        ]:
            if k in p:
                flat[k] = p[k]
        if "image_generation_provider" in p:
            flat["image_generation_provider"] = p["image_generation_provider"]
        if "tts_provider" in p:
            flat["tts_provider"] = p["tts_provider"]
        if "tts_endpoint" in p:
            flat["local_tts_endpoint"] = p["tts_endpoint"]
        if "tts_path" in p:
            flat["local_tts_path"] = p["tts_path"]

    # 5.1. Dedicated TTS section
    if "tts" in data and isinstance(data["tts"], dict):
        t = data["tts"]
        if "provider" in t:
            flat["tts_provider"] = t["provider"]
        if "endpoint" in t:
            flat["local_tts_endpoint"] = t["endpoint"]
        if "local_endpoint" in t:
            flat["local_tts_endpoint"] = t["local_endpoint"]
        if "path" in t:
            flat["local_tts_path"] = t["path"]
        if "local_path" in t:
            flat["local_tts_path"] = t["local_path"]
        if "model_path" in t:
            flat["local_tts_path"] = t["model_path"]
        if "model" in t:
            flat["local_tts_model"] = t["model"]
        if "voice" in t:
            flat["tts_voice"] = str(t["voice"])
            flat["local_tts_voice"] = str(t["voice"])
        if "timeout" in t:
            flat["local_tts_timeout"] = float(t["timeout"])

    if "local_tts" in data and isinstance(data["local_tts"], dict):
        lt = data["local_tts"]
        if "endpoint" in lt:
            flat["local_tts_endpoint"] = lt["endpoint"]
        if "path" in lt:
            flat["local_tts_path"] = lt["path"]
        if "model" in lt:
            flat["local_tts_model"] = lt["model"]
        if "voice" in lt:
            flat["local_tts_voice"] = lt["voice"]
        if "timeout" in lt:
            flat["local_tts_timeout"] = float(lt["timeout"])

    # 6. Storage section
    if "storage" in data and isinstance(data["storage"], dict):
        s = data["storage"]
        if "backend" in s:
            flat["storage_backend"] = s["backend"]
        if "local_dir" in s:
            flat["storage_local_dir"] = s["local_dir"]
        if "r2" in s and isinstance(s["r2"], dict):
            for k in [
                "account_id",
                "access_key_id",
                "secret_access_key",
                "bucket_name",
                "public_url",
            ]:
                if k in s["r2"]:
                    flat[f"r2_{k}"] = s["r2"][k]

    # 7. Whisper section
    if "whisper" in data and isinstance(data["whisper"], dict):
        w = data["whisper"]
        if "model_size" in w:
            flat["whisper_model_size"] = w["model_size"]
        if "device" in w:
            flat["whisper_device"] = w["device"]

    # 8. Remotion section
    if "remotion" in data and isinstance(data["remotion"], dict):
        r = data["remotion"]
        if "project_dir" in r:
            flat["remotion_project_dir"] = r["project_dir"]
        if "output_dir" in r:
            flat["remotion_output_dir"] = r["output_dir"]

    # 9. Clustering section
    if "clustering" in data and isinstance(data["clustering"], dict):
        c = data["clustering"]
        if "similarity_threshold" in c:
            flat["similarity_threshold"] = float(c["similarity_threshold"])
        if "time_limit_hours" in c:
            flat["time_limit_hours"] = int(c["time_limit_hours"])
        if "max_clusters" in c:
            flat["max_clusters"] = int(c["max_clusters"])

    # 9.1 Video and Timeline section
    if "video" in data and isinstance(data["video"], dict):
        v = data["video"]
        if "aspect_ratio" in v:
            flat["aspect_ratio"] = v["aspect_ratio"]
        if "target_beats" in v:
            flat["target_beats"] = int(v["target_beats"])

    # 10. Media, Inspector, and Branding sections
    if "media" in data and isinstance(data["media"], dict):
        med = data["media"]
        if "cache_dir" in med:
            flat["media_cache_dir"] = med["cache_dir"]
        if "ratio" in med:
            flat["default_media_type_ratio"] = med["ratio"]
        if "inspector_mode" in med:
            flat["media_inspector_mode"] = med["inspector_mode"]
        if "multimodal_model" in med:
            val = med["multimodal_model"]
            if isinstance(val, list):
                if val:
                    flat["media_inspector_model"] = str(val[0])
            else:
                flat["media_inspector_model"] = str(val)
        if "min_relevance_score" in med:
            flat["media_inspector_min_score"] = float(med["min_relevance_score"])
        if "provider_priority" in med and isinstance(med["provider_priority"], list):
            flat["provider_priority"] = med["provider_priority"]
        if "enabled_providers" in med and isinstance(med["enabled_providers"], list):
            flat["enabled_providers"] = med["enabled_providers"]
        if "custom_providers" in med and isinstance(med["custom_providers"], list):
            flat["custom_providers"] = med["custom_providers"]
    elif "providers" in data and isinstance(data["providers"], dict):
        p_block = data["providers"]
        if "priority" in p_block and isinstance(p_block["priority"], list):
            flat["provider_priority"] = p_block["priority"]
        if "enabled" in p_block and isinstance(p_block["enabled"], list):
            flat["enabled_providers"] = p_block["enabled"]
        if "custom" in p_block and isinstance(p_block["custom"], list):
            flat["custom_providers"] = p_block["custom"]

    if "watermark" in data and isinstance(data["watermark"], dict):
        wm = data["watermark"]
        if "text" in wm:
            flat["watermark_text"] = wm["text"]
        if "image_path" in wm:
            flat["watermark_image_path"] = wm["image_path"]
        if "position" in wm:
            flat["watermark_position"] = wm["position"]
        if "opacity" in wm:
            flat["watermark_opacity"] = wm["opacity"]
        if "header_badge" in wm:
            flat["channel_badge_text"] = wm["header_badge"]
        if "channel_badge" in wm:
            flat["channel_badge_text"] = wm["channel_badge"]

    if "branding" in data and isinstance(data["branding"], dict):
        b = data["branding"]
        if "header_badge" in b:
            flat["channel_badge_text"] = b["header_badge"]
        if "channel_badge" in b:
            flat["channel_badge_text"] = b["channel_badge"]
        if "watermark_text" in b:
            flat["watermark_text"] = b["watermark_text"]
        if "caption_style" in b:
            flat["caption_style"] = b["caption_style"]
        if "caption_level" in b:
            flat["caption_level"] = b["caption_level"]
        if "caption_font_size" in b:
            flat["caption_font_size"] = b["caption_font_size"]
        if "caption_uppercase" in b:
            flat["caption_uppercase"] = b["caption_uppercase"]
        if "subscribe_title" in b:
            flat["subscribe_title"] = b["subscribe_title"]
        if "subscribe_subtitle" in b:
            flat["subscribe_subtitle"] = b["subscribe_subtitle"]
        if "subscribe_button_text" in b:
            flat["subscribe_button_text"] = b["subscribe_button_text"]
        if "subscribe_duration_seconds" in b:
            flat["subscribe_duration_seconds"] = b["subscribe_duration_seconds"]
        if "subscribe_style" in b:
            flat["subscribe_style"] = b["subscribe_style"]
        if "subscribe_enabled" in b:
            flat["subscribe_enabled"] = b["subscribe_enabled"]
        if "horizontal_watermark_position" in b:
            flat["horizontal_watermark_position"] = b["horizontal_watermark_position"]
        if "horizontal_caption_level" in b:
            flat["horizontal_caption_level"] = b["horizontal_caption_level"]
        if "horizontal_channel_badge_text" in b:
            flat["horizontal_channel_badge_text"] = b["horizontal_channel_badge_text"]
        if "horizontal_lower_third_title" in b:
            flat["horizontal_lower_third_title"] = b["horizontal_lower_third_title"]
    if "captions" in data and isinstance(data["captions"], dict):
        c = data["captions"]
        if "style" in c:
            flat["caption_style"] = c["style"]
        if "level" in c:
            flat["caption_level"] = c["level"]
        if "font_size" in c:
            flat["caption_font_size"] = c["font_size"]
        if "uppercase" in c:
            flat["caption_uppercase"] = c["uppercase"]
    if "subscribe" in data and isinstance(data["subscribe"], dict):
        s = data["subscribe"]
        if "title" in s:
            flat["subscribe_title"] = s["title"]
        if "subtitle" in s:
            flat["subscribe_subtitle"] = s["subtitle"]
        if "button_text" in s:
            flat["subscribe_button_text"] = s["button_text"]
        if "duration_seconds" in s:
            flat["subscribe_duration_seconds"] = s["duration_seconds"]
        if "style" in s:
            flat["subscribe_style"] = s["style"]
        if "enabled" in s:
            flat["subscribe_enabled"] = s["enabled"]
    if "timing" in data and isinstance(data["timing"], dict):
        t = data["timing"]
        if "intro_delay_seconds" in t:
            flat["intro_delay_seconds"] = t["intro_delay_seconds"]
        if "outro_duration_seconds" in t:
            flat["outro_duration_seconds"] = t["outro_duration_seconds"]
        if "cluster_review_timeout_seconds" in t:
            flat["cluster_review_timeout_seconds"] = t["cluster_review_timeout_seconds"]
        if "review_timeout_seconds" in t:
            flat["cluster_review_timeout_seconds"] = t["review_timeout_seconds"]

    if "review" in data and isinstance(data["review"], dict):
        rev = data["review"]
        if "timeout_seconds" in rev:
            flat["cluster_review_timeout_seconds"] = rev["timeout_seconds"]
        if "cluster_review_timeout_seconds" in rev:
            flat["cluster_review_timeout_seconds"] = rev["cluster_review_timeout_seconds"]

    # 11. Prompts & System Prompts section
    if "prompts" in data and isinstance(data["prompts"], dict):
        p = data["prompts"]
        if "planning" in p and isinstance(p["planning"], dict):
            if "system_prompt" in p["planning"]:
                flat["prompts_planning_system_prompt"] = p["planning"]["system_prompt"]
            if "file" in p["planning"]:
                flat["prompts_planning_file"] = p["planning"]["file"]
        if "writing" in p and isinstance(p["writing"], dict):
            if "system_prompt" in p["writing"]:
                flat["prompts_writing_system_prompt"] = p["writing"]["system_prompt"]
            if "file" in p["writing"]:
                flat["prompts_writing_file"] = p["writing"]["file"]
        if "media_inspector" in p and isinstance(p["media_inspector"], dict):
            if "system_prompt" in p["media_inspector"]:
                flat["prompts_media_inspector_system_prompt"] = p["media_inspector"][
                    "system_prompt"
                ]
            if "file" in p["media_inspector"]:
                flat["prompts_media_inspector_file"] = p["media_inspector"]["file"]

    # 12. RSS Feeds section
    raw_feeds = None
    if "rss_feeds" in data and isinstance(data["rss_feeds"], list):
        raw_feeds = data["rss_feeds"]
    elif "feeds" in data and isinstance(data["feeds"], list):
        raw_feeds = data["feeds"]
    elif (
        "rss" in data
        and isinstance(data["rss"], dict)
        and isinstance(data["rss"].get("feeds"), list)
    ):
        raw_feeds = data["rss"]["feeds"]

    if raw_feeds is not None:
        normalized_feeds: list[dict[str, str]] = []
        for item in raw_feeds:
            if isinstance(item, str):
                item_str = item.strip()
                source_name = item_str.split("/")[2] if "//" in item_str else "RSS Feed"
                normalized_feeds.append({"name": source_name, "url": item_str})
            elif isinstance(item, dict) and "url" in item:
                source_name = item.get("name") or (
                    item["url"].split("/")[2] if "//" in item["url"] else "RSS Feed"
                )
                normalized_feeds.append({"name": str(source_name), "url": str(item["url"]).strip()})
        flat["rss_feeds"] = normalized_feeds

    # 13. Webhooks & Housekeeping
    if "webhooks" in data and isinstance(data["webhooks"], dict):
        wh = data["webhooks"]
        if "url" in wh:
            flat["webhook_url"] = wh["url"]
        if "secret" in wh:
            flat["webhook_secret"] = wh["secret"]
    if "housekeeping" in data and isinstance(data["housekeeping"], dict):
        hk = data["housekeeping"]
        if "cache_retention_hours" in hk:
            flat["cache_retention_hours"] = hk["cache_retention_hours"]

    # 14. Security & Auth section
    if "security" in data and isinstance(data["security"], dict):
        sec = data["security"]
        if "api_auth_token" in sec:
            flat["api_auth_token"] = sec["api_auth_token"]
        if "admin_password" in sec:
            flat["admin_password"] = sec["admin_password"]
    elif "auth" in data and isinstance(data["auth"], dict):
        auth_sec = data["auth"]
        if "api_auth_token" in auth_sec:
            flat["api_auth_token"] = auth_sec["api_auth_token"]
        if "token" in auth_sec:
            flat["api_auth_token"] = auth_sec["token"]
        if "admin_password" in auth_sec:
            flat["admin_password"] = auth_sec["admin_password"]

    # 15. Budget section
    if "budget" in data and isinstance(data["budget"], dict):
        bg = data["budget"]
        if "daily_usd" in bg and bg["daily_usd"] is not None:
            flat["cost_daily_budget_usd"] = float(bg["daily_usd"])
        elif "daily_budget_usd" in bg and bg["daily_budget_usd"] is not None:
            flat["cost_daily_budget_usd"] = float(bg["daily_budget_usd"])
        if "monthly_usd" in bg and bg["monthly_usd"] is not None:
            flat["cost_monthly_budget_usd"] = float(bg["monthly_usd"])
        elif "monthly_budget_usd" in bg and bg["monthly_budget_usd"] is not None:
            flat["cost_monthly_budget_usd"] = float(bg["monthly_budget_usd"])

    # 16. YouTube section
    if "youtube" in data and isinstance(data["youtube"], dict):
        yt = data["youtube"]
        if "client_id" in yt:
            flat["youtube_client_id"] = yt["client_id"]
        if "client_secret" in yt:
            flat["youtube_client_secret"] = yt["client_secret"]
        if "refresh_token" in yt:
            flat["youtube_refresh_token"] = yt["refresh_token"]

    return {k: v for k, v in flat.items() if v is not None}


class YamlCustomSettingsSource(PydanticBaseSettingsSource):
    """Loads configuration values from config.yaml if present."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        yaml_path = find_yaml_config_path()
        if not yaml_path:
            return {}
        try:
            raw_content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw_content)
            if isinstance(data, dict):
                return flatten_yaml_data(data)
        except Exception:
            pass
        return {}


class NonEmptyEnvSettingsSource(EnvSettingsSource):
    """Environment settings source that ignores empty strings and template placeholders."""

    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        filtered: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, str):
                s = v.strip()
                if not s or (s.startswith("your_") and s.endswith("_here")):
                    continue
            filtered[k] = v
        return filtered


class Settings(BaseSettings):
    """Pipeline configuration settings loaded from config.yaml, environment, or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/ai_news_video",
        description="PostgreSQL or SQLite connection string",
    )

    # LiteLLM Proxy
    litellm_base_url: str = Field(
        default="http://localhost:4000",
        description="Base URL for the LiteLLM proxy instance",
    )
    litellm_api_key: str = Field(
        default="sk-litellm-master-key",
        description="API key for authentication with LiteLLM proxy",
    )

    # Model Registry and Role Fallback Chains
    model_registry: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Unified registry of model provider endpoints, credentials, and protocols",
    )
    roles: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Ordered priority fallback lists mapping pipeline roles to model aliases",
    )

    # LLM Model Routing (routed through LiteLLM or direct OpenAI-compatible endpoint)
    llm_planning_model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier for Stage 1 beat sheet planning via LiteLLM",
    )
    llm_writing_model: str = Field(
        default="deepseek-chat",
        description="Model identifier for Stage 2 persona dialogue expansion via LiteLLM",
    )
    llm_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Model identifier for vector embeddings (or 'local' / 'bge-small-en-v1.5')",
    )
    embedding_base_url: str | None = Field(
        default=None,
        description="Custom endpoint for embedding generation (e.g. Ollama or custom API)",
    )
    embedding_api_key: str | None = Field(
        default=None,
        description="API key for custom embedding endpoint (or BYOK provider)",
    )

    # Provider API Keys
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    deepseek_api_key: str | None = Field(default=None, description="DeepSeek API key")
    gemini_api_key: str | None = Field(default=None, description="Google Gemini API key")
    pexels_api_key: str = Field(default="", description="Pexels Stock API key")
    pixabay_api_key: str = Field(default="", description="Pixabay Stock API key")
    giphy_api_key: str = Field(default="", description="Giphy API key")
    flux_api_key: str = Field(default="", description="FLUX or AI generation API key")
    flux_endpoint: str = Field(default="", description="FLUX or AI generation endpoint URL")
    image_generation_provider: Literal["flux", "gemini", "local", "fallback"] = Field(
        default="flux",
        description="Image generation provider backend",
    )
    tts_provider: Literal["gemini", "edge_tts", "local", "auto"] = Field(
        default="gemini",
        description="TTS voice synthesis provider priority: gemini, edge_tts, local, or auto",
    )
    tts_voice: str = Field(
        default="Puck",
        description="Default voice persona or identifier for speech synthesis",
    )
    local_tts_endpoint: str = Field(
        default="http://localhost:8880/v1/audio/speech",
        description=(
            "Endpoint URL for local HTTP TTS server "
            "(e.g. Kokoro, Piper, or OpenAI-compatible server)"
        ),
    )
    local_tts_path: str = Field(
        default="",
        description=(
            "Filesystem path to local TTS model weights, ONNX file, or binary (e.g. Piper model)"
        ),
    )
    local_tts_model: str = Field(
        default="kokoro",
        description="Model name or architecture for local TTS provider (e.g. kokoro, piper)",
    )
    local_tts_voice: str = Field(
        default="af_heart",
        description="Default voice identifier for local TTS provider",
    )
    local_tts_timeout: float = Field(
        default=60.0,
        description="Timeout in seconds for local TTS synthesis requests",
    )
    google_cse_api_key: str | None = Field(
        default=None, description="Google Custom Search JSON API key"
    )
    google_cse_cx: str | None = Field(default=None, description="Google Custom Search Engine CX ID")
    serpapi_api_key: str | None = Field(default=None, description="SerpApi key for Google Images")

    # Media and Visual Assets
    media_cache_dir: Path = Field(
        default=Path("artifacts/media"),
        description="Local directory for cached visual media",
    )
    media_router_rules_file: str = Field(
        default="prompts/media_routing_rules.yaml",
        description="Path to media routing instructions and rules YAML",
    )
    default_media_type_ratio: float = Field(
        default=0.5,
        description="Ratio of stock clips to comedic GIFs",
    )
    provider_priority: list[str] = Field(
        default_factory=lambda: [
            "asset_library",
            "pexels",
            "giphy",
            "google_search",
            "pixabay",
            "flux",
            "brand_card",
        ],
        description="Priority order for visual asset providers in the fallback cascade",
    )
    enabled_providers: list[str] = Field(
        default_factory=lambda: [
            "asset_library",
            "pexels",
            "giphy",
            "google_search",
            "pixabay",
            "flux",
            "brand_card",
        ],
        description="List of enabled provider identifiers",
    )
    custom_providers: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of dynamically registered custom image, video, or GIF provider configurations"
        ),
    )

    # Media Inspector
    media_inspector_mode: Literal["off", "multimodal", "hil"] = Field(
        default="multimodal",
        description="Media inspector mode: 'off', 'multimodal', or 'hil'",
    )
    media_inspector_model: str = Field(
        default="gemini-3.5-flash-lite",
        description="VLM model for multimodal media inspection",
    )
    media_inspector_min_score: float = Field(
        default=6.0,
        description="Minimum relevance score (1-10) for candidate approval in multimodal mode",
    )

    # Watermark and Branding
    channel_badge_text: str = Field(
        default="AI NEWS BY ESWAR",
        description="Top header channel badge text in title card",
    )
    watermark_text: str = Field(
        default="@AINewsDesk",
        description="Watermark text overlay e.g. @AINewsDesk",
    )
    watermark_image_path: str = Field(
        default="",
        description="Path to transparent PNG logo",
    )
    watermark_position: Literal["top-right", "top-left", "bottom-right", "bottom-left"] = Field(
        default="top-right",
        description="Watermark position on screen",
    )
    watermark_opacity: float = Field(
        default=0.8,
        description="Watermark opacity from 0.0 to 1.0",
    )

    # Caption Customization and Positioning
    caption_style: Literal["hormozi", "minimal", "karaoke", "news_ticker", "cinematic"] = Field(
        default="hormozi",
        description="Caption animation and typography preset",
    )
    caption_level: float = Field(
        default=30.0,
        description="Vertical caption position percentage offset from bottom (10 to 85)",
    )
    caption_font_size: int = Field(
        default=48,
        description="Base caption font size in pixels",
    )
    caption_uppercase: bool = Field(
        default=True,
        description="Force uppercase typography on captions",
    )

    # Ending Subscribe Watermark and Call-to-Action
    subscribe_title: str = Field(
        default="SUBSCRIBE FOR DAILY AI UPDATES",
        description="Headline text for the ending subscribe call to action",
    )
    subscribe_subtitle: str = Field(
        default="@AINewsDesk | Engineering First",
        description="Subheadline or channel handle for ending subscribe card",
    )
    subscribe_button_text: str = Field(
        default="SUBSCRIBE",
        description="Button CTA label on ending card",
    )
    subscribe_duration_seconds: float = Field(
        default=3.5,
        description="Duration of the ending subscribe watermark card",
    )
    subscribe_style: Literal["card", "lower_third", "minimal_badge"] = Field(
        default="card",
        description="Visual layout preset for ending subscribe watermark",
    )
    subscribe_enabled: bool = Field(
        default=True,
        description="Enable ending subscribe watermark outro",
    )

    # Horizontal (16:9) Branding Options
    horizontal_watermark_position: Literal[
        "top-right", "top-left", "bottom-right", "bottom-left"
    ] = Field(
        default="top-right",
        description="Watermark position on 16:9 widescreen canvas",
    )
    horizontal_caption_level: float = Field(
        default=15.0,
        description="Vertical caption position percentage offset from bottom for 16:9 canvas",
    )
    horizontal_channel_badge_text: str = Field(
        default="AI NEWS DESK",
        description="Channel badge text for 16:9 landscape videos",
    )
    horizontal_lower_third_title: str = Field(
        default="BREAKING AI ARCHITECTURE",
        description="Default lower-third banner headline for 16:9 landscape videos",
    )

    # Timing Controls
    intro_delay_seconds: float = Field(
        default=1.5,
        description="Splash/watermark display before speech begins",
    )
    outro_duration_seconds: float = Field(
        default=3.0,
        description="Ending card display after speech ends",
    )
    cluster_review_timeout_seconds: float = Field(
        default=300.0,
        description="Timeout in seconds for interactive cluster selection review gate",
    )

    # Prompt and System Prompt Configuration
    prompts_planning_file: str = Field(
        default="prompts/beat_sheet.yaml",
        description="Prompt YAML template file for story narrative planning",
    )
    prompts_planning_system_prompt: str | None = Field(
        default=None,
        description="Optional inline system prompt override for narrative planning",
    )
    prompts_writing_file: str = Field(
        default="prompts/eswar_host_persona.yaml",
        description="Prompt YAML template file for script narration and host persona",
    )
    prompts_writing_system_prompt: str | None = Field(
        default=None,
        description="Optional inline system prompt override for script narration",
    )
    prompts_media_inspector_file: str = Field(
        default="prompts/media_inspector.yaml",
        description="Prompt YAML template file for multimodal visual media inspection",
    )
    prompts_media_inspector_system_prompt: str | None = Field(
        default=None,
        description="Optional inline system prompt override for media inspection",
    )
    prompts_roundup_file: str = Field(
        default="prompts/roundup_script.yaml",
        description="Prompt YAML template file for multi-story news roundup scripts",
    )

    # Storage Settings
    storage_backend: Literal["local", "s3"] = Field(
        default="local",
        description="Asset storage backend: local or s3 (Cloudflare R2)",
    )
    storage_local_dir: Path = Field(
        default=Path("./data/assets"),
        description="Local directory for media assets when storage_backend is local",
    )

    # Cloudflare R2 / S3 Configuration
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_url: str | None = None

    # Audio Alignment / Whisper
    whisper_model_size: str = Field(
        default="base",
        description="faster-whisper model size: tiny, base, small, medium",
    )
    whisper_device: str = Field(
        default="cpu",
        description="Device for faster-whisper inference: cpu or cuda",
    )

    # Remotion Rendering
    remotion_project_dir: Path = Field(
        default=Path("./remotion"),
        description="Path to the Remotion project root",
    )
    remotion_output_dir: Path = Field(
        default=Path("./output/videos"),
        description="Directory for rendered video exports",
    )

    # Video and Timeline Defaults
    aspect_ratio: Literal["9:16", "16:9"] = Field(
        default="9:16",
        description="Target aspect ratio for video generation: 9:16 vertical or 16:9 widescreen",
    )
    target_beats: int = Field(
        default=5,
        description="Target number of story beats for script structuring",
    )

    # Clustering Hyperparameters
    similarity_threshold: float = Field(
        default=0.82,
        description="Cosine similarity cutoff for grouping news articles",
    )
    time_limit_hours: int = Field(
        default=24,
        description="Ingestion filter time window in hours",
    )
    max_clusters: int = Field(
        default=5,
        description="Maximum number of story clusters to process per pipeline run",
    )

    # RSS Feeds List
    rss_feeds: list[dict[str, str]] = Field(
        default_factory=lambda: list(DEFAULT_RSS_FEEDS),
        description="Configured RSS feeds for news ingestion",
    )

    # Webhooks & Housekeeping
    webhook_url: str | None = Field(
        default=None,
        description="Optional webhook notification endpoint URL",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Secret token for HMAC webhook signature verification",
    )
    cache_retention_hours: int = Field(
        default=48,
        description="Retention window in hours for unindexed temporary media files",
    )

    # Security & Authentication
    api_auth_token: str | None = Field(
        default=None,
        description="Optional bearer token for securing API and CLI endpoints",
    )
    admin_password: str | None = Field(
        default=None,
        description="Optional admin password for web dashboard session login",
    )

    # Budget Guardrails
    cost_daily_budget_usd: float | None = Field(
        default=None,
        description="Optional daily cost cap in USD to halt automated runs",
    )
    cost_monthly_budget_usd: float | None = Field(
        default=None,
        description="Optional monthly cost cap in USD to halt automated runs",
    )

    # YouTube Direct Publishing OAuth
    youtube_client_id: str | None = Field(
        default=None,
        description="Google OAuth Client ID for YouTube video upload",
    )
    youtube_client_secret: str | None = Field(
        default=None,
        description="Google OAuth Client Secret for YouTube video upload",
    )
    youtube_refresh_token: str | None = Field(
        default=None,
        description="Google OAuth Refresh Token for YouTube video upload",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            NonEmptyEnvSettingsSource(settings_cls),
            YamlCustomSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def config_source_label(self) -> str:
        """Return human-readable label for the primary loaded configuration file."""
        p = find_yaml_config_path()
        if p:
            return f"{p} (YAML)"
        return ".env (Environment)"

    def get_model_definitions_for_role(self, role: str) -> list[ModelDefinition]:
        """Resolve ordered fallback chain of ModelDefinition objects for a given role."""
        model_names = self.roles.get(role, [])
        registry_map: dict[str, dict[str, Any]] = {
            str(m["name"]): m for m in self.model_registry if isinstance(m, dict) and m.get("name")
        }

        resolved: list[ModelDefinition] = []
        for name in model_names:
            if name in registry_map:
                entry = dict(registry_map[name])
                if not entry.get("api_key"):
                    entry["api_key"] = self._resolve_fallback_api_key(
                        entry.get("model_name", name), entry.get("base_url")
                    )
                resolved.append(ModelDefinition(**entry))
            else:
                resolved.append(self._synthesize_model_definition(name, role))

        if not resolved:
            legacy_model = self._get_legacy_model_for_role(role)
            if legacy_model:
                resolved.append(self._synthesize_model_definition(legacy_model, role))

        return resolved

    def get_model_definition_by_name(self, name: str, role: str = "planning") -> ModelDefinition:
        """Find a model in the registry by name or synthesize a default definition."""
        for entry in self.model_registry:
            if isinstance(entry, dict) and entry.get("name") == name:
                entry_copy = dict(entry)
                if not entry_copy.get("api_key"):
                    entry_copy["api_key"] = self._resolve_fallback_api_key(
                        entry_copy.get("model_name", name), entry_copy.get("base_url")
                    )
                return ModelDefinition(**entry_copy)
        return self._synthesize_model_definition(name, role)

    def _get_legacy_model_for_role(self, role: str) -> str:
        """Return the default fallback model string for a given pipeline role."""
        if role == "planning":
            return self.llm_planning_model
        if role == "writing":
            return self.llm_writing_model
        if role == "embedding":
            return self.llm_embedding_model
        if role == "vlm_inspector":
            return self.media_inspector_model
        return self.llm_planning_model

    def _resolve_fallback_api_key(self, model_name: str, base_url: str | None = None) -> str | None:
        """Resolve the appropriate API key based on model naming or provider base URL."""
        m_lower = model_name.lower()
        if "gemini" in m_lower or "google" in m_lower:
            return self.gemini_api_key
        if "deepseek" in m_lower:
            return self.deepseek_api_key
        if any(x in m_lower for x in ["gpt", "o1", "o3", "text-embedding"]):
            return self.openai_api_key
        if "claude" in m_lower or "anthropic" in m_lower:
            return os.environ.get("ANTHROPIC_API_KEY") or self.api_auth_token
        return self.litellm_api_key or self.openai_api_key or "sk-dummy"

    def _synthesize_model_definition(self, name: str, role: str) -> ModelDefinition:
        """Construct a ModelDefinition for a standalone model name using system credentials."""
        m_lower = name.lower()
        endpoint_type: Literal["chat", "embedding", "multimodal"] = "chat"
        if role == "embedding":
            endpoint_type = "embedding"
        elif role == "vlm_inspector":
            endpoint_type = "multimodal"

        if "claude" in m_lower or "anthropic" in m_lower:
            return ModelDefinition(
                name=name,
                model_name=name,
                base_url="https://api.anthropic.com/v1",
                api_key=os.environ.get("ANTHROPIC_API_KEY") or self.api_auth_token,
                api_format="anthropic",
                endpoint_type=endpoint_type,
            )

        if "gemini" in m_lower or "google" in m_lower:
            return ModelDefinition(
                name=name,
                model_name=name,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=self.gemini_api_key,
                api_format="openai",
                endpoint_type=endpoint_type,
            )

        if "deepseek" in m_lower:
            return ModelDefinition(
                name=name,
                model_name=name,
                base_url="https://api.deepseek.com/v1",
                api_key=self.deepseek_api_key,
                api_format="openai",
                endpoint_type=endpoint_type,
            )

        if any(x in m_lower for x in ["gpt", "o1", "o3", "text-embedding"]):
            return ModelDefinition(
                name=name,
                model_name=name,
                base_url="https://api.openai.com/v1",
                api_key=self.openai_api_key,
                api_format="openai",
                endpoint_type=endpoint_type,
            )

        # Default fallback to LiteLLM proxy
        raw_url = (self.litellm_base_url or "http://localhost:4000").rstrip("/")
        effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
        return ModelDefinition(
            name=name,
            model_name=name,
            base_url=effective_base_url,
            api_key=self.litellm_api_key or "sk-litellm-master-key",
            api_format="openai",
            endpoint_type=endpoint_type,
        )

    def ensure_directories(self) -> None:
        """Create required local directories if they do not exist."""
        self.storage_local_dir.mkdir(parents=True, exist_ok=True)
        self.remotion_output_dir.mkdir(parents=True, exist_ok=True)
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "audio").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "captions").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "broll").mkdir(parents=True, exist_ok=True)


settings = Settings()


def reload_settings(config_path: str | Path | None = None) -> Settings:
    """Hot-reload settings in-place from specified YAML file or active environment."""
    if config_path:
        os.environ["APP_CONFIG_FILE"] = str(Path(config_path).resolve())
    new_settings = Settings()
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(new_settings, field_name))
    settings.ensure_directories()
    return settings
