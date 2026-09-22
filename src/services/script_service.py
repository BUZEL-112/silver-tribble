import html
import json
import re
from pathlib import Path
from typing import Any

import jinja2
import yaml
from openai import OpenAI

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


def sanitize_news_text(text: str) -> str:
    """Strip marketing boilerplate, newsletter promos, HTML entities, and formatting."""
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    patterns = [
        (
            r"This story appeared in [^.]*(?:newsletter|AI)[^.]*\."
            r"(?:\s*To get stories like this in your inbox first,?\s*sign up here\.?)?"
        ),
        r"Sign up (?:for|to) [^.]*\.",
        r"To get stories like this in your inbox[^.]*\.",
        r"Subscribe to [^.]*\.",
        r"Read more at [^.]*\.",
        r"Follow us on [^.]*\.",
        r"Click here to [^.]*\.",
        r"https?://\S+",
        r"\[.*?\]",
    ]
    for pat in patterns:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def clean_narration_for_tts(text: str) -> str:
    """Format narration text for natural TTS delivery without emojis or markup."""
    if not text:
        return ""
    cleaned = re.sub(r"\*+", "", text)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    cleaned = re.sub(r"\([a-zA-Z\s]{2,25}\)", "", cleaned)
    cleaned = re.sub(r"[\"“”]", "", cleaned)
    cleaned = re.sub(r"[\u2014\u2013]", "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class ScriptService:
    """Orchestrates structured script generation across gpt-4o-mini and DeepSeek."""

    def __init__(
        self,
        article_repo: ArticleRepository,
        script_repo: ScriptRepository,
        cost_repo: CostRepository,
        client: OpenAI | None = None,
        prompts_dir: Path | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        openai_key: str | None = None,
        deepseek_key: str | None = None,
        gemini_key: str | None = None,
    ) -> None:
        self.article_repo = article_repo
        self.script_repo = script_repo
        self.cost_repo = cost_repo
        self.prompts_dir = prompts_dir or Path("prompts")
        self._custom_client = client
        self.base_url = base_url
        self.api_key = api_key
        self.openai_key = openai_key or settings.openai_api_key
        self.deepseek_key = deepseek_key or settings.deepseek_api_key
        self.gemini_key = gemini_key or settings.gemini_api_key
        self.client = client or self._resolve_client(settings.llm_planning_model)

    def _resolve_client(self, model: str) -> OpenAI:
        """Resolve the appropriate OpenAI-compatible client for the target model."""
        if self._custom_client:
            return self._custom_client

        # If base_url was explicitly passed (CLI --api-base or --litellm-url)
        if self.base_url:
            raw_url = self.base_url.rstrip("/")
            effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
            effective_key = (
                self.api_key
                or settings.litellm_api_key
                or self.openai_key
                or self.deepseek_key
                or "sk-dummy"
            )
            return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=12.0)

        # Direct provider keys based on model family
        m_lower = model.lower()
        if ("deepseek" in m_lower) and self.deepseek_key:
            return OpenAI(
                base_url="https://api.deepseek.com/v1",
                api_key=self.deepseek_key,
                timeout=12.0,
            )

        if any(x in m_lower for x in ["gpt", "o1", "o3", "text-embedding"]) and self.openai_key:
            return OpenAI(
                base_url="https://api.openai.com/v1",
                api_key=self.openai_key,
                timeout=12.0,
            )

        if ("gemini" in m_lower) and self.gemini_key:
            return OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=self.gemini_key,
                timeout=12.0,
            )

        if self.api_key and self.api_key.startswith("sk-proj-"):
            return OpenAI(
                base_url="https://api.openai.com/v1",
                api_key=self.api_key,
                timeout=12.0,
            )

        # If user configured a custom LiteLLM base URL in .env
        if settings.litellm_base_url and settings.litellm_base_url != "http://localhost:4000":
            raw_url = settings.litellm_base_url.rstrip("/")
            effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
            effective_key = self.api_key or settings.litellm_api_key or "sk-litellm-master-key"
            return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=12.0)

        # Default fallback to local LiteLLM proxy
        raw_url = settings.litellm_base_url.rstrip("/")
        effective_base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
        effective_key = self.api_key or settings.litellm_api_key or "sk-litellm-master-key"
        return OpenAI(base_url=effective_base_url, api_key=effective_key, timeout=10.0)

    def _load_prompt(self, filename: str) -> dict[str, Any]:
        p = Path(filename)
        if p.is_file():
            prompt_path = p
        else:
            prompt_path = self.prompts_dir / p.name
        with open(prompt_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def generate_beat_sheet(
        self,
        cluster_id: int,
        aspect_ratio: str = "9:16",
        target_seconds: int = 50,
        model: str | None = None,
    ) -> BeatSheetResponse:
        """Stage 1: Generate structured narrative beat sheet using planning model."""
        cluster = self.article_repo.get_cluster_by_id(cluster_id)
        if not cluster:
            raise ValueError(f"StoryCluster with id {cluster_id} not found")

        articles = self.article_repo.get_articles_by_ids(cluster.article_ids)
        sanitized_articles = [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source,
                "summary": sanitize_news_text(a.summary),
                "link": a.link,
            }
            for a in articles
        ]
        prompt_file = settings.prompts_planning_file or "beat_sheet.yaml"
        prompt_data = self._load_prompt(prompt_file)
        system_prompt = settings.prompts_planning_system_prompt or prompt_data["system_prompt"]

        template = jinja2.Template(prompt_data["user_prompt_template"])
        format_label = "Vertical Short" if aspect_ratio == "9:16" else "Horizontal Widescreen"
        user_message = template.render(
            aspect_ratio=aspect_ratio,
            format_label=format_label,
            target_seconds=target_seconds,
            articles=sanitized_articles,
        )

        target_model = model or settings.llm_planning_model
        try:
            client = self._resolve_client(target_model)
            try:
                response = client.chat.completions.create(
                    model=target_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.7,
                )
            except Exception:
                if self.gemini_key and target_model != "gemini-3.5-flash-lite":
                    target_model = "gemini-3.5-flash-lite"
                    client = self._resolve_client(target_model)
                    response = client.chat.completions.create(
                        model=target_model,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        temperature=0.7,
                    )
                else:
                    raise

            raw_json = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                parsed = {
                    "title": cluster.title if cluster else "AI News Update",
                    "beats": parsed,
                }
            elif isinstance(parsed, dict) and "beats" not in parsed:
                for k in ["items", "beat_sheet", "outline", "data"]:
                    if k in parsed and isinstance(parsed[k], list):
                        parsed["beats"] = parsed[k]
                        break
            if isinstance(parsed, dict) and not parsed.get("title"):
                parsed["title"] = cluster.title if cluster else "AI News Update"

            beat_sheet = BeatSheetResponse.model_validate(parsed)

            # Pricing estimate based on standard tokens
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 500)
            completion_tokens = getattr(usage, "completion_tokens", 400)
            cost_usd = (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000

            self.cost_repo.log_cost(
                CostLogCreate(
                    stage="script_beat_sheet",
                    provider="litellm",
                    model=target_model,
                    units=float(prompt_tokens + completion_tokens),
                    unit_type="tokens",
                    cost_usd=cost_usd,
                )
            )
            return beat_sheet
        except Exception:
            # Fallback for local testing or API offline
            import re

            raw_summary = cluster.summary or ""
            clean_summary = re.sub(r"\[.*?\]\s*[^:]*:\s*", "", raw_summary).strip()
            period_pos = clean_summary[:160].rfind(".")
            if period_pos > 30:
                context_point = clean_summary[: period_pos + 1].strip()
            elif clean_summary:
                context_point = clean_summary[:140].rsplit(" ", 1)[0] + "."
            else:
                context_point = cluster.title

            return BeatSheetResponse(
                title=cluster.title[:80],
                beats=[
                    {
                        "beat_number": 1,
                        "beat_type": "hook",
                        "emotion": "alarm",
                        "shot_type": "wide",
                        "core_point": f"Breaking news in AI: {cluster.title[:60]}",
                        "visual_direction": "High energy digital glitch headline reveal",
                        "on_screen_text": "BREAKING AI NEWS",
                        "target_duration_seconds": 8.0,
                    },
                    {
                        "beat_number": 2,
                        "beat_type": "context",
                        "emotion": "technical_focus",
                        "shot_type": "medium",
                        "core_point": context_point,
                        "visual_direction": "Data center servers with neon cyan glow",
                        "on_screen_text": "THE RAW REALITY",
                        "target_duration_seconds": 15.0,
                    },
                    {
                        "beat_number": 3,
                        "beat_type": "outro",
                        "emotion": "humor",
                        "shot_type": "reaction",
                        "core_point": "Stay skeptical of the AI hype cycle and hit subscribe",
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
        model: str | None = None,
    ) -> ScriptRecord:
        """Stage 2: Expand beat sheet into comedic dialogue using writing model."""
        cluster = self.article_repo.get_cluster_by_id(cluster_id)
        cluster_title = cluster.title if cluster else beat_sheet.title
        raw_articles = self.article_repo.get_articles_by_ids(cluster.article_ids) if cluster else []
        sanitized_articles = [
            {
                "id": a.id,
                "title": a.title,
                "source": a.source,
                "summary": sanitize_news_text(a.summary),
            }
            for a in raw_articles
        ]

        prompt_file = settings.prompts_writing_file or "eswar_host_persona.yaml"
        prompt_data = self._load_prompt(prompt_file)
        system_prompt = settings.prompts_writing_system_prompt or prompt_data["system_prompt"]

        template = jinja2.Template(prompt_data["user_prompt_template"])
        user_message = template.render(
            cluster_title=cluster_title,
            articles=sanitized_articles,
            beats=[beat.model_dump() for beat in beat_sheet.beats],
        )

        target_model = model or settings.llm_writing_model
        try:
            client = self._resolve_client(target_model)
            try:
                response = client.chat.completions.create(
                    model=target_model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.8,
                )
            except Exception:
                if self.gemini_key and target_model != "gemini-3.5-flash-lite":
                    target_model = "gemini-3.5-flash-lite"
                    client = self._resolve_client(target_model)
                    response = client.chat.completions.create(
                        model=target_model,
                        response_format={"type": "json_object"},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        temperature=0.8,
                    )
                else:
                    raise

            raw_json = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                parsed = {
                    "title": cluster_title,
                    "expanded_beats": parsed,
                    "full_narration_script": " ".join(
                        b.get("narration_text", "") for b in parsed if isinstance(b, dict)
                    ),
                }
            elif isinstance(parsed, dict):
                if "expanded_beats" not in parsed:
                    for k in ["beats", "expandedBeats", "items"]:
                        if k in parsed and isinstance(parsed[k], list):
                            parsed["expanded_beats"] = parsed[k]
                            break
                if not parsed.get("title"):
                    parsed["title"] = cluster_title
                if not parsed.get("full_narration_script"):
                    beats_list = parsed.get("expanded_beats", [])
                    parsed["full_narration_script"] = " ".join(
                        b.get("narration_text", "") for b in beats_list if isinstance(b, dict)
                    )

            if isinstance(parsed, dict) and "expanded_beats" in parsed:
                for b in parsed["expanded_beats"]:
                    if isinstance(b, dict) and "narration_text" in b:
                        b["narration_text"] = clean_narration_for_tts(b["narration_text"])
                if "full_narration_script" in parsed:
                    parsed["full_narration_script"] = clean_narration_for_tts(
                        parsed["full_narration_script"]
                    )

            expansion = ScriptExpansionResponse.model_validate(parsed)

            # Pricing estimate based on standard tokens
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 600)
            completion_tokens = getattr(usage, "completion_tokens", 500)
            cost_usd = (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000

            self.cost_repo.log_cost(
                CostLogCreate(
                    stage="script_dialogue",
                    provider="litellm",
                    model=target_model,
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
            fallback_beats = []
            for b in beat_sheet.beats:
                clean_pt = sanitize_news_text(b.core_point)
                if b.beat_type == "hook":
                    narr = (
                        f"Here is the major artificial intelligence story breaking today: "
                        f"{cluster_title}. Let us examine what got announced and why it matters."
                    )
                elif b.beat_type == "outro":
                    narr = (
                        "As the technology advances, the real challenge will be separating "
                        "practical engineering reality from the endless promotional hype cycle."
                    )
                else:
                    narr = (
                        f"Looking at the announcement details, {clean_pt}. "
                        "Engineering teams and competitors are already analyzing the implications."
                    )

                fallback_beats.append(
                    {
                        "beat_number": b.beat_number,
                        "beat_type": b.beat_type,
                        "narration_text": clean_narration_for_tts(narr),
                        "visual_direction": b.visual_direction,
                        "on_screen_text": b.on_screen_text,
                        "estimated_duration_seconds": b.target_duration_seconds,
                    }
                )

            beats_data = fallback_beats
            full_narration = " ".join([b["narration_text"] for b in beats_data])
            title = beat_sheet.title

        script_record = self.script_repo.create_script(
            cluster_id=cluster_id,
            title=title,
            aspect_ratio=aspect_ratio,
            beats=beats_data,
            full_narration=full_narration,
        )
        self.article_repo.update_cluster_status(cluster_id, "scripted")
        return script_record

    def generate_full_script(
        self,
        cluster_id: int,
        aspect_ratio: str = "9:16",
        planner_model: str | None = None,
        writer_model: str | None = None,
    ) -> ScriptRecord:
        """Run two-call pipeline end-to-end to create and store a finalized script."""
        beat_sheet = self.generate_beat_sheet(
            cluster_id=cluster_id,
            aspect_ratio=aspect_ratio,
            model=planner_model,
        )
        return self.expand_script_persona(
            cluster_id=cluster_id,
            beat_sheet=beat_sheet,
            aspect_ratio=aspect_ratio,
            model=writer_model,
        )

    def generate_roundup_script(
        self,
        cluster_ids: list[int],
        aspect_ratio: str = "9:16",
        model: str | None = None,
    ) -> ScriptRecord:
        """Generate a sequential multi-story news roundup script in numerical cluster order."""
        if not cluster_ids:
            raise ValueError("At least one cluster_id is required for a roundup")

        # Sort uniquely in strict numerical ascending order of cluster IDs
        sorted_cluster_ids = sorted(list(set(cluster_ids)))
        valid_clusters = []
        for cid in sorted_cluster_ids:
            c = self.article_repo.get_cluster_by_id(cid)
            if c is not None:
                valid_clusters.append(c)

        if not valid_clusters:
            raise ValueError(f"No valid clusters found for IDs {cluster_ids}")

        # Dynamic duration: dedicate 22 seconds per story rather than compressing into 55s
        story_duration_each = 22.0
        hook_duration = 8.0
        outro_duration = 7.0
        story_time = len(valid_clusters) * story_duration_each
        target_seconds = int(hook_duration + story_time + outro_duration)

        stories_data = []
        for idx, c in enumerate(valid_clusters):
            raw_articles = self.article_repo.get_articles_by_ids(c.article_ids)
            stories_data.append(
                {
                    "story_index": idx + 1,
                    "cluster_id": c.id,
                    "title": c.title,
                    "summary": sanitize_news_text(c.summary or ""),
                    "articles": [
                        {
                            "source": a.source,
                            "title": a.title,
                            "summary": sanitize_news_text(a.summary),
                        }
                        for a in raw_articles
                    ],
                }
            )

        prompt_file = settings.prompts_roundup_file or "roundup_script.yaml"
        prompt_data = self._load_prompt(prompt_file)
        default_sys = "You are an executive AI tech news producer."
        system_prompt = prompt_data.get("system_prompt", default_sys)
        template = jinja2.Template(prompt_data["user_prompt_template"])
        format_label = "Vertical Short" if aspect_ratio == "9:16" else "Horizontal Widescreen"
        user_message = template.render(
            aspect_ratio=aspect_ratio,
            format_label=format_label,
            target_seconds=target_seconds,
            story_count=len(valid_clusters),
            story_duration=int(story_duration_each),
            stories=stories_data,
        )

        target_model = model or settings.llm_planning_model
        try:
            client = self._resolve_client(target_model)
            response = client.chat.completions.create(
                model=target_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.7,
            )
            raw_json = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_json)
            title = parsed.get("title", f"AI Daily Roundup: {len(valid_clusters)} Top Stories")
            raw_beats = parsed.get("beats", [])
            beats_data = []
            for idx, b in enumerate(raw_beats):
                default_dur = b.get("estimated_duration_seconds", story_duration_each)
                dur = float(b.get("target_duration_seconds", default_dur))
                beats_data.append(
                    {
                        "beat_number": b.get("beat_number", idx + 1),
                        "beat_type": b.get("beat_type", "context"),
                        "emotion": b.get("emotion", "neutral"),
                        "shot_type": b.get("shot_type", "medium"),
                        "core_point": b.get("core_point", ""),
                        "visual_direction": b.get(
                            "visual_direction", "modern datacenter server room"
                        ),
                        "on_screen_text": b.get("on_screen_text", f"AI STORY {idx + 1}"),
                        "target_duration_seconds": dur,
                        "estimated_duration_seconds": dur,
                        "narration_text": clean_narration_for_tts(
                            b.get("narration_text", b.get("core_point", ""))
                        ),
                    }
                )
            full_narration = parsed.get("full_narration_script") or " ".join(
                [b["narration_text"] for b in beats_data]
            )
            full_narration = clean_narration_for_tts(full_narration)
        except Exception:
            # Deterministic fallback roundup script presented sequentially
            title = f"AI Daily Roundup: {len(valid_clusters)} Stories in Numerical Order"
            fallback_beats = [
                {
                    "beat_number": 1,
                    "beat_type": "hook",
                    "emotion": "alarm",
                    "shot_type": "wide",
                    "core_point": (
                        f"Top artificial intelligence news today covering "
                        f"{len(valid_clusters)} major stories."
                    ),
                    "visual_direction": "High energy breaking tech news headline overlay",
                    "on_screen_text": "TODAY IN AI",
                    "target_duration_seconds": hook_duration,
                    "estimated_duration_seconds": hook_duration,
                    "narration_text": (
                        f"Here is your daily artificial intelligence roundup covering "
                        f"{len(valid_clusters)} major developments presented in sequential order."
                    ),
                },
            ]
            for idx, c in enumerate(valid_clusters):
                clean_t = c.title[:45]
                c_summary = (
                    c.summary
                    or "Engineers and researchers are actively evaluating the real world impact."
                )
                fallback_beats.append(
                    {
                        "beat_number": idx + 2,
                        "beat_type": "context" if idx % 2 == 0 else "breakthrough",
                        "emotion": "technical_focus",
                        "shot_type": "medium",
                        "core_point": f"Cluster #{c.id}: {c.title}",
                        "visual_direction": f"Technical visualization depicting {clean_t}",
                        "on_screen_text": f"STORY {idx + 1} [ID #{c.id}]",
                        "target_duration_seconds": story_duration_each,
                        "estimated_duration_seconds": story_duration_each,
                        "narration_text": (
                            f"Story number {idx + 1}, Cluster ID {c.id}: {c.title}. {c_summary}"
                        ),
                    }
                )
            fallback_beats.append(
                {
                    "beat_number": len(fallback_beats) + 1,
                    "beat_type": "outro",
                    "emotion": "humor",
                    "shot_type": "graphic",
                    "core_point": "Hit subscribe for daily AI reality checks.",
                    "visual_direction": (
                        "Outro card with pulsating subscribe button and channel logo"
                    ),
                    "on_screen_text": "STAY TUNED",
                    "target_duration_seconds": outro_duration,
                    "estimated_duration_seconds": outro_duration,
                    "narration_text": (
                        "That wraps up today's sequential news roundup. "
                        "Hit subscribe to stay ahead of the curve."
                    ),
                }
            )
            beats_data = fallback_beats
            full_narration = " ".join([b["narration_text"] for b in beats_data])

        primary_cluster_id = valid_clusters[0].id
        all_cluster_ids = [c.id for c in valid_clusters]
        script_record = self.script_repo.create_script(
            cluster_id=primary_cluster_id,
            cluster_ids=all_cluster_ids,
            title=title,
            aspect_ratio=aspect_ratio,
            beats=beats_data,
            full_narration=full_narration,
        )
        for c in valid_clusters:
            self.article_repo.update_cluster_status(c.id, "scripted")

        return script_record
