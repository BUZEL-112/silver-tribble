import logging
import re
import wave
from pathlib import Path

from src.core.config import settings
from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository
from src.services.local_tts_provider import LocalEndpointTtsProvider
from src.services.storage_service import StorageService

logger = logging.getLogger(__name__)

PHONETIC_TTS_PRONUNCIATIONS = [
    (re.compile(r"\bDario Amodei\b", re.IGNORECASE), "Dario Amo-day-ee"),
    (re.compile(r"\bAmodei\b", re.IGNORECASE), "Amo-day-ee"),
]


class TtsService:
    """Synthesizes voice narration from script text via Gemini, edge-tts, or local endpoint provider."""

    def __init__(
        self,
        storage_service: StorageService,
        cost_repo: CostRepository,
        api_key: str | None = None,
        tts_provider: str | None = None,
        local_endpoint: str | None = None,
        local_path: str | Path | None = None,
        local_model: str | None = None,
        local_voice: str | None = None,
        local_timeout: float | None = None,
        local_provider: LocalEndpointTtsProvider | None = None,
    ) -> None:
        self.storage_service = storage_service
        self.cost_repo = cost_repo
        self.api_key = api_key or settings.gemini_api_key
        self.tts_provider = tts_provider or settings.tts_provider
        self.local_endpoint = local_endpoint or settings.local_tts_endpoint
        self.local_path = local_path if local_path is not None else settings.local_tts_path
        self.local_model = local_model or settings.local_tts_model
        self.local_voice = local_voice or settings.local_tts_voice
        self.local_timeout = local_timeout or settings.local_tts_timeout

        self.local_provider = local_provider or LocalEndpointTtsProvider(
            endpoint_url=self.local_endpoint,
            model_path=self.local_path,
            model_name=self.local_model,
            voice_name=self.local_voice,
            timeout=self.local_timeout,
        )

    def _synthesize_edge_tts(
        self,
        text: str,
        output_path: Path,
        voice_name: str = "en-US-ChristopherNeural",
    ) -> float:
        """Synthesize natural speech using edge-tts and convert to 24kHz mono WAV."""
        import asyncio
        import concurrent.futures
        import subprocess

        import edge_tts

        temp_mp3 = output_path.with_suffix(".tmp.mp3")
        try:
            communicate = edge_tts.Communicate(text, voice_name)
            coro = communicate.save(str(temp_mp3))

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(asyncio.run, coro).result()
            else:
                asyncio.run(coro)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(temp_mp3),
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    str(output_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            with wave.open(str(output_path), "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                return frames / float(rate)
        finally:
            if temp_mp3.exists():
                temp_mp3.unlink()

    def synthesize_speech(
        self,
        text: str,
        job_id: int,
        voice_name: str = "Puck",
    ) -> tuple[str, float]:
        """Synthesize script text into audio and store the file.

        Returns a tuple of (stored_audio_path_or_url, duration_in_seconds).
        Fails fast if synthesis cannot be completed; silent synthetic fallback has been removed.
        """
        destination_filename = f"audio/narration_job_{job_id}.wav"
        local_temp_file = self.storage_service.get_local_path(destination_filename)
        local_temp_file.parent.mkdir(parents=True, exist_ok=True)

        character_count = len(text)
        duration_seconds: float = 0.0
        provider = "gemini"
        model_name = voice_name
        cost_usd = 0.0
        last_error: Exception | None = None

        spoken_text = text
        for pattern, replacement in PHONETIC_TTS_PRONUNCIATIONS:
            spoken_text = pattern.sub(replacement, spoken_text)

        synthesized = False
        target_local_voice = voice_name if voice_name and voice_name != "Puck" else self.local_voice

        # 1. Primary: If provider explicitly set to local, run local endpoint synthesis first
        if self.tts_provider == "local":
            try:
                duration_seconds = self.local_provider.synthesize(
                    text=spoken_text,
                    output_path=local_temp_file,
                    voice_name=target_local_voice,
                )
                provider = "local_tts"
                model_name = f"local-{self.local_model}"
                cost_usd = 0.0
                synthesized = True
            except Exception as exc:
                last_error = exc
                logger.warning("Local TTS provider failed: %s", exc)
                synthesized = False

        # 2. Try Gemini Flash Audio if selected and configured
        if not synthesized and self.tts_provider in ["gemini", "auto"]:
            if self.api_key and self.api_key != "your_gemini_api_key_here":
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(api_key=self.api_key)
                    g_voice = "Puck" if "Neural" in voice_name else voice_name
                    # Fallback to current available flash model
                    target_model = "gemini-2.5-flash" if "gemini" in self.api_key else "gemini-2.0-flash"
                    response = client.models.generate_content(
                        model=target_model,
                        contents=spoken_text,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=g_voice)
                                )
                            ),
                        ),
                    )

                    audio_bytes = None
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "inline_data") and part.inline_data:
                            audio_bytes = part.inline_data.data
                            break

                    if audio_bytes:
                        local_temp_file.write_bytes(audio_bytes)
                        with wave.open(str(local_temp_file), "rb") as w:
                            frames = w.getnframes()
                            rate = w.getframerate()
                            duration_seconds = frames / float(rate)
                        provider = "gemini"
                        model_name = f"{target_model}-audio-{g_voice}"
                        cost_usd = (character_count / 1000.0) * 0.04
                        synthesized = True
                except Exception as exc:
                    last_error = exc
                    logger.warning("Gemini TTS provider failed: %s", exc)
                    synthesized = False

        # 3. Fallback to edge-tts neural voice
        if not synthesized and self.tts_provider in ["gemini", "edge_tts", "auto"]:
            try:
                edge_voice = voice_name if "Neural" in voice_name else "en-US-ChristopherNeural"
                duration_seconds = self._synthesize_edge_tts(
                    spoken_text, local_temp_file, edge_voice
                )
                provider = "edge_tts"
                model_name = edge_voice
                synthesized = True
            except Exception as exc:
                last_error = exc
                logger.warning("Edge-TTS provider failed: %s", exc)
                synthesized = False

        # 4. Fallback to local endpoint provider if not already attempted
        if not synthesized and self.tts_provider != "local":
            try:
                duration_seconds = self.local_provider.synthesize(
                    text=spoken_text,
                    output_path=local_temp_file,
                    voice_name=target_local_voice,
                )
                provider = "local_tts"
                model_name = f"local-{self.local_model}"
                cost_usd = 0.0
                synthesized = True
            except Exception as exc:
                last_error = exc
                logger.warning("Fallback local TTS provider failed: %s", exc)
                synthesized = False

        # 5. Fail fast: silent fallback is completely removed
        if not synthesized:
            msg = (
                f"TTS synthesis failed for job #{job_id}. "
                f"Attempted provider '{self.tts_provider}'. Silent synthetic fallback has been removed."
            )
            if last_error:
                raise RuntimeError(msg) from last_error
            raise RuntimeError(msg)

        self.cost_repo.log_cost(
            CostLogCreate(
                job_id=job_id,
                stage="tts_voice",
                provider=provider,
                model=model_name,
                units=float(character_count),
                unit_type="characters",
                cost_usd=cost_usd,
            )
        )

        stored_path = self.storage_service.save_file(local_temp_file, destination_filename)
        return stored_path, duration_seconds
