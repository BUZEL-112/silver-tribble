"""Storage service interface and concrete adapters for local disk and S3/R2."""

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.config import settings


class StorageService(ABC):
    """Abstract interface for managing pipeline audio, video, and image assets."""

    @abstractmethod
    def save_bytes(self, data: bytes, destination_key: str) -> str:
        """Persist raw byte data and return the access path or URL."""
        pass

    @abstractmethod
    def save_file(self, local_source_path: Path, destination_key: str) -> str:
        """Upload or copy a local file to storage and return its identifier."""
        pass

    @abstractmethod
    def get_local_path(self, asset_key_or_path: str) -> Path:
        """Ensure the asset is accessible as a local Path on the filesystem."""
        pass


class LocalStorageService(StorageService):
    """Stores assets directly on local disk under the configured storage directory."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.storage_local_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, data: bytes, destination_key: str) -> str:
        target_path = self.base_dir / destination_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return str(target_path.resolve())

    def save_file(self, local_source_path: Path, destination_key: str) -> str:
        target_path = self.base_dir / destination_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if local_source_path.resolve() != target_path.resolve():
            target_path.write_bytes(local_source_path.read_bytes())
        return str(target_path.resolve())

    def get_local_path(self, asset_key_or_path: str) -> Path:
        path = Path(asset_key_or_path)
        if path.is_absolute():
            return path
        return (self.base_dir / asset_key_or_path).resolve()


class S3StorageService(StorageService):
    """Stores assets in Cloudflare R2 or Amazon S3 using boto3 client."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        endpoint_url = None
        if settings.r2_account_id:
            endpoint_url = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"

        self.bucket = settings.r2_bucket_name or "ai-video-assets"
        self.public_url = settings.r2_public_url
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            config=Config(signature_version="s3v4"),
        )
        self.local_cache_dir = settings.storage_local_dir / "cache"
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, data: bytes, destination_key: str) -> str:
        self.s3_client.put_object(Bucket=self.bucket, Key=destination_key, Body=data)
        if self.public_url:
            return f"{self.public_url.rstrip('/')}/{destination_key}"
        return f"s3://{self.bucket}/{destination_key}"

    def save_file(self, local_source_path: Path, destination_key: str) -> str:
        with open(local_source_path, "rb") as f:
            self.s3_client.put_object(Bucket=self.bucket, Key=destination_key, Body=f)
        if self.public_url:
            return f"{self.public_url.rstrip('/')}/{destination_key}"
        return f"s3://{self.bucket}/{destination_key}"

    def get_local_path(self, asset_key_or_path: str) -> Path:
        if asset_key_or_path.startswith("http://") or asset_key_or_path.startswith("https://"):
            key = asset_key_or_path.split("/")[-1]
        elif asset_key_or_path.startswith("s3://"):
            parts = asset_key_or_path.replace("s3://", "").split("/", 1)
            key = parts[1] if len(parts) > 1 else parts[0]
        else:
            key = asset_key_or_path

        local_path = self.local_cache_dir / key
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.s3_client.download_file(self.bucket, key, str(local_path))
        return local_path


def get_storage_service() -> StorageService:
    """Factory creating configured StorageService implementation."""
    if settings.storage_backend == "s3" and settings.r2_access_key_id:
        return S3StorageService()
    return LocalStorageService()
