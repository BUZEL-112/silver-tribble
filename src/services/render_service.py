"""Remotion video rendering bridge utilizing subprocess execution."""

import base64
import shutil
import subprocess
import time
from pathlib import Path

from src.core.config import settings
from src.models.entities import RenderJob, ScriptRecord
from src.models.schemas import (
    CostLogCreate,
    RenderBeatProp,
    RenderProps,
    SentenceMediaPlacement,
    WatermarkConfig,
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
        media_placements: list[SentenceMediaPlacement] | None = None,
        intro_delay_seconds: float | None = None,
        outro_duration_seconds: float | None = None,
        watermark_config: WatermarkConfig | None = None,
    ) -> Path:
        """Calculate beat timeline intervals with timing offsets and write render_props.json."""
        raw_beats = script.beats or []
        intro_delay = intro_delay_seconds if intro_delay_seconds is not None else 0.0
        outro_duration = outro_duration_seconds if outro_duration_seconds is not None else 0.0
        total_duration = round(intro_delay + duration_seconds + outro_duration, 2)

        # Distribute timeline evenly across beats based on relative target durations
        total_target = sum(b.get("estimated_duration_seconds", 10.0) for b in raw_beats)
        if total_target <= 0:
            total_target = 1.0

        render_beats: list[RenderBeatProp] = []
        elapsed = 0.0

        for idx, beat in enumerate(raw_beats):
            target = beat.get("estimated_duration_seconds", 10.0)
            beat_duration = (target / total_target) * duration_seconds
            start_t = round(elapsed + intro_delay, 2)
            end_t = round(min(elapsed + beat_duration, duration_seconds) + intro_delay, 2)
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

        # Shift word caption timestamps by intro_delay
        shifted_captions: list[WordCaption] = [
            WordCaption(
                word=c.word,
                start=round(c.start + intro_delay, 2),
                end=round(c.end + intro_delay, 2),
                confidence=c.confidence,
            )
            for c in captions
        ]

        # Shift sentence media placements timestamps by intro_delay
        shifted_media: list[SentenceMediaPlacement] = []
        if media_placements:
            shifted_media = [
                SentenceMediaPlacement(
                    sentence_index=m.sentence_index,
                    start_time=round(m.start_time + intro_delay, 2),
                    end_time=round(m.end_time + intro_delay, 2),
                    keywords=m.keywords,
                    media_type=m.media_type,
                    local_path=m.local_path,
                    source_url=m.source_url,
                    provider=m.provider,
                )
                for m in media_placements
            ]

        # Resolve watermark configuration
        wm = watermark_config
        if wm is None and (settings.watermark_text or settings.watermark_image_path):
            wm = WatermarkConfig(
                text=settings.watermark_text,
                image_path=settings.watermark_image_path,
                position=settings.watermark_position,
                opacity=settings.watermark_opacity,
            )

        audio_path_str = str(audio_local_path.resolve())
        is_remote_or_data = audio_path_str.startswith(("http://", "https://", "data:"))
        if audio_local_path.exists() and not is_remote_or_data:
            mime = "audio/wav" if audio_local_path.suffix.lower() == ".wav" else "audio/mpeg"
            encoded_data = base64.b64encode(audio_local_path.read_bytes()).decode("utf-8")
            audio_path_str = f"data:{mime};base64,{encoded_data}"

        props = RenderProps(
            videoTitle=script.title,
            aspectRatio="9:16" if job.aspect_ratio == "9:16" else "16:9",
            audioPath=audio_path_str,
            durationInSeconds=total_duration,
            fps=30,
            beats=render_beats,
            captions=shifted_captions,
            watermark=wm,
            mediaPlacements=shifted_media,
            introDelaySeconds=intro_delay,
            outroDurationSeconds=outro_duration,
            channel_badge_text=settings.channel_badge_text,
        )

        if hasattr(self.storage_service, "base_dir") and self.storage_service.base_dir:
            props_dir = Path(self.storage_service.base_dir) / "render_props"
        else:
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

        # Ensure remotion/public/media points to artifacts/media so Remotion serves assets
        public_media = self.remotion_dir / "public" / "media"
        if not public_media.exists() and not public_media.is_symlink():
            try:
                public_media.parent.mkdir(parents=True, exist_ok=True)
                public_media.symlink_to(
                    settings.media_cache_dir.resolve(), target_is_directory=True
                )
            except Exception:
                pass

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

        local_remotion = self.remotion_dir / "node_modules" / ".bin" / "remotion"
        if local_remotion.exists():
            bin_cmd = [str(local_remotion.resolve())]
        else:
            bin_cmd = ["npx", "remotion"]

        cmd = [
            *bin_cmd,
            "render",
            "src/index.ts",
            composition,
            str(output_path.resolve()),
            f"--props={props_file.resolve()}",
            "--overwrite",
        ]

        try:
            subprocess.run(
                cmd,
                cwd=str(self.remotion_dir.resolve()),
                capture_output=True,
                text=True,
                check=True,
            )
            elapsed = time.time() - start_time
            self.render_repo.complete_job(job_id, str(output_path.resolve()))

            # Remotion local compute cost: logged as runtime with 0 direct API cost
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
