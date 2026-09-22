"""Audits narration scripts for pacing, hook strength, and retention characteristics."""

from typing import Any

from src.models.entities import ScriptRecord
from src.models.schemas import ScriptAuditReport


class ScriptAuditorService:
    """Evaluates narration script metrics against YouTube retention benchmarks."""

    HOOK_TRIGGER_WORDS = {
        "breaking",
        "finally",
        "secret",
        "revealed",
        "warning",
        "game-changer",
        "disaster",
        "shocker",
        "unbelievable",
        "just dropped",
        "leak",
        "crazy",
        "danger",
        "nobody",
        "stop",
    }

    def audit_script(
        self,
        script: ScriptRecord | str | None = None,
        duration_seconds: float | None = None,
        beats: list[dict[str, Any]] | None = None,
        title: str | None = None,
        full_narration: str | None = None,
    ) -> ScriptAuditReport:
        """Analyze narration text and beat structure, returning comprehensive quality metrics."""
        if full_narration is not None:
            narration = full_narration.strip()
            resolved_beats = beats or []
        elif isinstance(script, str):
            narration = script.strip()
            resolved_beats = beats or []
        elif script is not None:
            narration = (script.full_narration or "").strip()
            resolved_beats = beats or script.beats or []
        else:
            narration = ""
            resolved_beats = beats or []

        words = narration.split()
        word_count = len(words)

        if duration_seconds and duration_seconds > 0:
            est_duration = duration_seconds
        elif resolved_beats:
            est_duration = sum(
                float(b.get("estimated_duration_seconds", 10.0)) for b in resolved_beats
            )
        else:
            # Standard conversational pacing: ~2.5 words per second
            est_duration = max(word_count / 2.5, 10.0)

        wpm = (word_count / est_duration) * 60.0 if est_duration > 0 else 0.0

        if wpm > 185.0:
            pacing_rating = "too_fast"
        elif wpm < 125.0:
            pacing_rating = "too_slow"
        else:
            pacing_rating = "optimal"

        first_sentence = narration.split(".")[0].lower() if narration else ""
        has_question = "?" in first_sentence or first_sentence.startswith(
            ("why", "how", "what", "is", "did", "can", "will")
        )
        has_breaking = any(trigger in first_sentence for trigger in self.HOOK_TRIGGER_WORDS)

        hook_score = 5.0
        if has_question:
            hook_score += 2.5
        if has_breaking:
            hook_score += 2.5
        if len(first_sentence.split()) <= 15 and (has_question or has_breaking):
            # Punchy short opening hook bonus
            hook_score += 1.0
        hook_score = min(hook_score, 10.0)

        recommendations: list[str] = []
        if pacing_rating == "too_fast":
            recommendations.append(
                f"Pacing is rapid ({wpm:.1f} WPM). Insert strategic pauses or trim adjectives."
            )
        elif pacing_rating == "too_slow":
            recommendations.append(
                f"Pacing is sluggish ({wpm:.1f} WPM). Tighten narrative sentences for retention."
            )

        if not has_question and not has_breaking:
            recommendations.append(
                "First sentence lacks a hook trigger. Start with an unexpected question."
            )

        if word_count < 40:
            recommendations.append(
                "Script is brief. Ensure key context and punchline beats are addressed."
            )

        if not recommendations:
            recommendations.append(
                "Script pacing and hook structure align well with high-retention video standards."
            )

        return ScriptAuditReport(
            word_count=word_count,
            estimated_duration_seconds=round(est_duration, 2),
            words_per_minute=round(wpm, 1),
            pacing_rating=pacing_rating,
            hook_score=round(hook_score, 1),
            has_question_hook=has_question,
            has_breaking_trigger=has_breaking,
            recommendations=recommendations,
        )
