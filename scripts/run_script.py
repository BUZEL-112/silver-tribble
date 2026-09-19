#!/usr/bin/env python3
"""Standalone runner for beat sheet planning and script narration generation."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.database import get_session, init_db
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.script_repository import ScriptRepository
from src.services.script_service import ScriptService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate script for story cluster")
    parser.add_argument("--cluster-id", type=int, default=None, help="Target cluster ID")
    parser.add_argument(
        "--auto-top",
        action="store_true",
        help="Automatically select highest priority pending cluster",
    )
    parser.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio (9:16 or 16:9)")
    parser.add_argument("--planner-model", default=None, help="LLM model for beat sheet planning")
    parser.add_argument("--writer-model", default=None, help="LLM model for dialogue writing")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--actor", default="cli", help="Actor identifier for action logging")
    args = parser.parse_args()

    try:
        init_db()
        with get_session() as session:
            art_repo = ArticleRepository(session)
            script_repo = ScriptRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            target_id = args.cluster_id
            if target_id is None:
                if args.auto_top:
                    recent = art_repo.get_recent_clusters(limit=10)
                    pending = [c for c in recent if c.status == "pending"]
                    if not pending and recent:
                        pending = recent
                    if not pending:
                        raise ValueError("No story clusters found to generate script for.")
                    target_id = pending[0].id
                else:
                    raise ValueError("Must provide either --cluster-id or --auto-top")

            service = ScriptService(
                article_repo=art_repo,
                script_repo=script_repo,
                cost_repo=cost_repo,
            )

            with action_repo.track_operation(
                stage="script",
                action="generate_script",
                actor=args.actor,
                details={"cluster_id": target_id, "aspect_ratio": args.aspect_ratio},
            ):
                record = service.generate_full_script(
                    cluster_id=target_id,
                    aspect_ratio=args.aspect_ratio,
                    planner_model=args.planner_model,
                    writer_model=args.writer_model,
                )

            words = record.full_narration.split()
            result = {
                "status": "success",
                "script_id": record.id,
                "title": record.title,
                "word_count": len(words),
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(
                    f"Generated script #{record.id}: '{record.title}' "
                    f"({len(words)} words for cluster {target_id})"
                )

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Script generation failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
