"""Application configuration and environment settings."""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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
    for candidate in [Path("config.yaml"), Path("config/config.yaml")]:
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

    # 4. Models section
    if "models" in data and isinstance(data["models"], dict):
        m = data["models"]
        if "planning" in m:
            flat["llm_planning_model"] = m["planning"]
        if "writing" in m:
            flat["llm_writing_model"] = m["writing"]
        if "embedding" in m:
            flat["llm_embedding_model"] = m["embedding"]
        if "embedding_base_url" in m:
            flat["embedding_base_url"] = m["embedding_base_url"]
        if "embedding_api_key" in m:
            flat["embedding_api_key"] = m["embedding_api_key"]

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
        ]:
            if k in p:
                flat[k] = p[k]
        if "image_generation_provider" in p:
            flat["image_generation_provider"] = p["image_generation_provider"]
        if "tts_provider" in p:
            flat["tts_provider"] = p["tts_provider"]

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
            flat["similarity_threshold"] = c["similarity_threshold"]

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
            flat["media_inspector_model"] = med["multimodal_model"]
        if "min_relevance_score" in med:
            flat["media_inspector_min_score"] = float(med["min_relevance_score"])

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
    tts_provider: Literal["gemini", "edge_tts", "auto"] = Field(
        default="gemini",
        description="TTS voice synthesis provider priority: gemini, edge_tts, or auto",
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

    # Clustering Hyperparameters
    similarity_threshold: float = Field(
        default=0.82,
        description="Cosine similarity cutoff for grouping news articles",
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
            env_settings,
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
