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


def test_render_dry_run_execution(
    script_repo: ScriptRepository,
    render_repo: RenderRepository,
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
    tmp_path: Path,
):
    script = script_repo.create_script(
        cluster_id=1,
        title="Dry Run Test Video",
        aspect_ratio="9:16",
        beats=[],
        full_narration="Short narration.",
    )
    job = render_repo.create_job(script_id=script.id, aspect_ratio="9:16")
    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"MOCK_WAV")

    service = RenderService(
        render_repo=render_repo,
        cost_repo=cost_repo,
        storage_service=temp_storage,
        remotion_dir=tmp_path / "remotion",
        output_dir=tmp_path / "output",
    )
    service.prepare_render_props(
        job=job,
        script=script,
        captions=[],
        audio_local_path=audio_file,
        duration_seconds=5.0,
    )

    out_file = service.execute_render(job_id=job.id, dry_run=True)
    assert out_file.exists()
    assert out_file.read_bytes() == b"MOCK_MP4_VIDEO_CONTAINER_DATA"

    updated_job = render_repo.get_job_by_id(job.id)
    assert updated_job is not None
    assert updated_job.status == "completed"
    assert updated_job.output_video_path == str(out_file.resolve())


def test_render_repository_lifecycle(render_repo: RenderRepository):
    job = render_repo.create_job(script_id=1, aspect_ratio="16:9")
    assert job.status == "pending"

    render_repo.update_job_audio(job.id, "/path/to/audio.wav", 12.5)
    updated = render_repo.get_job_by_id(job.id)
    assert updated is not None
    assert updated.audio_path == "/path/to/audio.wav"
    assert updated.duration_seconds == 12.5

    render_repo.update_job_captions(job.id, "/path/to/captions.json")
    assert render_repo.get_job_by_id(job.id).captions_path == "/path/to/captions.json"

    render_repo.update_job_render_props(job.id, "/path/to/props.json")
    assert render_repo.get_job_by_id(job.id).render_props_path == "/path/to/props.json"

    render_repo.fail_job(job.id, "Test error message")
    failed = render_repo.get_job_by_id(job.id)
    assert failed.status == "failed"
    assert failed.error_message == "Test error message"
    assert failed.completed_at is not None

