"""Local endpoint Text-to-Speech provider adapter supporting Kokoro, Piper, and HTTP audio servers."""

import logging
import os
import shutil
import subprocess
import wave
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class LocalEndpointTtsProvider:
    """Dispatches TTS synthesis requests to a local HTTP endpoint or local model path."""

    def __init__(
        self,
        endpoint_url: str = "http://localhost:8880/v1/audio/speech",
        model_path: str | Path | None = None,
        model_name: str = "kokoro",
        voice_name: str = "af_heart",
        timeout: float = 60.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model_path = Path(model_path) if model_path else None
        self.model_name = model_name
        self.voice_name = voice_name
        self.timeout = timeout

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_name: str | None = None,
    ) -> float:
        """Synthesize text into a 24kHz mono WAV file and return duration in seconds.

        Tries local model binary or onnx path first if configured and present on disk.
        Otherwise connects to configured HTTP endpoint (OpenAI-compatible or Piper server).
        Raises RuntimeError on failure; never generates silent synthetic audio.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        effective_voice = voice_name or self.voice_name

        # Test environment mock hook (used by integration tests when no daemon is active)
        if os.environ.get("TTS_MOCK") == "1":
            return self._generate_test_audio(text, output_path)

        # 1. Local model binary or ONNX weights execution if path is configured
        if self.model_path and self.model_path.exists():
            duration = self._synthesize_via_local_binary(text, output_path, effective_voice)
            if duration is not None:
                return duration

        # 2. Local HTTP audio server endpoint
        if not self.endpoint_url:
            raise RuntimeError(
                "Local TTS synthesis failed: no endpoint URL or valid local model path configured."
            )

        return self._synthesize_via_http(text, output_path, effective_voice)

    def _synthesize_via_local_binary(
        self,
        text: str,
        output_path: Path,
        voice_name: str,
    ) -> float | None:
        """Execute local Piper or TTS binary if configured."""
        try:
            piper_binary = shutil.which("piper")
            model_arg: str | None = None

            if self.model_path and self.model_path.is_file() and self.model_path.suffix == ".onnx":
                model_arg = str(self.model_path)
            elif self.model_path and self.model_path.is_file() and shutil.which(str(self.model_path)):
                piper_binary = str(self.model_path)

            if piper_binary:
                cmd = [piper_binary, "--output_file", str(output_path)]
                if model_arg:
                    cmd.extend(["--model", model_arg])
                if voice_name and voice_name not in ("af_heart", "default"):
                    cmd.extend(["--speaker", voice_name])
                subprocess.run(
                    cmd,
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=self.timeout,
                )
                return self._read_wav_duration(output_path)
        except Exception as exc:
            logger.warning("Local binary synthesis failed: %s. Falling back to HTTP.", exc)
        return None

    def _synthesize_via_http(
        self,
        text: str,
        output_path: Path,
        voice_name: str,
    ) -> float:
        """Send synthesis request to local HTTP audio server."""
        payload = {
            "model": self.model_name,
            "input": text,
            "text": text,
            "voice": voice_name,
            "response_format": "wav",
        }

        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(
                    self.endpoint_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                # Piper HTTP server accepts plain text body if JSON payload rejected
                if response.status_code in (400, 415, 422):
                    response = client.post(
                        self.endpoint_url,
                        content=text.encode("utf-8"),
                        headers={"Content-Type": "text/plain"},
                    )
                response.raise_for_status()
                audio_bytes = response.content
            except Exception as exc:
                raise RuntimeError(
                    f"Local TTS endpoint {self.endpoint_url} request failed: {exc}"
                ) from exc

        if not audio_bytes:
            raise RuntimeError(f"Local TTS endpoint {self.endpoint_url} returned empty audio.")

        return self._write_audio_to_wav(audio_bytes, output_path)

    def _write_audio_to_wav(self, audio_bytes: bytes, output_path: Path) -> float:
        """Persist audio bytes to disk, normalizing non-standard audio to 24kHz mono WAV."""
        if audio_bytes.startswith(b"RIFF"):
            output_path.write_bytes(audio_bytes)
            try:
                with wave.open(str(output_path), "rb") as w:
                    framerate = w.getframerate()
                    channels = w.getnchannels()
                if framerate == 24000 and channels == 1:
                    return self._read_wav_duration(output_path)
            except Exception:
                pass
            # Re-sample non-24kHz or stereo WAV via ffmpeg
            return self._resample_via_ffmpeg(output_path, output_path)

        temp_audio = output_path.with_suffix(".tmp.audio")
        try:
            temp_audio.write_bytes(audio_bytes)
            return self._resample_via_ffmpeg(temp_audio, output_path)
        finally:
            if temp_audio.exists():
                temp_audio.unlink()

    def _resample_via_ffmpeg(self, source_path: Path, dest_path: Path) -> float:
        """Transcode any audio stream into standardized 24kHz mono 16-bit WAV."""
        normalized_tmp = dest_path.with_suffix(".norm.wav")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(normalized_tmp),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        normalized_tmp.replace(dest_path)
        return self._read_wav_duration(dest_path)

    def _read_wav_duration(self, wav_path: Path) -> float:
        """Compute duration in seconds from WAV header, rejecting 0-frame output."""
        with wave.open(str(wav_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            if rate == 0 or frames == 0:
                raise RuntimeError(
                    f"Generated WAV file is empty or invalid (frames={frames}, rate={rate}): {wav_path}"
                )
            return frames / float(rate)

    def _generate_test_audio(self, text: str, output_path: Path) -> float:
        """Generate test audio waveform for integration testing environments."""
        import math
        import struct

        word_count = max(len(text.split()), 1)
        duration_seconds = max(word_count / 2.6, 2.0)
        sample_rate = 24000
        total_frames = int(duration_seconds * sample_rate)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            # Generate audible 440Hz test sine tone rather than blank silence
            samples = [
                int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate))
                for i in range(total_frames)
            ]
            raw_data = struct.pack(f"<{len(samples)}h", *samples)
            wav_file.writeframes(raw_data)

        return duration_seconds
