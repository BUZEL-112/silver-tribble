#!/usr/bin/env python3
"""Standalone runner for inspecting and editing job media placements."""

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
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.storage_service import get_storage_service


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect and edit sentence-level media placements by index"
    )
    parser.add_argument("--job-id", type=int, required=True, help="Target render job ID")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all material placements for the job with index numbers",
    )
    parser.add_argument("--index", type=int, default=None, help="Material sentence index to edit")
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Search query to find new asset on Pexels or Giphy",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Local file path to replace media with",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Direct URL to download and replace media with",
    )
    parser.add_argument(
        "--provider",
        choices=["pexels", "giphy", "custom"],
        default=None,
        help="Media provider for search (pexels or giphy)",
    )
    parser.add_argument(
        "--re-render",
        action="store_true",
        help="Re-render video immediately after updating media",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate render without invoking Remotion binary",
    )
    parser.add_argument(
        "--show-indices",
        action="store_true",
        help="Display on-screen scene index badges during playback (review mode)",
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
            job_id = job.id
            aspect_ratio = job.aspect_ratio or "9:16"
            script_id = job.script_id
            captions_path = job.captions_path

            media_svc = MediaService(storage_service=storage, cost_repo=cost_repo)
            placements = media_svc.get_job_placements(job_id)

            # If user requested listing
            if args.list or (args.index is None and not args.re_render):
                result = {
                    "status": "success",
                    "job_id": job_id,
                    "media_count": len(placements),
                    "placements": [p.model_dump() for p in placements],
                }
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"=== Media Placements for Job #{job_id} ({len(placements)} materials) ===")
                    for p in placements:
                        print(
                            f"[Scene #{p.sentence_index}] {p.start_time:.1f}s - {p.end_time:.1f}s | "
                            f"{p.media_type.upper()} ({p.provider}) | {p.local_path or p.source_url}"
                        )
                        if p.text:
                            print(f"  Sentence: {p.text}")
                        if p.query:
                            print(f"  Search Query: {p.query}")
                return

            updated_placement = None

            # Handle editing by index
            if args.index is not None:
                with action_repo.track_operation(
                    stage="media",
                    action="edit_media_placement",
                    actor=args.actor,
                    job_id=job_id,
                    details={"sentence_index": args.index},
                ):
                    if args.query:
                        prov = args.provider or "pexels"
                        updated_placement = media_svc.search_and_replace_placement(
                            job_id=job_id,
                            sentence_index=args.index,
                            query=args.query,
                            provider=prov,
                            media_type="video",
                            aspect_ratio=aspect_ratio,
                        )
                    elif args.file:
                        updated_placement = media_svc.update_placement_media(
                            job_id=job_id,
                            sentence_index=args.index,
                            new_media_path_or_url=args.file,
                            provider="custom",
                        )
                    elif args.url:
                        updated_placement = media_svc.update_placement_media(
                            job_id=job_id,
                            sentence_index=args.index,
                            new_media_path_or_url=args.url,
                            provider="custom",
                        )
                    else:
                        raise ValueError(
                            "Must specify either --query, --file, or --url when editing an index"
                        )

            # Handle re-render if requested
            rendered_path = None
            if args.re_render:
                script = script_repo.get_script_by_id(script_id)
                if not script:
                    raise ValueError(f"Script record {script_id} not found")

                captions: list[WordCaption] = []
                if captions_path:
                    local_cap_path = storage.get_local_path(captions_path)
                    if local_cap_path.exists():
                        cap_data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                        captions = [WordCaption(**item) for item in cap_data]

                render_svc = RenderService(render_repo, cost_repo, storage)
                with action_repo.track_operation(
                    stage="render",
                    action="re_render_video",
                    actor=args.actor,
                    job_id=job_id,
                    details={
                        "dry_run": args.dry_run,
                        "show_indices": args.show_indices,
                    },
                ):
                    output_path = render_svc.re_render_job(
                        job_id=job_id,
                        dry_run=args.dry_run,
                        show_material_indices=args.show_indices,
                        script=script,
                        captions=captions,
                    )
                    rendered_path = str(output_path.resolve())

        result_payload = {
            "status": "success",
            "job_id": job_id,
            "updated_index": args.index,
            "updated_placement": updated_placement.model_dump() if updated_placement else None,
            "re_rendered": args.re_render,
            "output_video_path": rendered_path,
        }

        if args.json:
            print(json.dumps(result_payload, indent=2))
        else:
            if updated_placement:
                print(
                    f"Successfully updated Scene #{updated_placement.sentence_index} "
                    f"to {updated_placement.local_path}"
                )
            if rendered_path:
                print(f"Re-rendered video saved: {rendered_path}")

    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
