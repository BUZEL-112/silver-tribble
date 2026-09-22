"""SQLAlchemy ORM models for the video pipeline."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class Article(Base):
    """Raw or embedded news article fetched from RSS sources."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    link: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class StoryCluster(Base):
    """Cluster of closely related articles representing a single unified news story."""

    __tablename__ = "story_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    article_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    scripts: Mapped[list["ScriptRecord"]] = relationship(
        "ScriptRecord", back_populates="cluster", cascade="all, delete-orphan"
    )


class ScriptRecord(Base):
    """Beat sheet and expanded comedic dialogue generated for a story cluster."""

    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("story_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True, default=list)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="9:16")
    beats: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    full_narration: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    cluster: Mapped["StoryCluster"] = relationship("StoryCluster", back_populates="scripts")
    render_jobs: Mapped[list["RenderJob"]] = relationship(
        "RenderJob", back_populates="script", cascade="all, delete-orphan"
    )


class RenderJob(Base):
    """Render execution record tracking audio, captions, and the generated video."""

    __tablename__ = "render_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="9:16")
    audio_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    captions_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    render_props_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    output_video_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    script: Mapped["ScriptRecord"] = relationship("ScriptRecord", back_populates="render_jobs")


class CostLogEntry(Base):
    """Granular cost tracking entry for LLM, TTS, alignment, and render execution."""

    __tablename__ = "cost_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    units: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ActionLog(Base):
    """Audit log recording every operational event across all interfaces."""

    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False, default="cli")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class VisualAsset(Base):
    """Reusable visual asset record with emotion, VLM verification, and usage metadata."""

    __tablename__ = "visual_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image")
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    query: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    emotion_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    shot_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="9:16")
    vlm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vlm_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

