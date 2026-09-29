"""Unit tests for Gemini PR reviewer script."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.gemini_pr_review import (
    build_review_prompt,
    call_gemini_api,
    get_git_diff,
    load_styleguide,
    post_github_comment,
    run_pr_review,
)


def test_load_styleguide_existing(tmp_path: Path) -> None:
    """Styleguide file content should be loaded when file exists."""
    guide_file = tmp_path / "styleguide.md"
    guide_file.write_text("# Test Guide\nFollow SRP.", encoding="utf-8")

    result = load_styleguide(guide_file)
    assert result == "# Test Guide\nFollow SRP."


def test_load_styleguide_missing(tmp_path: Path) -> None:
    """Missing styleguide should return empty string without error."""
    missing_file = tmp_path / "does_not_exist.md"
    result = load_styleguide(missing_file)
    assert result == ""


def test_get_git_diff_success() -> None:
    """get_git_diff should return diff output from git command."""
    mock_proc = MagicMock()
    mock_proc.stdout = "diff --git a/foo.py b/foo.py\n+print('hello')"

    with patch("subprocess.run", return_value=mock_proc):
        diff = get_git_diff("origin/main", "HEAD")
        assert "+print('hello')" in diff


def test_get_git_diff_truncation() -> None:
    """Large diffs should be truncated to max_chars limit."""
    mock_proc = MagicMock()
    mock_proc.stdout = "x" * 200

    with patch("subprocess.run", return_value=mock_proc):
        diff = get_git_diff("origin/main", "HEAD", max_chars=50)
        assert len(diff) < 200
        assert "[Diff truncated due to size limits]" in diff


def test_get_git_diff_failure() -> None:
    """Command failure in git diff should raise RuntimeError when diff fails."""
    with (
        patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["git"])),
        pytest.raises(RuntimeError),
    ):
        get_git_diff("origin/main", "HEAD")


def test_run_pr_review_diff_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Workflow should return 1 when git diff extraction raises an error."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    with patch("scripts.gemini_pr_review.get_git_diff", side_effect=RuntimeError("git failed")):
        status = run_pr_review(base_ref="origin/main")
        assert status == 1


def test_build_review_prompt() -> None:
    """Prompt must include diff, title, body, and styleguide instructions."""
    diff = "+def calculate_sum(a: int, b: int) -> int:\n+    return a + b"
    styleguide = "Enforce Single Responsibility Principle."
    prompt = build_review_prompt(
        diff=diff,
        styleguide=styleguide,
        pr_title="feat: add sum",
        pr_body="Adds summation utility",
    )

    assert "feat: add sum" in prompt
    assert "Adds summation utility" in prompt
    assert "Enforce Single Responsibility Principle." in prompt
    assert "calculate_sum" in prompt
    assert "Do not use any emojis in your review." in prompt


def test_post_github_comment_gh_success() -> None:
    """Comment should be posted via gh CLI when available."""
    mock_proc = MagicMock()
    mock_proc.stdout = "https://github.com/foo/bar/pull/1#issuecomment-1"

    with patch("subprocess.run", return_value=mock_proc):
        success = post_github_comment(
            pr_number=1,
            comment="Review passed.",
            repo="foo/bar",
            github_token="fake_token",
        )
        assert success is True


def test_post_github_comment_rest_fallback() -> None:
    """When gh CLI fails, script should fall back to GitHub REST API."""
    mock_response = MagicMock()
    mock_response.status = 201
    mock_response.__enter__.return_value = mock_response

    with (
        patch("subprocess.run", side_effect=FileNotFoundError("gh not found")),
        patch("urllib.request.urlopen", return_value=mock_response),
    ):
        success = post_github_comment(
            pr_number=42,
            comment="Automated feedback",
            repo="test-owner/test-repo",
            github_token="ghp_fake",
        )
        assert success is True


def test_run_pr_review_no_api_key(monkeypatch) -> None:
    """Workflow should return 0 gracefully if GEMINI_API_KEY is missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    status = run_pr_review(base_ref="origin/main")
    assert status == 0


def test_run_pr_review_empty_diff(monkeypatch) -> None:
    """Workflow should return 0 gracefully if diff is empty."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    with patch("scripts.gemini_pr_review.get_git_diff", return_value=""):
        status = run_pr_review(base_ref="origin/main")
        assert status == 0


def test_run_pr_review_success(monkeypatch, tmp_path: Path) -> None:
    """Workflow should generate review and post comment when key and diff exist."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    styleguide_path = tmp_path / "styleguide.md"
    styleguide_path.write_text("Style rules", encoding="utf-8")

    with (
        patch("scripts.gemini_pr_review.get_git_diff", return_value="+new code line"),
        patch(
            "scripts.gemini_pr_review.call_gemini_api",
            return_value="Looks clean and well structured.",
        ),
        patch("scripts.gemini_pr_review.post_github_comment", return_value=True) as mock_post,
    ):
        status = run_pr_review(
            base_ref="origin/main",
            pr_number=10,
            repo="owner/repo",
            styleguide_path=styleguide_path,
        )
        assert status == 0
        mock_post.assert_called_once()


def test_call_gemini_api_model_fallback() -> None:
    """When the initial model fails, call_gemini_api should try fallback models."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Fallback review output"
    mock_client.models.generate_content.side_effect = [
        RuntimeError("404 Model Not Found"),
        mock_response,
    ]

    with patch("google.genai.Client", return_value=mock_client):
        result = call_gemini_api(
            prompt="Review this diff",
            api_key="test_key",
            model_name="deprecated-model",
        )
        assert result == "Fallback review output"
        assert mock_client.models.generate_content.call_count == 2


def test_call_gemini_api_falls_back_to_supported_flash_model() -> None:
    """Default model fallback should use the currently supported flash model."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Fallback review output"
    mock_client.models.generate_content.side_effect = [
        RuntimeError("503 UNAVAILABLE"),
        mock_response,
    ]

    with patch("google.genai.Client", return_value=mock_client):
        result = call_gemini_api(
            prompt="Review this diff",
            api_key="test_key",
            model_name="gemini-3.8-flash",
        )

    assert result == "Fallback review output"
    called_models = [
        call.kwargs["model"] for call in mock_client.models.generate_content.call_args_list
    ]
    assert called_models == ["gemini-3.8-flash", "gemini-2.5-flash"]
