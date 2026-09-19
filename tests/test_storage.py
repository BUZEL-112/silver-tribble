"""Unit tests for storage service adapter."""

from pathlib import Path

from src.services.storage_service import LocalStorageService


def test_save_bytes(temp_storage: LocalStorageService):
    data = b"RIFF....WAVEfmt ...."
    path_str = temp_storage.save_bytes(data, "audio/test_audio.wav")
    path = Path(path_str)

    assert path.exists()
    assert path.read_bytes() == data


def test_save_file(temp_storage: LocalStorageService, tmp_path: Path):
    source_file = tmp_path / "source.json"
    source_file.write_text('{"status": "ok"}', encoding="utf-8")

    path_str = temp_storage.save_file(source_file, "captions/test_captions.json")
    path = Path(path_str)

    assert path.exists()
    assert path.read_text(encoding="utf-8") == '{"status": "ok"}'


def test_get_local_path(temp_storage: LocalStorageService):
    key = "broll/clip1.mp4"
    resolved_path = temp_storage.get_local_path(key)
    assert resolved_path.is_absolute()
    assert resolved_path.name == "clip1.mp4"
