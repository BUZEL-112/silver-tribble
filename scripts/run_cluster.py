#!/usr/bin/env python3
"""Standalone runner for article embeddings and story clustering."""

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
from src.services.clustering_service import ClusteringService


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster articles into story topics")
    parser.add_argument("--threshold", type=float, default=0.82, help="Cosine similarity cutoff")
    parser.add_argument("--model", type=str, default=None, help="Embedding model name")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--actor", default="cli", help="Actor identifier for action logging")
    args = parser.parse_args()

    try:
        init_db()
        with get_session() as session:
            art_repo = ArticleRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)
            service = ClusteringService(article_repo=art_repo, cost_repo=cost_repo)

            with action_repo.track_operation(
                stage="cluster",
                action="cluster_articles",
                actor=args.actor,
                details={"threshold": args.threshold, "model": args.model},
            ):
                embedded_count = service.generate_embeddings_for_new_articles(model=args.model)
                clusters = service.cluster_recent_articles(threshold=args.threshold)

            top_id = clusters[0].id if clusters else None
            result = {
                "status": "success",
                "clusters_created": len(clusters),
                "top_cluster_id": top_id,
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(
                    f"Embedded {embedded_count} articles. Created {len(clusters)} clusters. "
                    f"Top cluster ID: {top_id}"
                )

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Clustering failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
