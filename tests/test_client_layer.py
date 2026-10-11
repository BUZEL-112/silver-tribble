"""Tests verifying client layer static assets, deployment configurations, and contracts."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_index_html_exists_and_encodes_cleanly() -> None:
    """Verify that index.html and docs/index.html exist, encode cleanly, and match exactly."""
    index_path = PROJECT_ROOT / "index.html"
    docs_path = PROJECT_ROOT / "docs" / "index.html"

    assert index_path.exists(), "index.html must exist at the repository root"
    assert docs_path.exists(), "docs/index.html must exist for GitHub Pages deployment"

    content = index_path.read_text(encoding="utf-8")
    docs_content = docs_path.read_text(encoding="utf-8")

    assert "<!DOCTYPE html>" in content
    assert "<html" in content
    assert "</html>" in content
    assert content == docs_content, "index.html and docs/index.html must remain in exact parity"


def test_index_html_satisfies_deploy_md_client_contracts() -> None:
    """Verify that index.html contains required client contracts, design viewer, and dashboard."""
    index_path = PROJECT_ROOT / "index.html"
    content = index_path.read_text(encoding="utf-8")

    # LocalStorage backend URL and auth token handling
    assert 'localStorage.getItem("ai_video_api_url")' in content
    assert 'localStorage.getItem("ai_video_auth_token")' in content
    assert 'id="auth-key-modal"' in content
    assert 'id="input-backend-url"' in content
    assert 'id="input-auth-key-val"' in content
    assert 'id="btn-header-auth-key"' in content
    assert 'id="btn-test-backend-connection"' in content

    # Enforce no hardcoded default token in client files
    assert "DEFAULT_AUTH_TOKEN" not in content
    assert "c01a1e0431fe2850a396304a79afaf0a" not in content

    # Base home view and navigation
    assert 'id="default-landing-view"' in content
    assert 'id="btn-goto-demo"' in content
    assert "navigateToDemo()" in content

    # Technical design documentation viewer on base home
    assert 'id="design-doc-viewer"' in content
    assert 'id="design-toc"' in content
    assert "markdown-it" in content
    assert 'class="mermaid' in content
    assert 'id="newsroom-ai-project"' in content
    assert 'id="system-explanation-and-design"' in content
    assert 'id="deployment"' in content
    assert 'id="post-analysis"' in content

    # Studio production dashboard container and elements
    assert 'id="dashboard-view"' in content
    assert 'id="html5-video-player"' in content
    assert 'id="kpi-spend"' in content
    assert 'id="kpi-rendered"' in content

    # Workspace tabs and pipeline execution controls
    assert 'id="tab-pipeline"' in content
    assert 'id="tab-clusters"' in content
    assert 'id="tab-script"' in content
    assert 'id="tab-media"' in content
    assert 'id="pipeline-modal"' in content


def test_index_html_has_no_emojis_or_emdash() -> None:
    """Enforce project rules: no emojis and no em-dashes in frontend assets."""
    for relative_path in ["index.html", "docs/index.html"]:
        file_path = PROJECT_ROOT / relative_path
        content = file_path.read_text(encoding="utf-8")

        assert "\u2014" not in content, f"Found em-dash in {relative_path}"

        # Verify no unexpected non-ascii characters (excluding curly quotes if any)
        allowed_unicode = {"\u2018", "\u2019", "\u201c", "\u201d"}
        non_ascii = [c for c in content if ord(c) > 127 and c not in allowed_unicode]
        assert len(non_ascii) == 0, f"Found non-ascii/emojis in {relative_path}: {non_ascii}"


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
