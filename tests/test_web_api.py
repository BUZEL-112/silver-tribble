from pathlib import Path

from fastapi.testclient import TestClient

from src.core.database import get_session, init_db
from src.models.entities import Article, StoryCluster
from src.web import app

client = TestClient(app)


def test_get_dashboard_root() -> None:
    """Verify GET / returns HTML dashboard with 200 status code."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "AI Video Studio" in response.text


def test_dashboard_javascript_syntax() -> None:
    """Verify inline JavaScript in dashboard HTML has valid syntax without parsing errors."""
    import re
    import shutil
    import subprocess
    import tempfile

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    scripts = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) > 0

    node_bin = shutil.which("node")
    if node_bin:
        for idx, script in enumerate(scripts):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(script)
                temp_path = f.name
            try:
                proc = subprocess.run(
                    [node_bin, "--check", temp_path],
                    capture_output=True,
                    text=True,
                )
                assert proc.returncode == 0, f"Script block {idx} syntax error: {proc.stderr}"
            finally:
                Path(temp_path).unlink(missing_ok=True)


def test_stage_run_confirmation_modal_and_logic() -> None:
    """Verify repeat stage run confirmation modal markup, Yes/No buttons, and 5-minute guard."""
    import shutil
    import subprocess

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Verify modal DOM elements and text
    assert 'id="modal-stage-confirmation"' in html
    assert "You have run this step once. Do you still want to run again?" in html
    assert 'id="stage-confirm-btn-yes"' in html
    assert 'id="stage-confirm-btn-no"' in html
    assert 'id="stage-confirm-elapsed"' in html
    assert 'id="stage-confirm-remaining"' in html

    # Verify JavaScript confirmation functions and 5-minute timeout constant
    assert "STAGE_CONFIRMATION_TIMEOUT_MS = 5 * 60 * 1000" in html
    assert "function runStageWithConfirmation(" in html
    assert "function openStageConfirmModal(" in html
    assert "function closeStageConfirmModal(" in html

    node_bin = shutil.which("node")
    if node_bin:
        verify_script = """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync("src/templates/dashboard.html", "utf-8");

const storage = {};
const elements = {};
function createMockEl(id) {
  return {
    id,
    classList: {
      classes: new Set(["hidden"]),
      add(c) { this.classes.add(c); },
      remove(c) { this.classes.delete(c); },
      contains(c) { return this.classes.has(c); }
    },
    textContent: "",
    innerHTML: "",
    addEventListener: () => {}
  };
}

const context = {
  console,
  sessionStorage: {
    getItem: (k) => storage[k] || null,
    setItem: (k, v) => { storage[k] = String(v); },
    removeItem: (k) => { delete storage[k]; }
  },
  document: {
    getElementById: (id) => {
      if (!elements[id]) elements[id] = createMockEl(id);
      return elements[id];
    },
    addEventListener: () => {}
  },
  setInterval: () => 123,
  clearInterval: () => {}
};
context.window = context;

const m = html.match(/<script(?![^>]*src=)[^>]*>([\\s\\S]*?)<\\/script>/);
vm.runInNewContext(m[1], context);

let calledCount = 0;
// 1. First tap executes immediately
context.runStageWithConfirmation("ingest", "Stage 1: Ingest RSS", () => {
  calledCount++;
});
if (calledCount !== 1) process.exit(1);

// 2. Second tap within 5 mins opens modal and does not run immediately
context.runStageWithConfirmation("ingest", "Stage 1: Ingest RSS", () => {
  calledCount++;
});
if (calledCount !== 1) process.exit(2);
const modal = context.document.getElementById("modal-stage-confirmation");
if (modal.classList.contains("hidden")) process.exit(3);

// 3. Clicking No dismisses without running
context.closeStageConfirmModal(false);
if (!modal.classList.contains("hidden")) process.exit(4);
if (calledCount !== 1) process.exit(5);

// 4. Second tap again and clicking Yes executes callback
context.runStageWithConfirmation("ingest", "Stage 1: Ingest RSS", () => {
  calledCount++;
});
context.closeStageConfirmModal(true);
if (calledCount !== 2) process.exit(6);

// 5. Tap after 5 minutes runs immediately
context.sessionStorage.setItem("stage_last_run_ingest", String(Date.now() - 6 * 60 * 1000));
context.runStageWithConfirmation("ingest", "Stage 1: Ingest RSS", () => {
  calledCount++;
});
if (calledCount !== 3) process.exit(7);
"""
        proc = subprocess.run([node_bin, "-e", verify_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node verification failed: {proc.stderr}"


def test_live_execution_output_persists_on_reload() -> None:
    """Verify live execution output console persists across reloads in localStorage."""
    import shutil
    import subprocess

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    assert 'id="console-output"' in html
    assert "Live Execution Output" in html
    assert "CONSOLE_STORAGE_KEY" in html
    assert "function loadConsoleOutput(" in html
    assert "function saveConsoleOutput(" in html
    assert "function logToConsole(" in html
    assert "function clearConsole(" in html

    node_bin = shutil.which("node")
    if node_bin:
        verify_script = """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync("src/templates/dashboard.html", "utf-8");

const localStore = {};
function createEnv() {
  const elements = {};
  function createMockEl(id) {
    return {
      id,
      classList: {
        classes: new Set(),
        add(c) { this.classes.add(c); },
        remove(c) { this.classes.delete(c); },
        contains(c) { return this.classes.has(c); }
      },
      textContent: id === "console-output" ? "System initialized. Ready for operations." : "",
      innerHTML: "",
      addEventListener: () => {}
    };
  }

  const context = {
    console,
    localStorage: {
      getItem: (k) => localStore[k] || null,
      setItem: (k, v) => { localStore[k] = String(v); },
      removeItem: (k) => { delete localStore[k]; }
    },
    sessionStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {}
    },
    document: {
      getElementById: (id) => {
        if (!elements[id]) elements[id] = createMockEl(id);
        return elements[id];
      },
      addEventListener: () => {}
    },
    setInterval: () => 123,
    clearInterval: () => {}
  };
  context.window = context;

  const m = html.match(/<script(?![^>]*src=)[^>]*>([\\s\\S]*?)<\\/script>/);
  vm.runInNewContext(m[1], context);
  return context;
}

// 1. Initial run: log messages
const env1 = createEnv();
env1.logToConsole("Triggering stage: ingest...");
env1.logToConsole("[INGEST] Articles fetched: 12");

const pre1 = env1.document.getElementById("console-output");
if (!pre1.textContent.includes("Triggering stage: ingest...")) process.exit(1);
if (!localStore["ai_video_live_console_output"]) process.exit(2);

// 2. Simulate reload: create a new environment (new DOM with default placeholder text)
const env2 = createEnv();
const pre2 = env2.document.getElementById("console-output");
// Before loadConsoleOutput, it has the default placeholder
if (pre2.textContent !== "System initialized. Ready for operations.") process.exit(3);

// Execute loadConsoleOutput on reload
env2.loadConsoleOutput();

// Now pre2 must have restored previous logs instead of resetting
if (!pre2.textContent.includes("Triggering stage: ingest...")) process.exit(4);
if (!pre2.textContent.includes("[INGEST] Articles fetched: 12")) process.exit(5);

// 3. Log additional message after reload
env2.logToConsole("[CLUSTER] Clusters created: 3");
if (!pre2.textContent.includes("[CLUSTER] Clusters created: 3")) process.exit(6);
const savedLog = localStore["ai_video_live_console_output"];
if (!savedLog || !savedLog.includes("[CLUSTER] Clusters created: 3")) process.exit(7);

// 4. Test clear console
env2.clearConsole();
if (pre2.textContent !== "Console cleared.") process.exit(8);
if (localStore["ai_video_live_console_output"] !== "Console cleared.") process.exit(9);
"""
        proc = subprocess.run([node_bin, "-e", verify_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Console persistence node verification failed: {proc.stderr}"


def test_settings_api() -> None:
    """Verify reading and updating watermark and timing settings."""
    res_get = client.get("/api/settings")
    assert res_get.status_code == 200
    data = res_get.json()
    assert "watermark_position" in data

    update_payload = {
        "watermark_text": "@CustomWatermark",
        "watermark_position": "bottom-right",
        "watermark_opacity": 0.75,
        "intro_delay_seconds": 2.5,
        "outro_duration_seconds": 4.0,
        "caption_style": "cinematic",
        "caption_level": 45.0,
        "caption_font_size": 52,
        "caption_uppercase": False,
        "subscribe_title": "SUBSCRIBE TO AI BREAKDOWNS",
        "subscribe_subtitle": "@AINewsDesk | Raw Engineering",
        "subscribe_button_text": "JOIN DESK",
        "subscribe_duration_seconds": 4.5,
        "subscribe_style": "lower_third",
        "subscribe_enabled": True,
        "horizontal_watermark_position": "top-left",
        "horizontal_caption_level": 18.0,
        "horizontal_channel_badge_text": "AI NEWS DESK WIDESCREEN",
        "horizontal_lower_third_title": "FRONTIER REASONING ANALYSIS",
    }
    res_post = client.post("/api/settings", json=update_payload)
    assert res_post.status_code == 200
    updated = res_post.json()["settings"]
    assert updated["watermark_text"] == "@CustomWatermark"
    assert updated["watermark_position"] == "bottom-right"
    assert updated["watermark_opacity"] == 0.75
    assert updated["intro_delay_seconds"] == 2.5
    assert updated["outro_duration_seconds"] == 4.0
    assert updated["caption_style"] == "cinematic"
    assert updated["caption_level"] == 45.0
    assert updated["caption_font_size"] == 52
    assert updated["caption_uppercase"] is False
    assert updated["subscribe_title"] == "SUBSCRIBE TO AI BREAKDOWNS"
    assert updated["subscribe_subtitle"] == "@AINewsDesk | Raw Engineering"
    assert updated["subscribe_button_text"] == "JOIN DESK"
    assert updated["subscribe_duration_seconds"] == 4.5
    assert updated["subscribe_style"] == "lower_third"
    assert updated["subscribe_enabled"] is True
    assert updated["horizontal_watermark_position"] == "top-left"
    assert updated["horizontal_caption_level"] == 18.0
    assert updated["horizontal_channel_badge_text"] == "AI NEWS DESK WIDESCREEN"
    assert updated["horizontal_lower_third_title"] == "FRONTIER REASONING ANALYSIS"


def test_logs_api() -> None:
    """Verify action logs query endpoint."""
    res = client.get("/api/logs?limit=10")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_pipeline_endpoints_lifecycle() -> None:
    """Verify pipeline stages triggerable via API."""
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]

    # Seed story cluster
    with get_session() as session:
        art = Article(
            title=f"FastAPI Integration Pipeline Test {uid}",
            link=f"https://example.com/fastapi-test-art-{uid}",
            source="WebNews",
            summary="Testing API endpoints for video pipeline with complete sentence details.",
        )
        session.add(art)
        session.commit()

        cluster = StoryCluster(
            cluster_hash=f"hash_web_api_{uid}",
            title=f"FastAPI Integration Pipeline Test {uid}",
            summary=f"[WebNews] {art.title}: {art.summary}",
            article_ids=[art.id],
            status="pending",
        )
        session.add(cluster)
        session.commit()
        cluster_id = cluster.id

    # 1. Script stage
    res_script = client.post(
        "/api/pipeline/script",
        json={"cluster_id": cluster_id, "aspect_ratio": "9:16"},
    )
    assert res_script.status_code == 200
    script_data = res_script.json()
    assert script_data["status"] == "success"
    script_id = script_data["script_id"]

    # 2. Get script
    res_get_script = client.get(f"/api/scripts/{script_id}")
    assert res_get_script.status_code == 200
    assert res_get_script.json()["id"] == script_id

    # 3. Update script
    res_put_script = client.put(
        f"/api/scripts/{script_id}",
        json={"title": "Updated Title via Web API"},
    )
    assert res_put_script.status_code == 200
    assert res_put_script.json()["title"] == "Updated Title via Web API"

    # 4. Voice stage
    res_voice = client.post(
        "/api/pipeline/voice",
        json={"script_id": script_id, "aspect_ratio": "9:16"},
    )
    assert res_voice.status_code == 200
    voice_data = res_voice.json()
    assert voice_data["status"] == "success"
    job_id = voice_data["job_id"]

    # 5. Media stage
    res_media = client.post(
        "/api/pipeline/media",
        json={"job_id": job_id},
    )
    assert res_media.status_code == 200
    assert res_media.json()["status"] == "success"

    # 6. Render stage (dry-run)
    res_render = client.post(
        "/api/pipeline/render",
        json={"job_id": job_id, "dry_run": True},
    )
    assert res_render.status_code == 200
    assert res_render.json()["status"] == "success"
    assert "output_video_path" in res_render.json()

    # 7. Jobs list
    res_jobs = client.get("/api/jobs")
    assert res_jobs.status_code == 200
    jobs = res_jobs.json()
    assert any(j["id"] == job_id for j in jobs)


def test_config_yaml_api(tmp_path: Path) -> None:
    """Verify loading, reading, and hot-reloading YAML configuration via API."""
    res_active = client.get("/api/config/active")
    assert res_active.status_code == 200
    assert "config_source" in res_active.json()

    res_yaml = client.get("/api/config/yaml")
    assert res_yaml.status_code == 200
    assert "yaml_content" in res_yaml.json()

    custom_yaml = """
watermark:
  text: "@DynamicPlugAndPlay"
  position: "bottom-left"
  opacity: 0.95
timing:
  intro_delay_seconds: 2.0
  outro_duration_seconds: 4.5
"""
    custom_path = str(tmp_path / "custom_test_config.yaml")
    res_save = client.post(
        "/api/config/save",
        json={"config_path": custom_path, "yaml_content": custom_yaml},
    )
    assert res_save.status_code == 200
    saved_data = res_save.json()
    assert saved_data["status"] == "success"
    assert saved_data["settings"]["watermark_text"] == "@DynamicPlugAndPlay"
    assert saved_data["settings"]["watermark_position"] == "bottom-left"

    res_load = client.post(
        "/api/config/load",
        json={"config_path": custom_path},
    )
    assert res_load.status_code == 200
    assert res_load.json()["status"] == "success"


def test_roundup_and_assets_api() -> None:
    """Verify roundup script generation and visual assets endpoints."""
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]

    with get_session() as session:
        art1 = Article(
            title=f"Roundup Article 1 {uid}",
            link=f"https://example.com/roundup-1-{uid}",
            source="TechRadar",
            summary="Story 1 summary on generative robotics.",
        )
        art2 = Article(
            title=f"Roundup Article 2 {uid}",
            link=f"https://example.com/roundup-2-{uid}",
            source="VentureBeat",
            summary="Story 2 summary on model inference optimization.",
        )
        session.add_all([art1, art2])
        session.commit()

        c1 = StoryCluster(
            cluster_hash=f"hash_r1_{uid}",
            title=f"Roundup Cluster 1 {uid}",
            summary="Story 1 summary",
            article_ids=[art1.id],
            status="pending",
        )
        c2 = StoryCluster(
            cluster_hash=f"hash_r2_{uid}",
            title=f"Roundup Cluster 2 {uid}",
            summary="Story 2 summary",
            article_ids=[art2.id],
            status="pending",
        )
        session.add_all([c1, c2])
        session.commit()
        c1_id = c1.id
        c2_id = c2.id

    # 1. Trigger roundup script generation via API
    res = client.post(
        "/api/pipeline/roundup-script",
        json={"cluster_ids": [c1_id, c2_id], "aspect_ratio": "9:16"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "script_id" in data
    assert data["beats_count"] > 0

    # 2. Test visual asset listing API
    res_assets = client.get("/api/assets?limit=10")
    assert res_assets.status_code == 200
    assert isinstance(res_assets.json(), list)


def test_clusters_and_articles_endpoints() -> None:
    """Verify listing clusters with articles, fetching single cluster, and cluster articles."""
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]

    art1_title = f"Cluster Article Alpha {uid}"
    art2_title = f"Cluster Article Beta {uid}"
    cluster_title = f"Inspection Cluster {uid}"

    with get_session() as session:
        art1 = Article(
            title=art1_title,
            link=f"https://example.com/alpha-{uid}",
            source="TechSource",
            summary="Alpha summary regarding artificial intelligence.",
        )
        art2 = Article(
            title=art2_title,
            link=f"https://example.com/beta-{uid}",
            source="AiDaily",
            summary="Beta summary discussing machine learning.",
        )
        session.add_all([art1, art2])
        session.commit()

        cluster = StoryCluster(
            cluster_hash=f"hash_inspect_{uid}",
            title=cluster_title,
            summary="Summary of inspection cluster",
            article_ids=[art1.id, art2.id],
            article_count=99,
            status="pending",
        )
        session.add(cluster)
        session.commit()
        cluster_id = cluster.id

    # 1. Test GET /api/clusters with include_articles
    res_list = client.get("/api/clusters?limit=10&include_articles=true")
    assert res_list.status_code == 200
    clusters_data = res_list.json()
    assert isinstance(clusters_data, list)
    matching = [c for c in clusters_data if c["id"] == cluster_id]
    assert len(matching) == 1
    assert matching[0]["article_count"] == 99
    assert len(matching[0]["articles"]) == 2
    assert matching[0]["articles"][0]["title"] in [art1_title, art2_title]

    # 2. Test GET /api/clusters/{cluster_id}
    res_single = client.get(f"/api/clusters/{cluster_id}")
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["id"] == cluster_id
    assert single_data["title"] == cluster_title
    assert len(single_data["articles"]) == 2

    # 3. Test GET /api/clusters/{cluster_id}/articles
    res_articles = client.get(f"/api/clusters/{cluster_id}/articles")
    assert res_articles.status_code == 200
    articles_data = res_articles.json()
    assert len(articles_data) == 2
    assert articles_data[0]["source"] in ["TechSource", "AiDaily"]

    # 4. Test 404 on nonexistent cluster
    res_404 = client.get("/api/clusters/999999")
    assert res_404.status_code == 404

    # 5. Test paginated clusters endpoint
    res_paged = client.get("/api/clusters?page=1&page_size=1&include_articles=true")
    assert res_paged.status_code == 200
    paged_data = res_paged.json()
    assert isinstance(paged_data, dict)
    assert "items" in paged_data
    assert "total" in paged_data
    assert "page" in paged_data
    assert "page_size" in paged_data
    assert "total_pages" in paged_data
    assert paged_data["page"] == 1
    assert paged_data["page_size"] == 1
    assert paged_data["total"] >= 1
    assert len(paged_data["items"]) == 1
    assert "X-Total-Count" in res_paged.headers

    # 6. Test clusters count endpoint
    res_count = client.get("/api/clusters/count")
    assert res_count.status_code == 200
    count_data = res_count.json()
    assert "count" in count_data
    assert count_data["count"] >= 1


def test_platform_stats_and_costs_api() -> None:
    """Verify KPI stats ribbon and cost analytics endpoints."""
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert "articles_count" in stats
    assert "clusters_count" in stats
    assert "jobs_count" in stats
    assert "completed_jobs_count" in stats
    assert "assets_count" in stats
    assert "total_spend_usd" in stats
    assert isinstance(stats["total_spend_usd"], (int, float))

    res_costs = client.get("/api/costs")
    assert res_costs.status_code == 200
    costs = res_costs.json()
    assert "total_spend_usd" in costs
    assert "spend_by_stage" in costs
    assert "per_video_costs" in costs
    assert isinstance(costs["spend_by_stage"], list)
    assert isinstance(costs["per_video_costs"], list)


def test_providers_api_endpoints() -> None:
    """Verify provider catalog listing, priority shifting, toggling, and removal endpoints."""
    # 1. List providers
    res = client.get("/api/providers")
    assert res.status_code == 200
    providers = res.json()
    assert isinstance(providers, list)
    assert len(providers) >= 4

    # 2. Shift priority
    res_move = client.post("/api/providers/giphy/move?direction=up")
    assert res_move.status_code == 200
    move_data = res_move.json()
    assert move_data["status"] == "success"
    assert "priority_order" in move_data

    # 3. Toggle provider
    res_toggle = client.post("/api/providers/pexels/toggle", json={"enabled": False})
    assert res_toggle.status_code == 200
    assert res_toggle.json()["is_enabled"] is False

    # Restore toggle
    client.post("/api/providers/pexels/toggle", json={"enabled": True})

    # 4. Test provider connection
    res_test = client.post("/api/providers/test", json={"provider_id": "local"})
    assert res_test.status_code == 200
    assert res_test.json()["status"] == "success"

    # 5. Batch test all providers
    res_all = client.post("/api/providers/test-all")
    assert res_all.status_code == 200
    assert isinstance(res_all.json(), list)


def test_visual_config_api_endpoints() -> None:
    """Verify visual configuration endpoints, presets listing, and hot-reload application."""
    # 1. Get presets
    res_presets = client.get("/api/config/visual/presets")
    assert res_presets.status_code == 200
    presets = res_presets.json()
    assert len(presets) >= 4

    # 2. Get current visual config
    res_config = client.get("/api/config/visual")
    assert res_config.status_code == 200
    cfg = res_config.json()
    assert "aspect_ratio" in cfg
    assert "target_beats" in cfg

    # 3. Apply preset
    res_apply = client.post("/api/config/visual/preset/viral_shorts_9_16")
    assert res_apply.status_code == 200
    applied = res_apply.json()
    assert applied["aspect_ratio"] == "9:16"
    assert applied["target_beats"] == 5

    # 4. Update visual config
    res_update = client.post(
        "/api/config/visual",
        json={
            "aspect_ratio": "16:9",
            "target_beats": 7,
            "max_clusters": 4,
            "tts_voice": "Charon",
        },
    )
    assert res_update.status_code == 200
    updated = res_update.json()
    assert updated["aspect_ratio"] == "16:9"
    assert updated["target_beats"] == 7
    assert updated["max_clusters"] == 4
    assert updated["tts_voice"] == "Charon"


def test_articles_api_listing_and_filtering() -> None:
    """Verify GET /api/articles returns articles with search, source, and limit filters."""
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]

    with get_session() as session:
        art1 = Article(
            title=f"Article Neural Network {uid}",
            link=f"https://example.com/art-neural-{uid}",
            source=f"SourceNeural_{uid}",
            summary="Neural networks research breakdown.",
        )
        art2 = Article(
            title=f"Article Database Scaling {uid}",
            link=f"https://example.com/art-db-{uid}",
            source=f"SourceDB_{uid}",
            summary="Postgres scaling strategies.",
        )
        session.add(art1)
        session.add(art2)
        session.commit()
        art1_id = art1.id
        art2_id = art2.id

    # 1. Test basic fetch
    res = client.get("/api/articles?limit=50")
    assert res.status_code == 200
    articles = res.json()
    assert isinstance(articles, list)

    # 2. Test search filter
    res_search = client.get("/api/articles", params={"search": f"Neural Network {uid}"})
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert any(a["id"] == art1_id for a in search_data)
    assert not any(a["id"] == art2_id for a in search_data)

    # 3. Test source filter
    res_source = client.get(f"/api/articles?source=SourceDB_{uid}")
    assert res_source.status_code == 200
    source_data = res_source.json()
    assert any(a["id"] == art2_id for a in source_data)
    assert not any(a["id"] == art1_id for a in source_data)

    # 4. Test fetch without limit returns all articles
    res_all = client.get("/api/articles")
    assert res_all.status_code == 200
    all_articles = res_all.json()
    assert any(a["id"] == art1_id for a in all_articles)
    assert any(a["id"] == art2_id for a in all_articles)

    # 5. Test limit can exceed 500 without validation error
    res_large = client.get("/api/articles?limit=1000")
    assert res_large.status_code == 200


def test_cluster_runs_and_clusters_by_run_id_api() -> None:
    """Verify GET /api/cluster-runs, cluster run id filtering, and run_cluster_index."""
    import uuid

    init_db()
    uid = uuid.uuid4().hex[:8]
    run_id_a = f"run_{uid}_a"
    run_id_b = f"run_{uid}_b"

    with get_session() as session:
        c1 = StoryCluster(
            cluster_hash=f"{run_id_a}:1",
            title=f"Story Run A First {uid}",
            summary="Summary A1",
            article_ids=[1],
            article_count=1,
            cluster_run_id=run_id_a,
            run_cluster_index=1,
        )
        c2 = StoryCluster(
            cluster_hash=f"{run_id_a}:2",
            title=f"Story Run A Second {uid}",
            summary="Summary A2",
            article_ids=[2],
            article_count=1,
            cluster_run_id=run_id_a,
            run_cluster_index=2,
        )
        c3 = StoryCluster(
            cluster_hash=f"{run_id_b}:1",
            title=f"Story Run B First {uid}",
            summary="Summary B1",
            article_ids=[3],
            article_count=1,
            cluster_run_id=run_id_b,
            run_cluster_index=1,
        )
        session.add_all([c1, c2, c3])
        session.commit()
        c1_id = c1.id
        c2_id = c2.id
        c3_id = c3.id

    # 1. Test GET /api/cluster-runs
    res_runs = client.get("/api/cluster-runs")
    assert res_runs.status_code == 200
    runs = res_runs.json()
    assert isinstance(runs, list)
    assert any(r["run_id"] == run_id_a for r in runs)
    assert any(r["run_id"] == run_id_b for r in runs)

    # 2. Test GET /api/clusters?cluster_run_id=run_id_a
    res_clusters_a = client.get(f"/api/clusters?cluster_run_id={run_id_a}")
    assert res_clusters_a.status_code == 200
    clusters_a_data = res_clusters_a.json()
    items_a = (
        clusters_a_data.get("items", clusters_a_data)
        if isinstance(clusters_a_data, dict)
        else clusters_a_data
    )
    items_a_ids = [item["id"] for item in items_a]
    assert c1_id in items_a_ids
    assert c2_id in items_a_ids
    assert c3_id not in items_a_ids

    # Verify run_cluster_index is present
    for item in items_a:
        if item["id"] == c1_id:
            assert item["run_cluster_index"] == 1
            assert item["cluster_run_id"] == run_id_a
        elif item["id"] == c2_id:
            assert item["run_cluster_index"] == 2
            assert item["cluster_run_id"] == run_id_a


def test_cluster_trigger_with_request_body() -> None:
    """Verify POST /api/pipeline/cluster accepts json payload with article_ids and threshold."""
    from unittest.mock import MagicMock, patch

    mock_cluster_result = MagicMock()
    mock_cluster_result.id = 999
    mock_cluster_result.title = "Mock Cluster"
    mock_cluster_result.cluster_hash = "mock:1"
    mock_cluster_result.article_count = 2
    mock_cluster_result.cluster_run_id = "run_mock_123"
    mock_cluster_result.run_cluster_index = 1
    mock_cluster_result.created_at = None

    with patch("src.web.ClusteringService") as mock_cls:
        service_instance = MagicMock()
        service_instance.last_run_id = "run_mock_123"
        service_instance.cluster_recent_articles.return_value = [mock_cluster_result]
        mock_cls.return_value = service_instance

        res = client.post(
            "/api/pipeline/cluster",
            json={
                "threshold": 0.88,
                "article_ids": [10, 20],
                "hours_back": 12,
                "cluster_run_id": "run_mock_123",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["cluster_run_id"] == "run_mock_123"
        assert data["clusters_count"] == 1
        assert len(data["clusters"]) == 1
        assert data["clusters"][0]["cluster_run_id"] == "run_mock_123"
        assert data["clusters"][0]["run_cluster_index"] == 1

        service_instance.cluster_recent_articles.assert_called_once_with(
            threshold=0.88,
            article_ids=[10, 20],
            hours_back=12,
            cluster_run_id="run_mock_123",
        )


def test_clustering_and_script_modals_markup_and_js() -> None:
    """Verify Modal 9 (cluster articles), Modal 10 (write script), and their JS handlers."""
    import shutil
    import subprocess

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Modal 9 markup
    assert 'id="modal-cluster-articles"' in html
    assert 'id="modal-articles-table-body"' in html
    assert 'id="modal-article-search"' in html
    assert 'id="modal-cluster-threshold"' in html
    assert 'id="modal-cluster-run-id-input"' in html
    assert 'id="btn-modal-execute-cluster"' in html

    # Modal 10 markup
    assert 'id="modal-write-script"' in html
    assert 'id="modal-script-run-select"' in html
    assert 'id="modal-script-cluster-select"' in html
    assert 'id="modal-script-cluster-preview"' in html
    assert 'id="btn-modal-execute-script"' in html

    # Story Intelligence run filter
    assert 'id="clusters-run-filter"' in html

    # JS functions
    assert "function openClusterModal(" in html
    assert "function closeClusterModal(" in html
    assert "function setClusterModalHours(" in html
    assert "function executeModalClustering(" in html
    assert "function openWriteScriptModal(" in html
    assert "function closeWriteScriptModal(" in html
    assert "function loadWriteScriptModalRuns(" in html
    assert "function onModalScriptRunChange(" in html
    assert "function onModalScriptClusterChange(" in html
    assert "function executeModalWriteScript(" in html
    assert "function loadClusterRunsDropdown(" in html
    assert "function onClusterRunFilterChange(" in html

    node_bin = shutil.which("node")
    if node_bin:
        verify_script = """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync("src/templates/dashboard.html", "utf-8");

const elements = {};
function createMockEl(id) {
  return {
    id,
    classList: {
      classes: new Set(["hidden"]),
      add(c) { this.classes.add(c); },
      remove(c) { this.classes.delete(c); },
      contains(c) { return this.classes.has(c); }
    },
    textContent: "",
    innerHTML: "",
    value: "",
    disabled: false,
    checked: false,
    addEventListener: () => {}
  };
}

const context = {
  console,
  document: {
    getElementById: (id) => {
      if (!elements[id]) elements[id] = createMockEl(id);
      return elements[id];
    },
    addEventListener: () => {}
  },
  fetch: async () => ({
    ok: true,
    json: async () => []
  }),
  setInterval: () => 1,
  setTimeout: (cb) => cb(),
  clearTimeout: () => {}
};
context.window = context;

const m = html.match(/<script(?![^>]*src=)[^>]*>([\\s\\S]*?)<\\/script>/);
vm.runInNewContext(m[1], context);

// Test Modal 9 open and close
context.openClusterModal();
const modalCluster = context.document.getElementById("modal-cluster-articles");
if (modalCluster.classList.contains("hidden")) process.exit(1);

context.closeClusterModal();
if (!modalCluster.classList.contains("hidden")) process.exit(2);

// Test Modal 10 open and close
context.openWriteScriptModal(5);
const modalScript = context.document.getElementById("modal-write-script");
if (modalScript.classList.contains("hidden")) process.exit(3);

context.closeWriteScriptModal();
if (!modalScript.classList.contains("hidden")) process.exit(4);
"""
        proc = subprocess.run([node_bin, "-e", verify_script], capture_output=True, text=True)
        assert proc.returncode == 0, f"Node verification failed: {proc.stderr}"
