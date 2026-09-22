import re
import wave
from pathlib import Path

from src.core.config import settings
from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository
from src.services.storage_service import StorageService

PHONETIC_TTS_PRONUNCIATIONS = [
    (re.compile(r"\bDario Amodei\b", re.IGNORECASE), "Dario Amo-day-ee"),
    (re.compile(r"\bAmodei\b", re.IGNORECASE), "Amo-day-ee"),
]


class TtsService:
    """Synthesizes voice narration from script text via Google GenAI."""

    def __init__(
        self,
        storage_service: StorageService,
        cost_repo: CostRepository,
        api_key: str | None = None,
        tts_provider: str | None = None,
    ) -> None:
        self.storage_service = storage_service
        self.cost_repo = cost_repo
        self.api_key = api_key or settings.gemini_api_key
        self.tts_provider = tts_provider or settings.tts_provider

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

    def _generate_synthetic_wav(self, text: str, output_path: Path) -> float:
        """Create a silent placeholder WAV file with calibrated duration for tests/offline."""
        word_count = max(len(text.split()), 1)
        duration_seconds = max(word_count / 2.6, 2.0)
        sample_rate = 24000
        total_frames = int(duration_seconds * sample_rate)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * total_frames)

        return duration_seconds

    def synthesize_speech(
        self,
        text: str,
        job_id: int,
        voice_name: str = "Puck",
    ) -> tuple[str, float]:
        """Synthesize script text into audio and store the file.

        Returns a tuple of (stored_audio_path_or_url, duration_in_seconds).
        """
        destination_filename = f"audio/narration_job_{job_id}.wav"
        local_temp_file = settings.storage_local_dir / destination_filename
        local_temp_file.parent.mkdir(parents=True, exist_ok=True)

        character_count = len(text)
        duration_seconds: float
        provider = "gemini"
        model_name = voice_name
        cost_usd = 0.0

        spoken_text = text
        for pattern, replacement in PHONETIC_TTS_PRONUNCIATIONS:
            spoken_text = pattern.sub(replacement, spoken_text)

        synthesized = False

        # 1. Primary: Try Gemini 2.0 Flash Audio if configured and selected
        should_try_gemini_first = self.tts_provider in ["gemini", "auto"]
        if should_try_gemini_first and self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                g_voice = "Puck" if "Neural" in voice_name else voice_name
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
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
                    model_name = f"gemini-2.0-flash-audio-{g_voice}"
                    cost_usd = (character_count / 1000.0) * 0.04
                    synthesized = True
            except Exception:
                synthesized = False

        # 2. Secondary fallback: edge-tts neural voice
        if not synthesized:
            try:
                edge_voice = voice_name if "Neural" in voice_name else "en-US-ChristopherNeural"
                duration_seconds = self._synthesize_edge_tts(
                    spoken_text, local_temp_file, edge_voice
                )
                provider = "edge_tts"
                model_name = edge_voice
                synthesized = True
            except Exception:
                synthesized = False

        # 3. Tertiary fallback: calibrated synthetic WAV
        if not synthesized:
            duration_seconds = self._generate_synthetic_wav(text, local_temp_file)
            provider = "synthetic_fallback"
            model_name = "silent_wav"

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
