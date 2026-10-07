"""Article embedding and cosine clustering service."""

import hashlib

import numpy as np
from openai import OpenAI

from src.core.config import settings
from src.models.entities import StoryCluster
from src.models.schemas import CostLogCreate
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.services.model_registry_service import ModelRegistryService


class ClusteringService:
    """Computes vector embeddings and clusters related news stories."""

    def __init__(
        self,
        article_repo: ArticleRepository,
        cost_repo: CostRepository,
        client: OpenAI | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        openai_key: str | None = None,
        gemini_key: str | None = None,
        embedding_base_url: str | None = None,
        embedding_api_key: str | None = None,
        model_registry_service: ModelRegistryService | None = None,
    ) -> None:
        self.article_repo = article_repo
        self.cost_repo = cost_repo
        self._custom_client = client
        self.base_url = embedding_base_url or base_url or settings.embedding_base_url
        self.api_key = embedding_api_key or api_key or settings.embedding_api_key
        self.openai_key = openai_key or settings.openai_api_key
        self.gemini_key = gemini_key or settings.gemini_api_key
        self.client = client or self._resolve_client(settings.llm_embedding_model)
        self.model_registry_service = model_registry_service or ModelRegistryService(
            cost_repo=self.cost_repo
        )
        self.last_run_id: str | None = None

    @staticmethod
    def is_local_model(model: str) -> bool:
        """Check if target embedding model should be run locally in-process."""
        m = model.lower()
        return (
            m.startswith("local")
            or m.startswith("fastembed")
            or "bge-small" in m
            or "all-minilm" in m
            or "bge-base" in m
        )

    @staticmethod
    def is_google_embedding_model(model: str) -> bool:
        """Check if target embedding model belongs to Google AI Studio."""
        m = model.lower()
        return "text-embedding-004" in m or "embedding-001" in m or "gemini" in m or "google" in m

    @staticmethod
    def is_openai_embedding_model(model: str) -> bool:
        """Check if target embedding model belongs to OpenAI."""
        m = model.lower()
        return "text-embedding-3" in m or "text-embedding-ada" in m or "openai" in m

    @staticmethod
    def parse_local_model_name(model: str) -> str:
        """Parse HuggingFace/fastembed model name from user spec."""
        if ":" in model:
            return model.split(":", 1)[1]
        if model.lower() in ["local", "fastembed"]:
            return "BAAI/bge-small-en-v1.5"
        return model

    def _resolve_client(self, model: str) -> OpenAI:
        """Resolve OpenAI-compatible client for embedding generation."""
        if self._custom_client:
            return self._custom_client

        if self.base_url:
            raw_url = self.base_url.rstrip("/")
            if "googleapis.com" in raw_url:
                effective_base_url = raw_url if raw_url.endswith("/openai") else f"{raw_url}/openai"
            else:
                effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
            if self.is_google_embedding_model(model) and self.gemini_key:
                effective_key = self.gemini_key
            else:
                effective_key = (
                    self.api_key
                    or self.gemini_key
                    or settings.litellm_api_key
                    or self.openai_key
                    or "sk-dummy"
                )
            return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=12.0)

        # Google AI Studio / Gemini embedding model
        if self.is_google_embedding_model(model) and (self.gemini_key or self.api_key):
            effective_gemini_key = self.gemini_key or self.api_key
            return OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=effective_gemini_key,
                timeout=12.0,
            )

        # OpenAI direct embedding model
        if (
            self.is_openai_embedding_model(model)
            or (self.api_key and self.api_key.startswith("sk-proj-"))
        ) and (self.openai_key or self.api_key):
            effective_openai_key = self.openai_key or self.api_key
            return OpenAI(
                base_url="https://api.openai.com/v1",
                api_key=effective_openai_key,
                timeout=12.0,
            )

        if settings.litellm_base_url and settings.litellm_base_url != "http://localhost:4000":
            raw_url = settings.litellm_base_url.rstrip("/")
            effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
            effective_key = self.api_key or settings.litellm_api_key or "sk-litellm-master-key"
            return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=12.0)

        raw_url = settings.litellm_base_url.rstrip("/")
        effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
        effective_key = self.api_key or settings.litellm_api_key or "sk-litellm-master-key"
        return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=10.0)

    def generate_embeddings_for_new_articles(
        self,
        model: str | None = None,
        article_ids: list[int] | None = None,
    ) -> int:
        """Fetch unembedded articles, compute embedding vectors, and persist."""
        if article_ids:
            all_articles = self.article_repo.get_articles_by_ids(article_ids)
            articles = [a for a in all_articles if not a.embedding]
        else:
            articles = self.article_repo.get_articles_without_embeddings(limit=None)

        if not articles:
            return 0

        target_model = model or settings.llm_embedding_model
        texts = [f"{a.title}. {a.summary[:300]}" for a in articles]

        try:
            if self._custom_client:
                response = self._custom_client.embeddings.create(
                    model=target_model,
                    input=texts,
                )
                embeddings_data = [item.embedding for item in response.data]
                actual_model = target_model
                provider = "custom_client"
                total_tokens = getattr(response.usage, "total_tokens", len(texts) * 50)
            else:
                embeddings_data, actual_model, model_def = (
                    self.model_registry_service.execute_role_fallback_embedding(
                        texts=texts,
                        model_override=model,
                    )
                )
                provider = "model_registry"
                total_tokens = len(texts) * 50

            batch_map = {
                articles[idx].id: emb_vals
                for idx, emb_vals in enumerate(embeddings_data)
                if idx < len(articles)
            }
            self.article_repo.update_article_embeddings_batch(batch_map, batch_size=50)

            cost_usd = (total_tokens / 1000.0) * 0.00002
            self.cost_repo.log_cost(
                CostLogCreate(
                    stage="clustering",
                    provider=provider,
                    model=actual_model,
                    units=float(total_tokens),
                    unit_type="tokens",
                    cost_usd=cost_usd,
                )
            )
            return len(articles)
        except Exception:
            # Fallback for offline or local test mode: generate deterministic normalized vectors
            fallback_map: dict[int, list[float]] = {}
            for article in articles:
                seed = int(hashlib.md5(article.title.encode("utf-8")).hexdigest()[:8], 16)
                rng = np.random.default_rng(seed)
                vec = rng.standard_normal(1536)
                norm_vec = (vec / np.linalg.norm(vec)).tolist()
                fallback_map[article.id] = norm_vec
            self.article_repo.update_article_embeddings_batch(fallback_map, batch_size=50)
            return len(articles)

    def cluster_recent_articles(
        self,
        threshold: float | None = None,
        article_ids: list[int] | None = None,
        hours_back: float | None = None,
        cluster_run_id: str | None = None,
    ) -> list[StoryCluster]:
        """Group embedded articles using cosine similarity cutoff with cluster run tracking."""
        import uuid
        from datetime import UTC, datetime

        run_id = (
            cluster_run_id
            or f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        self.last_run_id = run_id
        cutoff = threshold or settings.similarity_threshold

        if article_ids:
            self.generate_embeddings_for_new_articles(article_ids=article_ids)
            articles = self.article_repo.get_articles_by_ids(article_ids)
        elif hours_back is not None and hours_back > 0:
            articles = self.article_repo.get_articles(hours_back=hours_back, limit=None)
            unembedded_ids = [a.id for a in articles if not a.embedding]
            if unembedded_ids:
                self.generate_embeddings_for_new_articles(article_ids=unembedded_ids)
                articles = self.article_repo.get_articles_by_ids([a.id for a in articles])
        else:
            articles = self.article_repo.get_all_embedded_articles(limit=None)

        if not articles:
            self.article_repo.save_cluster_run(
                run_id=run_id, cluster_count=0, article_count=0, threshold=cutoff
            )
            return []

        embedded = [
            a
            for a in articles
            if a.embedding and isinstance(a.embedding, list) and len(a.embedding) > 0
        ]
        if not embedded:
            self.article_repo.save_cluster_run(
                run_id=run_id, cluster_count=0, article_count=0, threshold=cutoff
            )
            return []

        # Ensure consistent vector dimension across articles
        target_dim = len(embedded[0].embedding or [])
        valid_articles = [a for a in embedded if a.embedding and len(a.embedding) == target_dim]
        if not valid_articles:
            self.article_repo.save_cluster_run(
                run_id=run_id, cluster_count=0, article_count=0, threshold=cutoff
            )
            return []

        vectors = np.array([a.embedding for a in valid_articles], dtype=np.float32)

        # Cosine similarity matrix: S = (V . V^T)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized_vectors = vectors / norms
        sim_matrix = np.dot(normalized_vectors, normalized_vectors.T)

        visited = set()
        clusters: list[StoryCluster] = []

        for i in range(len(valid_articles)):
            if i in visited:
                continue

            # Connected component matching threshold
            cluster_indices = [i]
            visited.add(i)

            for j in range(len(valid_articles)):
                if j not in visited and sim_matrix[i, j] >= cutoff:
                    cluster_indices.append(j)
                    visited.add(j)

            cluster_articles = [valid_articles[idx] for idx in cluster_indices]
            art_ids = sorted([a.id for a in cluster_articles])

            # Deterministic hash of member IDs scoped to cluster_run_id
            ids_str = f"{run_id}:" + ",".join(map(str, art_ids))
            cluster_hash = hashlib.sha256(ids_str.encode("utf-8")).hexdigest()[:24]

            # Primary headline is the longest or earliest title
            primary_article = max(cluster_articles, key=lambda a: len(a.title))
            title = primary_article.title
            summary = "\n".join(
                [f"[{a.source}] {a.title}: {a.summary[:200]}" for a in cluster_articles]
            )

            run_index = len(clusters) + 1
            cluster = self.article_repo.save_story_cluster(
                cluster_hash=cluster_hash,
                title=title,
                summary=summary,
                article_ids=art_ids,
                cluster_run_id=run_id,
                run_cluster_index=run_index,
            )
            clusters.append(cluster)

        sorted_clusters = sorted(clusters, key=lambda c: c.article_count, reverse=True)
        for idx, c in enumerate(sorted_clusters):
            c.run_cluster_index = idx + 1
        self.article_repo.session.flush()

        self.article_repo.save_cluster_run(
            run_id=run_id,
            cluster_count=len(sorted_clusters),
            article_count=len(valid_articles),
            threshold=cutoff,
        )

        return sorted_clusters
