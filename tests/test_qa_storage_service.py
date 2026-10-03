"""QA tests for LocalStorageService and the get_storage_service() factory.

Coverage:
- save_bytes() and save_file() happy paths
- Return-value contracts (string path, Path object)
- Parent-directory auto-creation
- Overwrite semantics
- Factory selects LocalStorageService when S3 is not configured
- Boundary: empty bytes payload
- Boundary: very long destination key (deep nested path)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.storage_service import LocalStorageService, get_storage_service

# ---------------------------------------------------------------------------
# save_bytes() -- LocalStorageService
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_bytes_happy_path_writes_data_to_disk(temp_storage: LocalStorageService) -> None:
    """save_bytes() should persist raw bytes at the resolved target path."""
    payload = b"hello storage"

    # Act
    returned_path = temp_storage.save_bytes(payload, "audio/narration.mp3")

    # Assert
    on_disk = Path(returned_path)
    assert on_disk.exists()
    assert on_disk.read_bytes() == payload


@pytest.mark.unit
def test_save_bytes_returns_string_path(temp_storage: LocalStorageService) -> None:
    """save_bytes() must return a str, not a Path object."""
    result = temp_storage.save_bytes(b"x", "output/clip.wav")

    assert isinstance(result, str)


@pytest.mark.unit
def test_save_bytes_creates_parent_directories_automatically(
    temp_storage: LocalStorageService,
) -> None:
    """save_bytes() must create arbitrarily nested subdirectories on the fly."""
    key = "a/b/c/d/deep_file.bin"

    returned_path = temp_storage.save_bytes(b"deep", key)

    assert Path(returned_path).exists()


@pytest.mark.unit
def test_save_bytes_overwrites_existing_file(temp_storage: LocalStorageService) -> None:
    """A second save_bytes() call with the same key must replace previous content."""
    key = "overwrite_me.txt"
    temp_storage.save_bytes(b"first", key)

    temp_storage.save_bytes(b"second", key)

    written = Path(temp_storage.save_bytes(b"second", key))
    assert written.read_bytes() == b"second"


@pytest.mark.unit
def test_save_bytes_empty_payload_writes_zero_byte_file(
    temp_storage: LocalStorageService,
) -> None:
    """Boundary: saving empty bytes should produce a zero-byte file without error."""
    returned_path = temp_storage.save_bytes(b"", "empty.bin")

    on_disk = Path(returned_path)
    assert on_disk.exists()
    assert on_disk.stat().st_size == 0


@pytest.mark.unit
def test_save_bytes_very_long_destination_key_succeeds(
    temp_storage: LocalStorageService,
) -> None:
    """Boundary: a destination key with many segments must still be accepted."""
    segments = "/".join(["segment"] * 10)
    long_key = f"{segments}/file.dat"

    returned_path = temp_storage.save_bytes(b"data", long_key)

    assert Path(returned_path).exists()


# ---------------------------------------------------------------------------
# save_file() -- LocalStorageService
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_save_file_happy_path_copies_file_contents(
    tmp_path: Path, temp_storage: LocalStorageService
) -> None:
    """save_file() should read the source file and write identical bytes at the destination."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video data")

    returned_path = temp_storage.save_file(source, "videos/clip.mp4")

    assert Path(returned_path).read_bytes() == b"video data"


@pytest.mark.unit
def test_save_file_returns_string_path(tmp_path: Path, temp_storage: LocalStorageService) -> None:
    """save_file() must return a str identifier, not a Path object."""
    source = tmp_path / "sample.txt"
    source.write_bytes(b"text")

    result = temp_storage.save_file(source, "docs/sample.txt")

    assert isinstance(result, str)


@pytest.mark.unit
def test_save_file_creates_nested_parent_directories(
    tmp_path: Path, temp_storage: LocalStorageService
) -> None:
    """save_file() must create any missing parent directories in the destination key."""
    source = tmp_path / "raw.jpg"
    source.write_bytes(b"jpeg")

    returned_path = temp_storage.save_file(source, "images/2024/01/photo.jpg")

    assert Path(returned_path).exists()


@pytest.mark.unit
def test_save_file_overwrites_previous_content(
    tmp_path: Path, temp_storage: LocalStorageService
) -> None:
    """A subsequent save_file() to the same key must replace existing content."""
    source_v1 = tmp_path / "v1.bin"
    source_v1.write_bytes(b"version-one")
    source_v2 = tmp_path / "v2.bin"
    source_v2.write_bytes(b"version-two")
    key = "artifact/latest.bin"

    temp_storage.save_file(source_v1, key)
    returned_path = temp_storage.save_file(source_v2, key)

    assert Path(returned_path).read_bytes() == b"version-two"


@pytest.mark.unit
def test_save_file_empty_source_writes_zero_byte_file(
    tmp_path: Path, temp_storage: LocalStorageService
) -> None:
    """Boundary: save_file() on an empty source must produce a zero-byte destination."""
    source = tmp_path / "empty.bin"
    source.write_bytes(b"")

    returned_path = temp_storage.save_file(source, "empty_copy.bin")

    assert Path(returned_path).stat().st_size == 0


# ---------------------------------------------------------------------------
# get_local_path() -- LocalStorageService
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_local_path_relative_key_returns_path_object(
    temp_storage: LocalStorageService,
) -> None:
    """get_local_path() for a relative key must return a Path instance."""
    result = temp_storage.get_local_path("audio/track.mp3")

    assert isinstance(result, Path)


@pytest.mark.unit
def test_get_local_path_relative_key_resolves_under_base_dir(
    temp_storage: LocalStorageService,
) -> None:
    """A relative key must resolve to a path inside the configured base_dir."""
    result = temp_storage.get_local_path("subfolder/file.txt")

    assert str(temp_storage.base_dir.resolve()) in str(result)


@pytest.mark.unit
def test_get_local_path_absolute_key_returned_unchanged(
    tmp_path: Path, temp_storage: LocalStorageService
) -> None:
    """An absolute path string must be returned as-is, not nested under base_dir."""
    absolute_key = str(tmp_path / "already_absolute.mp4")

    result = temp_storage.get_local_path(absolute_key)

    assert str(result) == absolute_key


@pytest.mark.unit
def test_get_local_path_nonexistent_key_returns_path_without_raising(
    temp_storage: LocalStorageService,
) -> None:
    """get_local_path() for a missing file must return a Path without raising."""
    result = temp_storage.get_local_path("does/not/exist.wav")

    assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# get_storage_service() factory
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_storage_service_returns_local_when_no_s3_configured() -> None:
    """Factory must return LocalStorageService when storage_backend != 's3'."""
    mock_settings = MagicMock()
    mock_settings.storage_backend = "local"
    mock_settings.r2_access_key_id = None
    mock_settings.storage_local_dir = Path("/tmp/test_storage")

    with patch("src.services.storage_service.settings", mock_settings):
        service = get_storage_service()

    assert isinstance(service, LocalStorageService)


@pytest.mark.unit
def test_get_storage_service_returns_local_when_s3_backend_lacks_credentials() -> None:
    """Factory must fall back to LocalStorageService when r2_access_key_id is absent."""
    mock_settings = MagicMock()
    mock_settings.storage_backend = "s3"
    mock_settings.r2_access_key_id = ""
    mock_settings.storage_local_dir = Path("/tmp/test_storage_fallback")

    with patch("src.services.storage_service.settings", mock_settings):
        service = get_storage_service()

    assert isinstance(service, LocalStorageService)
