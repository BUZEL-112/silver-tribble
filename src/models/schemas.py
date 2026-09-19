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
    provider: Literal["pexels", "giphy", "fallback"]


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


class CostLogCreate(BaseModel):
    """Cost entry creation schema."""

    stage: str
    provider: str
    model: str | None = None
    units: float = Field(..., ge=0)
    unit_type: str
    cost_usd: float = Field(..., ge=0)
    job_id: int | None = None
