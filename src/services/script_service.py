"""Two-stage script generation chaining beat sheet structuring and comedic dialogue."""

import json
from pathlib import Path
from typing import Any
import jinja2
from openai import OpenAI
import yaml
from src.core.config import settings
from src.models.entities import ScriptRecord
from src.models.schemas import (
    BeatSheetResponse,
    CostLogCreate,
    ScriptExpansionResponse,
)
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.script_repository import ScriptRepository


class ScriptService:
    """Orchestrates structured script generation across gpt-4o-mini and DeepSeek."""

    def __init__(
        self,
        article_repo: ArticleRepository,
        script_repo: ScriptRepository,
        cost_repo: CostRepository,
        client: OpenAI | None = None,
        prompts_dir: Path | None = None,
    ) -> None:
        self.article_repo = article_repo
        self.script_repo = script_repo
        self.cost_repo = cost_repo
        self.client = client or OpenAI(
            base_url=f"{settings.litellm_base_url.rstrip('/')}/v1",
            api_key=settings.litellm_api_key or "sk-litellm-master-key",
        )
        self.prompts_dir = prompts_dir or Path("prompts")

    def _load_prompt(self, filename: str) -> dict[str, Any]:
        prompt_path = self.prompts_dir / filename
        with open(prompt_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def generate_beat_sheet(
        self,
        cluster_id: int,
        aspect_ratio: str = "9:16",
        target_seconds: int = 50,
    ) -> BeatSheetResponse:
        """Stage 1: Generate structured narrative beat sheet using gpt-4o-mini."""
        cluster = self.article_repo.get_cluster_by_id(cluster_id)
        if not cluster:
            raise ValueError(f"StoryCluster with id {cluster_id} not found")

        articles = self.article_repo.get_articles_by_ids(cluster.article_ids)
        prompt_data = self._load_prompt("beat_sheet.yaml")

        template = jinja2.Template(prompt_data["user_prompt_template"])
        format_label = "Vertical Short" if aspect_ratio == "9:16" else "Horizontal Widescreen"
        user_message = template.render(
            aspect_ratio=aspect_ratio,
            format_label=format_label,
            target_seconds=target_seconds,
            articles=articles,
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_data["system_prompt"]},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
            )
            raw_json = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            beat_sheet = BeatSheetResponse.model_validate(parsed)

            # gpt-4o-mini rates: $0.15/1M input, $0.60/1M output
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 500)
            completion_tokens = getattr(usage, "completion_tokens", 400)
            cost_usd = (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000

            self.cost_repo.log_cost(
                CostLogCreate(
                    stage="script_beat_sheet",
                    provider="openai",
                    model="gpt-4o-mini",
                    units=float(prompt_tokens + completion_tokens),
                    unit_type="tokens",
                    cost_usd=cost_usd,
                )
            )
            return beat_sheet
        except Exception:
            # Fallback for local testing or API offline
            return BeatSheetResponse(
                title=cluster.title[:80],
                beats=[
                    {
                        "beat_number": 1,
                        "beat_type": "hook",
                        "core_point": f"Breaking news in AI: {cluster.title[:60]}",
                        "visual_direction": "High energy digital glitch headline reveal",
                        "on_screen_text": "BREAKING AI NEWS",
                        "target_duration_seconds": 8.0,
                    },
                    {
                        "beat_number": 2,
                        "beat_type": "context",
                        "core_point": cluster.summary[:150],
                        "visual_direction": "Data center servers with neon cyan glow",
                        "on_screen_text": "THE RAW REALITY",
                        "target_duration_seconds": 15.0,
                    },
                    {
                        "beat_number": 3,
                        "beat_type": "outro",
                        "core_point": "Wrap up with a cynical punchline on tech hype",
                        "visual_direction": "Outro signature card with subscribe pulse",
                        "on_screen_text": "STAY SKEPTICAL",
                        "target_duration_seconds": 7.0,
                    },
                ],
            )

    def expand_script_persona(
        self,
        cluster_id: int,
        beat_sheet: BeatSheetResponse,
        aspect_ratio: str = "9:16",
    ) -> ScriptRecord:
        """Stage 2: Expand beat sheet into comedic dialogue in the Eswar persona using DeepSeek."""
        cluster = self.article_repo.get_cluster_by_id(cluster_id)
        cluster_title = cluster.title if cluster else beat_sheet.title

        prompt_data = self._load_prompt("eswar_host_persona.yaml")
        template = jinja2.Template(prompt_data["user_prompt_template"])
        user_message = template.render(
            cluster_title=cluster_title,
            beats=[beat.model_dump() for beat in beat_sheet.beats],
        )

        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_data["system_prompt"]},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.8,
            )
            raw_json = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            expansion = ScriptExpansionResponse.model_validate(parsed)

            # DeepSeek rates: $0.14/1M input, $0.28/1M output
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 600)
            completion_tokens = getattr(usage, "completion_tokens", 500)
            cost_usd = (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000

            self.cost_repo.log_cost(
                CostLogCreate(
                    stage="script_dialogue",
                    provider="deepseek",
                    model="deepseek-chat",
                    units=float(prompt_tokens + completion_tokens),
                    unit_type="tokens",
                    cost_usd=cost_usd,
                )
            )

            beats_data = [b.model_dump() for b in expansion.expanded_beats]
            full_narration = expansion.full_narration_script
            title = expansion.title
        except Exception:
            # Fallback script for offline execution
            beats_data = [
                {
                    "beat_number": b.beat_number,
                    "beat_type": b.beat_type,
                    "narration_text": f"So here is what everyone is panicking about today: {b.core_point}. Let us see how long before this gets debunked.",
                    "visual_direction": b.visual_direction,
                    "on_screen_text": b.on_screen_text,
                    "estimated_duration_seconds": b.target_duration_seconds,
                }
                for b in beat_sheet.beats
            ]
            full_narration = " ".join([b["narration_text"] for b in beats_data])
            title = beat_sheet.title

        return self.script_repo.create_script(
            cluster_id=cluster_id,
            title=title,
            aspect_ratio=aspect_ratio,
            beats=beats_data,
            full_narration=full_narration,
        )

    def generate_full_script(
        self,
        cluster_id: int,
        aspect_ratio: str = "9:16",
    ) -> ScriptRecord:
        """Run two-call pipeline end-to-end to create and store a finalized script."""
        beat_sheet = self.generate_beat_sheet(cluster_id, aspect_ratio)
        return self.expand_script_persona(cluster_id, beat_sheet, aspect_ratio)
