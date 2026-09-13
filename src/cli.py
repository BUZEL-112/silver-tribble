"""Command line interface for managing and executing pipeline stages."""

from typing import Annotated
from rich.console import Console
from rich.table import Table
import typer
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
)
console = Console()


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
) -> None:
    """Embed new articles and group them into story clusters."""
    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        cost_repo = CostRepository(session)
        service = ClusteringService(article_repo, cost_repo)

        console.print("[cyan]Generating embeddings for new articles...[/cyan]")
        embedded_count = service.generate_embeddings_for_new_articles()
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
    aspect_ratio: Annotated[str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")] = "9:16",
) -> None:
    """Generate structured beat sheet and comedic narration for a story cluster."""
    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        script_repo = ScriptRepository(session)
        cost_repo = CostRepository(session)
        service = ScriptService(article_repo, script_repo, cost_repo)

        console.print(f"[cyan]Generating script for cluster {cluster_id}...[/cyan]")
        record = service.generate_full_script(cluster_id=cluster_id, aspect_ratio=aspect_ratio)

        console.print(f"[green]Created script record #{record.id}: '{record.title}'[/green]")
        console.print("\n[bold yellow]Spoken Narration Script:[/bold yellow]")
        console.print(record.full_narration)


@app.command()
def voice(
    script_id: Annotated[int, typer.Option("--script-id", "-s", help="Target script ID")],
    aspect_ratio: Annotated[str, typer.Option("--aspect-ratio", "-a", help="9:16 or 16:9")] = "9:16",
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
) -> None:
    """Execute end-to-end pipeline from news ingestion to final video render."""
    console.print("[bold cyan]Starting AI News to YouTube Video Pipeline[/bold cyan]")
    target_id = cluster_id if not auto_top else None
    result = run_video_pipeline(
        cluster_id=target_id,
        aspect_ratio=aspect_ratio,
        dry_run=dry_run,
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
                vid_table.add_row(str(v["job_id"]), f"${v['total_usd']:.4f}", str(v["records_count"]))

            console.print(vid_table)


if __name__ == "__main__":
    app()
