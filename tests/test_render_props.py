"""Unit tests for Remotion render props preparation."""

import json
from pathlib import Path
from src.models.schemas import WordCaption
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.render_service import RenderService
from src.services.storage_service import LocalStorageService


def test_prepare_render_props_timeline(
    script_repo: ScriptRepository,
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    script = script_repo.create_script(
        cluster_id=1,
        title="AI News Fast Cut",
        aspect_ratio="9:16",
        beats=[
            {
                "beat_number": 1,
                "beat_type": "hook",
                "on_screen_text": "HOOK TEXT",
                "visual_direction": "Visual 1",
                "estimated_duration_seconds": 10.0,
            },
            {
                "beat_number": 2,
                "beat_type": "outro",
                "on_screen_text": "OUTRO TEXT",
                "visual_direction": "Visual 2",
                "estimated_duration_seconds": 10.0,
            },
        ],
        full_narration="Here is the hook. Here is the outro.",
    )

    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")

    captions = [
        WordCaption(word="Here", start=0.0, end=0.4),
        WordCaption(word="is", start=0.4, end=0.6),
    ]

    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"MOCK_WAV")

    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        remotion_dir=tmp_path / "remotion",
        output_dir=tmp_path / "output",
    )

    props_path = service.prepare_render_props(
        job=job,
        script=script,
        captions=captions,
        audio_local_path=audio_file,
        duration_seconds=20.0,
    )

    assert props_path.exists()
    data = json.loads(props_path.read_text(encoding="utf-8"))

    assert data["videoTitle"] == "AI News Fast Cut"
    assert data["aspectRatio"] == "9:16"
    assert data["durationInSeconds"] == 20.0
    assert len(data["beats"]) == 2

    # Beat 1 should start at 0.0 and end around 10.0
    assert data["beats"][0]["start_time"] == 0.0
    assert data["beats"][0]["end_time"] == 10.0
    # Beat 2 should start at 10.0 and end at 20.0
    assert data["beats"][1]["start_time"] == 10.0
    assert data["beats"][1]["end_time"] == 20.0
