"""Cluster review service presenting news cluster overviews
and managing interactive story selection with timeout fallback.
"""

import io
import re
import select
import sys

from rich.console import Console
from rich.table import Table

from src.core.config import settings
from src.models.entities import StoryCluster
from src.repositories.action_log_repository import ActionLogRepository


class ClusterReviewService:
    """Coordinates manual and automated cluster selection with configurable review timeouts."""

    def __init__(
        self,
        console: Console | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.console = console or Console()
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.cluster_review_timeout_seconds
        )

    def render_clusters_table(self, clusters: list[StoryCluster]) -> Table:
        """Construct a formatted Rich table summarizing available story clusters."""
        table = Table(
            title="Available AI Story Clusters",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Cluster ID", justify="right", style="cyan", width=12)
        table.add_column("Articles", justify="right", style="magenta", width=10)
        table.add_column("Primary Headline", style="bold white", min_width=35)
        table.add_column("Summary Preview", style="dim", min_width=45)
        table.add_column("Status", style="yellow", width=12)

        for c in clusters:
            clean_summary = (c.summary or "").replace("\n", " ").strip()
            if len(clean_summary) > 90:
                clean_summary = clean_summary[:87] + "..."
            status_style = "green" if c.status == "scripted" else "yellow"
            table.add_row(
                str(c.id),
                str(c.article_count),
                c.title,
                clean_summary,
                f"[{status_style}]{c.status}[/{status_style}]",
            )
        return table

    def display_overview(self, clusters: list[StoryCluster]) -> None:
        """Render cluster overview table to standard output."""
        if not clusters:
            self.console.print("[yellow]No story clusters available to display.[/yellow]")
            return
        table = self.render_clusters_table(clusters)
        self.console.print(table)

    def _read_stdin_with_timeout(
        self,
        prompt_text: str,
        timeout_seconds: float,
    ) -> str | None:
        """Prompt user on stdout and await input on stdin up to timeout_seconds.

        Returns the input string if entered, or None if the timeout expired.
        """
        sys.stdout.write(prompt_text)
        sys.stdout.flush()

        try:
            rlist, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
            if rlist:
                return sys.stdin.readline()
            return None
        except (io.UnsupportedOperation, OSError, AttributeError):
            return None

    def prompt_cluster_selection(
        self,
        clusters: list[StoryCluster],
        timeout_seconds: float | None = None,
        default_id: int | None = None,
        is_interactive: bool | None = None,
        actor: str = "cli",
        action_repo: ActionLogRepository | None = None,
    ) -> list[int]:
        """Present cluster options and collect user selection with timeout fallback.

        Returns a list of chosen cluster IDs (single ID or multiple IDs for a roundup).
        """
        if not clusters:
            fallback = default_id if default_id is not None else 1
            return [fallback]

        effective_default = default_id if default_id is not None else clusters[0].id
        effective_timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        valid_ids = {c.id for c in clusters}

        # Determine whether terminal supports interactive prompts
        is_tty = (
            is_interactive
            if is_interactive is not None
            else (hasattr(sys.stdin, "isatty") and sys.stdin.isatty() and sys.stdout.isatty())
        )

        if not is_tty:
            # Non-interactive / headless environment: immediately proceed with default
            if action_repo:
                action_repo.record_action(
                    stage="cluster",
                    action="cluster_review_auto_selected",
                    actor=actor,
                    status="success",
                    message=(
                        f"Non-interactive session: proceeding with default "
                        f"Cluster #{effective_default}"
                    ),
                    details={"selected_cluster_ids": [effective_default]},
                )
            return [effective_default]

        # Display formatted cluster overview
        self.display_overview(clusters)

        prompt_str = (
            f"\n[Review Gate] Enter cluster ID(s) to script (e.g. '1' or '3, 6, 8'), "
            f"or press Enter for default [Cluster {effective_default}] "
            f"(Timeout: {effective_timeout:.0f}s): "
        )

        user_raw = self._read_stdin_with_timeout(prompt_str, effective_timeout)

        if user_raw is None:
            # Timeout triggered automated fallback
            self.console.print(
                f"\n[bold yellow][TIMEOUT] Review window of {effective_timeout:.0f}s expired. "
                f"Proceeding with default top cluster #{effective_default}.[/bold yellow]\n"
            )
            if action_repo:
                action_repo.record_action(
                    stage="cluster",
                    action="cluster_review_timeout_fallback",
                    actor=actor,
                    status="fallback",
                    message=f"Review window expired. Defaulting to Cluster #{effective_default}",
                    details={
                        "timeout_seconds": effective_timeout,
                        "fallback_cluster_id": effective_default,
                    },
                )
            return [effective_default]

        trimmed = user_raw.strip()
        if not trimmed:
            # User accepted default by pressing Enter
            self.console.print(f"[green]Selected default top cluster #{effective_default}.[/green]")
            if action_repo:
                action_repo.record_action(
                    stage="cluster",
                    action="cluster_review_selected",
                    actor=actor,
                    status="success",
                    message=f"User accepted default Cluster #{effective_default}",
                    details={"selected_cluster_ids": [effective_default]},
                )
            return [effective_default]

        # Parse comma- or space-separated cluster IDs
        tokens = [t.strip() for t in re.split(r"[\s,]+", trimmed) if t.strip()]
        parsed_ids: list[int] = []
        for tok in tokens:
            if tok.isdigit():
                parsed_ids.append(int(tok))

        # Validate that parsed IDs exist in the provided clusters
        recognized_ids = [cid for cid in parsed_ids if cid in valid_ids]

        if not recognized_ids:
            self.console.print(
                f"[bold red]Unrecognized cluster IDs '{trimmed}'. "
                f"Falling back to default cluster #{effective_default}.[/bold red]"
            )
            if action_repo:
                action_repo.record_action(
                    stage="cluster",
                    action="cluster_review_invalid_input_fallback",
                    actor=actor,
                    status="fallback",
                    message=f"Invalid input '{trimmed}'. Fallback to Cluster #{effective_default}",
                    details={"input": trimmed, "fallback_cluster_id": effective_default},
                )
            return [effective_default]

        if len(recognized_ids) == 1:
            self.console.print(
                f"[bold green]Selected story cluster #{recognized_ids[0]}.[/bold green]"
            )
        else:
            self.console.print(
                f"[bold green]Selected {len(recognized_ids)} clusters: "
                f"{recognized_ids}.[/bold green]"
            )

        if action_repo:
            action_repo.record_action(
                stage="cluster",
                action="cluster_review_selected",
                actor=actor,
                status="success",
                message=f"User selected clusters: {recognized_ids}",
                details={"selected_cluster_ids": recognized_ids},
            )

        return recognized_ids
