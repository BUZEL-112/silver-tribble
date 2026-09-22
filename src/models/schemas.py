"""Pydantic schemas for data validation and domain contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedItem(BaseModel):
    """Normalized article item parsed from RSS feeds."""

    title: str = Field(..., min_length=3)
    link: str = Field(..., min_length=5)
    summary: str = Field(default="")
    source: str = Field(..., min_length=1)
    published_at: datetime | None = None


class StoryBeat(BaseModel):
    """Single narrative beat defining pacing, visuals, and editorial focus."""

    beat_number: int = Field(..., ge=1)
    beat_type: Literal["hook", "context", "breakthrough", "skepticism", "outro"] = "context"
    core_point: str = Field(..., min_length=3)
    visual_direction: str = Field(..., min_length=3)
    on_screen_text: str = Field(..., min_length=1, max_length=100)
    target_duration_seconds: float = Field(..., gt=0)
    emotion: str = Field(default="neutral")
    shot_type: str = Field(default="medium")


class BeatSheetResponse(BaseModel):
    """Structured response from LLM beat sheet generation."""

    title: str = Field(..., min_length=3)
    beats: list[StoryBeat] = Field(..., min_length=2)


class ExpandedBeat(BaseModel):
    """Expanded beat containing finalized comedic spoken dialogue."""

    beat_number: int = Field(..., ge=1)
    beat_type: str
    narration_text: str = Field(..., min_length=3)
    visual_direction: str = Field(..., min_length=3)
    on_screen_text: str = Field(..., min_length=1)
    estimated_duration_seconds: float = Field(..., gt=0)
    emotion: str = Field(default="neutral")
    shot_type: str = Field(default="medium")


class ScriptExpansionResponse(BaseModel):
    """Complete comedic script response with dialogue per beat."""

    title: str = Field(..., min_length=3)
    expanded_beats: list[ExpandedBeat] = Field(..., min_length=2)
    full_narration_script: str = Field(..., min_length=10)


class WordCaption(BaseModel):
    """Word-level timestamp produced by Whisper for kinetic typography."""

    word: str
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CaptionSegment(BaseModel):
    """Sentence or phrase segment composed of timed words."""

    text: str
    start: float = Field(..., ge=0)
    end: float = Field(..., ge=0)
    words: list[WordCaption] = Field(default_factory=list)


class SentenceMediaPlacement(BaseModel):
    """Sentence-level media asset placement mapping."""

    sentence_index: int
    start_time: float
    end_time: float
    keywords: list[str]
    media_type: Literal["image", "video", "gif"]
    local_path: str
    source_url: str
    provider: Literal[
        "pexels",
        "pixabay",
        "giphy",
        "google_search",
        "brand_card",
        "flux_generation",
        "ai_generated",
        "asset_library",
        "fallback",
        "custom",
    ]
    text: str = ""
    query: str = ""
    emotion: str = "neutral"
    shot_type: str = "medium"


class WatermarkConfig(BaseModel):
    """Visual watermark overlay configuration."""

    text: str = ""
    image_path: str = ""
    position: Literal["top-right", "top-left", "bottom-right", "bottom-left"] = "top-right"
    opacity: float = 0.8


class RenderBeatProp(BaseModel):
    """Beat payload passed into Remotion composition."""

    beat_number: int
    beat_type: str
    on_screen_text: str
    visual_direction: str
    broll_video_path: str | None = None
    start_time: float
    end_time: float
    emotion: str = "neutral"
    shot_type: str = "medium"


class RenderProps(BaseModel):
    """Complete props payload fed into Remotion CLI or bundle."""

    model_config = ConfigDict(populate_by_name=True)

    video_title: str = Field(..., alias="videoTitle")
    aspect_ratio: Literal["9:16", "16:9"] = Field(..., alias="aspectRatio")
    audio_path: str = Field(..., alias="audioPath")
    duration_in_seconds: float = Field(..., alias="durationInSeconds", gt=0)
    fps: int = Field(default=30)
    beats: list[RenderBeatProp] = Field(default_factory=list)
    captions: list[WordCaption] = Field(default_factory=list)
    watermark: WatermarkConfig | None = Field(default=None, alias="watermark")
    media_placements: list[SentenceMediaPlacement] = Field(
        default_factory=list, alias="mediaPlacements"
    )
    intro_delay_seconds: float = Field(default=0.0, alias="introDelaySeconds")
    outro_duration_seconds: float = Field(default=0.0, alias="outroDurationSeconds")
    channel_badge_text: str = Field(default="AI NEWS BY ESWAR", alias="channelBadgeText")
    show_material_indices: bool = Field(default=False, alias="showMaterialIndices")


class CostLogCreate(BaseModel):
    """Cost entry creation schema."""

    stage: str
    provider: str
    model: str | None = None
    units: float = Field(..., ge=0)
    unit_type: str
    cost_usd: float = Field(..., ge=0)
    job_id: int | None = None


class VisualAssetCreate(BaseModel):
    """Schema for indexing new assets into the asset library."""

    asset_hash: str
    source_url: str | None = None
    local_path: str
    media_type: Literal["video", "image", "gif"] = "image"
    provider: str
    query: str = ""
    tags: list[str] = Field(default_factory=list)
    emotion_tags: list[str] = Field(default_factory=list)
    shot_type: str | None = None
    aspect_ratio: str = "9:16"
    vlm_score: float | None = None
    vlm_reason: str | None = None


class VisualAssetResponse(BaseModel):
    """Schema for returning indexed asset information."""

    id: int
    asset_hash: str
    source_url: str | None
    local_path: str
    media_type: str
    provider: str
    query: str
    tags: list[str]
    emotion_tags: list[str]
    shot_type: str | None
    aspect_ratio: str
    vlm_score: float | None
    vlm_reason: str | None
    usage_count: int
    created_at: datetime
    last_used_at: datetime


class YouTubeChapter(BaseModel):
    """Chapter timestamp marker for video description."""

    title: str
    timestamp: str
    seconds: float


class YouTubeMetadata(BaseModel):
    """Publishing package for YouTube video uploads."""

    title_options: list[str]
    description: str
    chapters: list[YouTubeChapter]
    tags: list[str]
    hashtags: list[str]


class ScriptAuditReport(BaseModel):
    """Retention, pacing, and hook quality audit report for a script."""

    word_count: int
    estimated_duration_seconds: float
    words_per_minute: float
    pacing_rating: Literal["optimal", "too_fast", "too_slow"]
    hook_score: float
    has_question_hook: bool
    has_breaking_trigger: bool
    recommendations: list[str]


class HealthComponentStatus(BaseModel):
    """Status for an individual infrastructure component."""

    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    details: str


class HealthStatus(BaseModel):
    """System-wide health and readiness report."""

    status: Literal["healthy", "degraded", "unhealthy"]
    components: list[HealthComponentStatus]
    checks_passed: int
    total_checks: int


class PruneResult(BaseModel):
    """Summary of cleaned temporary media cache artifacts."""

    files_scanned: int
    files_deleted: int
    bytes_freed: int
