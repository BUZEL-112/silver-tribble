import re
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from src.core.config import settings
from src.core.database import get_session, init_db
from src.flows.video_pipeline_flow import run_video_pipeline
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.clustering_service import ClusteringService
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
                console.print(
                    f"Pinging [bold]{role}[/bold] ('{model}') via local fastembed..."
                )
                try:
                    from fastembed import TextEmbedding

                    local_name = ClusteringService.parse_local_model_name(model)
                    fe = TextEmbedding(model_name=local_name)
                    res = list(fe.embed(["ping"]))[0]
                    console.print(
                        f"[bold green]✓ Success:[/bold green] {role} ('{model}') "
                        f"locally computed {len(res)}-dim vector (0 network calls)."
                    )
                except Exception as e:
                    console.print(f"[bold red]✗ Failed:[/bold red] {role} ('{model}'): {e}")
                continue

            if role == "Embedding Model" and ClusteringService.is_google_embedding_model(model):
                console.print(
                    f"Pinging [bold]{role}[/bold] ('{model}') via Google AI Studio..."
                )
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
                        f"[bold green]✓ Success:[/bold green] {role} ('{model}') "
                        f"generated {emb_dim}-dim vector via Google AI Studio."
                    )
                except Exception as e:
                    console.print(f"[bold red]✗ Failed:[/bold red] {role} ('{model}'): {e}")
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
                        f"[bold green]✓ Success:[/bold green] {role} ('{model}') "
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
                        f"[bold green]✓ Success:[/bold green] {role} ('{model}') responded: "
                        f"[dim]{reply.strip()}[/dim]"
                    )
            except Exception as e:
                console.print(f"[bold red]✗ Failed:[/bold red] {role} ('{model}'): {e}")


@app.command()
def setup_db() -> None:
    """Initialize database tables and extensions."""
    settings.ensure_directories()
    init_db()
    console.print("[green]Database tables initialized successfully.[/green]")


@app.command()
def ingest() -> None:
    """Fetch latest AI news articles from RSS feeds."""
    init_db()
    service = RssService()
    items = service.fetch_all_feeds()
    with get_session() as session:
        repo = ArticleRepository(session)
        saved = repo.save_feed_items(items)
        console.print(
            f"[green]Ingested {len(items)} items. Saved {len(saved)} new unique articles.[/green]"
        )


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
) -> None:
    """Embed new articles and group them into story clusters."""
    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        cost_repo = CostRepository(session)
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
        console.print(f"[cyan]Generating embeddings using '{effective_emb}'...[/cyan]")
        embedded_count = service.generate_embeddings_for_new_articles(model=embedding_model)
        console.print(f"[green]Embedded {embedded_count} articles.[/green]")

        console.print(f"[cyan]Clustering stories with threshold {threshold}...[/cyan]")
        clusters = service.cluster_recent_articles(threshold=threshold)

        table = Table(title="Detected AI Story Clusters")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Articles", justify="right", style="magenta")
        table.add_column("Primary Headline", style="white")
        table.add_column("Status", style="yellow")

        for c in clusters:
            table.add_row(str(c.id), str(c.article_count), c.title[:75], c.status)

        console.print(table)


@app.command()
def script(
    cluster_id: Annotated[int, typer.Option("--cluster-id", "-c", help="Target cluster ID")],
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
) -> None:
    """Generate structured beat sheet and comedic narration for a story cluster."""
    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
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
        console.print(
            f"[cyan]Generating script for cluster {cluster_id} "
            f"(Planner: [bold yellow]{effective_planner}[/bold yellow], "
            f"Writer: [bold yellow]{effective_writer}[/bold yellow])...[/cyan]"
        )
        record = service.generate_full_script(
            cluster_id=cluster_id,
            aspect_ratio=aspect_ratio,
            planner_model=planner_model,
            writer_model=writer_model,
        )

        console.print(f"[green]Created script record #{record.id}: '{record.title}'[/green]")
        console.print("\n[bold yellow]Spoken Narration Script:[/bold yellow]")
        console.print(record.full_narration)


@app.command()
def voice(
    script_id: Annotated[int, typer.Option("--script-id", "-s", help="Target script ID")],
    aspect_ratio: Annotated[
        str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")
    ] = "9:16",
) -> None:
    """Synthesize voice track and word-level caption timestamps."""
    settings.ensure_directories()
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        script_repo = ScriptRepository(session)
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)

        script_record = script_repo.get_script_by_id(script_id)
        if not script_record:
            console.print(f"[red]Script ID {script_id} not found.[/red]")
            raise typer.Exit(code=1)

        job = render_repo.create_job(script_id=script_id, aspect_ratio=aspect_ratio)

        console.print(f"[cyan]Synthesizing TTS audio for script #{script_id}...[/cyan]")
        tts = TtsService(storage, cost_repo)
        audio_path, duration = tts.synthesize_speech(script_record.full_narration, job.id)
        render_repo.update_job_audio(job.id, audio_path, duration)
        console.print(f"[green]Audio generated ({duration:.1f}s): {audio_path}[/green]")

        console.print("[cyan]Extracting word timestamps with Whisper...[/cyan]")
        captions_service = CaptionService(storage, cost_repo)
        captions_path, captions = captions_service.generate_captions(
            audio_path, job.id, script_record.full_narration, duration
        )
        render_repo.update_job_captions(job.id, captions_path)
        console.print(
            f"[green]Captions extracted ({len(captions)} words): {captions_path}[/green]"
        )
        console.print(f"[bold green]Render job #{job.id} prepared for rendering.[/bold green]")


@app.command()
def render(
    job_id: Annotated[int, typer.Option("--job-id", "-j", help="Render job ID")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Mock Remotion render without executing node")
    ] = False,
) -> None:
    """Render the finalized video through the Remotion engine."""
    init_db()
    storage = get_storage_service()

    with get_session() as session:
        render_repo = RenderRepository(session)
        cost_repo = CostRepository(session)
        script_repo = ScriptRepository(session)

        job = render_repo.get_job_by_id(job_id)
        if not job:
            console.print(f"[red]Render job {job_id} not found.[/red]")
            raise typer.Exit(code=1)

        script_record = script_repo.get_script_by_id(job.script_id)
        if not script_record:
            console.print(f"[red]Script {job.script_id} not found.[/red]")
            raise typer.Exit(code=1)

        caption_service = CaptionService(storage, cost_repo)
        _, captions = caption_service.generate_captions(
            audio_path_or_url=job.audio_path or "",
            job_id=job.id,
            reference_text=script_record.full_narration,
            total_duration=job.duration_seconds or 30.0,
        )

        audio_local_path = storage.get_local_path(job.audio_path or "")
        service = RenderService(render_repo, cost_repo, storage)

        console.print("[cyan]Writing Remotion render props...[/cyan]")
        service.prepare_render_props(
            job=job,
            script=script_record,
            captions=captions,
            audio_local_path=audio_local_path,
            duration_seconds=job.duration_seconds or 30.0,
        )

        console.print(f"[cyan]Rendering video for job #{job.id}...[/cyan]")
        output_path = service.execute_render(job_id=job.id, dry_run=dry_run)
        console.print(f"[bold green]Render completed: {output_path}[/bold green]")


@app.command()
def run(
    auto_top: Annotated[
        bool, typer.Option("--auto-top", help="Pick the highest-volume trending story cluster")
    ] = True,
    cluster_id: Annotated[int | None, typer.Option("--cluster-id", "-c")] = None,
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
) -> None:
    """Execute end-to-end pipeline from news ingestion to final video render."""
    console.print("[bold cyan]Starting AI News to YouTube Video Pipeline[/bold cyan]")
    target_id = cluster_id if cluster_id is not None else None
    effective_url = api_base or litellm_url
    effective_key = api_key or litellm_key
    result = run_video_pipeline(
        cluster_id=target_id,
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
    console.print("\n[bold green]Pipeline Run Completed Successfully[/bold green]")
    console.print(f"Cluster ID: {result['cluster_id']}")
    console.print(f"Script ID:  {result['script_id']}")
    console.print(f"Job ID:     {result['job_id']}")
    console.print(f"Video File: {result['video_path']}")


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


if __name__ == "__main__":
    app()
