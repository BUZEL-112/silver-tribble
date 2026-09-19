#!/usr/bin/env python3
"""Standalone runner for Remotion video render execution."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.config import settings
from src.core.database import get_session, init_db
from src.models.schemas import SentenceMediaPlacement, WordCaption
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.storage_service import get_storage_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Render final video with Remotion")
    parser.add_argument("--job-id", type=int, required=True, help="Target render job ID")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate render without invoking Node/Remotion binary",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--actor", default="cli", help="Actor identifier for action logging")
    args = parser.parse_args()

    try:
        settings.ensure_directories()
        init_db()
        storage = get_storage_service()

        with get_session() as session:
            render_repo = RenderRepository(session)
            script_repo = ScriptRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            job = render_repo.get_job_by_id(args.job_id)
            if not job:
                raise ValueError(f"Render job {args.job_id} not found")

            script = script_repo.get_script_by_id(job.script_id)
            if not script:
                raise ValueError(f"Script record {job.script_id} not found")

            # Load captions
            captions: list[WordCaption] = []
            if job.captions_path:
                local_cap_path = storage.get_local_path(job.captions_path)
                if local_cap_path.exists():
                    data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                    captions = [WordCaption(**item) for item in data]

            if not captions:
                caption_svc = CaptionService(storage, cost_repo)
                _, captions = caption_svc.generate_captions(
                    audio_path_or_url=job.audio_path or "",
                    job_id=job.id,
                    reference_text=script.full_narration,
                    total_duration=job.duration_seconds or 30.0,
                )

            # Load or generate media placements
            placements: list[SentenceMediaPlacement] = []
            placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
            if placements_path.exists():
                try:
                    raw_p = json.loads(placements_path.read_text(encoding="utf-8"))
                    placements = [SentenceMediaPlacement(**item) for item in raw_p]
                except Exception:
                    placements = []

            if not placements:
                media_svc = MediaService(storage_service=storage, cost_repo=cost_repo)
                placements = media_svc.process_media_for_job(
                    job_id=job.id,
                    captions=captions,
                    beats=script.beats,
                )

            audio_local_path = storage.get_local_path(job.audio_path or "")
            render_svc = RenderService(render_repo, cost_repo, storage)

            render_svc.prepare_render_props(
                job=job,
                script=script,
                captions=captions,
                audio_local_path=audio_local_path,
                duration_seconds=job.duration_seconds or 30.0,
                media_placements=placements,
            )

            with action_repo.track_operation(
                stage="render",
                action="render_video",
                actor=args.actor,
                job_id=job.id,
                details={"dry_run": args.dry_run, "aspect_ratio": job.aspect_ratio},
            ):
                output_path = render_svc.execute_render(
                    job_id=job.id,
                    dry_run=args.dry_run,
                )

            result = {
                "status": "success",
                "job_id": job.id,
                "output_video_path": str(output_path.resolve()),
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(f"Render completed for job #{job.id}: {output_path}")

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Render failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
