"""Pydantic schemas for data validation and domain contracts."""

from datetime import datetime
from typing import Any, Literal

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
    provider: (
        Literal[
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
        | str
    )
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
    caption_style: str = Field(default="hormozi", alias="captionStyle")
    caption_level: float = Field(default=30.0, alias="captionLevel")
    caption_font_size: int = Field(default=48, alias="captionFontSize")
    caption_uppercase: bool = Field(default=True, alias="captionUppercase")
    subscribe_title: str = Field(default="SUBSCRIBE FOR DAILY AI UPDATES", alias="subscribeTitle")
    subscribe_subtitle: str = Field(
        default="@AINewsDesk | Engineering First", alias="subscribeSubtitle"
    )
    subscribe_button_text: str = Field(default="SUBSCRIBE", alias="subscribeButtonText")
    subscribe_duration_seconds: float = Field(default=3.5, alias="subscribeDurationSeconds")
    subscribe_style: str = Field(default="card", alias="subscribeStyle")
    subscribe_enabled: bool = Field(default=True, alias="subscribeEnabled")
    horizontal_branding: dict[str, Any] | None = Field(default=None, alias="horizontalBranding")


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


class CustomProviderConfig(BaseModel):
    """Configuration for an externally registered image, GIF, or video provider."""

    id: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_\-]+$")
    name: str = Field(..., min_length=1)
    media_type: Literal["image", "gif", "video"] = "image"
    mode: Literal["rest_query", "openai_compatible"] = "rest_query"
    endpoint_url: str = Field(..., min_length=5)
    http_method: Literal["GET", "POST"] = "GET"
    auth_header_name: str = "Authorization"
    auth_token: str = ""
    query_param_name: str = "q"
    response_url_path: str = "url"
    enabled: bool = True
    priority: int = 10


class ProviderInfo(BaseModel):
    """Metadata, priority rank, and configuration status for a media provider."""

    id: str
    name: str
    category: Literal[
        "stock_video",
        "stock_photo",
        "reaction_gif",
        "ai_generation",
        "custom",
        "brand_card",
        "web_search",
    ]
    media_types: list[Literal["image", "gif", "video"]]
    is_custom: bool = False
    is_configured: bool = False
    is_enabled: bool = True
    priority_rank: int = 1
    api_key_masked: str | None = None
    endpoint_url: str | None = None
    custom_config: CustomProviderConfig | None = None


class ProviderTestRequest(BaseModel):
    """Payload to test connectivity of a built-in or custom provider."""

    provider_id: str
    api_key: str | None = None
    custom_config: CustomProviderConfig | None = None


class ProviderTestResponse(BaseModel):
    """Connectivity test result for a provider."""

    provider_id: str
    status: Literal["success", "error"]
    latency_ms: float
    message: str
    sample_preview_url: str | None = None


class ProviderPriorityRequest(BaseModel):
    """Payload to update priority ordering of providers."""

    priority_order: list[str] = Field(..., min_length=1)


class ProviderToggleRequest(BaseModel):
    """Payload to toggle provider enabled state."""

    enabled: bool


class ProviderCredentialsRequest(BaseModel):
    """Payload to update credentials for a provider."""

    provider_id: str
    api_key: str = Field(..., min_length=1)


class VisualPresetInfo(BaseModel):
    """Preset metadata for one-click visual configuration buttons."""

    id: str
    name: str
    badge: str
    description: str


class VisualConfigSchema(BaseModel):
    """Visual pipeline configuration state presented in dashboard UI."""

    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    target_beats: int = Field(default=5, ge=3, le=9)
    max_clusters: int = Field(default=5, ge=1, le=20)
    time_limit_hours: int = Field(default=24, ge=1, le=168)
    tts_provider: Literal["gemini", "edge_tts", "local", "auto"] = "gemini"
    tts_voice: str = "Puck"
    caption_style: Literal["hormozi", "minimal", "karaoke", "news_ticker", "cinematic"] = "hormozi"
    caption_level: float = 30.0
    caption_font_size: int = 48
    caption_uppercase: bool = True
    default_media_type_ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    media_inspector_mode: Literal["off", "multimodal", "hil"] = "multimodal"
    media_inspector_min_score: float = Field(default=6.0, ge=1.0, le=10.0)
    llm_planning_model: str = "gpt-4o-mini"
    llm_writing_model: str = "deepseek-chat"
    similarity_threshold: float = Field(default=0.82, ge=0.5, le=0.98)
    active_preset: str | None = None


class VisualConfigUpdateRequest(BaseModel):
    """Payload to update visual configuration parameters from dashboard buttons."""

    aspect_ratio: Literal["9:16", "16:9"] | None = None
    target_beats: int | None = Field(default=None, ge=3, le=9)
    max_clusters: int | None = Field(default=None, ge=1, le=20)
    time_limit_hours: int | None = Field(default=None, ge=1, le=168)
    tts_provider: Literal["gemini", "edge_tts", "local", "auto"] | None = None
    tts_voice: str | None = None
    caption_style: Literal["hormozi", "minimal", "karaoke", "news_ticker", "cinematic"] | None = (
        None
    )
    caption_level: float | None = Field(default=None, ge=5.0, le=90.0)
    caption_font_size: int | None = Field(default=None, ge=20, le=96)
    caption_uppercase: bool | None = None
    default_media_type_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    media_inspector_mode: Literal["off", "multimodal", "hil"] | None = None
    media_inspector_min_score: float | None = Field(default=None, ge=1.0, le=10.0)
    llm_planning_model: str | None = None
    llm_writing_model: str | None = None
    similarity_threshold: float | None = Field(default=None, ge=0.5, le=0.98)
    active_preset: str | None = None


class YouTubeUploadRequest(BaseModel):
    """Payload to trigger video publishing to YouTube."""

    job_id: int
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    privacy_status: Literal["private", "unlisted", "public"] = "unlisted"


class YouTubeUploadResult(BaseModel):
    """Result data from YouTube video publishing."""

    video_id: str
    video_url: str
    title: str
    privacy_status: str
    uploaded_at: str


class ModelDefinition(BaseModel):
    """Configuration for a specific model provider endpoint."""

    name: str = Field(..., min_length=1, description="Friendly alias or identifier")
    model_name: str = Field(
        ..., min_length=1, description="Underlying model identifier passed to the API"
    )
    base_url: str | None = Field(default=None, description="Base API endpoint URL")
    api_key: str | None = Field(
        default=None, description="API key or environment variable reference"
    )
    api_format: Literal["openai", "anthropic"] = Field(
        default="openai", description="API wire protocol format"
    )
    endpoint_type: Literal["chat", "embedding", "multimodal"] = Field(
        default="chat", description="Endpoint capability type"
    )
    timeout: float = Field(default=30.0, ge=1.0, description="HTTP request timeout in seconds")
    extra_headers: dict[str, str] = Field(
        default_factory=dict, description="Custom HTTP request headers"
    )


class RoleMappingsConfig(BaseModel):
    """Fallback priority chains mapping pipeline roles to model names."""

    planning: list[str] = Field(
        default_factory=list, description="Ordered model aliases for beat sheet generation"
    )
    writing: list[str] = Field(
        default_factory=list, description="Ordered model aliases for host dialogue expansion"
    )
    embedding: list[str] = Field(
        default_factory=list, description="Ordered model aliases for text embedding generation"
    )
    vlm_inspector: list[str] = Field(
        default_factory=list,
        description="Ordered model aliases for visual candidate inspection",
    )


class ClusterRunResponse(BaseModel):
    """Cluster execution run summary."""

    run_id: str
    cluster_count: int = 0
    article_count: int = 0
    threshold: float = 0.82
    created_at: datetime


class ArticleSummary(BaseModel):
    """Article metadata summary for UI selection."""

    id: int
    title: str
    link: str
    source: str
    summary: str
    published_at: datetime | None = None
    created_at: datetime | None = None
    has_embedding: bool = False


class ClusterTriggerRequest(BaseModel):
    """Payload to trigger news clustering."""

    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    model: str | None = None
    article_ids: list[int] | None = None
    hours_back: float | None = None
    cluster_run_id: str | None = None


class ModelDefinitionResponse(BaseModel):
    """Model definition formatted for client display with masked credentials."""

    name: str
    model_name: str
    base_url: str | None = None
    api_key_masked: str | None = None
    is_configured: bool = False
    api_format: Literal["openai", "anthropic"] = "openai"
    endpoint_type: Literal["chat", "embedding", "multimodal"] = "chat"
    timeout: float = 30.0
    extra_headers: dict[str, str] = Field(default_factory=dict)


class ModelTestRequest(BaseModel):
    """Request payload to test a registered or draft model definition."""

    model_name: str = Field(..., min_length=1, description="Model alias or name to test")
    prompt: str | None = Field(default=None, description="Optional custom test prompt")


class ModelTestResponse(BaseModel):
    """Result of a model endpoint connectivity test."""

    model_name: str
    status: Literal["success", "error"]
    latency_ms: float
    message: str


class RoleFallbacksUpdateRequest(BaseModel):
    """Payload to update ordered model fallback chains for pipeline roles."""

    planning: list[str] | None = None
    writing: list[str] | None = None
    embedding: list[str] | None = None
    vlm_inspector: list[str] | None = None


class SystemConfigResponse(BaseModel):
    """Full system configuration state matching current application structure."""

    database: dict[str, Any]
    litellm: dict[str, Any]
    model_registry: list[ModelDefinitionResponse]
    roles: RoleMappingsConfig
    providers: dict[str, Any]
    tts: dict[str, Any]
    storage: dict[str, Any]
    whisper: dict[str, Any]
    remotion: dict[str, Any]
    clustering: dict[str, Any]
    video: dict[str, Any]
    media: dict[str, Any]
    timing: dict[str, Any]
    budget: dict[str, Any]
    security: dict[str, Any]
    youtube: dict[str, Any]
    rss_feeds: list[dict[str, str]]
    config_source: str
    config_path: str | None = None


class SystemConfigUpdateRequest(BaseModel):
    """Payload to update modular system configuration sections."""

    litellm: dict[str, Any] | None = None
    providers: dict[str, Any] | None = None
    tts: dict[str, Any] | None = None
    storage: dict[str, Any] | None = None
    whisper: dict[str, Any] | None = None
    remotion: dict[str, Any] | None = None
    clustering: dict[str, Any] | None = None
    video: dict[str, Any] | None = None
    media: dict[str, Any] | None = None
    timing: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    security: dict[str, Any] | None = None
