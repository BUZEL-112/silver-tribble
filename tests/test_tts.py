"""Unit tests for local endpoint TTS provider and TtsService."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.config import flatten_yaml_data
from src.repositories.cost_repository import CostRepository
from src.services.local_tts_provider import LocalEndpointTtsProvider
from src.services.storage_service import LocalStorageService
from src.services.tts_service import TtsService


def _create_mock_wav_bytes(
    duration_seconds: float = 1.0,
    sample_rate: int = 24000,
    channels: int = 1,
) -> bytes:
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate * channels))
    return buffer.getvalue()


def test_flatten_yaml_tts_section():
    data = {
        "tts": {
            "provider": "local",
            "endpoint": "http://localhost:5000",
            "path": "/opt/piper/models/voice.onnx",
            "model": "piper",
            "voice": "en_US-lessac",
            "timeout": 45.0,
        }
    }
    flattened = flatten_yaml_data(data)
    assert flattened["tts_provider"] == "local"
    assert flattened["local_tts_endpoint"] == "http://localhost:5000"
    assert flattened["local_tts_path"] == "/opt/piper/models/voice.onnx"
    assert flattened["local_tts_model"] == "piper"
    assert flattened["local_tts_voice"] == "en_US-lessac"
    assert flattened["local_tts_timeout"] == 45.0


def test_local_tts_provider_http_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TTS_MOCK", raising=False)
    output_wav = tmp_path / "output.wav"
    mock_wav_bytes = _create_mock_wav_bytes(duration_seconds=2.5, sample_rate=24000)

    provider = LocalEndpointTtsProvider(
        endpoint_url="http://localhost:8880/v1/audio/speech",
        model_name="kokoro",
        voice_name="af_heart",
    )

    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_wav_bytes
        mock_post.return_value = mock_response

        duration = provider.synthesize("Hello world", output_wav)

    assert round(duration, 1) == 2.5
    assert output_wav.exists()


def test_local_tts_provider_plain_text_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TTS_MOCK", raising=False)
    output_wav = tmp_path / "output_plain.wav"
    mock_wav_bytes = _create_mock_wav_bytes(duration_seconds=1.5)

    provider = LocalEndpointTtsProvider(
        endpoint_url="http://localhost:5000",
        model_name="piper",
    )

    resp_415 = MagicMock()
    resp_415.status_code = 415

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.content = mock_wav_bytes

    with patch("httpx.Client.post", side_effect=[resp_415, resp_200]):
        duration = provider.synthesize("Plain text retry test", output_wav)

    assert round(duration, 1) == 1.5
    assert output_wav.exists()


def test_local_tts_provider_empty_audio_raises_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TTS_MOCK", raising=False)
    output_wav = tmp_path / "empty.wav"

    provider = LocalEndpointTtsProvider(endpoint_url="http://localhost:8880/v1/audio/speech")

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b""
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError) as exc_info:
            provider.synthesize("Testing empty response", output_wav)

    assert "empty audio" in str(exc_info.value).lower()


def test_local_tts_provider_resample_via_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TTS_MOCK", raising=False)
    output_wav = tmp_path / "resampled.wav"
    # Piper 16000Hz audio that needs resampling to 24000Hz mono
    mock_wav_bytes = _create_mock_wav_bytes(duration_seconds=1.0, sample_rate=16000)

    provider = LocalEndpointTtsProvider(endpoint_url="http://localhost:8880/v1/audio/speech")

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = mock_wav_bytes
        mock_post.return_value = mock_resp

        duration = provider.synthesize("Resample test", output_wav)

    assert duration > 0.5
    assert output_wav.exists()


def test_tts_service_local_storage_and_cost_logging(
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
):
    mock_local_provider = MagicMock(spec=LocalEndpointTtsProvider)

    def fake_synthesize(text: str, output_path: Path, voice_name: str | None = None) -> float:
        output_path.write_bytes(_create_mock_wav_bytes(duration_seconds=3.0))
        return 3.0

    mock_local_provider.synthesize.side_effect = fake_synthesize

    service = TtsService(
        storage_service=temp_storage,
        cost_repo=cost_repo,
        tts_provider="local",
        local_provider=mock_local_provider,
    )

    stored_path, duration = service.synthesize_speech("AI news headline update", job_id=42)

    assert duration == 3.0
    assert "audio/narration_job_42.wav" in stored_path
    assert Path(stored_path).exists()

    cost_records = cost_repo.get_spend_by_stage()
    tts_records = [r for r in cost_records if r["stage"] == "tts_voice"]
    assert len(tts_records) == 1
    assert tts_records[0]["total_usd"] == 0.0


def test_tts_service_fails_fast_without_silent_fallback(
    cost_repo: CostRepository,
    temp_storage: LocalStorageService,
):
    mock_local_provider = MagicMock(spec=LocalEndpointTtsProvider)
    mock_local_provider.synthesize.side_effect = RuntimeError("Local connection refused")

    service = TtsService(
        storage_service=temp_storage,
        cost_repo=cost_repo,
        tts_provider="local",
        local_provider=mock_local_provider,
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.synthesize_speech("Failed speech prompt", job_id=99)

    assert "Silent synthetic fallback has been removed" in str(exc_info.value)
