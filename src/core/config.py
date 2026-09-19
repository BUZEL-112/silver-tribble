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
        for k in ["openai_api_key", "deepseek_api_key", "gemini_api_key", "pexels_api_key"]:
            if k in p:
                flat[k] = p[k]

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

    # 10. RSS Feeds section
    if "rss_feeds" in data and isinstance(data["rss_feeds"], list):
        flat["rss_feeds"] = data["rss_feeds"]

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
    pexels_api_key: str | None = Field(default=None, description="Pexels Stock API key")

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
        (self.storage_local_dir / "audio").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "captions").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "broll").mkdir(parents=True, exist_ok=True)


settings = Settings()
