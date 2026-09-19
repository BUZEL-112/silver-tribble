"""Sentence-level media search and asset retrieval service using Pexels and Giphy."""

import re
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
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)

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
                if gap >= 0.7:
                    has_long_pause = True

            exceeds_word_count = len(current_words) >= 10

            if has_terminal_punct or has_long_pause or exceeds_word_count:
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
    ) -> tuple[str, str] | None:
        """Search Pexels API for video or photo URL and return (source_url, file_extension)."""
        if not self.pexels_api_key:
            return None

        headers = {"Authorization": self.pexels_api_key}

        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    url = f"https://api.pexels.com/videos/search?query={query}&per_page=1&orientation=portrait"
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        videos = data.get("videos", [])
                        if videos and videos[0].get("video_files"):
                            # Pick medium or sd video file
                            files = videos[0]["video_files"]
                            best_file = files[0]
                            for f in files:
                                if f.get("quality") in ["sd", "hd"]:
                                    best_file = f
                                    break
                            return best_file["link"], "mp4"

                # Fallback or photo search
                photo_url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=portrait"
                resp = client.get(photo_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    photos = data.get("photos", [])
                    if photos and photos[0].get("src"):
                        src_dict = photos[0]["src"]
                        src_url = src_dict.get("large") or src_dict.get("original")
                        if src_url:
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

    def download_asset(self, url: str, destination_path: Path) -> bool:
        """Download remote asset to local destination path."""
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    destination_path.write_bytes(resp.content)
                    return True
        except Exception:
            return False
        return False

    def process_media_for_job(
        self,
        job_id: int,
        captions: list[WordCaption],
        beats: list[dict[str, Any]] | None = None,
    ) -> list[SentenceMediaPlacement]:
        """Generate keywords, fetch assets from Pexels/Giphy with graceful fallback."""
        sentences = self.group_captions_into_sentences(captions)
        if not sentences:
            return []

        beats_list = beats or []
        placements: list[SentenceMediaPlacement] = []

        for idx, sentence_info in enumerate(sentences):
            start_t = sentence_info["start_time"]
            end_t = sentence_info["end_time"]
            text = sentence_info["text"]

            keywords = self.extract_keywords(text, max_keywords=3)
            query_str = " ".join(keywords[:2]) if keywords else "ai technology"

            # Determine tone from matching beat
            active_beat = None
            for b in beats_list:
                b_start = b.get("start_time", 0.0)
                b_end = b.get("end_time", 9999.0)
                if start_t >= b_start and start_t < b_end:
                    active_beat = b
                    break

            beat_type = active_beat.get("beat_type", "context") if active_beat else "context"

            # Comedic / skepticism / exaggeration beats prefer Giphy GIFs
            prefer_giphy = beat_type in ["skepticism", "outro"] or (
                idx % 2 == 1 and bool(self.giphy_api_key)
            )

            chosen_placement: SentenceMediaPlacement | None = None

            if prefer_giphy and self.giphy_api_key:
                result = self.search_giphy(query_str)
                if result:
                    source_url, ext = result
                    dest_file = self.media_cache_dir / f"job_{job_id}_sent_{idx}.{ext}"
                    if self.download_asset(source_url, dest_file):
                        chosen_placement = SentenceMediaPlacement(
                            sentence_index=idx,
                            start_time=start_t,
                            end_time=end_t,
                            keywords=keywords,
                            media_type="gif",
                            local_path=str(dest_file.resolve()),
                            source_url=source_url,
                            provider="giphy",
                        )

            if not chosen_placement and self.pexels_api_key:
                m_type: Literal["video", "image"] = "video" if idx % 2 == 0 else "image"
                result = self.search_pexels(query_str, media_type=m_type)
                if result:
                    source_url, ext = result
                    dest_file = self.media_cache_dir / f"job_{job_id}_sent_{idx}.{ext}"
                    if self.download_asset(source_url, dest_file):
                        chosen_placement = SentenceMediaPlacement(
                            sentence_index=idx,
                            start_time=start_t,
                            end_time=end_t,
                            keywords=keywords,
                            media_type="video" if ext == "mp4" else "image",
                            local_path=str(dest_file.resolve()),
                            source_url=source_url,
                            provider="pexels",
                        )

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
