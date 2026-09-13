"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError
from src.models.schemas import (
    BeatSheetResponse,
    CostLogCreate,
    FeedItem,
    RenderBeatProp,
    RenderProps,
    StoryBeat,
    WordCaption,
)


def test_feed_item_valid():
    item = FeedItem(
        title="OpenAI Releases New Frontier Model",
        link="https://techcrunch.com/ai/new-model",
        summary="A new model with advanced reasoning capabilities.",
        source="TechCrunch AI",
    )
    assert item.title == "OpenAI Releases New Frontier Model"
    assert item.source == "TechCrunch AI"


def test_feed_item_invalid():
    with pytest.raises(ValidationError):
        FeedItem(title="", link="invalid", source="")


def test_story_beat_validation():
    beat = StoryBeat(
        beat_number=1,
        beat_type="hook",
        core_point="The hype cycle begins anew.",
        visual_direction="Glitch text with neon cyan pulse",
        on_screen_text="HYPE VS REALITY",
        target_duration_seconds=6.5,
    )
    assert beat.beat_type == "hook"
    assert beat.target_duration_seconds == 6.5


def test_beat_sheet_response():
    sheet = BeatSheetResponse(
        title="AI Benchmark Showdown",
        beats=[
            StoryBeat(
                beat_number=1,
                beat_type="hook",
                core_point="Is the benchmark real?",
                visual_direction="Question mark with cyber grid",
                on_screen_text="REAL OR FAKE?",
                target_duration_seconds=5.0,
            ),
            StoryBeat(
                beat_number=2,
                beat_type="outro",
                core_point="Stay skeptical.",
                visual_direction="Outro card",
                on_screen_text="SUBSCRIBE",
                target_duration_seconds=5.0,
            ),
        ],
    )
    assert len(sheet.beats) == 2


def test_render_props_serialization():
    props = RenderProps(
        videoTitle="AI News Update",
        aspectRatio="9:16",
        audioPath="/tmp/audio.wav",
        durationInSeconds=20.0,
        fps=30,
        beats=[
            RenderBeatProp(
                beat_number=1,
                beat_type="hook",
                on_screen_text="HEADLINE",
                visual_direction="Visual",
                start_time=0.0,
                end_time=5.0,
            )
        ],
        captions=[WordCaption(word="Hello", start=0.0, end=0.5)],
    )

    dumped = props.model_dump(by_alias=True)
    assert dumped["videoTitle"] == "AI News Update"
    assert dumped["aspectRatio"] == "9:16"
    assert len(dumped["beats"]) == 1
    assert len(dumped["captions"]) == 1


def test_cost_log_create_schema():
    entry = CostLogCreate(
        stage="tts_voice",
        provider="gemini",
        model="gemini-2.0-flash",
        units=1500.0,
        unit_type="characters",
        cost_usd=0.06,
        job_id=42,
    )
    assert entry.cost_usd == 0.06
    assert entry.job_id == 42
