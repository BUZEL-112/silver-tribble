"""Unit tests for VisualDirectorService and scene staging directives."""

from src.models.schemas import VisualCategory, VisualCue
from src.services.media_router import MediaRouter
from src.services.visual_director_service import VisualDirectorService


def test_visual_director_fallback_known_entity() -> None:
    """Verify known entities are mapped to canonical editorial entities."""
    director = VisualDirectorService()
    cues = director.direct_visuals(
        sentences=["Dario Amodei delivered an unexpected speech on frontier model safety."]
    )
    assert len(cues) == 1
    cue = cues[0]
    assert cue.category == VisualCategory.EDITORIAL_ENTITY
    assert cue.entity_name == "Dario Amodei"
    assert cue.suggested_shot_type == "close_up"


def test_visual_director_fallback_code_or_data() -> None:
    """Verify security, sandbox, or code contexts are routed to terminal/code category."""
    director = VisualDirectorService()
    sentence = "The autonomous agent escaped the sandbox environment and altered bash permissions."
    cues = director.direct_visuals(sentences=[sentence])
    assert len(cues) == 1
    cue = cues[0]
    assert cue.category == VisualCategory.CODE_OR_DATA
    assert cue.graphic_overlay_type == "terminal"
    assert cue.generative_prompt is not None
    assert "terminal" in cue.generative_prompt.lower()


def test_visual_director_fallback_physical_broll() -> None:
    """Verify physical hardware is routed to concrete stock searches rather than 'technology'."""
    director = VisualDirectorService()
    cues = director.direct_visuals(
        sentences=["Thousands of semiconductor chips were inspected inside the manufacturing fab."]
    )
    assert len(cues) == 1
    cue = cues[0]
    assert cue.category == VisualCategory.PHYSICAL_BROLL
    assert cue.stock_search_query is not None
    assert "technology" not in cue.stock_search_query.lower()
    has_target = (
        "semiconductor" in cue.stock_search_query.lower()
        or "wafer" in cue.stock_search_query.lower()
    )
    assert has_target


def test_visual_director_fallback_conceptual_ai() -> None:
    """Verify abstract concepts without stock representations generate AI prompts."""
    director = VisualDirectorService()
    cues = director.direct_visuals(
        sentences=["Researchers discovered emergent multi-agent coordination during evaluations."]
    )
    assert len(cues) == 1
    cue = cues[0]
    assert cue.category == VisualCategory.CONCEPTUAL_AI
    assert cue.generative_prompt is not None
    assert "9:16" in cue.generative_prompt


def test_media_router_with_visual_cue() -> None:
    """Verify MediaRouter selects sources directly using VisualCue directives."""
    router = MediaRouter()

    # Case 1: Editorial entity cue
    entity_cue = VisualCue(
        sentence_index=0,
        category=VisualCategory.EDITORIAL_ENTITY,
        entity_name="Jensen Huang",
    )
    src, query = router.select_source("The keynote started.", visual_cue=entity_cue)
    assert src == "google_search"
    assert query == "Jensen Huang"

    # Case 2: Conceptual AI cue
    concept_cue = VisualCue(
        sentence_index=1,
        category=VisualCategory.CONCEPTUAL_AI,
        generative_prompt="A glowing neural matrix in dark studio lighting",
    )
    src, query = router.select_source("The weights converged.", visual_cue=concept_cue)
    assert src == "ai_generated"
    assert query == "A glowing neural matrix in dark studio lighting"

    # Case 3: Physical b-roll cue
    broll_cue = VisualCue(
        sentence_index=2,
        category=VisualCategory.PHYSICAL_BROLL,
        stock_search_query="server racks in modern datacenter",
    )
    src, query = router.select_source("The cluster came online.", visual_cue=broll_cue)
    assert src == "pexels_video"
    assert query == "server racks in modern datacenter"


def test_extract_core_visual_noun_no_technology_fallback() -> None:
    """Verify extract_core_visual_noun does not return 'technology' for arbitrary sentences."""
    router = MediaRouter()
    noun = router.extract_core_visual_noun(
        "Autonomous agents altered configurations without administrative authorization"
    )
    assert noun != "technology"
    assert len(noun) > 0
