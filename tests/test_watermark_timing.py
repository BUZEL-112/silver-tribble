"""Unit tests for watermark configuration and timing offset alignment."""

import json
from pathlib import Path

from src.models.entities import ScriptRecord, StoryCluster
from src.models.schemas import SentenceMediaPlacement, WatermarkConfig, WordCaption
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.render_service import RenderService
from src.services.storage_service import LocalStorageService


def test_timing_offsets_and_watermark(
    tmp_path: Path,
    db_session,
    render_repo: RenderRepository,
    script_repo: ScriptRepository,
    cost_repo: CostRepository,
) -> None:
    """Verify intro delay offsets audio, captions, and media timestamps correctly."""
    cluster = StoryCluster(
        cluster_hash="hash_test_timing",
        title="AI News Timing Test",
        summary="Testing timing offsets and watermarks",
        article_ids=[1],
        status="pending",
    )
    db_session.add(cluster)
    db_session.commit()

    script = ScriptRecord(
        cluster_id=cluster.id,
        title="Timing Test Video",
        aspect_ratio="9:16",
        beats=[
            {
                "beat_number": 1,
                "beat_type": "context",
                "on_screen_text": "HOOK",
                "estimated_duration_seconds": 10.0,
            }
        ],
        full_narration="Here is our timed narration test.",
    )
    db_session.add(script)
    db_session.commit()

    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    captions = [
        WordCaption(word="Here", start=0.0, end=0.4),
        WordCaption(word="is", start=0.5, end=0.8),
        WordCaption(word="news", start=0.9, end=1.5),
    ]

    media_placements = [
        SentenceMediaPlacement(
            sentence_index=0,
            start_time=0.0,
            end_time=1.5,
            keywords=["news"],
            media_type="image",
            local_path="/path/to/img.jpg",
            source_url="https://example.com/img.jpg",
            provider="fallback",
        )
    ]

    storage = LocalStorageService(base_dir=tmp_path / "assets")
    audio_file = tmp_path / "test_audio.wav"
    audio_file.write_bytes(b"RIFFdummywavdata")

    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=storage,
        remotion_dir=tmp_path / "remotion",
        output_dir=tmp_path / "output",
    )

    intro_delay = 2.0
    outro_dur = 3.0
    audio_duration = 10.0

    watermark = WatermarkConfig(
        text="@TestDesk",
        position="top-right",
        opacity=0.85,
    )

    props_file = service.prepare_render_props(
        job=job,
        script=script,
        captions=captions,
        audio_local_path=audio_file,
        duration_seconds=audio_duration,
        media_placements=media_placements,
        intro_delay_seconds=intro_delay,
        outro_duration_seconds=outro_dur,
        watermark_config=watermark,
    )

    assert props_file.exists()
    props_data = json.loads(props_file.read_text(encoding="utf-8"))

    # Total duration = intro (2.0) + audio (10.0) + outro (3.0) = 15.0
    assert props_data["durationInSeconds"] == 15.0
    assert props_data["introDelaySeconds"] == 2.0
    assert props_data["outroDurationSeconds"] == 3.0

    # Captions must be shifted by intro_delay (+2.0)
    shifted_caps = props_data["captions"]
    assert shifted_caps[0]["word"] == "Here"
    assert shifted_caps[0]["start"] == 2.0
    assert shifted_caps[0]["end"] == 2.4

    # Media placements must be shifted by intro_delay (+2.0)
    shifted_media = props_data["mediaPlacements"]
    assert len(shifted_media) == 1
    assert shifted_media[0]["start_time"] == 2.0
    assert shifted_media[0]["end_time"] == 3.5

    # Watermark should match
    assert props_data["watermark"]["text"] == "@TestDesk"
    assert props_data["watermark"]["position"] == "top-right"
    assert props_data["watermark"]["opacity"] == 0.85
