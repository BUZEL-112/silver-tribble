"""Tests for RssService in src/services/rss_service.py.

Covers:
- clean_html: tag stripping, entity unescaping, boilerplate removal, whitespace
  collapse, empty/None-like inputs.
- parse_feed_date: published_parsed precedence, updated_parsed fallback, missing
  attributes.
- canonicalize_url: tracking-param removal, scheme/netloc lowercasing, trailing
  slash stripping, fragment removal, empty input, non-tracking param preservation.
- fetch_all_feeds: string feeds, dict feeds, missing-title/link skipping,
  per-feed exception isolation, all-feeds-fail, deduplication via canonicalize_url.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.rss_service import RssService

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_entry(
    title: str = "Test Title",
    link: str = "https://example.com/article",
    summary: str = "",
    published_parsed: tuple[int, ...] | None = None,
    updated_parsed: tuple[int, ...] | None = None,
    **extra: Any,
) -> SimpleNamespace:
    """Build a fake feedparser entry namespace."""
    ns: dict[str, Any] = {
        "title": title,
        "link": link,
        "summary": summary,
    }
    if published_parsed is not None:
        ns["published_parsed"] = published_parsed
    if updated_parsed is not None:
        ns["updated_parsed"] = updated_parsed
    ns.update(extra)
    return SimpleNamespace(**ns)


def _make_feed(entries: list[SimpleNamespace]) -> MagicMock:
    """Build a fake feedparser result object."""
    feed = MagicMock()
    feed.entries = entries
    return feed


# ---------------------------------------------------------------------------
# clean_html
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_html_strips_html_tags_returns_plain_text() -> None:
    svc = RssService(feeds=[])

    result = svc.clean_html("<p>Hello <b>world</b></p>")

    assert result == "Hello world"


@pytest.mark.unit
def test_clean_html_unescapes_html_entities() -> None:
    svc = RssService(feeds=[])

    result = svc.clean_html("&amp; &quot;quoted&quot; &#39;single&#39;")

    assert "&amp;" not in result
    assert result == "& \"quoted\" 'single'"


@pytest.mark.unit
def test_clean_html_removes_newsletter_boilerplate() -> None:
    svc = RssService(feeds=[])
    raw = "Great article. This story appeared in the AI newsletter."

    result = svc.clean_html(raw)

    assert "newsletter" not in result.lower()


@pytest.mark.unit
def test_clean_html_removes_sign_up_boilerplate() -> None:
    svc = RssService(feeds=[])
    raw = "Breaking news. Sign up for our weekly digest."

    result = svc.clean_html(raw)

    assert "sign up" not in result.lower()


@pytest.mark.unit
def test_clean_html_removes_subscribe_boilerplate() -> None:
    svc = RssService(feeds=[])
    raw = "Interesting. Subscribe to our newsletter."

    result = svc.clean_html(raw)

    assert "subscribe" not in result.lower()


@pytest.mark.unit
def test_clean_html_removes_read_more_boilerplate() -> None:
    svc = RssService(feeds=[])
    raw = "Short preview. Read more at example.com."

    result = svc.clean_html(raw)

    assert "read more" not in result.lower()


@pytest.mark.unit
def test_clean_html_removes_follow_us_boilerplate() -> None:
    svc = RssService(feeds=[])
    raw = "Content here. Follow us on Twitter."

    result = svc.clean_html(raw)

    assert "follow us" not in result.lower()


@pytest.mark.unit
def test_clean_html_removes_ellipsis_bracket_pattern() -> None:
    svc = RssService(feeds=[])
    raw = "Article text [...]"

    result = svc.clean_html(raw)

    assert "[...]" not in result


@pytest.mark.unit
def test_clean_html_removes_unicode_ellipsis_bracket_pattern() -> None:
    svc = RssService(feeds=[])
    raw = "Article text [\u2026]"

    result = svc.clean_html(raw)

    assert "[\u2026]" not in result


@pytest.mark.unit
def test_clean_html_empty_string_returns_empty() -> None:
    svc = RssService(feeds=[])

    result = svc.clean_html("")

    assert result == ""


@pytest.mark.unit
def test_clean_html_whitespace_only_string_returns_empty() -> None:
    svc = RssService(feeds=[])

    result = svc.clean_html("   ")

    assert result == ""


@pytest.mark.unit
def test_clean_html_condenses_internal_whitespace() -> None:
    svc = RssService(feeds=[])
    raw = "word1   \n\t  word2"

    result = svc.clean_html(raw)

    assert "  " not in result
    assert result == "word1 word2"


# ---------------------------------------------------------------------------
# parse_feed_date
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_feed_date_returns_datetime_from_published_parsed() -> None:
    svc = RssService(feeds=[])
    ts = time.gmtime(0)
    entry = _make_entry(published_parsed=ts)

    result = svc.parse_feed_date(entry)  # type: ignore[arg-type]

    assert result is not None
    assert result.year == 1970


@pytest.mark.unit
def test_parse_feed_date_falls_back_to_updated_parsed_when_published_absent() -> None:
    svc = RssService(feeds=[])
    ts = time.gmtime(3600)
    entry = _make_entry(updated_parsed=ts)

    result = svc.parse_feed_date(entry)  # type: ignore[arg-type]

    assert result is not None
    assert result.year == 1970


@pytest.mark.unit
def test_parse_feed_date_returns_none_when_no_date_attributes_exist() -> None:
    svc = RssService(feeds=[])
    entry = SimpleNamespace(title="No date")

    result = svc.parse_feed_date(entry)  # type: ignore[arg-type]

    assert result is None


@pytest.mark.unit
def test_parse_feed_date_published_parsed_takes_precedence_over_updated() -> None:
    svc = RssService(feeds=[])
    pub_ts = time.gmtime(0)
    upd_ts = time.gmtime(86400)
    entry = _make_entry(published_parsed=pub_ts, updated_parsed=upd_ts)

    result = svc.parse_feed_date(entry)  # type: ignore[arg-type]

    assert result is not None
    assert result.year == 1970
    assert result.month == 1
    assert result.day == 1


# ---------------------------------------------------------------------------
# canonicalize_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_canonicalize_url_strips_utm_source() -> None:
    url = "https://example.com/article?utm_source=twitter&id=42"

    result = RssService.canonicalize_url(url)

    assert "utm_source" not in result
    assert "id=42" in result


@pytest.mark.unit
def test_canonicalize_url_strips_utm_medium() -> None:
    url = "https://example.com/article?utm_medium=social"

    result = RssService.canonicalize_url(url)

    assert "utm_medium" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_utm_campaign() -> None:
    url = "https://example.com/article?utm_campaign=launch"

    result = RssService.canonicalize_url(url)

    assert "utm_campaign" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_fbclid() -> None:
    url = "https://example.com/article?fbclid=abc123"

    result = RssService.canonicalize_url(url)

    assert "fbclid" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_gclid() -> None:
    url = "https://example.com/article?gclid=def456"

    result = RssService.canonicalize_url(url)

    assert "gclid" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_ref_param() -> None:
    url = "https://example.com/article?ref=homepage"

    result = RssService.canonicalize_url(url)

    assert "ref=" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_source_param() -> None:
    url = "https://example.com/article?source=rss"

    result = RssService.canonicalize_url(url)

    assert "source=" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_rss_param() -> None:
    url = "https://example.com/article?rss=1"

    result = RssService.canonicalize_url(url)

    assert "rss=" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_feed_param() -> None:
    url = "https://example.com/article?feed=atom"

    result = RssService.canonicalize_url(url)

    assert "feed=" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_mc_cid_param() -> None:
    url = "https://example.com/article?mc_cid=abc"

    result = RssService.canonicalize_url(url)

    assert "mc_cid" not in result


@pytest.mark.unit
def test_canonicalize_url_strips_mc_eid_param() -> None:
    url = "https://example.com/article?mc_eid=xyz"

    result = RssService.canonicalize_url(url)

    assert "mc_eid" not in result


@pytest.mark.unit
def test_canonicalize_url_lowercases_scheme() -> None:
    url = "HTTPS://Example.COM/article"

    result = RssService.canonicalize_url(url)

    assert result.startswith("https://example.com/")


@pytest.mark.unit
def test_canonicalize_url_lowercases_netloc() -> None:
    url = "https://WWW.EXAMPLE.COM/article"

    result = RssService.canonicalize_url(url)

    assert "www.example.com" in result


@pytest.mark.unit
def test_canonicalize_url_strips_trailing_slash_from_path() -> None:
    url = "https://example.com/article/"

    result = RssService.canonicalize_url(url)

    assert result == "https://example.com/article"


@pytest.mark.unit
def test_canonicalize_url_preserves_root_slash() -> None:
    url = "https://example.com/"

    result = RssService.canonicalize_url(url)

    assert result == "https://example.com/"


@pytest.mark.unit
def test_canonicalize_url_strips_fragment() -> None:
    url = "https://example.com/article#section-2"

    result = RssService.canonicalize_url(url)

    assert "#" not in result
    assert "section-2" not in result


@pytest.mark.unit
def test_canonicalize_url_returns_empty_string_for_empty_input() -> None:
    result = RssService.canonicalize_url("")

    assert result == ""


@pytest.mark.unit
def test_canonicalize_url_preserves_non_tracking_query_params() -> None:
    url = "https://example.com/article?page=2&sort=asc"

    result = RssService.canonicalize_url(url)

    assert "page=2" in result
    assert "sort=asc" in result


# ---------------------------------------------------------------------------
# fetch_all_feeds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fetch_all_feeds_with_string_feeds_returns_feed_items(mocker: Any) -> None:
    entry = _make_entry(title="AI Breakthrough", link="https://example.com/ai")
    mock_parsed = _make_feed([entry])
    mocker.patch("feedparser.parse", return_value=mock_parsed)
    svc = RssService(feeds=["https://example.com/feed.rss"])

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].title == "AI Breakthrough"
    assert result[0].source == "example.com"


@pytest.mark.unit
def test_fetch_all_feeds_with_dict_feeds_uses_name_and_url(mocker: Any) -> None:
    entry = _make_entry(title="AI Update", link="https://techcrunch.com/ai-story")
    mock_parsed = _make_feed([entry])
    mocker.patch("feedparser.parse", return_value=mock_parsed)
    svc = RssService(feeds=[{"name": "TechCrunch AI", "url": "https://techcrunch.com/feed/"}])

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].source == "TechCrunch AI"


@pytest.mark.unit
def test_fetch_all_feeds_skips_entries_with_missing_title(mocker: Any) -> None:
    entry_no_title = _make_entry(title="", link="https://example.com/article")
    entry_good = _make_entry(title="Valid Article", link="https://example.com/valid")
    mocker.patch("feedparser.parse", return_value=_make_feed([entry_no_title, entry_good]))
    svc = RssService(feeds=["https://example.com/feed.rss"])

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].title == "Valid Article"


@pytest.mark.unit
def test_fetch_all_feeds_skips_entries_with_missing_link(mocker: Any) -> None:
    entry_no_link = _make_entry(title="No Link Article", link="")
    entry_good = _make_entry(title="Good Article", link="https://example.com/good")
    mocker.patch("feedparser.parse", return_value=_make_feed([entry_no_link, entry_good]))
    svc = RssService(feeds=["https://example.com/feed.rss"])

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].title == "Good Article"


@pytest.mark.unit
def test_fetch_all_feeds_continues_when_one_feed_raises(mocker: Any) -> None:
    entry = _make_entry(title="Second Feed Story", link="https://second.com/story")
    good_feed = _make_feed([entry])
    mocker.patch(
        "feedparser.parse",
        side_effect=[RuntimeError("network error"), good_feed],
    )
    svc = RssService(
        feeds=[
            "https://failing-feed.com/rss",
            "https://second.com/rss",
        ]
    )

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].title == "Second Feed Story"


@pytest.mark.unit
def test_fetch_all_feeds_returns_empty_list_when_all_feeds_fail(mocker: Any) -> None:
    mocker.patch("feedparser.parse", side_effect=RuntimeError("all down"))
    svc = RssService(feeds=["https://feed-a.com/rss", "https://feed-b.com/rss"])

    result = svc.fetch_all_feeds()

    assert result == []


@pytest.mark.unit
def test_fetch_all_feeds_canonicalizes_links_from_multiple_feeds(mocker: Any) -> None:
    shared_url = "https://example.com/shared-article?utm_source=twitter"
    entry_a = _make_entry(title="Story A", link=shared_url)
    entry_b = _make_entry(title="Story B", link="https://example.com/shared-article?utm_source=rss")
    feed_a = _make_feed([entry_a])
    feed_b = _make_feed([entry_b])
    mocker.patch("feedparser.parse", side_effect=[feed_a, feed_b])
    svc = RssService(
        feeds=[
            "https://feed-a.com/rss",
            "https://feed-b.com/rss",
        ]
    )

    result = svc.fetch_all_feeds()

    assert len(result) == 2
    assert result[0].link == "https://example.com/shared-article"
    assert result[1].link == "https://example.com/shared-article"


@pytest.mark.unit
def test_fetch_all_feeds_dict_feed_missing_name_uses_netloc(mocker: Any) -> None:
    entry = _make_entry(title="Nameless Feed Story", link="https://noname.com/story")
    mocker.patch("feedparser.parse", return_value=_make_feed([entry]))
    svc = RssService(feeds=[{"url": "https://noname.com/feed/"}])

    result = svc.fetch_all_feeds()

    assert len(result) == 1
    assert result[0].source == "noname.com"


@pytest.mark.unit
def test_fetch_all_feeds_cleans_summary_html(mocker: Any) -> None:
    entry = _make_entry(
        title="Story",
        link="https://example.com/s",
        summary="<p>Good content. Subscribe to our newsletter.</p>",
    )
    mocker.patch("feedparser.parse", return_value=_make_feed([entry]))
    svc = RssService(feeds=["https://example.com/rss"])

    result = svc.fetch_all_feeds()

    assert "<p>" not in result[0].summary
    assert "subscribe" not in result[0].summary.lower()
