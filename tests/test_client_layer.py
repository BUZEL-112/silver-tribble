"""Tests verifying client layer static assets, deployment configurations, and contracts."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_index_html_exists_and_encodes_cleanly() -> None:
    """Verify that index.html exists at the repository root and has valid UTF-8 encoding."""
    index_path = PROJECT_ROOT / "index.html"
    assert index_path.exists(), "index.html must exist at the repository root"
    content = index_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "<html" in content
    assert "</html>" in content


def test_index_html_satisfies_deploy_md_client_contracts() -> None:
    """Verify that index.html contains required localStorage keys and API configurations."""
    index_path = PROJECT_ROOT / "index.html"
    content = index_path.read_text(encoding="utf-8")

    # LocalStorage keys from deploy.md specification
    assert 'localStorage.getItem("ai_video_api_url")' in content
    assert 'localStorage.getItem("ai_video_auth_token")' in content
    assert "BACKEND_API_URL" in content
    assert "AUTH_TOKEN" in content

    # Cloud Run settings modal elements
    assert 'id="cloud-settings-modal"' in content
    assert 'id="input-backend-url"' in content
    assert 'id="input-auth-token"' in content
    assert 'id="btn-cloud-status"' in content

    # Dynamic metrics and video player
    assert 'id="rendered-video-player"' in content
    assert 'id="select-video-source"' in content
    assert 'id="metric-cost"' in content
    assert 'id="metric-runs"' in content

    # Pipeline execution controls
    assert 'id="pipeline-target-label"' in content
    assert 'id="chk-dry-run"' in content
    assert 'id="select-pipeline-ratio"' in content
    assert 'id="btn-run-simulation"' in content

    # Artifact synchronization
    assert 'id="btn-sync-artifacts"' in content
    assert 'id="artifact-source-tag"' in content


def test_index_html_has_no_emojis_or_emdash() -> None:
    """Enforce project rules: no emojis and no em-dashes in frontend assets."""
    index_path = PROJECT_ROOT / "index.html"
    content = index_path.read_text(encoding="utf-8")

    assert "\u2014" not in content, "Found em-dash in index.html"

    # Verify no unexpected non-ascii characters (excluding curly quotes if any)
    allowed_unicode = {"\u2018", "\u2019", "\u201c", "\u201d"}
    non_ascii = [c for c in content if ord(c) > 127 and c not in allowed_unicode]
    assert len(non_ascii) == 0, f"Found non-ascii/emojis in index.html: {non_ascii}"


def test_huggingface_space_manifest() -> None:
    """Verify Hugging Face Static Space README.md exists and has valid YAML frontmatter."""
    hf_readme_path = PROJECT_ROOT / "huggingface" / "README.md"
    assert hf_readme_path.exists(), "huggingface/README.md must exist"
    content = hf_readme_path.read_text(encoding="utf-8")
    assert content.startswith("---")
    parts = content.split("---", 2)
    assert len(parts) >= 3, "Frontmatter must be enclosed by triple dashes"
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["sdk"] == "static"
    assert frontmatter["title"] == "AI Video Studio Portfolio"


def test_github_actions_deployment_workflow() -> None:
    """Verify deploy.yml workflow is valid and contains backend and frontend jobs."""
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "deploy.yml"
    assert workflow_path.exists(), ".github/workflows/deploy.yml must exist"
    content = workflow_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)

    assert "deploy-backend" in data["jobs"]
    assert "deploy-frontend" in data["jobs"]
    frontend_job = data["jobs"]["deploy-frontend"]
    assert "pages" in frontend_job.get("permissions", {})
