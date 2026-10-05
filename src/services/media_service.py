import json
import re
import subprocess
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus

import httpx

from src.core.config import settings
from src.models.schemas import (
    CostLogCreate,
    SentenceMediaPlacement,
    WordCaption,
)
from src.repositories.asset_repository import AssetRepository
from src.repositories.cost_repository import CostRepository
from src.services.brand_card_service import BrandCardService
from src.services.image_search_service import ImageSearchService
from src.services.media_inspector import MediaInspector
from src.services.media_router import MediaRouter
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
        asset_repo: AssetRepository | None = None,
        pexels_api_key: str | None = None,
        pixabay_api_key: str | None = None,
        giphy_api_key: str | None = None,
        media_cache_dir: Path | None = None,
        default_ratio: float | None = None,
    ) -> None:
        self.storage_service = storage_service or get_storage_service()
        self.cost_repo = cost_repo
        self.asset_repo = asset_repo
        self.pexels_api_key = (
            pexels_api_key if pexels_api_key is not None else settings.pexels_api_key
        )
        self.pixabay_api_key = (
            pixabay_api_key if pixabay_api_key is not None else settings.pixabay_api_key
        )
        self.giphy_api_key = giphy_api_key if giphy_api_key is not None else settings.giphy_api_key
        self.media_cache_dir = media_cache_dir or settings.media_cache_dir
        self.default_ratio = (
            default_ratio if default_ratio is not None else settings.default_media_type_ratio
        )
        self.inspector = MediaInspector()
        self.image_search = ImageSearchService()
        self.brand_cards = BrandCardService()
        self.router = MediaRouter(
            storage_service=self.storage_service,
            cost_repo=self.cost_repo,
            asset_repo=self.asset_repo,
            inspector=self.inspector,
            image_search_service=self.image_search,
            brand_card_service=self.brand_cards,
            media_cache_dir=self.media_cache_dir,
        )
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
            if (
                (has_terminal_punct and dur >= 1.8)
                or (has_long_pause and dur >= 1.5)
                or exceeds_word_count
            ):
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
        aspect_ratio: str = "9:16",
    ) -> tuple[str, str] | None:
        """Search Pexels API for video or photo URL, filtering out excluded_urls."""
        if not self.pexels_api_key:
            return None

        headers = {"Authorization": self.pexels_api_key}
        orientation = "portrait" if aspect_ratio == "9:16" else "landscape"

        # Sanitize and condense query into clean keywords
        clean_words = [w for w in re.findall(r"[a-zA-Z0-9]+", query) if w.lower() not in STOP_WORDS]
        effective_query = " ".join(clean_words[:4]) if len(clean_words) >= 2 else query

        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    url = f"https://api.pexels.com/videos/search?query={effective_query}&per_page=15&orientation={orientation}"
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
                photo_url = f"https://api.pexels.com/v1/search?query={effective_query}&per_page=15&orientation={orientation}"
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

    def search_pexels_candidates(
        self,
        query: str,
        media_type: Literal["video", "image"] = "video",
        limit: int = 12,
        aspect_ratio: str = "9:16",
    ) -> list[dict[str, Any]]:
        """Search Pexels API and return multiple candidate items with preview URLs."""
        if not self.pexels_api_key or not query.strip():
            return []

        headers = {"Authorization": self.pexels_api_key}
        orientation = "portrait" if aspect_ratio == "9:16" else "landscape"
        clean_words = [w for w in re.findall(r"[a-zA-Z0-9]+", query) if w.lower() not in STOP_WORDS]
        effective_query = " ".join(clean_words[:4]) if len(clean_words) >= 2 else query

        candidates: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    url = (
                        f"https://api.pexels.com/videos/search?query={effective_query}"
                        f"&per_page={limit}&orientation={orientation}"
                    )
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
                            candidates.append(
                                {
                                    "id": str(v.get("id", "")),
                                    "title": f"Pexels Video {v.get('id', '')}",
                                    "preview_url": v.get("image", ""),
                                    "source_url": link,
                                    "provider": "pexels",
                                    "media_type": "video",
                                    "width": v.get("width"),
                                    "height": v.get("height"),
                                    "duration": v.get("duration", 0),
                                }
                            )
                else:
                    photo_url = (
                        f"https://api.pexels.com/v1/search?query={effective_query}"
                        f"&per_page={limit}&orientation={orientation}"
                    )
                    resp = client.get(photo_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        photos = data.get("photos", [])
                        for p in photos:
                            src_dict = p.get("src", {})
                            preview_url = src_dict.get("medium") or src_dict.get("tiny") or ""
                            source_url = src_dict.get("large") or src_dict.get("original") or ""
                            if not source_url:
                                continue
                            candidates.append(
                                {
                                    "id": str(p.get("id", "")),
                                    "title": p.get("alt") or f"Pexels Photo {p.get('id', '')}",
                                    "preview_url": preview_url,
                                    "source_url": source_url,
                                    "provider": "pexels",
                                    "media_type": "image",
                                    "width": p.get("width"),
                                    "height": p.get("height"),
                                    "duration": 0,
                                }
                            )
        except Exception:
            return []
        return candidates

    def search_pixabay(
        self,
        query: str,
        media_type: Literal["video", "image"] = "video",
        excluded_urls: set[str] | None = None,
        aspect_ratio: str = "9:16",
    ) -> tuple[str, str] | None:
        """Search Pixabay API for stock video or photo URL, filtering out excluded_urls."""
        if not self.pixabay_api_key:
            return None

        clean_words = [w for w in re.findall(r"[a-zA-Z0-9]+", query) if w.lower() not in STOP_WORDS]
        effective_query = "+".join(clean_words[:3]) if clean_words else query
        orientation = "vertical" if aspect_ratio == "9:16" else "horizontal"

        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    url = (
                        f"https://pixabay.com/api/videos/?key={self.pixabay_api_key}"
                        f"&q={effective_query}&orientation={orientation}&per_page=10"
                    )
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = data.get("hits", [])
                        for hit in hits:
                            videos = hit.get("videos", {})
                            for res_key in ["medium", "large", "small", "tiny"]:
                                if res_key in videos and videos[res_key].get("url"):
                                    v_url = videos[res_key]["url"]
                                    if excluded_urls and v_url in excluded_urls:
                                        continue
                                    return v_url, "mp4"

                # Photo search fallback
                img_url = (
                    f"https://pixabay.com/api/?key={self.pixabay_api_key}"
                    f"&q={effective_query}&image_type=photo&orientation={orientation}&per_page=10"
                )
                resp = client.get(img_url)
                if resp.status_code == 200:
                    data = resp.json()
                    hits = data.get("hits", [])
                    for hit in hits:
                        src_url = hit.get("largeImageURL") or hit.get("webformatURL")
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

        params: dict[str, str | int] = {
            "api_key": self.giphy_api_key or "",
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

    def search_giphy_candidates(
        self,
        query: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Search Giphy API for reaction meme GIFs and return multiple candidate items."""
        if not self.giphy_api_key or not query.strip():
            return []

        params: dict[str, str | int] = {
            "api_key": self.giphy_api_key or "",
            "q": query,
            "limit": limit,
            "rating": "pg-13",
        }

        candidates: list[dict[str, Any]] = []
        try:
            with httpx.Client(timeout=10.0) as client:
                url = "https://api.giphy.com/v1/gifs/search"
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    gifs = data.get("data", [])
                    for g in gifs:
                        imgs = g.get("images", {})
                        preview_url = (
                            imgs.get("fixed_height_small", {}).get("url")
                            or imgs.get("downsized_medium", {}).get("url")
                            or imgs.get("original", {}).get("url")
                        )
                        source_url = imgs.get("original", {}).get("url") or imgs.get(
                            "downsized_medium", {}
                        ).get("url")
                        if not preview_url or not source_url:
                            continue
                        candidates.append(
                            {
                                "id": str(g.get("id", "")),
                                "title": g.get("title") or "Giphy GIF",
                                "preview_url": preview_url,
                                "source_url": source_url,
                                "provider": "giphy",
                                "media_type": "gif",
                                "width": imgs.get("original", {}).get("width"),
                                "height": imgs.get("original", {}).get("height"),
                                "duration": 0,
                            }
                        )
        except Exception:
            return []
        return candidates

    def search_pixabay_candidates(
        self,
        query: str,
        media_type: Literal["video", "image"] = "video",
        limit: int = 12,
        aspect_ratio: str = "9:16",
    ) -> list[dict[str, Any]]:
        """Search Pixabay API and return candidate items with preview and source links."""
        if not self.pixabay_api_key or not query.strip():
            return []

        orientation = "vertical" if aspect_ratio == "9:16" else "horizontal"
        candidates: list[dict[str, Any]] = []

        try:
            with httpx.Client(timeout=10.0) as client:
                if media_type == "video":
                    limit_count = min(limit, 50)
                    encoded_q = quote_plus(query)
                    url = (
                        f"https://pixabay.com/api/videos/?key={self.pixabay_api_key}"
                        f"&q={encoded_q}&orientation={orientation}&per_page={limit_count}"
                    )
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = data.get("hits", [])
                        for h in hits:
                            videos = h.get("videos", {})
                            best_link = None
                            for k in ["large", "medium", "small", "tiny"]:
                                if k in videos and videos[k].get("url"):
                                    best_link = videos[k]["url"]
                                    break
                            if not best_link:
                                continue
                            picture_id = h.get("picture_id")
                            preview = (
                                f"https://i.vimeocdn.com/video/{picture_id}_640x360.jpg"
                                if picture_id
                                else best_link
                            )
                            candidates.append(
                                {
                                    "id": str(h.get("id")),
                                    "title": f"Pixabay Video {h.get('id')}",
                                    "preview_url": preview,
                                    "source_url": best_link,
                                    "provider": "pixabay",
                                    "media_type": "video",
                                    "width": videos.get("large", {}).get("width") or 1080,
                                    "height": videos.get("large", {}).get("height") or 1920,
                                    "duration": h.get("duration", 0),
                                }
                            )
                else:
                    limit_count = min(limit, 50)
                    encoded_q = quote_plus(query)
                    url = (
                        f"https://pixabay.com/api/?key={self.pixabay_api_key}"
                        f"&q={encoded_q}&image_type=photo&orientation={orientation}"
                        f"&per_page={limit_count}"
                    )
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        hits = data.get("hits", [])
                        for h in hits:
                            src = h.get("largeImageURL") or h.get("webformatURL")
                            prev = h.get("webformatURL") or h.get("previewURL")
                            if not src:
                                continue
                            candidates.append(
                                {
                                    "id": str(h.get("id")),
                                    "title": f"Pixabay Photo {h.get('tags') or h.get('id')}",
                                    "preview_url": prev,
                                    "source_url": src,
                                    "provider": "pixabay",
                                    "media_type": "image",
                                    "width": h.get("imageWidth"),
                                    "height": h.get("imageHeight"),
                                    "duration": 0,
                                }
                            )
        except Exception:
            return []
        return candidates

    def search_custom_candidates(
        self,
        provider_id: str,
        query: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Query custom registered HTTP endpoint and return candidate items."""
        cfg_item = next((c for c in settings.custom_providers if c.get("id") == provider_id), None)
        if not cfg_item:
            return []

        try:
            from src.models.schemas import CustomProviderConfig

            c = CustomProviderConfig.model_validate(cfg_item)
            headers: dict[str, str] = {}
            if c.auth_token:
                headers[c.auth_header_name] = c.auth_token

            with httpx.Client(timeout=12.0) as client:
                if c.mode == "openai_compatible":
                    resp = client.post(
                        c.endpoint_url,
                        json={"prompt": query, "n": 1, "size": "1024x1024"},
                        headers=headers,
                    )
                else:
                    if "{query}" in c.endpoint_url:
                        target_url = c.endpoint_url.replace("{query}", query)
                    else:
                        sep = "&" if "?" in c.endpoint_url else "?"
                        target_url = f"{c.endpoint_url}{sep}{c.query_param_name}={query}"
                    if c.http_method == "POST":
                        resp = client.post(target_url, json={"query": query}, headers=headers)
                    else:
                        resp = client.get(target_url, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    parts = re.split(r"\.|\\b", c.response_url_path.strip())
                    curr = data
                    for p in parts:
                        if not p:
                            continue
                        if isinstance(curr, dict) and p in curr:
                            curr = curr[p]
                        elif isinstance(curr, list):
                            try:
                                curr = curr[int(p)]
                            except Exception:
                                curr = None
                                break
                    if isinstance(curr, str) and curr.startswith(("http://", "https://")):
                        return [
                            {
                                "id": f"{c.id}_1",
                                "title": f"{c.name} result for '{query}'",
                                "preview_url": curr,
                                "source_url": curr,
                                "provider": c.id,
                                "media_type": c.media_type,
                                "width": 1080,
                                "height": 1920,
                                "duration": 0,
                            }
                        ]
        except Exception:
            return []
        return []

    def download_asset(self, url: str, destination_path: Path) -> tuple[bool, Path]:
        """Download remote asset to local path, transcoding GIFs to MP4 to prevent looping."""
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

    def generate_visual_query(
        self,
        sentence_text: str,
        beat_info: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
    ) -> tuple[str, list[str], Literal["video", "gif"]]:
        """Derive high-relevance visual search terms and media format for a sentence."""
        lower_sent = sentence_text.lower()
        extracted_kw = keywords or self.extract_keywords(sentence_text, max_keywords=3)

        # Check beat context
        beat_type = (beat_info or {}).get("beat_type", "context")
        visual_dir = (beat_info or {}).get("visual_direction", "").lower()

        # Check if beat or sentence warrants a reaction GIF / meme
        is_reaction = beat_type in ["skepticism", "reaction"] or any(
            p in lower_sent
            for p in [
                "spoiler alert",
                "good luck",
                "terrible business",
                "nobody ever",
                "having none of it",
                "panicking",
                "roller coaster",
            ]
        )

        if is_reaction and self.giphy_api_key:
            if any(p in lower_sent for p in ["skeptic", "having none of it", "terrible"]):
                return "skeptical eye roll reaction", extracted_kw, "gif"
            if any(p in lower_sent for p in ["panic", "alarm", "doomsday"]):
                return "shocked panic reaction", extracted_kw, "gif"
            if any(p in lower_sent for p in ["nobody ever", "good luck"]):
                return "confused facepalm reaction", extracted_kw, "gif"
            return "funny tech reaction", extracted_kw, "gif"

        # Check if visual_direction from beat contains concrete visual scenes
        if visual_dir:
            if any(k in visual_dir for k in ["server", "data center", "rack"]):
                return "data center glowing server rack", extracted_kw, "video"
            if any(k in visual_dir for k in ["chip", "semiconductor", "wafer"]):
                return "semiconductor microchip silicon wafer", extracted_kw, "video"
            if any(k in visual_dir for k in ["robot", "humanoid", "arm"]):
                return "humanoid robot technology", extracted_kw, "video"
            if any(k in visual_dir for k in ["code", "terminal", "typing", "screen"]):
                return "computer programming code screen", extracted_kw, "video"
            if any(k in visual_dir for k in ["headline", "glitch", "breaking"]):
                return "breaking news digital technology", extracted_kw, "video"
            if any(k in visual_dir for k in ["press", "conference", "podium", "interview"]):
                return "press conference microphones media", extracted_kw, "video"

        # Domain-anchored semantic matching for stock b-roll
        if any(
            k in lower_sent
            for k in ["jensen", "huang", "nvidia", "gpu", "blackwell", "rubin", "hopper"]
        ):
            return "nvidia gpu microchip semiconductor", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["dario", "amodei", "anthropic", "claude", "altman", "openai", "chatgpt"]
        ):
            return "artificial intelligence neural network data center", extracted_kw, "video"
        if any(
            k in lower_sent for k in ["server", "hardware", "infrastructure", "compute", "cluster"]
        ):
            return "data center glowing server room", extracted_kw, "video"
        if any(
            k in lower_sent for k in ["chip", "semiconductor", "silicon", "transistor", "nanometer"]
        ):
            return "semiconductor silicon chip circuit board", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["evaluator", "evaluators", "safety", "inspect", "audit", "security"]
        ):
            return "cybersecurity digital security server room", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["regulat", "treaties", "agreements", "democratic", "global", "treaty"]
        ):
            return "global digital network connection technology", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["robot", "agent", "agents", "autonomous", "superintelligence", "gods"]
        ):
            return "futuristic humanoid robot artificial intelligence", extracted_kw, "video"
        if any(k in lower_sent for k in ["code", "coding", "software", "developer", "engineer"]):
            return "software developer coding computer screen", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["slow", "brake", "brakes", "pause", "speed", "pace", "emergency"]
        ):
            return "cyber warning digital technology interface", extracted_kw, "video"
        if any(
            k in lower_sent
            for k in ["money", "billion", "billions", "venture", "market", "gold rush", "trillion"]
        ):
            return "silicon valley corporate tech meeting", extracted_kw, "video"
        if any(k in lower_sent for k in ["wifi", "wi-fi", "network", "internet", "cloud"]):
            return "digital cloud networking cyber tech", extracted_kw, "video"

        primary_kw = extracted_kw[0] if extracted_kw else "technology"
        return f"artificial intelligence {primary_kw}", extracted_kw, "video"

    def process_media_for_job(
        self,
        job_id: int,
        captions: list[WordCaption],
        beats: list[dict[str, Any]] | None = None,
        aspect_ratio: str = "9:16",
    ) -> list[SentenceMediaPlacement]:
        """Generate keywords, fetch assets with deduplication, GIF-freeze, and inspector gate."""
        sentences = self.group_captions_into_sentences(captions)
        if not sentences:
            return []

        beats_list = beats or []
        placements: list[SentenceMediaPlacement] = []
        used_urls: set[str] = set()
        total_sentences = len(sentences)

        for idx, sentence_info in enumerate(sentences):
            start_t = sentence_info["start_time"]
            end_t = sentence_info["end_time"]
            text = sentence_info["text"]

            matching_beat = None
            if beats_list:
                beat_idx = min(
                    len(beats_list) - 1,
                    int(idx / max(1, total_sentences) * len(beats_list)),
                )
                matching_beat = beats_list[beat_idx]

            placement = self.router.route_and_fetch(
                job_id=job_id,
                sentence_index=idx,
                sentence_text=text,
                start_time=start_t,
                end_time=end_t,
                beat_info=matching_beat,
                used_urls=used_urls,
                aspect_ratio=aspect_ratio,
                media_service_ref=self,
            )
            placements.append(placement)

        # Continuous interval clamping: eliminate black gaps between consecutive clips
        for i in range(len(placements) - 1):
            placements[i].end_time = placements[i + 1].start_time
        if placements and captions:
            placements[-1].end_time = round(captions[-1].end, 2)

        # Persist placements to disk
        self.save_job_placements(job_id, placements)

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

    def get_job_placements(self, job_id: int) -> list[SentenceMediaPlacement]:
        """Read saved sentence media placements for a given render job."""
        placements_file = self.media_cache_dir / f"placements_job_{job_id}.json"
        if not placements_file.exists():
            return []
        try:
            data = json.loads(placements_file.read_text(encoding="utf-8"))
            return [SentenceMediaPlacement.model_validate(item) for item in data]
        except Exception:
            return []

    def save_job_placements(self, job_id: int, placements: list[SentenceMediaPlacement]) -> Path:
        """Persist placements to disk and sync with existing render_props.json if present."""
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        placements_file = self.media_cache_dir / f"placements_job_{job_id}.json"
        placements_data = [p.model_dump() for p in placements]
        placements_file.write_text(json.dumps(placements_data, indent=2), encoding="utf-8")

        # Also update render_props if props file exists
        props_file = settings.storage_local_dir / "render_props" / f"props_job_{job_id}.json"
        if props_file.exists():
            try:
                props_dict = json.loads(props_file.read_text(encoding="utf-8"))
                props_dict["mediaPlacements"] = placements_data
                props_file.write_text(json.dumps(props_dict, indent=2), encoding="utf-8")
            except Exception:
                pass

        return placements_file

    def update_placement_media(
        self,
        job_id: int,
        sentence_index: int,
        new_media_path_or_url: str,
        new_query: str | None = None,
        new_media_type: Literal["video", "image", "gif"] | None = None,
        provider: Literal[
            "pexels",
            "pixabay",
            "giphy",
            "google_search",
            "brand_card",
            "flux_generation",
            "ai_generated",
            "asset_library",
            "fallback",
            "custom",
        ] = "custom",
    ) -> SentenceMediaPlacement:
        """Replace media asset for a specific sentence index by path or URL."""
        placements = self.get_job_placements(job_id)
        if not placements:
            raise ValueError(f"No placements found for job {job_id}")

        target_idx = None
        for i, p in enumerate(placements):
            if p.sentence_index == sentence_index:
                target_idx = i
                break

        if target_idx is None:
            raise ValueError(
                f"Sentence index {sentence_index} not found in placements for job {job_id}"
            )

        resolved_path = ""
        resolved_url = new_media_path_or_url
        is_url = new_media_path_or_url.startswith(("http://", "https://"))

        if is_url:
            ext = "mp4"
            if ".gif" in new_media_path_or_url.lower():
                ext = "gif"
            elif any(e in new_media_path_or_url.lower() for e in [".jpg", ".jpeg"]):
                ext = "jpg"
            elif ".png" in new_media_path_or_url.lower():
                ext = "png"
            dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_custom.{ext}"
            ok, final_path = self.download_asset(new_media_path_or_url, dest)
            if not ok:
                raise ValueError(f"Failed to download asset from {new_media_path_or_url}")
            resolved_path = str(final_path.resolve())
            resolved_url = new_media_path_or_url
        else:
            local_p = Path(new_media_path_or_url)
            if not local_p.is_absolute():
                local_p = Path.cwd() / local_p
            if not local_p.exists():
                raise FileNotFoundError(f"Local media file not found: {local_p}")
            dest = (
                self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_custom{local_p.suffix}"
            )
            if local_p.resolve() != dest.resolve():
                import shutil

                shutil.copy2(local_p, dest)
            resolved_path = str(dest.resolve())
            resolved_url = str(dest.resolve())

        # Determine media type
        p_path = Path(resolved_path)
        if new_media_type:
            inferred_type = new_media_type
        elif p_path.suffix.lower() == ".mp4":
            inferred_type = "video"
        elif p_path.suffix.lower() == ".gif":
            inferred_type = "gif"
        else:
            inferred_type = "image"

        placements[target_idx].local_path = resolved_path
        placements[target_idx].source_url = resolved_url
        placements[target_idx].media_type = inferred_type
        placements[target_idx].provider = provider
        if new_query:
            placements[target_idx].query = new_query

        self.save_job_placements(job_id, placements)
        return placements[target_idx]

    def search_and_replace_placement(
        self,
        job_id: int,
        sentence_index: int,
        query: str,
        provider: Literal["pexels", "giphy"] = "pexels",
        media_type: Literal["video", "image"] = "video",
        aspect_ratio: str = "9:16",
    ) -> SentenceMediaPlacement:
        """Search Pexels or Giphy with user query and replace media at sentence_index."""
        placements = self.get_job_placements(job_id)
        if not placements:
            raise ValueError(f"No placements found for job {job_id}")

        target_idx = None
        for i, p in enumerate(placements):
            if p.sentence_index == sentence_index:
                target_idx = i
                break

        if target_idx is None:
            raise ValueError(
                f"Sentence index {sentence_index} not found in placements for job {job_id}"
            )

        if provider == "pexels":
            res = self.search_pexels(query=query, media_type=media_type, aspect_ratio=aspect_ratio)
            if not res:
                raise ValueError(f"No Pexels {media_type} found for query '{query}'")
            source_url, ext = res
        elif provider == "giphy":
            res = self.search_giphy(query=query)
            if not res:
                raise ValueError(f"No Giphy GIF found for query '{query}'")
            source_url, ext = res
        elif provider == "google_search":
            res = self.image_search.search_image(query=query)
            if not res:
                raise ValueError(f"No Google/Web image found for query '{query}'")
            source_url, ext = res
        elif provider == "brand_card":
            dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_card.png"
            self.brand_cards.generate_card(query, dest)
            placements[target_idx].local_path = str(dest.resolve())
            placements[target_idx].source_url = ""
            placements[target_idx].media_type = "image"
            placements[target_idx].provider = "brand_card"
            placements[target_idx].query = query
            self.save_job_placements(job_id, placements)
            return placements[target_idx]
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}.{ext}"
        ok, final_path = self.download_asset(source_url, dest)
        if not ok:
            raise RuntimeError(f"Failed to download asset from {source_url}")

        actual_type: Literal["video", "image"] = (
            "video" if final_path.suffix.lower() == ".mp4" else "image"
        )
        placements[target_idx].local_path = str(final_path.resolve())
        placements[target_idx].source_url = source_url
        placements[target_idx].media_type = actual_type
        placements[target_idx].provider = provider
        placements[target_idx].query = query

        self.save_job_placements(job_id, placements)
        return placements[target_idx]
