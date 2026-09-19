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
    }
    res_post = client.post("/api/settings", json=update_payload)
    assert res_post.status_code == 200
    updated = res_post.json()["settings"]
    assert updated["watermark_text"] == "@CustomWatermark"
    assert updated["watermark_position"] == "bottom-right"
    assert updated["watermark_opacity"] == 0.75
    assert updated["intro_delay_seconds"] == 2.5
    assert updated["outro_duration_seconds"] == 4.0


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
