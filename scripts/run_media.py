#!/usr/bin/env python3
"""Standalone runner for sentence-level Pexels and Giphy visual media retrieval."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.config import settings
from src.core.database import get_session, init_db
from src.models.schemas import WordCaption
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.media_service import MediaService
from src.services.storage_service import get_storage_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch visual media assets for render job")
    parser.add_argument("--job-id", type=int, required=True, help="Target render job ID")
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

            # Load captions from file or generate fallback
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

            media_svc = MediaService(storage_service=storage, cost_repo=cost_repo)

            with action_repo.track_operation(
                stage="media",
                action="fetch_media_assets",
                actor=args.actor,
                job_id=job.id,
                details={"caption_count": len(captions)},
            ):
                media_items = media_svc.process_media_for_job(
                    job_id=job.id,
                    captions=captions,
                    beats=script.beats,
                )

            # Persist placement metadata in media cache directory
            placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
            placements_path.parent.mkdir(parents=True, exist_ok=True)
            placements_path.write_text(
                json.dumps([p.model_dump() for p in media_items], indent=2),
                encoding="utf-8",
            )

            result = {
                "status": "success",
                "job_id": job.id,
                "media_count": len(media_items),
                "media_items": [p.model_dump() for p in media_items],
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(
                    f"Job #{job.id} media fetched: {len(media_items)} items mapped. "
                    f"Placements saved to {placements_path}"
                )

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Media retrieval failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
