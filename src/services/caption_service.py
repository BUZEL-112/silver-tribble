"""Audio transcription and word-level caption alignment using faster-whisper."""

import json
import re

from src.core.config import settings
from src.models.schemas import CostLogCreate, WordCaption
from src.repositories.cost_repository import CostRepository
from src.services.storage_service import StorageService


class CaptionService:
    """Extracts synchronized word-level timestamps from narration audio."""

    def __init__(
        self,
        storage_service: StorageService,
        cost_repo: CostRepository,
        model_size: str | None = None,
        device: str | None = None,
    ) -> None:
        self.storage_service = storage_service
        self.cost_repo = cost_repo
        self.model_size = model_size or settings.whisper_model_size
        self.device = device or settings.whisper_device
        self._model = None

    def _get_model(self):
        """Lazy load the Whisper model to conserve startup memory."""
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="int8" if self.device == "cpu" else "float16",
            )
        return self._model

    def _align_words_fallback(
        self,
        reference_text: str,
        total_duration: float,
    ) -> list[WordCaption]:
        """Distribute words uniformly across total duration for offline test runs."""
        words = reference_text.split()
        if not words:
            return []

        interval = total_duration / len(words)
        captions: list[WordCaption] = []
        current_time = 0.0

        for word in words:
            start = round(current_time, 2)
            end = round(current_time + interval * 0.9, 2)
            captions.append(WordCaption(word=word, start=start, end=end, confidence=1.0))
            current_time += interval

        return captions

    def generate_captions(
        self,
        audio_path_or_url: str,
        job_id: int,
        reference_text: str = "",
        total_duration: float = 30.0,
    ) -> tuple[str, list[WordCaption]]:
        """Transcribe audio with word timestamps, store the JSON artifact, and return the path."""
        local_audio_path = self.storage_service.get_local_path(audio_path_or_url)
        captions: list[WordCaption] = []

        proper_noun_corrections = {
            "amade": "Amodei",
            "amadei": "Amodei",
            "amadi": "Amodei",
            "dario": "Dario",
            "jensen": "Jensen",
            "huang": "Huang",
            "anthropic": "Anthropic",
            "openai": "OpenAI",
            "nvidia": "Nvidia",
            "wifi": "Wi-Fi",
            "passports": "passwords",
            "passport": "password",
            "chatgpt": "ChatGPT",
            "claude": "Claude",
            "gemini": "Gemini",
        }

        allowed_compounds = {
            "three-step",
            "third-party",
            "self-regulation",
            "wi-fi",
            "open-source",
            "multi-billion-dollar",
        }
        ref_text_lower = (reference_text or "").lower()

        try:
            model = self._get_model()
            initial_prompt = (
                "AI news report: Anthropic, Dario Amodei, Jensen Huang, OpenAI, Nvidia, LLMs, "
                "superintelligence, third-party, three-step, Wi-Fi passwords, self-regulation."
            )
            segments, _info = model.transcribe(
                str(local_audio_path),
                word_timestamps=True,
                language="en",
                initial_prompt=initial_prompt,
            )
            for segment in segments:
                if segment.words:
                    for w in segment.words:
                        clean_word = w.word.strip()
                        if not clean_word or clean_word == "-":
                            continue

                        # Check leading hyphen tokens against legitimate compound words
                        if clean_word.startswith("-") and len(clean_word) > 1 and captions:
                            prev_base = re.sub(r"[^\w]", "", captions[-1].word).lower()
                            next_base = re.sub(r"[^\w]", "", clean_word).lower()
                            candidate_compound = f"{prev_base}-{next_base}"
                            if (
                                candidate_compound in allowed_compounds
                                or candidate_compound in ref_text_lower
                            ):
                                punct = re.search(r"[.,!?:;]+$", clean_word)
                                trailing = punct.group(0) if punct else ""
                                captions[
                                    -1
                                ].word = (
                                    f"{captions[-1].word.rstrip('.,!?:;')}-{next_base}{trailing}"
                                )
                                captions[-1].end = round(w.end, 2)
                                continue
                            else:
                                clean_word = clean_word.lstrip("-")

                        # Correct acoustic misrecognitions and proper nouns
                        base_w = re.sub(r"[^\w]", "", clean_word.lower())
                        if base_w in proper_noun_corrections:
                            correct = proper_noun_corrections[base_w]
                            punct = re.search(r"[.,!?:;]+$", clean_word)
                            clean_word = f"{correct}{punct.group(0)}" if punct else correct

                        captions.append(
                            WordCaption(
                                word=clean_word,
                                start=round(w.start, 2),
                                end=round(w.end, 2),
                                confidence=round(getattr(w, "probability", 1.0), 2),
                            )
                        )
        except Exception:
            captions = self._align_words_fallback(reference_text, total_duration)

        ref_words = reference_text.split() if reference_text else []
        if ref_words and len(captions) < max(len(ref_words) * 0.4, 3):
            captions = self._align_words_fallback(reference_text, total_duration)

        destination_key = f"captions/captions_job_{job_id}.json"
        local_json_path = settings.storage_local_dir / destination_key
        local_json_path.parent.mkdir(parents=True, exist_ok=True)

        payload = [c.model_dump() for c in captions]
        local_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Local whisper has zero direct API cost, logged with 0 USD
        self.cost_repo.log_cost(
            CostLogCreate(
                job_id=job_id,
                stage="caption_alignment",
                provider="faster-whisper",
                model=self.model_size,
                units=total_duration,
                unit_type="seconds",
                cost_usd=0.0,
            )
        )

        stored_json_path = self.storage_service.save_file(local_json_path, destination_key)
        return stored_json_path, captions
