"""Image search service supporting Google Custom Search, SerpApi, Wikimedia, and Web images."""

import re
import urllib.parse
from typing import Any

import httpx

from src.core.config import settings


class ImageSearchService:
    """Searches and retrieves authentic images for named entities, tech figures, and news."""

    def __init__(
        self,
        google_api_key: str | None = None,
        google_cx: str | None = None,
        serpapi_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.google_api_key = google_api_key or getattr(settings, "google_cse_api_key", None)
        self.google_cx = google_cx or getattr(settings, "google_cse_cx", None)
        self.serpapi_key = serpapi_key or getattr(settings, "serpapi_api_key", None)
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

    def search_image(self, query: str, excluded_urls: set[str] | None = None) -> tuple[str, str] | None:
        """Search available image providers in prioritized order and return (url, extension)."""
        clean_query = query.strip()
        if not clean_query:
            return None

        # 1. Google Custom Search API if configured
        if self.google_api_key and self.google_cx:
            res = self._search_google_cse(clean_query, excluded_urls)
            if res:
                return res

        # 2. SerpApi if configured
        if self.serpapi_key:
            res = self._search_serpapi(clean_query, excluded_urls)
            if res:
                return res

        # 3. Wikimedia Commons for authentic portraits and logos
        res_wiki = self._search_wikimedia(clean_query, excluded_urls)
        if res_wiki:
            return res_wiki

        # 4. Direct Web Image Search
        res_web = self._search_web_images(clean_query, excluded_urls)
        if res_web:
            return res_web

        return None

    def _search_google_cse(
        self, query: str, excluded_urls: set[str] | None = None
    ) -> tuple[str, str] | None:
        """Query official Google Custom Search JSON API."""
        try:
            params = {
                "key": self.google_api_key,
                "cx": self.google_cx,
                "q": query,
                "searchType": "image",
                "num": 5,
                "imgSize": "large",
            }
            url = "https://customsearch.googleapis.com/customsearch/v1"
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    for item in items:
                        img_link = item.get("link")
                        if not img_link or (excluded_urls and img_link in excluded_urls):
                            continue
                        ext = self._infer_extension(img_link)
                        return img_link, ext
        except Exception:
            return None
        return None

    def _search_serpapi(
        self, query: str, excluded_urls: set[str] | None = None
    ) -> tuple[str, str] | None:
        """Query SerpApi Google Images engine."""
        try:
            params = {
                "engine": "google_images",
                "q": query,
                "api_key": self.serpapi_key,
                "num": 5,
            }
            url = "https://serpapi.com/search.json"
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("images_results", [])
                    for r in results:
                        img_url = r.get("original") or r.get("thumbnail")
                        if not img_url or (excluded_urls and img_url in excluded_urls):
                            continue
                        ext = self._infer_extension(img_url)
                        return img_url, ext
        except Exception:
            return None
        return None

    def _search_wikimedia(
        self, query: str, excluded_urls: set[str] | None = None
    ) -> tuple[str, str] | None:
        """Search Wikimedia Commons for public domain portraits and official company photos."""
        try:
            # Clean query for encyclopedia article lookup
            tokens = [w for w in query.split() if w.lower() not in ["image", "photo", "pic", "hd"]]
            title = " ".join(tokens[:3])
            url = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=query&titles={urllib.parse.quote(title)}"
                f"&prop=pageimages&format=json&pithumbsize=1280"
            )
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    pages = resp.json().get("query", {}).get("pages", {})
                    for _, page in pages.items():
                        thumb = page.get("thumbnail", {}).get("source")
                        if thumb:
                            if excluded_urls and thumb in excluded_urls:
                                continue
                            ext = self._infer_extension(thumb)
                            return thumb, ext
        except Exception:
            return None
        return None

    def _search_web_images(
        self, query: str, excluded_urls: set[str] | None = None
    ) -> tuple[str, str] | None:
        """Search web image index for direct high-resolution image URLs."""
        try:
            url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}&first=1"
            with httpx.Client(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    matches = re.findall(r'murl&quot;:&quot;(https?://[^&]+)&quot;', resp.text)
                    if not matches:
                        matches = re.findall(r'\"murl\":\"(https?://[^\"]+)\"', resp.text)
                    for link in matches:
                        if excluded_urls and link in excluded_urls:
                            continue
                        if any(bad in link.lower() for bad in [".svg", "logo", "icon", "avatar", "1x1"]):
                            continue
                        ext = self._infer_extension(link)
                        return link, ext
        except Exception:
            return None
        return None

    @staticmethod
    def _infer_extension(url: str) -> str:
        """Determine image file extension from URL string."""
        clean_url = url.split("?")[0].lower()
        if clean_url.endswith(".png"):
            return "png"
        if clean_url.endswith(".webp"):
            return "webp"
        if clean_url.endswith(".gif"):
            return "gif"
        return "jpg"
