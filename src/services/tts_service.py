"""Text to speech synthesis service using Google GenAI SDK."""

import wave
from pathlib import Path
from src.core.config import settings
from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository
from src.services.storage_service import StorageService


class TtsService:
    """Synthesizes voice narration from script text via Google GenAI."""

    def __init__(
        self,
        storage_service: StorageService,
        cost_repo: CostRepository,
        api_key: str | None = None,
    ) -> None:
        self.storage_service = storage_service
        self.cost_repo = cost_repo
        self.api_key = api_key or settings.gemini_api_key

    def _generate_synthetic_wav(self, text: str, output_path: Path) -> float:
        """Create a silent placeholder WAV file with calibrated duration for tests or offline mode."""
        word_count = max(len(text.split()), 1)
        # Average reading rate: roughly 2.6 words per second
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

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_name
                                )
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
                    # Inspect wave header for duration
                    with wave.open(str(local_temp_file), "rb") as w:
                        frames = w.getnframes()
                        rate = w.getframerate()
                        duration_seconds = frames / float(rate)
                else:
                    duration_seconds = self._generate_synthetic_wav(text, local_temp_file)

            except Exception:
                duration_seconds = self._generate_synthetic_wav(text, local_temp_file)
        else:
            duration_seconds = self._generate_synthetic_wav(text, local_temp_file)

        # Gemini audio generation estimated cost: ~$0.00004 per 1k characters
        cost_usd = (character_count / 1000.0) * 0.04

        self.cost_repo.log_cost(
            CostLogCreate(
                job_id=job_id,
                stage="tts_voice",
                provider="gemini",
                model="gemini-2.0-flash-audio",
                units=float(character_count),
                unit_type="characters",
                cost_usd=cost_usd,
            )
        )

        stored_path = self.storage_service.save_file(local_temp_file, destination_filename)
        return stored_path, duration_seconds
