"""Service for uploading rendered videos directly to YouTube using OAuth 2.0."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from src.core.config import settings
from src.core.database import get_session
from src.models.schemas import YouTubeUploadRequest, YouTubeUploadResult
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.storage_service import StorageService, get_storage_service
from src.services.youtube_metadata_service import YouTubeMetadataService

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
)


class YouTubeUploadService:
    """Publishes videos to YouTube via Google OAuth 2.0 and YouTube Data API v3."""

    def __init__(
        self,
        storage_service: StorageService | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self.storage = storage_service or get_storage_service()
        self.client_id = client_id or settings.youtube_client_id
        self.client_secret = client_secret or settings.youtube_client_secret
        self.refresh_token = refresh_token or settings.youtube_refresh_token
        self.metadata_service = YouTubeMetadataService(self.storage)

    def is_configured(self) -> bool:
        """Check whether Google OAuth credentials for YouTube are fully present."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def refresh_access_token(self) -> str:
        """Obtain a fresh OAuth access token using the stored refresh token."""
        if not self.is_configured():
            raise ValueError(
                "YouTube OAuth credentials not configured. Please provide client_id, "
                "client_secret, and refresh_token in settings."
            )

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(GOOGLE_TOKEN_URL, data=payload)
                resp.raise_for_status()
                data = resp.json()
                token = data.get("access_token")
                if not token:
                    raise ValueError("OAuth response missing access_token field")
                return str(token)
        except Exception as exc:
            logger.error("Failed to refresh Google OAuth token: %s", exc)
            raise RuntimeError(f"Google OAuth token refresh failed: {exc}") from exc

    def upload_video_for_job(self, req: YouTubeUploadRequest) -> YouTubeUploadResult:
        """Publish the rendered video artifact for a given job to YouTube."""
        with get_session() as session:
            render_repo = RenderRepository(session)
            script_repo = ScriptRepository(session)
            action_repo = ActionLogRepository(session)

            job = render_repo.get_job_by_id(req.job_id)
            if not job:
                raise ValueError(f"RenderJob with id {req.job_id} not found")

            if not job.output_video_path:
                raise ValueError(
                    f"Job #{job.id} does not have an output video path. Has it rendered?"
                )

            video_path = self.storage.get_local_path(job.output_video_path)
            if not video_path.exists():
                raise FileNotFoundError(f"Video file not found at path: {video_path}")

            script = script_repo.get_script_by_id(job.script_id)
            if not script:
                raise ValueError(f"Script with id {job.script_id} not found")

            # Build metadata defaults if not overridden
            pkg = self.metadata_service.generate_metadata(
                script=script,
                job=job,
                duration_seconds=job.duration_seconds or 30.0,
            )
            title = req.title or (pkg.title_options[0] if pkg.title_options else script.title)
            description = req.description or pkg.description
            tags = req.tags or pkg.tags
            privacy = req.privacy_status

            access_token = self.refresh_access_token()
            file_size = video_path.stat().st_size

            # 1. Initiate resumable upload session
            init_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            }

            metadata_body: dict[str, Any] = {
                "snippet": {
                    "title": title[:100],
                    "description": description[:5000],
                    "tags": tags[:50],
                    "categoryId": "28",  # Science & Technology
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }

            with httpx.Client(timeout=30.0) as client:
                init_resp = client.post(
                    YOUTUBE_UPLOAD_URL,
                    headers=init_headers,
                    content=json.dumps(metadata_body),
                )
                init_resp.raise_for_status()

                upload_url = init_resp.headers.get("Location")
                if not upload_url:
                    raise RuntimeError("YouTube API did not return resumable upload Location")

            # 2. Upload video bytes to upload_url
            with open(video_path, "rb") as video_file:
                upload_headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(file_size),
                }
                with httpx.Client(timeout=300.0) as client:
                    upload_resp = client.put(
                        upload_url,
                        headers=upload_headers,
                        content=video_file.read(),
                    )
                    upload_resp.raise_for_status()
                    result_data = upload_resp.json()

            video_id = result_data.get("id")
            if not video_id:
                raise RuntimeError("YouTube API response did not contain video ID")

            video_url = f"https://youtu.be/{video_id}"

            action_repo.record_action(
                stage="render",
                action="publish_youtube",
                actor="youtube_service",
                status="success",
                job_id=job.id,
                message=f"Uploaded video to YouTube: {video_url}",
                details={
                    "video_id": video_id,
                    "video_url": video_url,
                    "privacy": privacy,
                },
            )

            return YouTubeUploadResult(
                video_id=video_id,
                video_url=video_url,
                title=title,
                privacy_status=privacy,
                uploaded_at=datetime.now(UTC).isoformat(),
            )
