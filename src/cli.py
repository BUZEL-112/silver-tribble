import json
import re
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from src.core.config import settings
from src.core.database import get_session, init_db
from src.flows.video_pipeline_flow import run_roundup_pipeline, run_video_pipeline
from src.models.schemas import SentenceMediaPlacement, WordCaption
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.article_repository import ArticleRepository
from src.repositories.asset_repository import AssetRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.cache_pruning_service import CachePruningService
from src.services.caption_service import CaptionService
from src.services.cluster_review_service import ClusterReviewService
from src.services.clustering_service import ClusteringService
from src.services.health_service import HealthService
from src.services.media_service import MediaService
from src.services.render_service import RenderService
from src.services.rss_service import RssService
from src.services.script_service import ScriptService
from src.services.storage_service import get_storage_service
from src.services.tts_service import TtsService

app = typer.Typer(
    name="ai-video",
    help="AI News to YouTube Video Generation Pipeline CLI",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def update_env_file(updates: dict[str, str], env_path: Path = Path(".env")) -> None:
    """Update or append key-value pairs in the .env file."""
    if not env_path.exists():
        content = ""
    else:
        content = env_path.read_text(encoding="utf-8")

    for key, value in updates.items():
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content = content.rstrip() + f"\n{key}={value}\n"

    env_path.write_text(content.strip() + "\n", encoding="utf-8")


@app.command(name="config-llm")
def config_llm(
    planner_model: Annotated[
        str | None,
        typer.Option("--planner-model", "-p", help="Set default planning model in .env"),
    ] = None,
    writer_model: Annotated[
        str | None,
        typer.Option("--writer-model", "-w", help="Set default writing model in .env"),
    ] = None,
    embedding_model: Annotated[
        str | None,
        typer.Option("--embedding-model", "-e", help="Set default embedding model in .env"),
    ] = None,
    litellm_url: Annotated[
        str | None,
        typer.Option("--litellm-url", help="Set LiteLLM Base URL in .env"),
    ] = None,
    litellm_key: Annotated[
        str | None,
        typer.Option("--litellm-key", help="Set LiteLLM API Key in .env"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="Set default API key in .env"),
    ] = None,
    api_base: Annotated[
        str | None,
        typer.Option("--api-base", help="Set default API base URL in .env"),
    ] = None,
    openai_key: Annotated[
        str | None,
        typer.Option("--openai-key", help="Set OpenAI API Key in .env"),
    ] = None,
    deepseek_key: Annotated[
        str | None,
        typer.Option("--deepseek-key", help="Set DeepSeek API Key in .env"),
    ] = None,
    gemini_key: Annotated[
        str | None,
        typer.Option("--gemini-key", help="Set Gemini API Key in .env"),
    ] = None,
    embedding_base_url: Annotated[
        str | None,
        typer.Option(
            "--embedding-base-url",
            help="Set custom embedding endpoint in .env (e.g. Ollama or custom API)",
        ),
    ] = None,
    embedding_key: Annotated[
        str | None,
        typer.Option("--embedding-key", help="Set custom embedding API key in .env"),
    ] = None,
    test_connection: Annotated[
        bool,
        typer.Option("--test", "-t", help="Test live connection to LiteLLM with configured models"),
    ] = False,
) -> None:
    """View, configure, or test LiteLLM proxy connection and model routing."""
    updates: dict[str, str] = {}
    if planner_model:
        updates["LLM_PLANNING_MODEL"] = planner_model
        settings.llm_planning_model = planner_model
    if writer_model:
        updates["LLM_WRITING_MODEL"] = writer_model
        settings.llm_writing_model = writer_model
    if embedding_model:
        updates["LLM_EMBEDDING_MODEL"] = embedding_model
        settings.llm_embedding_model = embedding_model
    if embedding_base_url:
        updates["EMBEDDING_BASE_URL"] = embedding_base_url
        settings.embedding_base_url = embedding_base_url
    if embedding_key:
        updates["EMBEDDING_API_KEY"] = embedding_key
        settings.embedding_api_key = embedding_key
    effective_url = api_base or litellm_url
    if effective_url:
        updates["LITELLM_BASE_URL"] = effective_url
        settings.litellm_base_url = effective_url
    effective_key = api_key or litellm_key
    if effective_key:
        updates["LITELLM_API_KEY"] = effective_key
        settings.litellm_api_key = effective_key
    if openai_key:
        updates["OPENAI_API_KEY"] = openai_key
        settings.openai_api_key = openai_key
    if deepseek_key:
        updates["DEEPSEEK_API_KEY"] = deepseek_key
        settings.deepseek_api_key = deepseek_key
    if gemini_key:
        updates["GEMINI_API_KEY"] = gemini_key
        settings.gemini_api_key = gemini_key

    if updates:
        update_env_file(updates)
        console.print(f"[bold green]Updated {len(updates)} setting(s) in .env file.[/bold green]")

    table = Table(title="Active LLM & LiteLLM Configuration")
    table.add_column("Parameter", style="cyan", justify="left")
    table.add_column("Current Value", style="white", justify="left")
    table.add_column("Environment Variable", style="dim", justify="left")

    def mask_key(k: str | None) -> str:
        if not k:
            return "[red]Not configured[/red]"
        if len(k) <= 8:
            return f"[green]{k[:2]}***{k[-2:]}[/green]"
        return f"[green]{k[:4]}...{k[-4:]}[/green]"

    table.add_row(
        "Active Config Source",
        f"[bold green]{settings.config_source_label}[/bold green]",
        "config.yaml / .env",
    )
    table.add_row(
        "Planning Model (Stage 1)",
        f"[bold yellow]{settings.llm_planning_model}[/bold yellow]",
        "LLM_PLANNING_MODEL",
    )
    table.add_row(
        "Writing Model (Stage 2)",
        f"[bold yellow]{settings.llm_writing_model}[/bold yellow]",
        "LLM_WRITING_MODEL",
    )
    table.add_row(
        "Embedding Model",
        f"[bold yellow]{settings.llm_embedding_model}[/bold yellow]",
        "LLM_EMBEDDING_MODEL",
    )
    emb_endpoint = settings.embedding_base_url or (
        "[bold green]In-Process Local (fastembed)[/bold green]"
        if ClusteringService.is_local_model(settings.llm_embedding_model)
        else f"{settings.litellm_base_url} (LiteLLM / Direct)"
    )
    table.add_row("Embedding Endpoint", emb_endpoint, "EMBEDDING_BASE_URL")
    table.add_row("Embedding API Key", mask_key(settings.embedding_api_key), "EMBEDDING_API_KEY")
    table.add_row("LiteLLM Proxy URL", settings.litellm_base_url, "LITELLM_BASE_URL")
    table.add_row("LiteLLM API Key", mask_key(settings.litellm_api_key), "LITELLM_API_KEY")
    table.add_row("OpenAI Direct Key", mask_key(settings.openai_api_key), "OPENAI_API_KEY")
    table.add_row("DeepSeek Direct Key", mask_key(settings.deepseek_api_key), "DEEPSEEK_API_KEY")
    table.add_row("Gemini Direct Key", mask_key(settings.gemini_api_key), "GEMINI_API_KEY")

    console.print(table)

    if test_connection:
        console.print("\n[cyan]Testing connection to LLM endpoints...[/cyan]")
        dummy_repo: Any = None
        probe_service = ScriptService(
            article_repo=dummy_repo,
            script_repo=dummy_repo,
            cost_repo=dummy_repo,
        )

        for role, model in [
            ("Planning Model", settings.llm_planning_model),
            ("Writing Model", settings.llm_writing_model),
            ("Embedding Model", settings.llm_embedding_model),
        ]:
            if role == "Embedding Model" and ClusteringService.is_local_model(model):
                console.print(f"Pinging [bold]{role}[/bold] ('{model}') via local fastembed...")
                try:
                    from fastembed import TextEmbedding

                    local_name = ClusteringService.parse_local_model_name(model)
                    fe = TextEmbedding(model_name=local_name)
                    res = list(fe.embed(["ping"]))[0]
                    console.print(
                        f"[bold green][OK] Success:[/bold green] {role} ('{model}') "
                        f"locally computed {len(res)}-dim vector (0 network calls)."
                    )
                except Exception as e:
                    console.print(f"[bold red][FAIL] Failed:[/bold red] {role} ('{model}'): {e}")
                continue

            if role == "Embedding Model" and ClusteringService.is_google_embedding_model(model):
                console.print(f"Pinging [bold]{role}[/bold] ('{model}') via Google AI Studio...")
                try:
                    from google import genai

                    effective_gkey = settings.gemini_api_key or settings.embedding_api_key
                    if not effective_gkey:
                        raise ValueError("GEMINI_API_KEY is not configured")
                    g_client = genai.Client(api_key=effective_gkey)
                    resp = g_client.models.embed_content(
                        model=model,
                        contents=["ping"],
                    )
                    emb_dim = len(resp.embeddings[0].values)
                    console.print(
                        f"[bold green][OK] Success:[/bold green] {role} ('{model}') "
                        f"generated {emb_dim}-dim vector via Google AI Studio."
                    )
                except Exception as e:
                    console.print(f"[bold red][FAIL] Failed:[/bold red] {role} ('{model}'): {e}")
                continue

            client = probe_service._resolve_client(model)
            endpoint = str(client.base_url)
            console.print(f"Pinging [bold]{role}[/bold] ('{model}') via {endpoint}...")
            try:
                if "embedding" in model.lower():
                    resp_emb = client.embeddings.create(
                        model=model,
                        input=["ping"],
                    )
                    emb_dim = len(resp_emb.data[0].embedding)
                    console.print(
                        f"[bold green][OK] Success:[/bold green] {role} ('{model}') "
                        f"generated {emb_dim}-dim vector."
                    )
                else:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=5,
                    )
                    reply = resp.choices[0].message.content or ""
                    console.print(
                        f"[bold green][OK] Success:[/bold green] {role} ('{model}') responded: "
                        f"[dim]{reply.strip()}[/dim]"
                    )
            except Exception as e:
                console.print(f"[bold red][FAIL] Failed:[/bold red] {role} ('{model}'): {e}")


@app.command()
def setup_db() -> None:
    """Initialize database tables and extensions."""
    settings.ensure_directories()
    init_db()
    console.print("[green]Database tables initialized successfully.[/green]")


@app.command()
def ingest(
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Fetch latest AI news articles from RSS feeds."""
    init_db()
    service = RssService()
    items = service.fetch_all_feeds()
    with get_session() as session:
        repo = ArticleRepository(session)
        action_repo = ActionLogRepository(session)
        with action_repo.track_operation(
            stage="ingest",
            action="fetch_rss_feeds",
            actor=actor,
            details={"fetched_items": len(items)},
        ):
            saved = repo.save_feed_items(items)

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "articles_fetched": len(items),
                        "new_articles_saved": len(saved),
                    }
                )
            )
        else:
            msg = f"Ingested {len(items)} items. Saved {len(saved)} new unique articles."
            console.print(f"[green]{msg}[/green]")


@app.command()
def cluster(
    threshold: Annotated[
        float, typer.Option("--threshold", "-t", help="Cosine similarity cutoff")
    ] = 0.82,
    embedding_model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Embedding model (e.g. text-embedding-3-small)"),
    ] = None,
    litellm_url: Annotated[
        str | None,
        typer.Option("--litellm-url", help="LiteLLM proxy URL (overrides LITELLM_BASE_URL)"),
    ] = None,
    litellm_key: Annotated[
        str | None,
        typer.Option("--litellm-key", help="LiteLLM API key (overrides LITELLM_API_KEY)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="API key for LiteLLM or direct provider"),
    ] = None,
    api_base: Annotated[
        str | None,
        typer.Option("--api-base", help="Custom OpenAI-compatible API base URL"),
    ] = None,
    openai_key: Annotated[
        str | None,
        typer.Option("--openai-key", help="Direct OpenAI API key for embeddings"),
    ] = None,
    embedding_base_url: Annotated[
        str | None,
        typer.Option(
            "--embedding-base-url",
            help="Custom embedding endpoint URL (e.g. Ollama http://localhost:11434/v1)",
        ),
    ] = None,
    embedding_key: Annotated[
        str | None,
        typer.Option("--embedding-key", help="API key for custom embedding endpoint"),
    ] = None,
    gemini_key: Annotated[
        str | None,
        typer.Option("--gemini-key", help="Direct Google Gemini / AI Studio API key"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Embed new articles and group them into story clusters."""
    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)
        effective_url = api_base or litellm_url
        effective_key = api_key or litellm_key
        service = ClusteringService(
            article_repo=article_repo,
            cost_repo=cost_repo,
            base_url=effective_url,
            api_key=effective_key,
            openai_key=openai_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_key,
        )

        effective_emb = embedding_model or settings.llm_embedding_model
        if not as_json:
            console.print(f"[cyan]Generating embeddings using '{effective_emb}'...[/cyan]")

        with action_repo.track_operation(
            stage="cluster",
            action="cluster_articles",
            actor=actor,
            details={"threshold": threshold, "model": effective_emb},
        ):
            embedded_count = service.generate_embeddings_for_new_articles(model=embedding_model)
            clusters = service.cluster_recent_articles(threshold=threshold)

        top_id = clusters[0].id if clusters else None
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "clusters_created": len(clusters),
                        "top_cluster_id": top_id,
                    }
                )
            )
            return

        console.print(f"[green]Embedded {embedded_count} articles.[/green]")
        console.print(f"[cyan]Clustering stories with threshold {threshold}...[/cyan]")

        table = Table(title="Detected AI Story Clusters")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Articles", justify="right", style="magenta")
        table.add_column("Primary Headline", style="white")
        table.add_column("Status", style="yellow")

        for c in clusters:
            table.add_row(str(c.id), str(c.article_count), c.title[:75], c.status)

        console.print(table)


@app.command(name="clusters")
def list_clusters(
    cluster_id: Annotated[
        int | None,
        typer.Option("--cluster-id", "-c", help="Inspect single cluster and its articles"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of clusters to list")] = 20,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
) -> None:
    """Inspect story clusters and view constituent articles inside each cluster."""
    init_db()
    with get_session() as session:
        art_repo = ArticleRepository(session)
        if cluster_id is not None:
            cluster = art_repo.get_cluster_by_id(cluster_id)
            if not cluster:
                err_msg = f"Cluster {cluster_id} not found"
                if as_json:
                    print(json.dumps({"status": "failed", "error": err_msg}))
                else:
                    console.print(f"[red]Story cluster #{cluster_id} not found.[/red]")
                raise typer.Exit(code=1)

            articles = art_repo.get_articles_by_ids(cluster.article_ids or [])
            if as_json:
                print(
                    json.dumps(
                        {
                            "id": cluster.id,
                            "title": cluster.title,
                            "summary": cluster.summary,
                            "status": cluster.status,
                            "article_count": cluster.article_count,
                            "articles": [
                                {
                                    "id": a.id,
                                    "title": a.title,
                                    "source": a.source,
                                    "link": a.link,
                                    "summary": a.summary,
                                }
                                for a in articles
                            ],
                        }
                    )
                )
                return

            console.print(
                f"\n[bold cyan]Story Cluster #{cluster.id}[/bold cyan]: "
                f"[bold white]{cluster.title}[/bold white]"
            )
            console.print(
                f"[yellow]Status:[/yellow] {cluster.status} | "
                f"[magenta]Article Count:[/magenta] {cluster.article_count}"
            )
            if cluster.summary:
                console.print(f"[dim]{cluster.summary[:200]}...[/dim]\n")

            table = Table(title=f"Articles in Cluster #{cluster.id}")
            table.add_column("Art ID", justify="right", style="cyan")
            table.add_column("Source", style="magenta")
            table.add_column("Title", style="white")
            table.add_column("Link", style="blue")

            for a in articles:
                table.add_row(str(a.id), a.source, a.title[:65], a.link[:45])
            console.print(table)
            return

        clusters = art_repo.get_recent_clusters(limit=limit)
        if as_json:
            print(
                json.dumps(
                    [
                        {
                            "id": c.id,
                            "title": c.title,
                            "article_count": c.article_count,
                            "status": c.status,
                            "created_at": c.created_at.isoformat() if c.created_at else None,
                        }
                        for c in clusters
                    ]
                )
            )
            return

        if not clusters:
            console.print(
                "[yellow]No story clusters found. Run 'ingest' and 'cluster' first.[/yellow]"
            )
            return

        table = Table(title=f"Available Story Clusters ({len(clusters)} items)")
        table.add_column("Cluster ID", justify="right", style="cyan")
        table.add_column("Articles", justify="right", style="magenta")
        table.add_column("Primary Headline", style="white")
        table.add_column("Status", style="yellow")
        table.add_column("Created", style="dim")

        for c in clusters:
            created_str = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "N/A"
            table.add_row(
                str(c.id),
                str(c.article_count),
                c.title[:70],
                c.status,
                created_str,
            )
        console.print(table)
        console.print("[dim]Use 'ai-video clusters -c <id>' to inspect member articles.[/dim]")


@app.command()
def script(
    cluster_id: Annotated[
        int | None, typer.Option("--cluster-id", "-c", help="Target single cluster ID")
    ] = None,
    cluster_ids: Annotated[
        str | None,
        typer.Option(
            "--cluster-ids",
            help="Comma-separated cluster IDs for multi-story script (e.g. 3,6,8)",
        ),
    ] = None,
    aspect_ratio: Annotated[
        str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")
    ] = "9:16",
    planner_model: Annotated[
        str | None,
        typer.Option(
            "--planner-model",
            "-p",
            help="Planning LLM model via LiteLLM (e.g. gpt-4o-mini, claude-3-5, gemini-2.0)",
        ),
    ] = None,
    writer_model: Annotated[
        str | None,
        typer.Option(
            "--writer-model",
            "-w",
            help="Writing LLM model via LiteLLM (e.g. deepseek-chat, gpt-4o, qwen)",
        ),
    ] = None,
    litellm_url: Annotated[
        str | None,
        typer.Option("--litellm-url", help="LiteLLM proxy URL (overrides LITELLM_BASE_URL)"),
    ] = None,
    litellm_key: Annotated[
        str | None,
        typer.Option("--litellm-key", help="LiteLLM API key (overrides LITELLM_API_KEY)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="API key for LiteLLM or direct provider"),
    ] = None,
    api_base: Annotated[
        str | None,
        typer.Option("--api-base", help="Custom OpenAI-compatible API base URL"),
    ] = None,
    openai_key: Annotated[
        str | None,
        typer.Option("--openai-key", help="Direct OpenAI API key (for planner model)"),
    ] = None,
    deepseek_key: Annotated[
        str | None,
        typer.Option("--deepseek-key", help="Direct DeepSeek API key (for writer model)"),
    ] = None,
    gemini_key: Annotated[
        str | None,
        typer.Option("--gemini-key", help="Direct Google Gemini API key"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Generate structured beat sheet and narration for single or multiple clusters."""
    init_db()

    target_ids: list[int] = []
    if cluster_ids:
        target_ids = sorted(list(set(int(x.strip()) for x in cluster_ids.split(",") if x.strip())))
    elif cluster_id is not None:
        target_ids = [cluster_id]

    if not target_ids:
        err_msg = "Must provide either --cluster-id or --cluster-ids"
        if as_json:
            print(json.dumps({"status": "failed", "error": err_msg}))
        else:
            console.print("[red]Must provide either --cluster-id or --cluster-ids.[/red]")
        raise typer.Exit(code=1)

    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)
        effective_url = api_base or litellm_url
        effective_key = api_key or litellm_key
        service = ScriptService(
            article_repo=article_repo,
            script_repo=script_repo,
            cost_repo=cost_repo,
            base_url=effective_url,
            api_key=effective_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
        )

        effective_planner = planner_model or settings.llm_planning_model
        effective_writer = writer_model or settings.llm_writing_model

        if len(target_ids) > 1:
            if not as_json:
                console.print(
                    f"[cyan]Generating multi-cluster roundup script for clusters {target_ids} "
                    f"(Writer: [bold yellow]{effective_writer}[/bold yellow])...[/cyan]"
                )
            with action_repo.track_operation(
                stage="script",
                action="generate_roundup_script",
                actor=actor,
                details={"cluster_ids": target_ids, "aspect_ratio": aspect_ratio},
            ):
                record = service.generate_roundup_script(
                    cluster_ids=target_ids,
                    aspect_ratio=aspect_ratio,
                    model=writer_model,
                )
        else:
            single_id = target_ids[0]
            if not as_json:
                console.print(
                    f"[cyan]Generating script for cluster {single_id} "
                    f"(Planner: [bold yellow]{effective_planner}[/bold yellow], "
                    f"Writer: [bold yellow]{effective_writer}[/bold yellow])...[/cyan]"
                )
            with action_repo.track_operation(
                stage="script",
                action="generate_script",
                actor=actor,
                details={"cluster_id": single_id, "aspect_ratio": aspect_ratio},
            ):
                record = service.generate_full_script(
                    cluster_id=single_id,
                    aspect_ratio=aspect_ratio,
                    planner_model=planner_model,
                    writer_model=writer_model,
                )

        words = record.full_narration.split()
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "script_id": record.id,
                        "title": record.title,
                        "cluster_ids": target_ids,
                        "word_count": len(words),
                    }
                )
            )
            return

        console.print(f"[green]Created script record #{record.id}: '{record.title}'[/green]")
        console.print("\n[bold yellow]Spoken Narration Script:[/bold yellow]")
        console.print(record.full_narration)


@app.command(name="roundup")
def roundup(
    top_n: Annotated[
        int, typer.Option("--top-n", "-n", help="Number of top clusters for the roundup")
    ] = 3,
    cluster_ids: Annotated[
        str | None,
        typer.Option("--cluster-ids", "-c", help="Comma-separated cluster IDs (e.g. 1,2,3)"),
    ] = None,
    aspect_ratio: Annotated[
        str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")
    ] = "9:16",
    run_pipeline: Annotated[
        bool,
        typer.Option(
            "--run",
            help="Run full pipeline to final video instead of only script generation",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock Remotion render without executing node")
    ] = False,
    writer_model: Annotated[
        str | None,
        typer.Option(
            "--writer-model",
            "-w",
            help="Writing LLM model via LiteLLM (e.g. deepseek-chat, gpt-4o, qwen)",
        ),
    ] = None,
    litellm_url: Annotated[
        str | None,
        typer.Option("--litellm-url", help="LiteLLM proxy URL (overrides LITELLM_BASE_URL)"),
    ] = None,
    litellm_key: Annotated[
        str | None,
        typer.Option("--litellm-key", help="LiteLLM API key (overrides LITELLM_API_KEY)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="API key for LiteLLM or direct provider"),
    ] = None,
    api_base: Annotated[
        str | None,
        typer.Option("--api-base", help="Custom OpenAI-compatible API base URL"),
    ] = None,
    openai_key: Annotated[
        str | None,
        typer.Option("--openai-key", help="Direct OpenAI API key"),
    ] = None,
    deepseek_key: Annotated[
        str | None,
        typer.Option("--deepseek-key", help="Direct DeepSeek API key"),
    ] = None,
    gemini_key: Annotated[
        str | None,
        typer.Option("--gemini-key", help="Direct Google Gemini API key"),
    ] = None,
    embedding_model: Annotated[
        str | None,
        typer.Option("--embedding-model", "-e", help="Embedding model for clustering"),
    ] = None,
    embedding_base_url: Annotated[
        str | None,
        typer.Option("--embedding-base-url", help="Custom embedding endpoint URL"),
    ] = None,
    embedding_key: Annotated[
        str | None,
        typer.Option("--embedding-key", help="API key for custom embedding endpoint"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Generate multi-story news roundup script or execute full roundup video pipeline."""
    init_db()
    effective_url = api_base or litellm_url
    effective_key = api_key or litellm_key

    if run_pipeline:
        if not as_json:
            console.print("[bold cyan]Starting Multi-Story News Roundup Pipeline[/bold cyan]")
        parsed_cluster_ids = (
            [int(x.strip()) for x in cluster_ids.split(",") if x.strip()] if cluster_ids else None
        )
        result = run_roundup_pipeline(
            cluster_ids=parsed_cluster_ids,
            top_n=top_n,
            aspect_ratio=aspect_ratio,
            dry_run=dry_run,
            writer_model=writer_model,
            embedding_model=embedding_model,
            litellm_url=effective_url,
            litellm_key=effective_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
            embedding_base_url=embedding_base_url,
            embedding_key=embedding_key,
        )
        if as_json:
            print(json.dumps({"status": "success", **result}))
            return

        console.print("\n[bold green]Roundup Pipeline Run Completed Successfully[/bold green]")
        console.print(f"Cluster IDs: {', '.join(result['cluster_ids'])}")
        console.print(f"Script ID:   {result['script_id']}")
        console.print(f"Job ID:      {result['job_id']}")
        console.print(f"Video File:  {result['video_path']}")
        return

    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        if cluster_ids:
            parsed = [int(x.strip()) for x in cluster_ids.split(",") if x.strip()]
            target_ids = sorted(list(set(parsed)))
        else:
            recent = article_repo.get_recent_clusters(limit=top_n * 2)
            pending = [c for c in recent if c.status == "pending"]
            pool = pending if len(pending) >= top_n else recent
            target_ids = sorted([c.id for c in pool[:top_n]])

        if not target_ids:
            err_msg = "No story clusters found for roundup."
            if as_json:
                print(json.dumps({"status": "failed", "error": err_msg}))
            else:
                console.print("[red]No story clusters found to generate a roundup for.[/red]")
            raise typer.Exit(code=1)

        service = ScriptService(
            article_repo=article_repo,
            script_repo=script_repo,
            cost_repo=cost_repo,
            base_url=effective_url,
            api_key=effective_key,
            openai_key=openai_key,
            deepseek_key=deepseek_key,
            gemini_key=gemini_key,
        )

        effective_writer = writer_model or settings.llm_writing_model
        if not as_json:
            console.print(
                f"[cyan]Generating roundup script for clusters {target_ids} "
                f"(Writer: [bold yellow]{effective_writer}[/bold yellow])...[/cyan]"
            )

        with action_repo.track_operation(
            stage="script",
            action="generate_roundup_script",
            actor=actor,
            details={"cluster_ids": target_ids, "aspect_ratio": aspect_ratio},
        ):
            record = service.generate_roundup_script(
                cluster_ids=target_ids,
                aspect_ratio=aspect_ratio,
                model=writer_model,
            )

        words = record.full_narration.split()
        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "script_id": record.id,
                        "title": record.title,
                        "cluster_ids": target_ids,
                        "beats_count": len(record.beats),
                        "word_count": len(words),
                    }
                )
            )
            return

        console.print(f"[green]Created roundup script #{record.id}: '{record.title}'[/green]")
        console.print(f"[cyan]Covering {len(target_ids)} clusters with {len(words)} words.[/cyan]")
        console.print("\n[bold yellow]Spoken Roundup Narration Script:[/bold yellow]")
        console.print(record.full_narration)


@app.command()
def voice(
    script_id: Annotated[int, typer.Option("--script-id", "-s", help="Target script ID")],
    aspect_ratio: Annotated[
        str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")
    ] = "9:16",
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Synthesize voice track and word-level caption timestamps."""
    settings.ensure_directories()
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        script_repo = ScriptRepository(session)
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        script_record = script_repo.get_script_by_id(script_id)
        if not script_record:
            if as_json:
                err_obj = {"status": "failed", "error": f"Script ID {script_id} not found."}
                print(json.dumps(err_obj))
            else:
                console.print(f"[red]Script ID {script_id} not found.[/red]")
            raise typer.Exit(code=1)

        job = render_repo.create_job(script_id=script_id, aspect_ratio=aspect_ratio)

        with action_repo.track_operation(
            stage="voice",
            action="synthesize_voice_and_captions",
            actor=actor,
            job_id=job.id,
            details={"script_id": script_id},
        ):
            if not as_json:
                console.print(f"[cyan]Synthesizing TTS audio for script #{script_id}...[/cyan]")
            tts = TtsService(storage, cost_repo)
            audio_path, duration = tts.synthesize_speech(script_record.full_narration, job.id)
            render_repo.update_job_audio(job.id, audio_path, duration)

            if not as_json:
                console.print(f"[green]Audio generated ({duration:.1f}s): {audio_path}[/green]")
                console.print("[cyan]Extracting word timestamps with Whisper...[/cyan]")

            captions_service = CaptionService(storage, cost_repo)
            captions_path, captions = captions_service.generate_captions(
                audio_path, job.id, script_record.full_narration, duration
            )
            render_repo.update_job_captions(job.id, captions_path)

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "job_id": job.id,
                        "audio_path": audio_path,
                        "duration": round(duration, 2),
                    }
                )
            )
            return

        console.print(f"[green]Captions extracted ({len(captions)} words): {captions_path}[/green]")
        console.print(f"[bold green]Render job #{job.id} prepared for rendering.[/bold green]")


@app.command()
def media(
    job_id: Annotated[int, typer.Option("--job-id", "-j", help="Target render job ID")],
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Fetch sentence-level visual assets (Pexels / Giphy) for a job."""
    settings.ensure_directories()
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        render_repo = RenderRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            if as_json:
                print(json.dumps({"status": "failed", "error": f"Render job {job_id} not found."}))
            else:
                console.print(f"[red]Render job {job_id} not found.[/red]")
            raise typer.Exit(code=1)

        script = script_repo.get_script_by_id(job.script_id)
        if not script:
            if as_json:
                err_obj = {"status": "failed", "error": f"Script {job.script_id} not found."}
                print(json.dumps(err_obj))
            else:
                console.print(f"[red]Script {job.script_id} not found.[/red]")
            raise typer.Exit(code=1)

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

        asset_repo = AssetRepository(session)
        media_svc = MediaService(
            storage_service=storage,
            cost_repo=cost_repo,
            asset_repo=asset_repo,
        )

        with action_repo.track_operation(
            stage="media",
            action="fetch_media_assets",
            actor=actor,
            job_id=job.id,
            details={"caption_count": len(captions)},
        ):
            media_items = media_svc.process_media_for_job(
                job_id=job.id,
                captions=captions,
                beats=script.beats,
            )

        placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
        placements_path.parent.mkdir(parents=True, exist_ok=True)
        placements_path.write_text(
            json.dumps([p.model_dump() for p in media_items], indent=2),
            encoding="utf-8",
        )

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "job_id": job.id,
                        "media_count": len(media_items),
                        "media_items": [p.model_dump() for p in media_items],
                    }
                )
            )
            return

        console.print(
            f"[green]Fetched {len(media_items)} media items for job #{job.id}. "
            f"Saved to {placements_path}[/green]"
        )


@app.command(name="edit-media")
def edit_media(
    job_id: Annotated[int, typer.Option("--job-id", "-j", help="Target render job ID")],
    list_items: Annotated[
        bool,
        typer.Option("--list", "-l", help="List all material placements with scene index numbers"),
    ] = False,
    index: Annotated[
        int | None, typer.Option("--index", "-i", help="Material sentence index to edit")
    ] = None,
    query: Annotated[
        str | None, typer.Option("--query", "-q", help="Search query for Pexels or Giphy")
    ] = None,
    file_path: Annotated[
        str | None, typer.Option("--file", "-f", help="Local media file path")
    ] = None,
    url: Annotated[str | None, typer.Option("--url", "-u", help="Direct URL to media file")] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Provider for search (pexels or giphy)")
    ] = None,
    re_render: Annotated[
        bool, typer.Option("--re-render", help="Re-render video after editing placement")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock Remotion render without executing node")
    ] = False,
    show_indices: Annotated[
        bool,
        typer.Option(
            "--show-indices",
            help="Display on-screen scene index badges during playback (review mode)",
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Inspect and replace sentence-level visual placements referenced by index number."""
    settings.ensure_directories()
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        render_repo = RenderRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            if as_json:
                print(json.dumps({"status": "failed", "error": f"Render job {job_id} not found."}))
            else:
                console.print(f"[red]Render job {job_id} not found.[/red]")
            raise typer.Exit(code=1)

        job_db_id = job.id
        job_aspect_ratio = job.aspect_ratio or "9:16"
        job_script_id = job.script_id
        job_captions_path = job.captions_path

        asset_repo = AssetRepository(session)
        media_svc = MediaService(
            storage_service=storage,
            cost_repo=cost_repo,
            asset_repo=asset_repo,
        )
        placements = media_svc.get_job_placements(job_db_id)

        if list_items or (index is None and not re_render):
            if as_json:
                print(
                    json.dumps(
                        {
                            "status": "success",
                            "job_id": job_db_id,
                            "media_count": len(placements),
                            "placements": [p.model_dump() for p in placements],
                        },
                        indent=2,
                    )
                )
                return

            table = Table(title=f"Media Placements for Render Job #{job_db_id}")
            table.add_column("Index", style="cyan", justify="right")
            table.add_column("Time Range", style="magenta")
            table.add_column("Type", style="yellow")
            table.add_column("Provider", style="green")
            table.add_column("Query", style="white")
            table.add_column("Narration", style="dim")
            table.add_column("Asset Path / URL", style="blue")

            for p in placements:
                time_range = f"{p.start_time:.1f}s - {p.end_time:.1f}s"
                text_snip = (
                    (p.text[:40] + "...") if p.text and len(p.text) > 40 else (p.text or "-")
                )
                path_snip = p.local_path or p.source_url or "-"
                if len(path_snip) > 45:
                    path_snip = "..." + path_snip[-42:]
                table.add_row(
                    f"#{p.sentence_index}",
                    time_range,
                    p.media_type.upper(),
                    p.provider,
                    p.query or "-",
                    text_snip,
                    path_snip,
                )

            console.print(table)
            return

        updated_placement = None
        if index is not None:
            if not query and not file_path and not url:
                if as_json:
                    print(
                        json.dumps(
                            {
                                "status": "failed",
                                "error": (
                                    "Must specify --query, --file, or --url when editing an index"
                                ),
                            }
                        )
                    )
                else:
                    console.print(
                        "[red]Must specify --query, --file, or --url when editing an index[/red]"
                    )
                raise typer.Exit(code=1)

            with action_repo.track_operation(
                stage="media",
                action="edit_media_placement",
                actor=actor,
                job_id=job_db_id,
                details={"sentence_index": index},
            ):
                if query:
                    prov = provider or "pexels"
                    updated_placement = media_svc.search_and_replace_placement(
                        job_id=job_db_id,
                        sentence_index=index,
                        query=query,
                        provider=prov,
                        media_type="video",
                        aspect_ratio=job_aspect_ratio,
                    )
                elif file_path:
                    updated_placement = media_svc.update_placement_media(
                        job_id=job_db_id,
                        sentence_index=index,
                        new_media_path_or_url=file_path,
                        provider="custom",
                    )
                elif url:
                    updated_placement = media_svc.update_placement_media(
                        job_id=job_db_id,
                        sentence_index=index,
                        new_media_path_or_url=url,
                        provider="custom",
                    )

        rendered_path_str = None
        if re_render:
            script = script_repo.get_script_by_id(job_script_id)
            if not script:
                if as_json:
                    print(
                        json.dumps(
                            {"status": "failed", "error": f"Script {job_script_id} not found"}
                        )
                    )
                else:
                    console.print(f"[red]Script {job_script_id} not found[/red]")
                raise typer.Exit(code=1)

            captions: list[WordCaption] = []
            if job_captions_path:
                local_cap_path = storage.get_local_path(job_captions_path)
                if local_cap_path.exists():
                    cap_data = json.loads(local_cap_path.read_text(encoding="utf-8"))
                    captions = [WordCaption(**item) for item in cap_data]

            render_svc = RenderService(render_repo, cost_repo, storage)
            with action_repo.track_operation(
                stage="render",
                action="re_render_video",
                actor=actor,
                job_id=job_db_id,
                details={"dry_run": dry_run, "show_indices": show_indices},
            ):
                out_path = render_svc.re_render_job(
                    job_id=job_db_id,
                    dry_run=dry_run,
                    show_material_indices=show_indices,
                    script=script,
                    captions=captions,
                )
                rendered_path_str = str(out_path.resolve())

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "job_id": job_db_id,
                        "updated_index": index,
                        "updated_placement": (
                            updated_placement.model_dump() if updated_placement else None
                        ),
                        "re_rendered": re_render,
                        "output_video_path": rendered_path_str,
                    },
                    indent=2,
                )
            )
            return

        if updated_placement:
            console.print(
                f"[bold green]Updated Scene #{updated_placement.sentence_index}:[/bold green] "
                f"{updated_placement.local_path or updated_placement.source_url}"
            )
        if rendered_path_str:
            console.print(f"[bold green]Re-rendered video output: {rendered_path_str}[/bold green]")


@app.command()
def render(
    job_id: Annotated[int, typer.Option("--job-id", "-j", help="Render job ID")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock Remotion render without executing node")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Render the finalized video through the Remotion engine."""
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        script_repo = ScriptRepository(session)
        action_repo = ActionLogRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            if as_json:
                print(json.dumps({"status": "failed", "error": f"Render job {job_id} not found."}))
            else:
                console.print(f"[red]Render job {job_id} not found.[/red]")
            raise typer.Exit(code=1)

        script_record = script_repo.get_script_by_id(job.script_id)
        if not script_record:
            if as_json:
                err_obj = {"status": "failed", "error": f"Script {job.script_id} not found."}
                print(json.dumps(err_obj))
            else:
                console.print(f"[red]Script {job.script_id} not found.[/red]")
            raise typer.Exit(code=1)

        caption_service = CaptionService(storage, cost_repo)
        _, captions = caption_service.generate_captions(
            audio_path_or_url=job.audio_path or "",
            job_id=job.id,
            reference_text=script_record.full_narration,
            total_duration=job.duration_seconds or 30.0,
        )

        placements: list[SentenceMediaPlacement] = []
        placements_path = settings.media_cache_dir / f"placements_job_{job.id}.json"
        if placements_path.exists():
            try:
                raw_p = json.loads(placements_path.read_text(encoding="utf-8"))
                placements = [SentenceMediaPlacement(**item) for item in raw_p]
            except Exception:
                placements = []

        audio_local_path = storage.get_local_path(job.audio_path or "")
        service = RenderService(render_repo, cost_repo, storage)

        if not as_json:
            console.print("[cyan]Writing Remotion render props...[/cyan]")

        service.prepare_render_props(
            job=job,
            script=script_record,
            captions=captions,
            audio_local_path=audio_local_path,
            duration_seconds=job.duration_seconds or 30.0,
            media_placements=placements,
        )

        if not as_json:
            console.print(f"[cyan]Rendering video for job #{job.id}...[/cyan]")

        with action_repo.track_operation(
            stage="render",
            action="render_video",
            actor=actor,
            job_id=job.id,
            details={"dry_run": dry_run},
        ):
            output_path = service.execute_render(job_id=job.id, dry_run=dry_run)

        if as_json:
            print(
                json.dumps(
                    {
                        "status": "success",
                        "job_id": job.id,
                        "output_video_path": str(output_path.resolve()),
                    }
                )
            )
            return

        console.print(f"[bold green]Render completed: {output_path}[/bold green]")


@app.command()
def run(
    auto_top: Annotated[
        bool,
        typer.Option(
            "--auto-top",
            help="Pick highest-volume trending cluster without interactive prompt",
        ),
    ] = False,
    cluster_id: Annotated[int | None, typer.Option("--cluster-id", "-c")] = None,
    cluster_ids: Annotated[
        str | None,
        typer.Option(
            "--cluster-ids",
            help="Comma-separated cluster IDs for multi-topic video (e.g. 3,6,8)",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            "-t",
            help="Review timeout in seconds for interactive cluster selection",
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--no-interactive",
            help="Enable or disable interactive cluster review gate",
        ),
    ] = True,
    aspect_ratio: Annotated[str, typer.Option("--aspect-ratio", "-a")] = "9:16",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock Remotion render without executing node")
    ] = False,
    planner_model: Annotated[
        str | None,
        typer.Option("--planner-model", "-p", help="Planning LLM model via LiteLLM"),
    ] = None,
    writer_model: Annotated[
        str | None,
        typer.Option("--writer-model", "-w", help="Writing LLM model via LiteLLM"),
    ] = None,
    litellm_url: Annotated[
        str | None,
        typer.Option("--litellm-url", help="LiteLLM proxy URL (overrides LITELLM_BASE_URL)"),
    ] = None,
    litellm_key: Annotated[
        str | None,
        typer.Option("--litellm-key", help="LiteLLM API key (overrides LITELLM_API_KEY)"),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", "-k", help="API key for LiteLLM or direct provider"),
    ] = None,
    api_base: Annotated[
        str | None,
        typer.Option("--api-base", help="Custom OpenAI-compatible API base URL"),
    ] = None,
    embedding_model: Annotated[
        str | None,
        typer.Option("--embedding-model", "-e", help="Embedding model for clustering"),
    ] = None,
    openai_key: Annotated[
        str | None,
        typer.Option("--openai-key", help="Direct OpenAI API key"),
    ] = None,
    deepseek_key: Annotated[
        str | None,
        typer.Option("--deepseek-key", help="Direct DeepSeek API key"),
    ] = None,
    embedding_base_url: Annotated[
        str | None,
        typer.Option(
            "--embedding-base-url",
            help="Custom embedding endpoint URL (e.g. Ollama http://localhost:11434/v1)",
        ),
    ] = None,
    embedding_key: Annotated[
        str | None,
        typer.Option("--embedding-key", help="API key for custom embedding endpoint"),
    ] = None,
    gemini_key: Annotated[
        str | None,
        typer.Option("--gemini-key", help="Direct Google Gemini / AI Studio API key"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
    actor: Annotated[
        str, typer.Option("--actor", help="Actor identifier for action logging")
    ] = "cli",
) -> None:
    """Execute end-to-end pipeline from news ingestion to final video render."""
    if not as_json:
        console.print("[bold cyan]Starting AI News to YouTube Video Pipeline[/bold cyan]")
    init_db()
    effective_url = api_base or litellm_url
    effective_key = api_key or litellm_key

    target_cluster_ids: list[int] | None = None
    if cluster_ids:
        target_cluster_ids = [int(x.strip()) for x in cluster_ids.split(",") if x.strip()]
    elif cluster_id is not None:
        target_cluster_ids = [cluster_id]
    elif auto_top or not interactive:
        target_cluster_ids = None
    else:
        # Interactive review gate with timeout fallback
        if not as_json:
            console.print("[cyan]Discovering fresh AI news story clusters...[/cyan]")
        with get_session() as session:
            art_repo = ArticleRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            rss_svc = RssService()
            items = rss_svc.fetch_all_feeds()
            art_repo.save_feed_items(items)

            clustering_svc = ClusteringService(
                article_repo=art_repo,
                cost_repo=cost_repo,
                base_url=effective_url,
                api_key=effective_key,
                openai_key=openai_key,
                gemini_key=gemini_key,
                embedding_base_url=embedding_base_url,
                embedding_api_key=embedding_key,
            )
            clustering_svc.generate_embeddings_for_new_articles(model=embedding_model)
            clusters = clustering_svc.cluster_recent_articles()

            if not clusters:
                clusters = art_repo.get_recent_clusters(limit=10)

            review_svc = ClusterReviewService(console=console, timeout_seconds=timeout)
            target_cluster_ids = review_svc.prompt_cluster_selection(
                clusters=clusters,
                timeout_seconds=timeout,
                is_interactive=interactive,
                actor=actor,
                action_repo=action_repo,
            )

    single_cluster_id = (
        target_cluster_ids[0] if (target_cluster_ids and len(target_cluster_ids) == 1) else None
    )
    multi_cluster_ids = (
        target_cluster_ids if (target_cluster_ids and len(target_cluster_ids) > 1) else None
    )

    result = run_video_pipeline(
        cluster_id=single_cluster_id,
        cluster_ids=multi_cluster_ids,
        aspect_ratio=aspect_ratio,
        dry_run=dry_run,
        planner_model=planner_model,
        writer_model=writer_model,
        embedding_model=embedding_model,
        litellm_url=effective_url,
        litellm_key=effective_key,
        openai_key=openai_key,
        deepseek_key=deepseek_key,
        gemini_key=gemini_key,
        embedding_base_url=embedding_base_url,
        embedding_key=embedding_key,
    )
    if as_json:
        print(json.dumps({"status": "success", **result}))
        return

    console.print("\n[bold green]Pipeline Run Completed Successfully[/bold green]")
    if result.get("cluster_id"):
        console.print(f"Cluster ID: {result.get('cluster_id')}")
    elif "cluster_ids" in result and isinstance(result["cluster_ids"], list):
        console.print(f"Cluster IDs: {', '.join(result['cluster_ids'])}")
    console.print(f"Script ID:   {result.get('script_id')}")
    console.print(f"Job ID:      {result.get('job_id')}")
    console.print(f"Video File:  {result.get('video_path')}")


@app.command()
def logs(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Number of recent logs to show")] = 50,
    stage: Annotated[str | None, typer.Option("--stage", help="Filter by pipeline stage")] = None,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter by status (started, success, failed)")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
) -> None:
    """Query and display pipeline audit action logs."""
    init_db()
    with get_session() as session:
        repo = ActionLogRepository(session)
        entries = repo.get_recent_logs(limit=limit, stage=stage, status=status)

        if as_json:
            out = [
                {
                    "id": e.id,
                    "stage": e.stage,
                    "action": e.action,
                    "actor": e.actor,
                    "status": e.status,
                    "job_id": e.job_id,
                    "message": e.message,
                    "duration_seconds": e.duration_seconds,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in entries
            ]
            print(json.dumps(out))
            return

        table = Table(title="Pipeline Audit Action Logs")
        table.add_column("ID", justify="right", style="cyan")
        table.add_column("Stage", style="blue")
        table.add_column("Action", style="white")
        table.add_column("Actor", style="magenta")
        table.add_column("Status", style="yellow")
        table.add_column("Job ID", justify="right")
        table.add_column("Duration (s)", justify="right")
        table.add_column("Message", style="dim")
        table.add_column("Time", style="dim")

        for e in entries:
            dur = f"{e.duration_seconds:.2f}" if e.duration_seconds is not None else "-"
            job_str = str(e.job_id) if e.job_id is not None else "-"
            t_str = e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "-"
            status_style = (
                "green" if e.status == "success" else ("red" if e.status == "failed" else "yellow")
            )
            table.add_row(
                str(e.id),
                e.stage,
                e.action,
                e.actor,
                f"[{status_style}]{e.status}[/{status_style}]",
                job_str,
                dur,
                e.message[:40] if e.message else "",
                t_str,
            )

        console.print(table)


@app.command()
def costs() -> None:
    """Display detailed cost breakdown across all pipeline stages."""
    init_db()
    with get_session() as session:
        repo = CostRepository(session)
        total = repo.get_total_spend()
        stage_spend = repo.get_spend_by_stage()
        video_spend = repo.get_per_video_costs()

        table = Table(title="Pipeline Spend by Stage")
        table.add_column("Stage", style="cyan")
        table.add_column("Invocations", justify="right", style="magenta")
        table.add_column("Total Cost (USD)", justify="right", style="green")

        for row in stage_spend:
            table.add_row(row["stage"], str(row["call_count"]), f"${row['total_usd']:.5f}")

        console.print(table)
        console.print(f"\n[bold]Total Pipeline Spend: [green]${total:.4f}[/green][/bold]\n")

        if video_spend:
            vid_table = Table(title="Cost per Video Job")
            vid_table.add_column("Job ID", style="cyan", justify="right")
            vid_table.add_column("Cost (USD)", style="green", justify="right")
            vid_table.add_column("Logged Stages", justify="right")

            for v in video_spend:
                vid_table.add_row(
                    str(v["job_id"]),
                    f"${v['total_usd']:.4f}",
                    str(v["records_count"]),
                )

            console.print(vid_table)


@app.command(name="export-litellm-config")
def export_litellm_config(
    output_path: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Path to write generated LiteLLM config YAML file",
        ),
    ] = Path("config/litellm_config.yaml"),
) -> None:
    """Generate LiteLLM proxy configuration automatically from active config.yaml."""
    planning_model = settings.llm_planning_model
    writing_model = settings.llm_writing_model
    embedding_model = settings.llm_embedding_model

    models: list[dict[str, Any]] = []

    def get_litellm_model_name(m: str) -> str:
        if (
            m.startswith("gpt")
            or m.startswith("text-embedding")
            or m.startswith("o1")
            or m.startswith("o3")
        ):
            return f"openai/{m}"
        if "deepseek" in m:
            return f"deepseek/{m}"
        if "gemini" in m:
            return f"gemini/{m}"
        return m

    def get_env_key(m: str) -> str:
        if "deepseek" in m:
            return "os.environ/DEEPSEEK_API_KEY"
        if "gemini" in m:
            return "os.environ/GEMINI_API_KEY"
        return "os.environ/OPENAI_API_KEY"

    added: set[str] = set()
    for m in [planning_model, writing_model, embedding_model]:
        if not m or m in added or m.lower() in ["local", "fastembed"]:
            continue
        added.add(m)
        models.append(
            {
                "model_name": m,
                "litellm_params": {
                    "model": get_litellm_model_name(m),
                    "api_key": get_env_key(m),
                    "timeout": 30,
                },
            }
        )

    litellm_cfg = {
        "model_list": models,
        "router_settings": {
            "num_retries": 2,
            "retry_after": 2,
            "timeout": 40,
        },
        "general_settings": {
            "master_key": settings.litellm_api_key or "sk-litellm-master-key",
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# ==============================================================================\n"
        "# Auto-generated LiteLLM Proxy Configuration\n"
        "# Generated from active application settings / config.yaml\n"
        "# ==============================================================================\n\n"
    )
    import yaml

    output_path.write_text(header + yaml.dump(litellm_cfg, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Exported LiteLLM configuration to [bold]{output_path}[/bold][/green]")


@app.command(name="assets")
def list_assets(
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max assets to display")] = 20,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider", "-p", help="Filter by provider (e.g. pexels, pixabay, flux_generation)"
        ),
    ] = None,
    emotion: Annotated[
        str | None, typer.Option("--emotion", "-e", help="Filter by emotion tag")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output machine-readable JSON")] = False,
) -> None:
    """List indexed visual assets in the reusable asset library."""
    init_db()
    with get_session() as session:
        repo = AssetRepository(session)
        records = repo.list_assets(limit=limit, provider=provider, emotion=emotion)

        if as_json:
            out = [
                {
                    "id": r.id,
                    "asset_hash": r.asset_hash,
                    "media_type": r.media_type,
                    "provider": r.provider,
                    "query": r.query,
                    "tags": r.tags,
                    "emotion_tags": r.emotion_tags,
                    "shot_type": r.shot_type,
                    "aspect_ratio": r.aspect_ratio,
                    "vlm_score": r.vlm_score,
                    "usage_count": r.usage_count,
                    "local_path": r.local_path,
                }
                for r in records
            ]
            print(json.dumps(out))
            return

        if not records:
            console.print("[yellow]No visual assets found in library matching criteria.[/yellow]")
            return

        table = Table(title=f"Visual Asset Library ({len(records)} items)")
        table.add_column("ID", justify="right", style="cyan")
        table.add_column("Provider", style="magenta")
        table.add_column("Type", style="green")
        table.add_column("Query / Prompt", style="white")
        table.add_column("Emotions", style="yellow")
        table.add_column("VLM Score", justify="right")
        table.add_column("Uses", justify="right")

        for r in records:
            emotions_str = ", ".join(r.emotion_tags[:2]) if r.emotion_tags else ""
            vlm_str = f"{r.vlm_score:.1f}" if r.vlm_score is not None else "N/A"
            query_str = (r.query or "")[:35]
            table.add_row(
                str(r.id),
                r.provider,
                r.media_type,
                query_str,
                emotions_str,
                vlm_str,
                str(r.usage_count),
            )
        console.print(table)


@app.command(name="ui")
def ui(
    host: Annotated[str, typer.Option("--host", "-h", help="Bind host address")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port number")] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Enable auto-reload on code modifications")
    ] = False,
) -> None:
    """Launch the Web UI dashboard."""
    import uvicorn

    console.print(f"[bold green]Starting Web UI on http://{host}:{port}[/bold green]")
    uvicorn.run("src.web:app", host=host, port=port, reload=reload)


@app.command(name="web")
def web(
    host: Annotated[str, typer.Option("--host", "-h", help="Bind host address")] = "0.0.0.0",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port number")] = 8000,
    reload: Annotated[
        bool, typer.Option("--reload", help="Enable auto-reload on code modifications")
    ] = False,
) -> None:
    """Launch the Web UI dashboard (alias for ui)."""
    ui(host=host, port=port, reload=reload)


@app.command(name="health")
def health_check() -> None:
    """Run comprehensive system diagnostics on database, storage, tools, and providers."""
    service = HealthService()
    status = service.run_health_check()

    table = Table(title=f"System Health Diagnostics (Overall: {status.status.upper()})")
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Details", style="white")

    for comp in status.components:
        color = (
            "green"
            if comp.status == "healthy"
            else ("yellow" if comp.status == "degraded" else "red")
        )
        table.add_row(comp.name, f"[{color}]{comp.status.upper()}[/{color}]", comp.details)

    console.print(table)


@app.command(name="prune")
def prune_cache(
    retention_hours: Annotated[
        int | None,
        typer.Option("--retention-hours", "-r", help="Prune files older than this many hours"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview pruned files without deleting them"),
    ] = False,
) -> None:
    """Prune unindexed temporary media files older than retention hours."""
    with get_session() as session:
        asset_repo = AssetRepository(session)
        service = CachePruningService(asset_repo=asset_repo)
        result = service.prune_cache(retention_hours=retention_hours, dry_run=dry_run)

    mb_freed = result.bytes_freed / (1024 * 1024)
    action_label = "Would delete" if dry_run else "Deleted"
    console.print(
        f"[bold green]Prune complete.[/bold green] {action_label} "
        f"{result.files_deleted} unindexed files out of {result.files_scanned} scanned, "
        f"freeing {mb_freed:.2f} MB."
    )


if __name__ == "__main__":
    app()
