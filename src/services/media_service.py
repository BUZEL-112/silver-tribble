import re
import subprocess
from pathlib import Path
from typing import Any, Literal

import httpx

from src.core.config import settings
from src.models.schemas import (
    CostLogCreate,
    SentenceMediaPlacement,
    WordCaption,
)
from src.repositories.cost_repository import CostRepository
from src.services.media_inspector import MediaInspector
from src.services.storage_service import StorageService, get_storage_service

STOP_WORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "arent",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "cant",
    "cannot",
    "could",
    "couldnt",
    "did",
    "didnt",
    "do",
    "does",
    "doesnt",
    "doing",
    "dont",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "hadnt",
    "has",
    "hasnt",
    "have",
    "havent",
    "having",
    "he",
    "hed",
    "hell",
    "hes",
    "her",
    "here",
    "heres",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "hows",
    "i",
    "id",
    "ill",
    "im",
    "ive",
    "if",
    "in",
    "into",
    "is",
    "isnt",
    "it",
    "its",
    "itself",
    "lets",
    "me",
    "more",
    "most",
    "mustnt",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "ought",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "shant",
    "she",
    "shed",
    "shell",
    "shes",
    "should",
    "shouldnt",
    "so",
    "some",
    "such",
    "than",
    "that",
    "thats",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "theres",
    "these",
    "they",
    "theyd",
    "theyll",
    "theyre",
    "theyve",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "wasnt",
    "we",
    "wed",
    "well",
    "were",
    "werent",
    "weve",
    "what",
    "whats",
    "when",
    "whens",
    "where",
    "wheres",
    "which",
    "while",
    "who",
    "whos",
    "whom",
    "why",
    "whys",
    "with",
    "wont",
    "would",
    "wouldnt",
    "you",
    "youd",
    "youll",
    "youre",
    "youve",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "just",
    "also",
    "now",
    "like",
    "get",
    "got",
    "look",
    "see",
    "new",
    "one",
}


class MediaService:
    """Finds and downloads visual assets corresponding to narration sentences."""

    def __init__(
        self,
        storage_service: StorageService | None = None,
        cost_repo: CostRepository | None = None,
        pexels_api_key: str | None = None,
        giphy_api_key: str | None = None,
        media_cache_dir: Path | None = None,
        default_ratio: float | None = None,
    ) -> None:
        self.storage_service = storage_service or get_storage_service()
        self.cost_repo = cost_repo
        self.pexels_api_key = (
            pexels_api_key if pexels_api_key is not None else settings.pexels_api_key
        )
        self.giphy_api_key = giphy_api_key if giphy_api_key is not None else settings.giphy_api_key
        self.media_cache_dir = media_cache_dir or settings.media_cache_dir
        self.default_ratio = (
            default_ratio if default_ratio is not None else settings.default_media_type_ratio
        )
        self.inspector = MediaInspector()
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        public_media = settings.remotion_project_dir / "public" / "media"
        if not public_media.exists() and not public_media.is_symlink():
            try:
                public_media.parent.mkdir(parents=True, exist_ok=True)
                public_media.symlink_to(self.media_cache_dir.resolve(), target_is_directory=True)
            except Exception:
                pass

    def extract_keywords(self, text: str, max_keywords: int = 3) -> list[str]:
        """Extract 1 to 3 distinct search keywords from text removing punctuation and stop words."""
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower()
        tokens = cleaned.split()
        filtered = [t for t in tokens if t not in STOP_WORDS and len(t) > 2]

        if not filtered:
            # Fallback to tokens longer than 2 chars if all were stopwords
            filtered = [t for t in tokens if len(t) > 2]

        if not filtered:
            return ["technology"]

        seen: set[str] = set()
        unique_keywords: list[str] = []
        for word in filtered:
            if word not in seen:
                seen.add(word)
                unique_keywords.append(word)
            if len(unique_keywords) >= max_keywords:
                break

        return unique_keywords

    def group_captions_into_sentences(
        self,
        captions: list[WordCaption],
    ) -> list[dict[str, Any]]:
        """Group word-level captions into sentence segments based on punctuation and pauses."""
        if not captions:
            return []

        sentences: list[dict[str, Any]] = []
        current_words: list[WordCaption] = []

        for idx, word_cap in enumerate(captions):
            current_words.append(word_cap)
            word_str = word_cap.word.strip()

            has_terminal_punct = bool(re.search(r"[.!?]$", word_str))
            has_long_pause = False
            if idx < len(captions) - 1:
                gap = captions[idx + 1].start - word_cap.end
                if gap >= 0.75:
                    has_long_pause = True

            dur = current_words[-1].end - current_words[0].start
            exceeds_word_count = len(current_words) >= 12

            # Enforce minimum 1.8s duration to avoid flash frames
            if (has_terminal_punct and dur >= 1.8) or (has_long_pause and dur >= 1.5) or exceeds_word_count:
                sent_text = " ".join(w.word for w in current_words)
                sentences.append(
                    {
                        "start_time": round(current_words[0].start, 2),
                        "end_time": round(current_words[-1].end, 2),
                        "text": sent_text,
                    }
                )
                current_words = []

        if current_words:
            sent_text = " ".join(w.word for w in current_words)
            sentences.append(
                {
                    "start_time": round(current_words[0].start, 2),
                    "end_time": round(current_words[-1].end, 2),
                    "text": sent_text,
                }
            )

        return sentences

    def search_pexels(
        self,
        query: str,
        media_type: Literal["video", "image"] = "video",
        excluded_urls: set[str] | None = None,
    ) -> tuple[str, str] | None:
        """Search Pexels API for video or photo URL, filtering out excluded_urls."""
        if not self.pexels_api_key:
            return None

        headers = {"Authorization": self.pexels_api_key}

        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    url = f"https://api.pexels.com/videos/search?query={query}&per_page=15&orientation=portrait"
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        videos = data.get("videos", [])
                        for v in videos:
                            files = v.get("video_files", [])
                            if not files:
                                continue
                            best_file = files[0]
                            for f in files:
                                if f.get("quality") in ["sd", "hd"]:
                                    best_file = f
                                    break
                            link = best_file.get("link")
                            if not link:
                                continue
                            if excluded_urls and link in excluded_urls:
                                continue
                            return link, "mp4"

                # Fallback or photo search
                photo_url = f"https://api.pexels.com/v1/search?query={query}&per_page=15&orientation=portrait"
                resp = client.get(photo_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    photos = data.get("photos", [])
                    for p in photos:
                        src_dict = p.get("src", {})
                        src_url = src_dict.get("large") or src_dict.get("original")
                        if not src_url:
                            continue
                        if excluded_urls and src_url in excluded_urls:
                            continue
                        return src_url, "jpg"

        except Exception:
            return None

        return None

    def search_giphy(self, query: str) -> tuple[str, str] | None:
        """Search Giphy API for reaction meme GIF and return (source_url, file_extension)."""
        if not self.giphy_api_key:
            return None

        params = {
            "api_key": self.giphy_api_key,
            "q": query,
            "limit": 1,
            "rating": "pg-13",
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                url = "https://api.giphy.com/v1/gifs/search"
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    gifs = data.get("data", [])
                    if gifs and gifs[0].get("images"):
                        imgs = gifs[0]["images"]
                        gif_url = imgs.get("downsized_medium", {}).get("url") or imgs.get(
                            "original", {}
                        ).get("url")
                        if gif_url:
                            return gif_url, "gif"
        except Exception:
            return None

        return None

    def download_asset(self, url: str, destination_path: Path) -> tuple[bool, Path]:
        """Download remote asset to local destination path, transcoding GIFs to MP4 to prevent looping."""
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    destination_path.write_bytes(resp.content)

                    # Transcode GIF to non-looping MP4 video for clean Remotion playback
                    if destination_path.suffix.lower() == ".gif":
                        mp4_file = destination_path.with_suffix(".mp4")
                        try:
                            cmd = [
                                "ffmpeg",
                                "-y",
                                "-i",
                                str(destination_path),
                                "-movflags",
                                "faststart",
                                "-pix_fmt",
                                "yuv420p",
                                "-vf",
                                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                                str(mp4_file),
                            ]
                            subprocess.run(
                                cmd,
                                check=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            if mp4_file.exists() and mp4_file.stat().st_size > 0:
                                return True, mp4_file
                        except Exception:
                            pass

                    return True, destination_path
        except Exception:
            return False, destination_path
        return False, destination_path

    def process_media_for_job(
        self,
        job_id: int,
        captions: list[WordCaption],
        beats: list[dict[str, Any]] | None = None,
    ) -> list[SentenceMediaPlacement]:
        """Generate keywords, fetch assets with deduplication, GIF-freeze, and inspector gate."""
        sentences = self.group_captions_into_sentences(captions)
        if not sentences:
            return []

        beats_list = beats or []
        placements: list[SentenceMediaPlacement] = []
        used_urls: set[str] = set()

        for idx, sentence_info in enumerate(sentences):
            start_t = sentence_info["start_time"]
            end_t = sentence_info["end_time"]
            text = sentence_info["text"]
            lower_text = text.lower()

            keywords = self.extract_keywords(text, max_keywords=3)
            base_kw = keywords[0] if keywords else "technology"

            # Domain-anchored query mapping to prevent generic/meme mismatches
            if any(k in lower_text for k in ["jensen", "huang", "nvidia"]):
                query_str = "nvidia gpu semiconductor microchip artificial intelligence"
            elif any(k in lower_text for k in ["dario", "amodei", "anthropic", "openai", "sam altman"]):
                query_str = "artificial intelligence neural network futuristic data center"
            elif any(k in lower_text for k in ["brakes", "slow", "pace", "frontier", "police"]):
                query_str = "server room futuristic cyber security technology"
            elif any(k in lower_text for k in ["regulat", "treaties", "agreements", "democratic", "global"]):
                query_str = "global digital network connection artificial intelligence"
            elif any(k in lower_text for k in ["diary", "privacy", "secret", "evaluators", "trust"]):
                query_str = "cybersecurity digital data privacy matrix code"
            elif any(k in lower_text for k in ["server", "hardware", "chip", "semiconductor", "models"]):
                query_str = "data center glowing server rack technology"
            elif any(k in lower_text for k in ["robot", "agent", "agents", "autonomous", "superintelligence", "gods"]):
                query_str = "futuristic humanoid robot artificial intelligence"
            elif any(k in lower_text for k in ["code", "coding", "software", "developer"]):
                query_str = "programming code screen computer developer technology"
            elif any(k in lower_text for k in ["wifi", "wi-fi", "password", "passwords"]):
                query_str = "digital networking router cyber tech futuristic"
            else:
                query_str = f"artificial intelligence futuristic technology {base_kw}"

            chosen_placement: SentenceMediaPlacement | None = None

            if self.pexels_api_key:
                # Default to vertical video with deduplication across the video
                result = self.search_pexels(query_str, media_type="video", excluded_urls=used_urls)
                if not result:
                    result = self.search_pexels(
                        f"artificial intelligence technology {base_kw}",
                        media_type="video",
                        excluded_urls=used_urls,
                    )
                if not result:
                    result = self.search_pexels(
                        "artificial intelligence technology",
                        media_type="video",
                        excluded_urls=used_urls,
                    )
                if result:
                    source_url, ext = result
                    dest_file = self.media_cache_dir / f"job_{job_id}_sent_{idx}.{ext}"
                    ok, final_path = self.download_asset(source_url, dest_file)
                    if ok:
                        actual_type = "video" if final_path.suffix.lower() == ".mp4" else "image"
                        approved, _ = self.inspector.inspect_candidate(
                            sentence_text=text,
                            keywords=keywords,
                            media_path=final_path,
                            media_type=actual_type,
                        )
                        if approved:
                            used_urls.add(source_url)
                            chosen_placement = SentenceMediaPlacement(
                                sentence_index=idx,
                                start_time=start_t,
                                end_time=end_t,
                                keywords=keywords,
                                media_type=actual_type,
                                local_path=str(final_path.resolve()),
                                source_url=source_url,
                                provider="pexels",
                            )
                        else:
                            used_urls.add(source_url)

            if not chosen_placement and self.giphy_api_key:
                reaction_query = f"{base_kw} technology reaction"
                result = self.search_giphy(reaction_query)
                if not result:
                    result = self.search_giphy("technology reaction")
                if result:
                    source_url, ext = result
                    dest_file = self.media_cache_dir / f"job_{job_id}_sent_{idx}.{ext}"
                    ok, final_path = self.download_asset(source_url, dest_file)
                    if ok:
                        actual_type = "video" if final_path.suffix.lower() == ".mp4" else "image"
                        approved, _ = self.inspector.inspect_candidate(
                            sentence_text=text,
                            keywords=keywords,
                            media_path=final_path,
                            media_type=actual_type,
                        )
                        if approved:
                            used_urls.add(source_url)
                            chosen_placement = SentenceMediaPlacement(
                                sentence_index=idx,
                                start_time=start_t,
                                end_time=end_t,
                                keywords=keywords,
                                media_type=actual_type,
                                local_path=str(final_path.resolve()),
                                source_url=source_url,
                                provider="giphy",
                            )
                        else:
                            used_urls.add(source_url)

            # Graceful fallback when keys missing or search returned no results
            if not chosen_placement:
                chosen_placement = SentenceMediaPlacement(
                    sentence_index=idx,
                    start_time=start_t,
                    end_time=end_t,
                    keywords=keywords,
                    media_type="image",
                    local_path="",
                    source_url="",
                    provider="fallback",
                )

            placements.append(chosen_placement)

        # Continuous interval clamping: eliminate black gaps between consecutive clips
        for i in range(len(placements) - 1):
            placements[i].end_time = placements[i + 1].start_time
        if placements and captions:
            placements[-1].end_time = round(captions[-1].end, 2)

        if self.cost_repo:
            self.cost_repo.log_cost(
                CostLogCreate(
                    job_id=job_id,
                    stage="media_retrieval",
                    provider="pexels_giphy",
                    model="asset_search",
                    units=len(placements),
                    unit_type="placements",
                    cost_usd=0.0,
                )
            )

        return placements
