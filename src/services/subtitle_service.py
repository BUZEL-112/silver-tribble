"""Subtitle generation service converting word-level captions to SRT and WebVTT formats."""

from pathlib import Path

from src.core.config import settings
from src.models.schemas import WordCaption


class SubtitleService:
    """Exports synchronized subtitle files in standard SRT and WebVTT specifications."""

    @staticmethod
    def format_timestamp_srt(seconds: float) -> str:
        """Format seconds into SRT timestamp string HH:MM:SS,mmm."""
        total_ms = int(round(seconds * 1000))
        hours = total_ms // 3600000
        mins = (total_ms % 3600000) // 60000
        secs = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return f"{hours:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    @staticmethod
    def format_timestamp_vtt(seconds: float) -> str:
        """Format seconds into WebVTT timestamp string HH:MM:SS.mmm."""
        total_ms = int(round(seconds * 1000))
        hours = total_ms // 3600000
        mins = (total_ms % 3600000) // 60000
        secs = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return f"{hours:02d}:{mins:02d}:{secs:02d}.{ms:03d}"

    def group_words_into_cues(
        self,
        captions: list[WordCaption],
        max_words_per_cue: int = 6,
        pause_threshold_seconds: float = 0.4,
    ) -> list[dict[str, object]]:
        """Group sequential words into readable subtitle cues based on length and pauses."""
        if not captions:
            return []

        cues: list[dict[str, object]] = []
        current_words: list[str] = []
        cue_start = captions[0].start
        last_end = captions[0].start

        for idx, cap in enumerate(captions):
            gap = cap.start - last_end
            ends_sentence = any(cap.word.endswith(p) for p in [".", "!", "?", ":", ";"])

            # Break cue if max length reached, significant pause detected, or sentence ended
            if current_words and (
                len(current_words) >= max_words_per_cue or gap >= pause_threshold_seconds
            ):
                cues.append(
                    {
                        "start": cue_start,
                        "end": last_end,
                        "text": " ".join(current_words),
                    }
                )
                current_words = [cap.word]
                cue_start = cap.start
            else:
                current_words.append(cap.word)

            last_end = cap.end

            if ends_sentence and idx < len(captions) - 1:
                cues.append(
                    {
                        "start": cue_start,
                        "end": last_end,
                        "text": " ".join(current_words),
                    }
                )
                current_words = []
                cue_start = captions[idx + 1].start

        if current_words:
            cues.append(
                {
                    "start": cue_start,
                    "end": last_end,
                    "text": " ".join(current_words),
                }
            )

        return cues

    def generate_srt(self, captions: list[WordCaption]) -> str:
        """Render standard SubRip Subtitle (.srt) document content."""
        cues = self.group_words_into_cues(captions)
        lines: list[str] = []

        for idx, cue in enumerate(cues, start=1):
            start_str = self.format_timestamp_srt(float(cue["start"]))
            end_str = self.format_timestamp_srt(float(cue["end"]))
            text_str = str(cue["text"])

            lines.append(str(idx))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(text_str)
            lines.append("")

        return "\n".join(lines)

    def generate_vtt(self, captions: list[WordCaption]) -> str:
        """Render WebVTT (.vtt) document content."""
        cues = self.group_words_into_cues(captions)
        lines: list[str] = ["WEBVTT", ""]

        for idx, cue in enumerate(cues, start=1):
            start_str = self.format_timestamp_vtt(float(cue["start"]))
            end_str = self.format_timestamp_vtt(float(cue["end"]))
            text_str = str(cue["text"])

            lines.append(str(idx))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(text_str)
            lines.append("")

        return "\n".join(lines)

    def export_subtitles(
        self,
        captions: list[WordCaption],
        job_id: int,
        output_dir: Path | None = None,
    ) -> dict[str, Path]:
        """Write both .srt and .vtt subtitle files for a given render job."""
        dest_dir = output_dir or (settings.storage_local_dir / "subtitles")
        dest_dir.mkdir(parents=True, exist_ok=True)

        srt_content = self.generate_srt(captions)
        vtt_content = self.generate_vtt(captions)

        srt_path = dest_dir / f"captions_job_{job_id}.srt"
        vtt_path = dest_dir / f"captions_job_{job_id}.vtt"

        srt_path.write_text(srt_content, encoding="utf-8")
        vtt_path.write_text(vtt_content, encoding="utf-8")

        return {"srt": srt_path, "vtt": vtt_path}
