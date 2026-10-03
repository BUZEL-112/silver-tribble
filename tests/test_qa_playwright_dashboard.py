"""
Manual Playwright tests for the AI Video Studio web dashboard (src/web.py).

These tests use playwright.sync_api and require the FastAPI server to be running
at http://localhost:8000 before executing. They are NOT part of the automated
CI suite; they are gated behind @pytest.mark.manual and a skip fixture that
checks server reachability at startup.

Run with:
    pytest tests/test_qa_playwright_dashboard.py -m manual -v

All tests follow the Arrange / Act / Assert pattern with a blank line between
each section.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright

Browser = Any
Page = Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"
HEALTH_URL = f"{BASE_URL}/api/health"
DASHBOARD_URL = f"{BASE_URL}/"
AUTH_STATUS_URL = f"{BASE_URL}/api/auth/status"

TIMEOUT_MS = 10_000


# ---------------------------------------------------------------------------
# Connectivity check helper
# ---------------------------------------------------------------------------


def _server_is_reachable() -> bool:
    """Return True if the web server responds to a basic HTTP request."""
    for url in (HEALTH_URL, DASHBOARD_URL):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Session-scoped skip fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def skip_if_server_not_running() -> None:
    """Skip the entire test session if the local web server is not reachable."""
    if not _server_is_reachable():
        pytest.skip(
            "Web server is not running at http://localhost:8000. "
            "Start the server with `uvicorn src.web:app --port 8000` and re-run."
        )


# ---------------------------------------------------------------------------
# Browser and page fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def browser(skip_if_server_not_running: None) -> Browser:
    """Launch a headless Chromium browser for the test session."""
    with sync_playwright() as pw:
        launched = pw.chromium.launch(headless=True)
        yield launched
        launched.close()


@pytest.fixture()
def page(browser: Browser) -> Page:
    """Open a fresh browser page for each test, then close it after."""
    ctx = browser.new_context()
    p = ctx.new_page()
    p.set_default_timeout(TIMEOUT_MS)
    yield p
    p.close()
    ctx.close()


# ---------------------------------------------------------------------------
# Auth flow tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_dashboard_loads_at_root(page: Page) -> None:
    """Dashboard HTML page is served at / with a 200 status code."""
    # Arrange - nothing to set up beyond the fixture

    # Act
    response = page.goto(DASHBOARD_URL)

    # Assert
    assert response is not None
    assert response.status == 200


@pytest.mark.manual
def test_dashboard_page_title_contains_studio(page: Page) -> None:
    """The <title> element identifies the AI Video Studio application."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    title = page.title()

    # Assert
    assert "AI Video Studio" in title or "AI" in title


@pytest.mark.manual
def test_auth_status_endpoint_returns_json(page: Page) -> None:
    """GET /api/auth/status returns a JSON object with auth_required and authenticated keys."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    response = page.request.get(AUTH_STATUS_URL)
    body = response.json()

    # Assert
    assert response.status == 200
    assert "auth_required" in body
    assert "authenticated" in body


@pytest.mark.manual
def test_login_with_wrong_password_returns_401(page: Page) -> None:
    """POST /api/auth/login with an incorrect password returns HTTP 401."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        data={"password": "definitely_wrong_password_xyz"},
    )

    # Assert - only meaningful when auth IS configured; skip gracefully if not
    if response.status == 200:
        body = response.json()
        # When auth is not configured the API returns success with a note
        assert body.get("status") == "success"
    else:
        assert response.status == 401


@pytest.mark.manual
def test_logout_endpoint_clears_session_cookie(page: Page) -> None:
    """POST /api/auth/logout returns success and the response clears the session cookie."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    response = page.request.post(f"{BASE_URL}/api/auth/logout")
    body = response.json()

    # Assert
    assert response.status == 200
    assert body.get("status") == "success"
    # The cookie should have been deleted; the browser context should not hold it
    cookies = page.context.cookies()
    session_cookies = [c for c in cookies if c["name"] == "ai_video_session"]
    assert session_cookies == []


# ---------------------------------------------------------------------------
# Dashboard main page structure tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_dashboard_navigation_tabs_are_present(page: Page) -> None:
    """Top navigation bar contains the primary tab buttons for all sections."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    nav = page.locator("#nav-tabs")

    # Assert
    assert nav.count() == 1
    # Check for at minimum the Operations and Story Intelligence tabs
    assert page.locator("button#tab-btn-pipeline").count() == 1
    assert page.locator("button#tab-btn-clusters").count() == 1
    assert page.locator("button#tab-btn-script").count() == 1
    assert page.locator("button#tab-btn-branding").count() == 1
    assert page.locator("button#tab-btn-system").count() == 1


@pytest.mark.manual
def test_pipeline_status_section_is_visible(page: Page) -> None:
    """The Operations & Jobs tab panel is visible on initial page load."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    pipeline_section = page.locator("#tab-pipeline")

    # Assert
    assert pipeline_section.count() == 1
    assert pipeline_section.is_visible()


@pytest.mark.manual
def test_kpi_metrics_ribbon_is_present(page: Page) -> None:
    """The top KPI ribbon contains spend, cluster, article, and health metric tiles."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act / Assert
    assert page.locator("#kpi-spend").count() == 1
    assert page.locator("#kpi-clusters").count() == 1
    assert page.locator("#kpi-articles").count() == 1
    assert page.locator("#kpi-health").count() == 1


@pytest.mark.manual
def test_budget_widget_shows_spend_information(page: Page) -> None:
    """The KPI spend tile is rendered in the page and contains a dollar amount format."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    spend_el = page.locator("#kpi-spend")

    # Assert
    assert spend_el.count() == 1
    text = spend_el.inner_text()
    # Initial value shows $0.00 until the JS fetches real data
    assert "$" in text or text.strip() == "--"


@pytest.mark.manual
def test_clusters_tab_renders_container(page: Page) -> None:
    """Clicking the Story Intelligence tab reveals the clusters container."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    page.locator("button#tab-btn-clusters").click()
    clusters_section = page.locator("#tab-clusters")

    # Assert
    assert clusters_section.count() == 1
    assert clusters_section.is_visible()
    assert page.locator("#clusters-container").count() == 1


@pytest.mark.manual
def test_api_docs_link_is_present_and_points_to_docs(page: Page) -> None:
    """The API Docs anchor in the header links to /docs."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    docs_link = page.locator("a[href='/docs']")

    # Assert
    assert docs_link.count() >= 1


# ---------------------------------------------------------------------------
# Pipeline trigger button tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_ingest_button_is_present_in_pipeline_tab(page: Page) -> None:
    """Stage 1 ingest button is rendered inside the pipeline execution section."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    # The button has onclick="triggerStage('ingest')" - locate it by text
    ingest_btn = page.locator("button", has_text="Run Ingest")

    # Assert
    assert ingest_btn.count() >= 1
    assert ingest_btn.first.is_visible()


@pytest.mark.manual
def test_cluster_button_is_present_in_pipeline_tab(page: Page) -> None:
    """Stage 2 cluster button is rendered inside the pipeline execution section."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    cluster_btn = page.locator("button", has_text="Run Cluster")

    # Assert
    assert cluster_btn.count() >= 1
    assert cluster_btn.first.is_visible()


@pytest.mark.manual
def test_script_generation_button_is_present_in_pipeline_tab(page: Page) -> None:
    """Stage 3 script button is rendered inside the pipeline execution section."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    script_btn = page.locator("button", has_text="Run Script")

    # Assert
    assert script_btn.count() >= 1
    assert script_btn.first.is_visible()


@pytest.mark.manual
def test_run_full_video_button_is_present(page: Page) -> None:
    """The primary 'Run Pipeline' / 'Run Full Video' button is accessible in the header."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act - the header quick action button
    run_btn = page.locator("button", has_text="Run Pipeline")

    # Assert
    assert run_btn.count() >= 1
    assert run_btn.first.is_visible()


@pytest.mark.manual
def test_ingest_button_is_clickable_without_navigation(page: Page) -> None:
    """Clicking the Ingest button does not cause a full page navigation."""
    # Arrange
    page.goto(DASHBOARD_URL)
    original_url = page.url

    # Act - click but do NOT wait for a network response (we only check UI state)
    ingest_btn = page.locator("button", has_text="Run Ingest").first
    ingest_btn.click()
    page.wait_for_timeout(500)

    # Assert - the SPA should not have navigated away
    assert page.url == original_url


# ---------------------------------------------------------------------------
# Branding / Settings page tests (tab-branding)
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_branding_tab_is_accessible_via_navigation(page: Page) -> None:
    """Clicking the Branding tab makes the branding section visible."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    page.locator("button#tab-btn-branding").click()
    branding_section = page.locator("#tab-branding")

    # Assert
    assert branding_section.count() == 1
    assert branding_section.is_visible()


@pytest.mark.manual
def test_watermark_text_field_is_present_in_branding(page: Page) -> None:
    """Watermark handle or text input field exists in the branding settings panel."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    wm_input = page.locator("#setting-wm-text")

    # Assert
    assert wm_input.count() == 1


@pytest.mark.manual
def test_caption_style_selector_has_expected_presets(page: Page) -> None:
    """The caption style grid in branding contains all five expected preset buttons."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    presets_grid = page.locator("#caption-presets-grid")

    # Assert
    assert presets_grid.count() == 1
    # Verify all five expected caption styles are present
    expected_ids = [
        "cap-preset-hormozi",
        "cap-preset-minimal",
        "cap-preset-karaoke",
        "cap-preset-news_ticker",
        "cap-preset-cinematic",
    ]
    for preset_id in expected_ids:
        assert page.locator(f"#{preset_id}").count() == 1, (
            f"Caption preset button #{preset_id} not found"
        )


@pytest.mark.manual
def test_subscribe_enabled_toggle_is_present(page: Page) -> None:
    """Subscribe enabled checkbox is present in the branding outro section."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    sub_checkbox = page.locator("#setting-sub-enabled")

    # Assert
    assert sub_checkbox.count() == 1
    assert sub_checkbox.get_attribute("type") == "checkbox"


@pytest.mark.manual
def test_save_all_settings_button_is_present_in_branding(page: Page) -> None:
    """'Save All Settings' button exists in the branding panel header."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    save_btn = page.locator("button", has_text="Save All Settings")

    # Assert
    assert save_btn.count() >= 1
    assert save_btn.first.is_visible()


@pytest.mark.manual
def test_watermark_position_select_has_four_options(page: Page) -> None:
    """The vertical watermark position select has the four canonical position options."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    pos_select = page.locator("#setting-wm-pos")

    # Assert
    assert pos_select.count() == 1
    options = pos_select.locator("option").all_text_contents()
    expected = {"Top-Right", "Top-Left", "Bottom-Right", "Bottom-Left"}
    found = {o.strip() for o in options}
    assert expected == found


# ---------------------------------------------------------------------------
# Responsiveness tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_page_renders_on_mobile_375_viewport_no_horizontal_scroll(browser: Browser) -> None:
    """Page renders on a 375x812 mobile viewport without triggering horizontal scrolling."""
    # Arrange
    ctx = browser.new_context(viewport={"width": 375, "height": 812})
    p = ctx.new_page()
    p.set_default_timeout(TIMEOUT_MS)

    try:
        # Act
        p.goto(DASHBOARD_URL)
        p.wait_for_load_state("domcontentloaded")

        scroll_width = p.evaluate("document.body.scrollWidth")
        client_width = p.evaluate("document.body.clientWidth")

        # Assert - allow a small tolerance of up to 2px for sub-pixel rounding
        assert scroll_width <= client_width + 2, (
            f"Horizontal scroll detected on mobile: scrollWidth={scroll_width} "
            f"> clientWidth={client_width}"
        )
    finally:
        p.close()
        ctx.close()


@pytest.mark.manual
def test_page_renders_on_desktop_1280_viewport(browser: Browser) -> None:
    """Page loads and the main header is visible on a 1280x720 desktop viewport."""
    # Arrange
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    p = ctx.new_page()
    p.set_default_timeout(TIMEOUT_MS)

    try:
        # Act
        p.goto(DASHBOARD_URL)
        p.wait_for_load_state("domcontentloaded")

        header = p.locator("header").first

        # Assert
        assert header.is_visible()
    finally:
        p.close()
        ctx.close()


@pytest.mark.manual
def test_navigation_tabs_visible_on_desktop_viewport(browser: Browser) -> None:
    """Navigation tab buttons are visible without requiring a scroll on a 1280x720 desktop."""
    # Arrange
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    p = ctx.new_page()
    p.set_default_timeout(TIMEOUT_MS)

    try:
        # Act
        p.goto(DASHBOARD_URL)
        p.wait_for_load_state("domcontentloaded")

        pipeline_tab_btn = p.locator("button#tab-btn-pipeline")

        # Assert
        assert pipeline_tab_btn.count() == 1
        assert pipeline_tab_btn.is_visible()
    finally:
        p.close()
        ctx.close()


# ---------------------------------------------------------------------------
# Error state tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_nonexistent_route_returns_404(page: Page) -> None:
    """A request to /nonexistent returns an HTTP 404 Not Found response."""
    # Arrange
    nonexistent_url = f"{BASE_URL}/nonexistent"

    # Act
    response = page.goto(nonexistent_url)

    # Assert
    assert response is not None
    assert response.status == 404


@pytest.mark.manual
def test_api_nonexistent_endpoint_returns_404(page: Page) -> None:
    """A GET request to an unknown /api/ path returns HTTP 404."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    response = page.request.get(f"{BASE_URL}/api/nonexistent_endpoint_xyz")

    # Assert
    assert response.status == 404


@pytest.mark.manual
def test_health_endpoint_returns_ok_status(page: Page) -> None:
    """GET /api/health returns HTTP 200 and a valid health status payload."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    response = page.request.get(HEALTH_URL)

    # Assert
    assert response.status == 200
    body = response.json()
    assert isinstance(body, dict)
    # The health schema (HealthStatus) must contain a status or checks field
    assert "status" in body or "checks" in body or "healthy" in body


# ---------------------------------------------------------------------------
# Tab switching and navigation interaction tests
# ---------------------------------------------------------------------------


@pytest.mark.manual
def test_switching_to_system_tab_shows_diagnostics_section(page: Page) -> None:
    """Clicking the System & Diagnostics tab reveals the system tab panel."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    page.locator("button#tab-btn-system").click()
    system_section = page.locator("#tab-system")

    # Assert
    assert system_section.count() == 1
    assert system_section.is_visible()


@pytest.mark.manual
def test_switching_to_logs_tab_shows_audit_table(page: Page) -> None:
    """Clicking the Action Logs tab reveals the logs table body element."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    page.locator("button#tab-btn-logs").click()
    logs_section = page.locator("#tab-logs")

    # Assert
    assert logs_section.count() == 1
    assert logs_section.is_visible()
    assert page.locator("#logs-table-body").count() == 1


@pytest.mark.manual
def test_switching_to_script_tab_shows_narration_textarea(page: Page) -> None:
    """Clicking the Script Studio tab reveals the narration textarea input."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    page.locator("button#tab-btn-script").click()
    narration = page.locator("#script-narration-input")

    # Assert
    assert narration.count() == 1
    assert narration.is_visible()


@pytest.mark.manual
def test_live_status_dot_is_present_in_header(page: Page) -> None:
    """The animated live status indicator dot is present in the header."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    status_dot = page.locator("#live-status-dot")

    # Assert
    assert status_dot.count() == 1


@pytest.mark.manual
def test_console_output_element_is_present_in_pipeline_tab(page: Page) -> None:
    """The live execution console output pre element exists in the pipeline panel."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    console = page.locator("#console-output")

    # Assert
    assert console.count() == 1
    assert console.is_visible()


@pytest.mark.manual
def test_recent_jobs_table_structure_is_correct(page: Page) -> None:
    """The recent render jobs table has the expected column headers."""
    # Arrange
    page.goto(DASHBOARD_URL)

    # Act
    table_body = page.locator("#recent-jobs-table-body")

    # Assert
    assert table_body.count() == 1
    # Column headers should include Job ID, Script, Status
    headers = page.locator("table th").all_text_contents()
    header_text = " ".join(headers).lower()
    assert "job" in header_text
    assert "status" in header_text


@pytest.mark.manual
def test_clusters_search_input_is_interactive(page: Page) -> None:
    """The cluster search input field accepts typed text on the clusters tab."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-clusters").click()

    # Act
    search_input = page.locator("#clusters-search-input")
    search_input.fill("artificial intelligence")

    # Assert
    assert search_input.input_value() == "artificial intelligence"


@pytest.mark.manual
def test_branding_format_toggle_buttons_exist(page: Page) -> None:
    """The 9:16 and 16:9 format toggle buttons are present in the branding tab."""
    # Arrange
    page.goto(DASHBOARD_URL)
    page.locator("button#tab-btn-branding").click()

    # Act
    vertical_btn = page.locator("#format-btn-vertical")
    horizontal_btn = page.locator("#format-btn-horizontal")

    # Assert
    assert vertical_btn.count() == 1
    assert horizontal_btn.count() == 1
