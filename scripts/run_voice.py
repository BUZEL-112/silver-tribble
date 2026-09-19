#!/usr/bin/env python3
"""Standalone runner for voice synthesis and Whisper caption alignment."""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.config import settings
from src.core.database import get_session, init_db
from src.repositories.action_log_repository import ActionLogRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.caption_service import CaptionService
from src.services.storage_service import get_storage_service
from src.services.tts_service import TtsService


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize voice and captions for script")
    parser.add_argument("--script-id", type=int, required=True, help="Target script ID")
    parser.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio (9:16 or 16:9)")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--actor", default="cli", help="Actor identifier for action logging")
    args = parser.parse_args()

    try:
        settings.ensure_directories()
        init_db()
        storage = get_storage_service()

        with get_session() as session:
            script_repo = ScriptRepository(session)
            render_repo = RenderRepository(session)
            cost_repo = CostRepository(session)
            action_repo = ActionLogRepository(session)

            script_record = script_repo.get_script_by_id(args.script_id)
            if not script_record:
                raise ValueError(f"Script record {args.script_id} not found")

            job = render_repo.create_job(
                script_id=args.script_id,
                aspect_ratio=args.aspect_ratio,
            )

            with action_repo.track_operation(
                stage="voice",
                action="synthesize_voice_and_captions",
                actor=args.actor,
                job_id=job.id,
                details={"script_id": args.script_id},
            ):
                tts = TtsService(storage, cost_repo)
                audio_path, duration = tts.synthesize_speech(
                    text=script_record.full_narration,
                    job_id=job.id,
                )
                render_repo.update_job_audio(job.id, audio_path, duration)

                caption_service = CaptionService(storage, cost_repo)
                captions_path, _captions = caption_service.generate_captions(
                    audio_path_or_url=audio_path,
                    job_id=job.id,
                    reference_text=script_record.full_narration,
                    total_duration=duration,
                )
                render_repo.update_job_captions(job.id, captions_path)

            result = {
                "status": "success",
                "job_id": job.id,
                "audio_path": audio_path,
                "duration": round(duration, 2),
            }

            if args.json:
                print(json.dumps(result))
            else:
                print(f"Job #{job.id} audio synthesized ({duration:.1f}s): {audio_path}")

    except Exception as exc:
        if args.json:
            sys.stderr.write(json.dumps({"status": "failed", "error": str(exc)}) + "\n")
        else:
            sys.stderr.write(f"Voice synthesis failed: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
