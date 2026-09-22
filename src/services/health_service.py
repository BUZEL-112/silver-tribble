"""System diagnostic and readiness health-check service."""

import shutil
import subprocess

from sqlalchemy import text

from src.core.config import settings
from src.core.database import get_session
from src.models.schemas import HealthComponentStatus, HealthStatus


class HealthService:
    """Verifies operational readiness of database, storage, external tools, and credentials."""

    def check_database(self) -> HealthComponentStatus:
        """Validate database session connection and query execution."""
        try:
            with get_session() as session:
                session.execute(text("SELECT 1"))
            return HealthComponentStatus(
                name="database",
                status="healthy",
                details=f"Connected to {settings.database_url.split('@')[-1]}",
            )
        except Exception as exc:
            return HealthComponentStatus(
                name="database",
                status="unhealthy",
                details=f"Database connection failed: {exc}",
            )

    def check_storage(self) -> HealthComponentStatus:
        """Verify storage directories exist and are writable."""
        directories = [
            settings.storage_local_dir,
            settings.media_cache_dir,
            settings.remotion_output_dir,
        ]
        failed: list[str] = []
        for d in directories:
            try:
                d.mkdir(parents=True, exist_ok=True)
                test_file = d / ".health_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
            except Exception as exc:
                failed.append(f"{d} ({exc})")

        if failed:
            return HealthComponentStatus(
                name="storage",
                status="unhealthy",
                details=f"Write check failed for: {', '.join(failed)}",
            )

        return HealthComponentStatus(
            name="storage",
            status="healthy",
            details="All storage and media cache directories are writable",
        )

    def check_ffmpeg(self) -> HealthComponentStatus:
        """Check for FFmpeg executable in system PATH."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return HealthComponentStatus(
                name="ffmpeg",
                status="unhealthy",
                details="FFmpeg binary not found in system PATH",
            )
        try:
            res = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            first_line = res.stdout.split("\n")[0] if res.stdout else "Available"
            return HealthComponentStatus(
                name="ffmpeg",
                status="healthy",
                details=first_line,
            )
        except Exception as exc:
            return HealthComponentStatus(
                name="ffmpeg",
                status="degraded",
                details=f"FFmpeg located at {ffmpeg_path} but version check failed: {exc}",
            )

    def check_node_and_remotion(self) -> HealthComponentStatus:
        """Verify Node.js and Remotion bundle setup."""
        node_path = shutil.which("node")
        if not node_path:
            return HealthComponentStatus(
                name="remotion",
                status="unhealthy",
                details="Node.js binary not found in system PATH",
            )

        remotion_dir = settings.remotion_project_dir
        if not remotion_dir.exists():
            return HealthComponentStatus(
                name="remotion",
                status="degraded",
                details=f"Remotion directory not found at {remotion_dir}",
            )

        return HealthComponentStatus(
            name="remotion",
            status="healthy",
            details=f"Node.js found ({node_path}), Remotion project ready at {remotion_dir}",
        )

    def check_providers(self) -> HealthComponentStatus:
        """Audit configured API keys for LLMs, TTS, and visual providers."""
        configured: list[str] = []
        missing: list[str] = []

        providers_map = {
            "OpenAI": settings.openai_api_key,
            "DeepSeek": settings.deepseek_api_key,
            "Gemini": settings.gemini_api_key,
            "Pexels": settings.pexels_api_key,
            "Pixabay": settings.pixabay_api_key,
            "Giphy": settings.giphy_api_key,
            "FLUX": settings.flux_api_key,
        }

        for name, key in providers_map.items():
            if key and str(key).strip():
                configured.append(name)
            else:
                missing.append(name)

        if not configured:
            return HealthComponentStatus(
                name="providers",
                status="degraded",
                details="No external provider API keys configured. Using local offline fallbacks.",
            )

        details_msg = f"Configured: {', '.join(configured)}"
        if missing:
            details_msg += f". Unconfigured: {', '.join(missing)}"

        return HealthComponentStatus(
            name="providers",
            status="healthy",
            details=details_msg,
        )

    def run_health_check(self) -> HealthStatus:
        """Run all diagnostic checks and synthesize system status."""
        components = [
            self.check_database(),
            self.check_storage(),
            self.check_ffmpeg(),
            self.check_node_and_remotion(),
            self.check_providers(),
        ]

        passed = sum(1 for c in components if c.status == "healthy")
        any_unhealthy = any(c.status == "unhealthy" for c in components)
        any_degraded = any(c.status == "degraded" for c in components)

        if any_unhealthy:
            overall_status = "unhealthy"
        elif any_degraded:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return HealthStatus(
            status=overall_status,
            components=components,
            checks_passed=passed,
            total_checks=len(components),
        )
