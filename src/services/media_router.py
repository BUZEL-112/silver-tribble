"""Visual media router evaluating sentence context to route to Asset Library,
Google Search, Pexels, Pixabay, Giphy, FLUX, or Brand Cards.
"""

import re
from pathlib import Path
from typing import Any, Literal

import yaml

from src.core.config import settings
from src.models.schemas import SentenceMediaPlacement, VisualAssetCreate
from src.repositories.asset_repository import AssetRepository
from src.repositories.cost_repository import CostRepository
from src.services.brand_card_service import BrandCardService
from src.services.image_generation_service import ImageGenerationService
from src.services.image_search_service import ImageSearchService
from src.services.media_inspector import MediaInspector
from src.services.storage_service import StorageService, get_storage_service


class MediaRouter:
    """Intelligently routes sentence visual requirements across providers and the asset library."""

    # Concrete visual keywords prioritized for stock footage searches
    CONCRETE_VISUAL_MAP: dict[str, str] = {
        "datacenter": "datacenter",
        "data center": "datacenter",
        "server": "server room",
        "supercomputer": "supercomputer",
        "cluster": "server racks",
        "chip": "microchip",
        "microchip": "microchip",
        "semiconductor": "microchip",
        "silicon": "silicon wafer",
        "gpu": "computer processor",
        "processor": "processor",
        "robot arm": "robot arm",
        "robotic": "robot arm",
        "robotics": "robot arm",
        "robot": "robotics",
        "humanoid": "humanoid robot",
        "cybersecurity": "cybersecurity",
        "security": "digital security",
        "code": "software code screen",
        "programming": "programming screen",
        "developer": "software engineer",
        "engineer": "computer engineer",
        "algorithm": "data network",
        "network": "network cables",
        "cloud": "cloud computing server",
        "ai": "artificial intelligence computer",
    }

    def __init__(
        self,
        storage_service: StorageService | None = None,
        cost_repo: CostRepository | None = None,
        asset_repo: AssetRepository | None = None,
        inspector: MediaInspector | None = None,
        image_search_service: ImageSearchService | None = None,
        brand_card_service: BrandCardService | None = None,
        image_generation_service: ImageGenerationService | None = None,
        rules_path: str | Path | None = None,
        media_cache_dir: Path | None = None,
    ) -> None:
        self.storage = storage_service or get_storage_service()
        self.cost_repo = cost_repo
        self.asset_repo = asset_repo
        self.inspector = inspector or MediaInspector()
        self.image_search = image_search_service or ImageSearchService()
        self.brand_cards = brand_card_service or BrandCardService()
        self.image_gen = image_generation_service or ImageGenerationService()
        self.media_cache_dir = media_cache_dir or settings.media_cache_dir
        self.media_cache_dir.mkdir(parents=True, exist_ok=True)
        self.rules = self._load_rules(rules_path or settings.media_router_rules_file)

    def _load_rules(self, rules_path: str | Path) -> dict[str, Any]:
        """Load routing instructions and rules from YAML file."""
        p = Path(rules_path)
        if p.exists() and p.is_file():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def extract_core_visual_noun(self, text: str, beat_visual: str = "") -> str:
        """Derive concrete physical visual noun to avoid 0-result multi-word failures."""
        combined = f"{text} {beat_visual}".lower()
        for key, query in self.CONCRETE_VISUAL_MAP.items():
            if re.search(rf"\b{re.escape(key)}\b", combined):
                return query
        return "technology"

    def select_source(
        self,
        sentence_text: str,
        beat_info: dict[str, Any] | None = None,
    ) -> tuple[
        Literal[
            "google_search", "giphy", "pexels_video", "pexels_photo", "brand_card", "ai_generated"
        ],
        str,
    ]:
        """Determine primary visual provider and search query based on routing instructions."""
        lower_sent = sentence_text.lower()
        beat_type = (beat_info or {}).get("beat_type", "context")
        beat_emotion = (beat_info or {}).get("emotion", "neutral")
        visual_dir = (beat_info or {}).get("visual_direction", "").lower()

        # Instruction 1: Check for real-world named entities (people, models, companies)
        detected_brand = self.brand_cards.detect_brand(sentence_text)
        named_entities = [
            "dario amodei",
            "sam altman",
            "jensen huang",
            "demis hassabis",
            "mark zuckerberg",
            "satya nadella",
            "claude",
            "anthropic",
            "openai",
            "nvidia",
            "deepseek",
            "blackwell",
            "chatgpt",
            "gemini",
            "llama",
            "tsmc",
        ]
        has_named_entity = detected_brand is not None or any(
            e in lower_sent for e in named_entities
        )

        if has_named_entity:
            query = detected_brand or next(
                (e for e in named_entities if e in lower_sent), sentence_text[:30]
            )
            return "google_search", query

        # Instruction 2: Skepticism, humor, or dramatic reactions
        is_reaction = (
            beat_type in ["skepticism", "reaction"]
            or beat_emotion in ["skepticism", "humor"]
            or any(
                p in lower_sent
                for p in [
                    "spoiler alert",
                    "good luck",
                    "terrible business",
                    "nobody knows",
                    "rolling their eyes",
                    "skeptical",
                    "doubt",
                    "who knows",
                ]
            )
        )
        if is_reaction:
            query = (
                "skeptical eye roll"
                if "rolling" in lower_sent or "eyes" in lower_sent
                else "confused reaction"
            )
            return "giphy", query

        # Instruction 3: Abstract, futuristic, or hypothetical concepts for FLUX / AI generation
        is_futuristic_or_abstract = (
            beat_emotion in ["awe", "futuristic"]
            or any(
                w in lower_sent
                for w in [
                    "superintelligence",
                    "singularity",
                    "quantum core",
                    "cybernetic mind",
                    "alien intelligence",
                    "digital consciousness",
                ]
            )
            or any(
                w in visual_dir
                for w in [
                    "futuristic quantum core",
                    "superintelligence brain",
                    "abstract neural matrix",
                    "digital singularity",
                ]
            )
        )
        if is_futuristic_or_abstract:
            gen_prompt = visual_dir or sentence_text[:80]
            return "ai_generated", gen_prompt

        # Instruction 4: General technical infrastructure / physical hardware
        core_noun = self.extract_core_visual_noun(sentence_text, visual_dir)
        return "pexels_video", core_noun

    def route_and_fetch(
        self,
        job_id: int,
        sentence_index: int,
        sentence_text: str,
        start_time: float,
        end_time: float,
        beat_info: dict[str, Any] | None,
        used_urls: set[str],
        aspect_ratio: str = "9:16",
        media_service_ref: Any = None,
    ) -> SentenceMediaPlacement:
        """Route sentence through prioritized visual sources and multimodal gate."""
        primary_source, initial_query = self.select_source(sentence_text, beat_info)
        core_noun = self.extract_core_visual_noun(
            sentence_text, (beat_info or {}).get("visual_direction", "")
        )
        beat_emotion = (beat_info or {}).get("emotion", "neutral")
        beat_shot_type = (beat_info or {}).get("shot_type", "medium")

        # ----------------------------------------------------------------------
        # Strategy 0: Reusable Visual Asset Library Lookup
        # ----------------------------------------------------------------------
        if self.asset_repo:
            existing_asset = self.asset_repo.find_matching_asset(
                query=core_noun,
                emotion=beat_emotion,
                aspect_ratio=aspect_ratio,
                excluded_paths={u for u in used_urls if "/" in u},
            )
            if existing_asset:
                self.asset_repo.increment_usage(existing_asset.id)
                used_urls.add(existing_asset.local_path)
                return SentenceMediaPlacement(
                    sentence_index=sentence_index,
                    start_time=start_time,
                    end_time=end_time,
                    keywords=[core_noun],
                    media_type=existing_asset.media_type,  # type: ignore[arg-type]
                    local_path=existing_asset.local_path,
                    source_url=existing_asset.source_url or "",
                    provider="asset_library",
                    text=sentence_text,
                    query=core_noun,
                    emotion=beat_emotion,
                    shot_type=beat_shot_type,
                )

        # ----------------------------------------------------------------------
        # Strategy 1: Google Image / Wikimedia Search for Named Entities
        # ----------------------------------------------------------------------
        if primary_source == "google_search":
            search_query = initial_query
            img_res = self.image_search.search_image(search_query, excluded_urls=used_urls)
            if img_res:
                src_url, ext = img_res
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}.{ext}"
                ok, final_path = self._download(src_url, dest, media_service_ref)
                if ok:
                    approved, reason = self.inspector.inspect_candidate(
                        sentence_text=sentence_text,
                        keywords=[search_query],
                        media_path=final_path,
                        media_type="image",
                    )
                    if approved:
                        used_urls.add(src_url)
                        self._index_asset(
                            source_url=src_url,
                            local_path=str(final_path.resolve()),
                            media_type="image",
                            provider="google_search",
                            query=search_query,
                            tags=[search_query],
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                            aspect_ratio=aspect_ratio,
                        )
                        return SentenceMediaPlacement(
                            sentence_index=sentence_index,
                            start_time=start_time,
                            end_time=end_time,
                            keywords=[search_query],
                            media_type="image",
                            local_path=str(final_path.resolve()),
                            source_url=src_url,
                            provider="google_search",
                            text=sentence_text,
                            query=search_query,
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                        )

            # Fallback 1b: If web photo missing or rejected, generate Tech Brand Card
            brand_key = self.brand_cards.detect_brand(sentence_text)
            if brand_key:
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_card.png"
                self.brand_cards.generate_card(
                    brand_key, dest, custom_subtitle="Official Tech Intelligence"
                )
                self._index_asset(
                    source_url="",
                    local_path=str(dest.resolve()),
                    media_type="image",
                    provider="brand_card",
                    query=brand_key,
                    tags=[brand_key],
                    emotion=beat_emotion,
                    shot_type=beat_shot_type,
                    aspect_ratio=aspect_ratio,
                )
                return SentenceMediaPlacement(
                    sentence_index=sentence_index,
                    start_time=start_time,
                    end_time=end_time,
                    keywords=[brand_key],
                    media_type="image",
                    local_path=str(dest.resolve()),
                    source_url="",
                    provider="brand_card",
                    text=sentence_text,
                    query=brand_key,
                    emotion=beat_emotion,
                    shot_type=beat_shot_type,
                )

        # ----------------------------------------------------------------------
        # Strategy 2: Giphy Reaction Meme GIFs
        # ----------------------------------------------------------------------
        if primary_source == "giphy" and media_service_ref and media_service_ref.giphy_api_key:
            gif_res = media_service_ref.search_giphy(initial_query)
            if not gif_res:
                gif_res = media_service_ref.search_giphy("skeptical reaction")
            if gif_res:
                src_url, ext = gif_res
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}.{ext}"
                ok, final_path = self._download(src_url, dest, media_service_ref)
                if ok:
                    approved, _ = self.inspector.inspect_candidate(
                        sentence_text=sentence_text,
                        keywords=[initial_query],
                        media_path=final_path,
                        media_type="image",
                    )
                    if approved:
                        used_urls.add(src_url)
                        self._index_asset(
                            source_url=src_url,
                            local_path=str(final_path.resolve()),
                            media_type="image",
                            provider="giphy",
                            query=initial_query,
                            tags=[initial_query],
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                            aspect_ratio=aspect_ratio,
                        )
                        return SentenceMediaPlacement(
                            sentence_index=sentence_index,
                            start_time=start_time,
                            end_time=end_time,
                            keywords=[initial_query],
                            media_type="image",
                            local_path=str(final_path.resolve()),
                            source_url=src_url,
                            provider="giphy",
                            text=sentence_text,
                            query=initial_query,
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                        )

        # ----------------------------------------------------------------------
        # Strategy 3: FLUX / Local AI Image Generation (for abstract or futuristic shots)
        # ----------------------------------------------------------------------
        if primary_source == "ai_generated":
            dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_flux.png"
            gen_prompt = initial_query or sentence_text
            ok, final_path = self.image_gen.generate_image(
                gen_prompt, dest, aspect_ratio=aspect_ratio
            )
            if ok:
                approved, _ = self.inspector.inspect_candidate(
                    sentence_text=sentence_text,
                    keywords=[core_noun],
                    media_path=final_path,
                    media_type="image",
                )
                if approved:
                    self._index_asset(
                        source_url="",
                        local_path=str(final_path.resolve()),
                        media_type="image",
                        provider="flux_generation",
                        query=core_noun,
                        tags=[core_noun, "ai_generated"],
                        emotion=beat_emotion,
                        shot_type=beat_shot_type,
                        aspect_ratio=aspect_ratio,
                    )
                    return SentenceMediaPlacement(
                        sentence_index=sentence_index,
                        start_time=start_time,
                        end_time=end_time,
                        keywords=[core_noun],
                        media_type="image",
                        local_path=str(final_path.resolve()),
                        source_url="",
                        provider="flux_generation",
                        text=sentence_text,
                        query=core_noun,
                        emotion=beat_emotion,
                        shot_type=beat_shot_type,
                    )

        # ----------------------------------------------------------------------
        # Strategy 4: Pexels Portrait Video
        # ----------------------------------------------------------------------
        if media_service_ref and getattr(media_service_ref, "pexels_api_key", None):
            vid_res = media_service_ref.search_pexels(
                query=core_noun,
                media_type="video",
                excluded_urls=used_urls,
                aspect_ratio=aspect_ratio,
            )
            if vid_res and isinstance(vid_res, (tuple, list)) and len(vid_res) == 2:
                src_url, ext = vid_res
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}.{ext}"
                ok, final_path = self._download(src_url, dest, media_service_ref)
                if ok:
                    approved, _ = self.inspector.inspect_candidate(
                        sentence_text=sentence_text,
                        keywords=[core_noun],
                        media_path=final_path,
                        media_type="video",
                    )
                    if approved:
                        used_urls.add(src_url)
                        self._index_asset(
                            source_url=src_url,
                            local_path=str(final_path.resolve()),
                            media_type="video",
                            provider="pexels",
                            query=core_noun,
                            tags=[core_noun],
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                            aspect_ratio=aspect_ratio,
                        )
                        return SentenceMediaPlacement(
                            sentence_index=sentence_index,
                            start_time=start_time,
                            end_time=end_time,
                            keywords=[core_noun],
                            media_type="video",
                            local_path=str(final_path.resolve()),
                            source_url=src_url,
                            provider="pexels",
                            text=sentence_text,
                            query=core_noun,
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                        )

        # ----------------------------------------------------------------------
        # Strategy 5: Pexels High-Res Photo Fallback
        # ----------------------------------------------------------------------
        if media_service_ref and getattr(media_service_ref, "pexels_api_key", None):
            photo_res = media_service_ref.search_pexels(
                query=core_noun,
                media_type="image",
                excluded_urls=used_urls,
                aspect_ratio=aspect_ratio,
            )
            if photo_res and isinstance(photo_res, (tuple, list)) and len(photo_res) == 2:
                src_url, ext = photo_res
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}.{ext}"
                ok, final_path = self._download(src_url, dest, media_service_ref)
                if ok:
                    approved, _ = self.inspector.inspect_candidate(
                        sentence_text=sentence_text,
                        keywords=[core_noun],
                        media_path=final_path,
                        media_type="image",
                    )
                    if approved:
                        used_urls.add(src_url)
                        self._index_asset(
                            source_url=src_url,
                            local_path=str(final_path.resolve()),
                            media_type="image",
                            provider="pexels",
                            query=core_noun,
                            tags=[core_noun],
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                            aspect_ratio=aspect_ratio,
                        )
                        return SentenceMediaPlacement(
                            sentence_index=sentence_index,
                            start_time=start_time,
                            end_time=end_time,
                            keywords=[core_noun],
                            media_type="image",
                            local_path=str(final_path.resolve()),
                            source_url=src_url,
                            provider="pexels",
                            text=sentence_text,
                            query=core_noun,
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                        )

        # ----------------------------------------------------------------------
        # Strategy 6: Pixabay Portrait Video & Photo Fallback
        # ----------------------------------------------------------------------
        if (
            media_service_ref
            and hasattr(media_service_ref, "search_pixabay")
            and isinstance(getattr(media_service_ref, "pixabay_api_key", None), str)
            and media_service_ref.pixabay_api_key
        ):
            pix_vid = media_service_ref.search_pixabay(
                query=core_noun,
                media_type="video",
                excluded_urls=used_urls,
                aspect_ratio=aspect_ratio,
            )
            if pix_vid and isinstance(pix_vid, (tuple, list)) and len(pix_vid) == 2:
                src_url, ext = pix_vid
                dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_pixabay.{ext}"
                ok, final_path = self._download(src_url, dest, media_service_ref)
                if ok:
                    approved, _ = self.inspector.inspect_candidate(
                        sentence_text=sentence_text,
                        keywords=[core_noun],
                        media_path=final_path,
                        media_type="video",
                    )
                    if approved:
                        used_urls.add(src_url)
                        self._index_asset(
                            source_url=src_url,
                            local_path=str(final_path.resolve()),
                            media_type="video",
                            provider="pixabay",
                            query=core_noun,
                            tags=[core_noun],
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                            aspect_ratio=aspect_ratio,
                        )
                        return SentenceMediaPlacement(
                            sentence_index=sentence_index,
                            start_time=start_time,
                            end_time=end_time,
                            keywords=[core_noun],
                            media_type="video",
                            local_path=str(final_path.resolve()),
                            source_url=src_url,
                            provider="pixabay",
                            text=sentence_text,
                            query=core_noun,
                            emotion=beat_emotion,
                            shot_type=beat_shot_type,
                        )

        # ----------------------------------------------------------------------
        # Strategy 7: Brand Card if Brand Detected
        # ----------------------------------------------------------------------
        detected_brand = self.brand_cards.detect_brand(sentence_text)
        if detected_brand:
            dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_card.png"
            self.brand_cards.generate_card(
                detected_brand,
                dest,
                custom_subtitle=(beat_info or {}).get("visual_direction")
                or "Artificial Intelligence",
            )
            self._index_asset(
                source_url="",
                local_path=str(dest.resolve()),
                media_type="image",
                provider="brand_card",
                query=detected_brand,
                tags=[detected_brand],
                emotion=beat_emotion,
                shot_type=beat_shot_type,
                aspect_ratio=aspect_ratio,
            )
            return SentenceMediaPlacement(
                sentence_index=sentence_index,
                start_time=start_time,
                end_time=end_time,
                keywords=[detected_brand],
                media_type="image",
                local_path=str(dest.resolve()),
                source_url="",
                provider="brand_card",
                text=sentence_text,
                query=detected_brand,
                emotion=beat_emotion,
                shot_type=beat_shot_type,
            )

        # ----------------------------------------------------------------------
        # Strategy 8: FLUX Procedural Fallback if No Stock Available
        # ----------------------------------------------------------------------
        dest = self.media_cache_dir / f"job_{job_id}_sent_{sentence_index}_procedural.png"
        ok, final_path = self.image_gen.generate_image(core_noun, dest, aspect_ratio=aspect_ratio)
        if ok and final_path.exists():
            return SentenceMediaPlacement(
                sentence_index=sentence_index,
                start_time=start_time,
                end_time=end_time,
                keywords=[core_noun],
                media_type="image",
                local_path=str(final_path.resolve()),
                source_url="",
                provider="fallback",
                text=sentence_text,
                query=core_noun,
                emotion=beat_emotion,
                shot_type=beat_shot_type,
            )

        return SentenceMediaPlacement(
            sentence_index=sentence_index,
            start_time=start_time,
            end_time=end_time,
            keywords=[core_noun],
            media_type="image",
            local_path="",
            source_url="",
            provider="fallback",
            text=sentence_text,
            query=core_noun,
            emotion=beat_emotion,
            shot_type=beat_shot_type,
        )

    def _index_asset(
        self,
        source_url: str,
        local_path: str,
        media_type: Literal["video", "image", "gif"],
        provider: str,
        query: str,
        tags: list[str],
        emotion: str = "neutral",
        shot_type: str = "medium",
        aspect_ratio: str = "9:16",
    ) -> None:
        """Register newly retrieved or generated media into the visual asset library."""
        if not self.asset_repo:
            return
        try:
            asset_hash = AssetRepository.generate_asset_hash(source_url, local_path)
            self.asset_repo.record_asset(
                VisualAssetCreate(
                    asset_hash=asset_hash,
                    source_url=source_url or None,
                    local_path=local_path,
                    media_type=media_type,
                    provider=provider,
                    query=query,
                    tags=tags,
                    emotion_tags=[emotion] if emotion else [],
                    shot_type=shot_type,
                    aspect_ratio=aspect_ratio,
                    vlm_score=8.5,
                )
            )
        except Exception:
            pass

    def _download(self, url: str, dest: Path, media_service_ref: Any) -> tuple[bool, Path]:
        """Download asset using media service downloader or direct fallback."""
        if media_service_ref and hasattr(media_service_ref, "download_asset"):
            return media_service_ref.download_asset(url, dest)

        try:
            import httpx

            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200 and len(r.content) > 500:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(r.content)
                    return True, dest
        except Exception:
            return False, dest
        return False, dest
