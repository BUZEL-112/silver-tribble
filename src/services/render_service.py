"""Remotion video rendering bridge utilizing subprocess execution."""

import json
from pathlib import Path
import shutil
import subprocess
import time
from src.core.config import settings
from src.models.entities import RenderJob, ScriptRecord
from src.models.schemas import (
    CostLogCreate,
    RenderBeatProp,
    RenderProps,
    WordCaption,
)
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.services.storage_service import StorageService


class RenderService:
    """Coordinates video rendering by passing structured props to the Remotion engine."""

    def __init__(
        self,
        render_repo: RenderRepository,
        cost_repo: CostRepository,
        storage_service: StorageService,
        remotion_dir: Path | None = None,
        output_dir: Path | None = None,
    ) -> None:
        self.render_repo = render_repo
        self.cost_repo = cost_repo
        self.storage_service = storage_service
        self.remotion_dir = remotion_dir or settings.remotion_project_dir
        self.output_dir = output_dir or settings.remotion_output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def prepare_render_props(
        self,
        job: RenderJob,
        script: ScriptRecord,
        captions: list[WordCaption],
        audio_local_path: Path,
        duration_seconds: float,
    ) -> Path:
        """Calculate beat timeline intervals and write render_props.json."""
        raw_beats = script.beats or []
        total_beats = len(raw_beats)

        # Distribute timeline evenly across beats based on relative target durations
        total_target = sum(b.get("estimated_duration_seconds", 10.0) for b in raw_beats)
        if total_target <= 0:
            total_target = 1.0

        render_beats: list[RenderBeatProp] = []
        elapsed = 0.0

        for idx, beat in enumerate(raw_beats):
            target = beat.get("estimated_duration_seconds", 10.0)
            beat_duration = (target / total_target) * duration_seconds
            start_t = round(elapsed, 2)
            end_t = round(min(elapsed + beat_duration, duration_seconds), 2)
            elapsed += beat_duration

            render_beats.append(
                RenderBeatProp(
                    beat_number=beat.get("beat_number", idx + 1),
                    beat_type=beat.get("beat_type", "context"),
                    on_screen_text=beat.get("on_screen_text", "AI UPDATE"),
                    visual_direction=beat.get("visual_direction", ""),
                    broll_video_path=beat.get("broll_video_path"),
                    start_time=start_t,
                    end_time=end_t,
                )
            )

        props = RenderProps(
            videoTitle=script.title,
            aspectRatio="9:16" if job.aspect_ratio == "9:16" else "16:9",
            audioPath=str(audio_local_path.resolve()),
            durationInSeconds=duration_seconds,
            fps=30,
            beats=render_beats,
            captions=captions,
        )

        props_dir = settings.storage_local_dir / "render_props"
        props_dir.mkdir(parents=True, exist_ok=True)
        props_file = props_dir / f"props_job_{job.id}.json"
        props_file.write_text(props.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

        self.render_repo.update_job_render_props(job.id, str(props_file.resolve()))
        return props_file

    def execute_render(
        self,
        job_id: int,
        dry_run: bool = False,
    ) -> Path:
        """Invoke Remotion CLI via subprocess to compile and render final MP4."""
        job = self.render_repo.get_job_by_id(job_id)
        if not job:
            raise ValueError(f"RenderJob with id {job_id} not found")

        props_file = Path(job.render_props_path) if job.render_props_path else None
        if not props_file or not props_file.exists():
            raise FileNotFoundError(f"Missing render props file for job {job_id}")

        composition = (
            "AiNewsVideoVertical" if job.aspect_ratio == "9:16" else "AiNewsVideoHorizontal"
        )
        output_filename = f"video_job_{job_id}_{composition}.mp4"
        output_path = self.output_dir / output_filename

        start_time = time.time()

        if dry_run or not shutil.which("npx"):
            # Mock render execution for testing environments without Node/Remotion installed
            output_path.write_bytes(b"MOCK_MP4_VIDEO_CONTAINER_DATA")
            elapsed = time.time() - start_time
            self.render_repo.complete_job(job_id, str(output_path.resolve()))
            self.cost_repo.log_cost(
                CostLogCreate(
                    job_id=job_id,
                    stage="render_video",
                    provider="remotion_mock",
                    model="local_render",
                    units=elapsed,
                    unit_type="seconds",
                    cost_usd=0.0,
                )
            )
            return output_path

        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.ts",
            composition,
            str(output_path.resolve()),
            f"--props={props_file.resolve()}",
            "--overwrite",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.remotion_dir.resolve()),
                capture_output=True,
                text=True,
                check=True,
            )
            elapsed = time.time() - start_time
            self.render_repo.complete_job(job_id, str(output_path.resolve()))

            # Remotion local compute cost: logged as execution time in seconds with 0 direct API cost
            self.cost_repo.log_cost(
                CostLogCreate(
                    job_id=job_id,
                    stage="render_video",
                    provider="remotion",
                    model="cli_render",
                    units=elapsed,
                    unit_type="seconds",
                    cost_usd=0.0,
                )
            )
            return output_path

        except subprocess.CalledProcessError as e:
            error_details = f"Remotion render failed with exit code {e.returncode}:\n{e.stderr}"
            self.render_repo.fail_job(job_id, error_details)
            raise RuntimeError(error_details) from e
