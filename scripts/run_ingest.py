#!/usr/bin/env python3
"""Standalone runner for news RSS feed ingestion."""

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
from src.services.rss_service import RssService


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest AI news RSS feeds")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--actor", default="cli", help="Actor identifier for action logging")
    args = parser.parse_args()

    try:
        init_db()
        rss_service = RssService()
        items = rss_service.fetch_all_feeds()

        with get_session() as session:
            art_repo = ArticleRepository(session)
            action_repo = ActionLogRepository(session)

            with action_repo.track_operation(
                stage="ingest",
                action="fetch_rss_feeds",
                actor=args.actor,
                details={"fetched_items": len(items)},
            ):
                saved = art_repo.save_feed_items(items)

            result = {
                "status": "success",
                "articles_fetched": len(items),
                "new_articles_saved": len(saved),
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(f"Fetched {len(items)} items. Saved {len(saved)} new unique articles.")

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Ingest failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
