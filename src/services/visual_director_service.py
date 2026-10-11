"""Visual Director service translating script sentences into structured scene directives."""

import json
import logging
import re
from typing import Any

from openai import OpenAI

from src.core.config import settings
from src.models.schemas import (
    CostLogCreate,
    VisualCategory,
    VisualCue,
    VisualDirectorResponse,
)
from src.repositories.cost_repository import CostRepository
from src.services.model_registry_service import ModelRegistryService

logger = logging.getLogger(__name__)


def extract_json_payload(raw_text: str) -> Any:
    """Extract and parse JSON content from text or markdown code fences."""
    cleaned = raw_text.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            cleaned = match.group(1).strip()
    return json.loads(cleaned)


class VisualDirectorService:
    """Orchestrates structured visual direction for each spoken script sentence."""

    # Curated known entities in AI news
    KNOWN_ENTITIES: dict[str, str] = {
        "dario amodei": "Dario Amodei",
        "sam altman": "Sam Altman",
        "jensen huang": "Jensen Huang",
        "demis hassabis": "Demis Hassabis",
        "mark zuckerberg": "Mark Zuckerberg",
        "satya nadella": "Satya Nadella",
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "nvidia": "Nvidia",
        "deepseek": "DeepSeek",
        "tsmc": "TSMC",
        "meta": "Meta",
        "google": "Google",
        "microsoft": "Microsoft",
    }

    def __init__(
        self,
        cost_repo: CostRepository | None = None,
        model_registry_service: ModelRegistryService | None = None,
        client: OpenAI | None = None,
        model_name: str | None = None,
    ) -> None:
        self.cost_repo = cost_repo
        self.model_registry_service = model_registry_service or ModelRegistryService(
            cost_repo=cost_repo
        )
        self.client = client or self._resolve_client()
        self.model_name = model_name or settings.llm_planning_model

    def _resolve_client(self) -> OpenAI:
        """Resolve OpenAI compatible client using configured API keys or LiteLLM."""
        raw_url = (settings.litellm_base_url or "http://localhost:4000").rstrip("/")
        base_url = raw_url if raw_url.endswith("/v1") else f"{raw_url}/v1"
        api_key = (
            settings.gemini_api_key
            or settings.openai_api_key
            or settings.litellm_api_key
            or "sk-dummy"
        )
        if settings.gemini_api_key and "gemini" in settings.llm_planning_model.lower():
            return OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=settings.gemini_api_key,
                timeout=15.0,
            )
        return OpenAI(base_url=base_url, api_key=api_key, timeout=15.0)

    def _build_system_prompt(self) -> str:
        """Construct system instructions for visual scene direction."""
        return (
            "You are a professional broadcast visual director for technical AI journalism. "
            "Given a list of spoken script sentences and narrative beats, "
            "output a structured JSON plan with a visual cue for every sentence. "
            "Never use generic stock keywords like 'technology'. "
            "Follow these categorization rules:\n"
            "1. 'editorial_entity': If a sentence mentions an executive, lab, or company name. "
            "Set entity_name to the canonical entity.\n"
            "2. 'code_or_data': If a sentence discusses benchmark metrics, code execution, "
            "bash terminal, or security exploits. "
            "Set graphic_overlay_type to 'terminal' or 'chart'.\n"
            "3. 'physical_broll': If a sentence describes real-world physical hardware or places "
            "(datacenters, cleanrooms, chip fabs, robot arms). "
            "Provide a concrete stock_search_query of physical objects.\n"
            "4. 'conceptual_ai': If a sentence describes abstract models, neural weights, "
            "agent coordination, or mathematical architectures where stock photos cannot exist. "
            "Provide a detailed generative_prompt.\n"
            "5. 'reaction': If the tone is comedic skepticism, eye rolling, or dramatic disbelief. "
            "Set suggested_shot_type to 'reaction'.\n\n"
            "Format your response as valid JSON matching this schema:\n"
            "{\n"
            '  "cues": [\n'
            "    {\n"
            '      "sentence_index": 0,\n'
            '      "category": "editorial_entity" | "physical_broll" | '
            '"code_or_data" | "conceptual_ai" | "reaction",\n'
            '      "entity_name": "string or null",\n'
            '      "stock_search_query": "concrete physical query or null",\n'
            '      "generative_prompt": "detailed prompt for 9:16 vertical render or null",\n'
            '      "graphic_overlay_type": "string or null",\n'
            '      "suggested_shot_type": "close_up" | "medium" | "wide" | "reaction",\n'
            '      "rationale": "editorial justification"\n'
            "    }\n"
            "  ]\n"
            "}"
        )

    def _fallback_direct_sentence(
        self,
        index: int,
        sentence: str,
        beat_info: dict[str, Any] | None = None,
    ) -> VisualCue:
        """Intelligently direct a sentence when LLM completion is unavailable."""
        lower = sentence.lower()
        beat_type = (beat_info or {}).get("beat_type", "context")
        beat_visual = (beat_info or {}).get("visual_direction", "").lower()

        # Check known entities
        for key, canonical in self.KNOWN_ENTITIES.items():
            if re.search(rf"\b{re.escape(key)}\b", lower):
                return VisualCue(
                    sentence_index=index,
                    category=VisualCategory.EDITORIAL_ENTITY,
                    entity_name=canonical,
                    suggested_shot_type="close_up",
                    rationale=f"Entity match for {canonical}",
                )

        # Check code, terminal, or technical exploits
        code_words = [
            "code",
            "bash",
            "terminal",
            "sandbox",
            "exploit",
            "socket",
            "script",
            "traceback",
        ]
        if any(w in lower for w in code_words):
            return VisualCue(
                sentence_index=index,
                category=VisualCategory.CODE_OR_DATA,
                graphic_overlay_type="terminal",
                generative_prompt=(
                    f"Glowing dark terminal window showing computer traceback and {sentence[:60]}, "
                    "9:16 vertical orientation, cinematic lighting"
                ),
                suggested_shot_type="medium",
                rationale="Technical code or terminal context",
            )

        # Check physical hardware b-roll
        hardware_map = {
            "datacenter": "server racks in modern datacenter",
            "server": "server room with blinking lights",
            "chip": "silicon wafer semiconductor inspection",
            "semiconductor": "semiconductor cleanroom manufacturing",
            "gpu": "high performance computing processor",
            "robot": "robotic arm in automated lab",
        }
        for kw, search_q in hardware_map.items():
            if kw in lower or kw in beat_visual:
                return VisualCue(
                    sentence_index=index,
                    category=VisualCategory.PHYSICAL_BROLL,
                    stock_search_query=search_q,
                    suggested_shot_type="medium",
                    rationale=f"Physical hardware presence: {kw}",
                )

        # Check reaction beats
        if beat_type in ["skepticism", "reaction"] or "rolling their eyes" in lower:
            return VisualCue(
                sentence_index=index,
                category=VisualCategory.REACTION,
                stock_search_query="skeptical eye roll reaction",
                suggested_shot_type="reaction",
                rationale="Skepticism or comedic beat",
            )

        # Default to conceptual AI generation instead of generic stock query
        return VisualCue(
            sentence_index=index,
            category=VisualCategory.CONCEPTUAL_AI,
            generative_prompt=(
                f"Cinematic technical visualization of {sentence[:80]}, "
                "dark studio aesthetic, high fidelity, 9:16 portrait vertical composition"
            ),
            suggested_shot_type="wide",
            rationale="Abstract concept routed to generative visual model",
        )

    def direct_visuals(
        self,
        sentences: list[str],
        beats: list[dict[str, Any]] | None = None,
        job_id: int | None = None,
    ) -> list[VisualCue]:
        """Produce structured visual staging cues for all script sentences."""
        if not sentences:
            return []

        beats_list = beats or []
        items_payload = []
        for idx, sent in enumerate(sentences):
            b_info = beats_list[idx] if idx < len(beats_list) else {}
            items_payload.append(
                {
                    "sentence_index": idx,
                    "sentence_text": sent,
                    "beat_type": b_info.get("beat_type", "context"),
                    "visual_direction": b_info.get("visual_direction", ""),
                }
            )

        user_content = (
            "Direct the visual presentation for these sentences in an AI news broadcast:\n"
            f"{json.dumps(items_payload, indent=2)}"
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": self._build_system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
            )
            raw_text = resp.choices[0].message.content or ""
            parsed = extract_json_payload(raw_text)
            validated = VisualDirectorResponse.model_validate(parsed)

            # Ensure all sentence indices exist
            cue_map = {cue.sentence_index: cue for cue in validated.cues}
            final_cues: list[VisualCue] = []
            for idx, sent in enumerate(sentences):
                if idx in cue_map:
                    final_cues.append(cue_map[idx])
                else:
                    b_info = beats_list[idx] if idx < len(beats_list) else None
                    final_cues.append(self._fallback_direct_sentence(idx, sent, b_info))

            if self.cost_repo and getattr(resp, "usage", None):
                prompt_tokens = getattr(resp.usage, "prompt_tokens", 0)
                completion_tokens = getattr(resp.usage, "completion_tokens", 0)
                cost_usd = (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000
                self.cost_repo.log_cost(
                    CostLogCreate(
                        job_id=job_id,
                        stage="visual_direction",
                        provider="visual_director",
                        model=self.model_name,
                        units=float(prompt_tokens + completion_tokens),
                        unit_type="tokens",
                        cost_usd=cost_usd,
                    )
                )

            return final_cues
        except Exception as exc:
            logger.warning(
                "Visual director LLM call failed (%s), using intelligent fallback direct.",
                exc,
            )
            return [
                self._fallback_direct_sentence(
                    idx,
                    sent,
                    beats_list[idx] if idx < len(beats_list) else None,
                )
                for idx, sent in enumerate(sentences)
            ]
