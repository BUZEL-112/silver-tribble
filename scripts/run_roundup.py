#!/usr/bin/env python3
"""Standalone runner for multi-story news roundup script generation."""

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
    parser = argparse.ArgumentParser(description="Generate multi-story roundup script")
    parser.add_argument(
        "--cluster-ids",
        type=str,
        default=None,
        help="Comma-separated cluster IDs for the roundup (e.g. 1,2,3)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of top clusters to include if cluster-ids is not specified (default: 3)",
    )
    parser.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio (9:16 or 16:9)")
    parser.add_argument("--model", default=None, help="LLM model for roundup generation")
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

            if args.cluster_ids:
                target_ids = [int(x.strip()) for x in args.cluster_ids.split(",") if x.strip()]
            else:
                recent = art_repo.get_recent_clusters(limit=args.top_n * 2)
                pending = [c for c in recent if c.status == "pending"]
                pool = pending if len(pending) >= args.top_n else recent
                target_ids = [c.id for c in pool[: args.top_n]]

            if not target_ids:
                raise ValueError("No story clusters found to generate a roundup for.")

            service = ScriptService(
                article_repo=art_repo,
                script_repo=script_repo,
                cost_repo=cost_repo,
            )

            with action_repo.track_operation(
                stage="script",
                action="generate_roundup_script",
                actor=args.actor,
                details={"cluster_ids": target_ids, "aspect_ratio": args.aspect_ratio},
            ):
                record = service.generate_roundup_script(
                    cluster_ids=target_ids,
                    aspect_ratio=args.aspect_ratio,
                    model=args.model,
                )

            words = record.full_narration.split()
            result = {
                "status": "success",
                "script_id": record.id,
                "title": record.title,
                "cluster_ids": target_ids,
                "beats_count": len(record.beats),
                "word_count": len(words),
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(
                    f"Generated roundup script #{record.id}: '{record.title}' "
                    f"({len(words)} words across {len(target_ids)} stories)"
                )

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Roundup script generation failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
