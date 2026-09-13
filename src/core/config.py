"""Application configuration and environment settings."""

from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pipeline configuration settings loaded from environment or .env file."""

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

    def ensure_directories(self) -> None:
        """Create required local directories if they do not exist."""
        self.storage_local_dir.mkdir(parents=True, exist_ok=True)
        self.remotion_output_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "audio").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "captions").mkdir(parents=True, exist_ok=True)
        (self.storage_local_dir / "broll").mkdir(parents=True, exist_ok=True)


settings = Settings()
