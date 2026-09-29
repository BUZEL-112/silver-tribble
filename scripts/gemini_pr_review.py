"""Automated pull request reviewer using Google Gemini.

Reads git diff for the pull request, applies repository styleguide rules,
generates a code review via the Gemini API, and publishes the review to GitHub.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure structured logging for review execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_styleguide(styleguide_path: Path) -> str:
    """Load styleguide instructions from disk.

    Args:
        styleguide_path: Path to the styleguide markdown file.

    Returns:
        String content of the styleguide, or empty string if not found.
    """
    if not styleguide_path.exists():
        logger.warning("Styleguide not found at %s", styleguide_path)
        return ""
    try:
        return styleguide_path.read_text(encoding="utf-8").strip()
    except OSError as err:
        logger.error("Failed to read styleguide at %s: %s", styleguide_path, err)
        return ""


def get_git_diff(base_ref: str, head_ref: str = "HEAD", max_chars: int = 50000) -> str:
    """Extract git diff between base_ref and head_ref.

    Args:
        base_ref: Base git reference (e.g. origin/main).
        head_ref: Head git reference (default HEAD).
        max_chars: Maximum character limit for returned diff.

    Returns:
        The git diff string, truncated if exceeding max_chars.
    """
    cmd = ["git", "diff", f"{base_ref}...{head_ref}"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        diff_text = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        logger.warning(
            "Triple-dot diff %s...%s failed: %s. Trying two-dot diff.",
            base_ref,
            head_ref,
            err,
        )
        try:
            fallback = subprocess.run(
                ["git", "diff", base_ref, head_ref],
                capture_output=True,
                text=True,
                check=True,
            )
            diff_text = fallback.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as fallback_err:
            logger.error("Failed to extract git diff: %s", fallback_err)
            raise RuntimeError(
                f"Failed to extract git diff between {base_ref} and {head_ref}: {fallback_err}"
            ) from fallback_err

    if len(diff_text) > max_chars:
        logger.info("Diff truncated from %d to %d characters.", len(diff_text), max_chars)
        diff_text = diff_text[:max_chars] + "\n\n[Diff truncated due to size limits]"

    return diff_text


def build_review_prompt(
    diff: str,
    styleguide: str,
    pr_title: str = "",
    pr_body: str = "",
) -> str:
    """Build the prompt for Gemini review.

    Args:
        diff: The git diff string.
        styleguide: Guidelines from .gemini/styleguide.md.
        pr_title: Pull request title.
        pr_body: Pull request body or description.

    Returns:
        Formatted prompt string.
    """
    prompt_parts = [
        "You are an expert automated code reviewer evaluating a pull request.",
        "Conduct a thorough, constructive, and actionable code review.",
        "",
        "Review constraints:",
        "1. Do not use any emojis in your review.",
        "2. Do not use em-dashes. Use hyphens, commas, or parentheses instead.",
        "3. Verify adherence to Single Responsibility Principle (SRP) and separation of concerns.",
        "4. Verify type hints and explicit interfaces.",
        "5. Identify potential runtime errors, edge cases, and missing test coverage.",
        "6. Provide concrete suggestions or code snippets where improvements are needed.",
        "",
    ]

    if styleguide:
        prompt_parts.extend(
            [
                "### Repository Styleguide and Architectural Standards:",
                styleguide,
                "",
            ]
        )

    if pr_title:
        prompt_parts.extend([f"### Pull Request Title: {pr_title}", ""])
    if pr_body:
        prompt_parts.extend([f"### Pull Request Description:\n{pr_body}", ""])

    prompt_parts.extend(
        [
            "### Code Changes (Git Diff):",
            "```diff",
            diff,
            "```",
            "",
            "Structure your response in Markdown with the following sections:",
            "## Summary of Changes",
            "## Architecture and Design Compliance",
            "## Potential Issues and Edge Cases",
            "## Recommendations and Action Items",
        ]
    )

    return "\n".join(prompt_parts)


def call_gemini_api(
    prompt: str,
    api_key: str,
    model_name: str = "gemini-3.8-flash",
) -> str:
    """Call Google Gemini API using google-genai SDK.

    Args:
        prompt: Review prompt.
        api_key: Gemini API key.
        model_name: Model identifier.

    Returns:
        Review content string generated by Gemini.
    """
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
        return response.text or ""
    except Exception as err:
        logger.error("Gemini API call failed for model %s: %s", model_name, err)
        fallback_models = ["gemini-3.8-flash", "gemini-2.5-flash"]
        for fallback in fallback_models:
            if fallback != model_name:
                logger.info("Attempting fallback to model %s...", fallback)
                try:
                    response = client.models.generate_content(
                        model=fallback,
                        contents=prompt,
                        config=config,
                    )
                    return response.text or ""
                except Exception as fallback_err:
                    logger.warning("Fallback model %s failed: %s", fallback, fallback_err)
        raise


def post_github_comment(
    pr_number: int,
    comment: str,
    repo: str | None = None,
    github_token: str | None = None,
) -> bool:
    """Post review comment to GitHub PR via gh CLI or REST API.

    Args:
        pr_number: Pull request number.
        comment: Review comment markdown body.
        repo: Repository slug in owner/repo format.
        github_token: GitHub token for authentication.

    Returns:
        True if comment was posted successfully, False otherwise.
    """
    token = github_token or os.environ.get("GITHUB_TOKEN")

    # Try gh CLI first
    try:
        env = os.environ.copy()
        if token:
            env["GITHUB_TOKEN"] = token
        cmd = ["gh", "pr", "comment", str(pr_number), "--body", comment]
        if repo:
            cmd.extend(["--repo", repo])
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        logger.info("Successfully posted comment via gh CLI: %s", res.stdout.strip())
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as gh_err:
        logger.warning("gh CLI comment failed: %s. Trying GitHub REST API.", gh_err)

    # Fallback to GitHub REST API
    if not token or not repo:
        logger.error("Cannot use GitHub REST API: GITHUB_TOKEN or repo not provided.")
        return False

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gemini-pr-reviewer",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"body": comment}).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req) as resp:
            if resp.status in (200, 201):
                logger.info("Successfully posted comment via GitHub REST API.")
                return True
            logger.error("GitHub REST API returned status %d", resp.status)
            return False
    except urllib.error.URLError as url_err:
        logger.error("GitHub REST API request failed: %s", url_err)
        return False


def run_pr_review(
    base_ref: str,
    head_ref: str = "HEAD",
    pr_number: int | None = None,
    repo: str | None = None,
    model_name: str = "gemini-3.8-flash",
    styleguide_path: Path | None = None,
    pr_title: str = "",
    pr_body: str = "",
) -> int:
    """Execute the PR review workflow.

    Args:
        base_ref: Base git reference.
        head_ref: Head git reference.
        pr_number: Optional PR number for posting review.
        repo: Optional repository slug (owner/repo).
        model_name: Gemini model identifier.
        styleguide_path: Optional path to styleguide file.
        pr_title: Optional PR title.
        pr_body: Optional PR description.

    Returns:
        0 on success or graceful skip, non-zero on failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning(
            "GEMINI_API_KEY is not configured. "
            "Please configure the GEMINI_API_KEY secret in repository settings "
            "to enable Gemini reviews."
        )
        return 0

    try:
        diff = get_git_diff(base_ref, head_ref)
    except Exception as err:
        logger.error("Failed to extract diff for review: %s", err)
        return 1

    if not diff:
        logger.info("No code diff found between %s and %s. Skipping review.", base_ref, head_ref)
        return 0

    target_styleguide = styleguide_path or Path(".gemini/styleguide.md")
    styleguide = load_styleguide(target_styleguide)

    prompt = build_review_prompt(
        diff=diff,
        styleguide=styleguide,
        pr_title=pr_title,
        pr_body=pr_body,
    )

    logger.info("Requesting review from Gemini model %s...", model_name)
    try:
        review_text = call_gemini_api(prompt=prompt, api_key=api_key, model_name=model_name)
    except Exception as err:
        logger.error("Failed to generate review from Gemini: %s", err)
        return 1

    formatted_review = (
        "### Gemini Code Assist Review\n\n"
        f"{review_text}\n\n"
        "---\n"
        "*Automated review generated by Gemini Code Assist reviewer.*"
    )

    if pr_number:
        logger.info("Posting review to PR #%d...", pr_number)
        success = post_github_comment(
            pr_number=pr_number,
            comment=formatted_review,
            repo=repo,
        )
        if not success:
            logger.error("Failed to post comment to PR #%d.", pr_number)
            return 1
    else:
        print("\n" + formatted_review + "\n")

    return 0


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the PR reviewer.

    Args:
        args: Command line argument list.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(description="Automated PR reviewer using Google Gemini.")
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("GITHUB_BASE_REF", "origin/main"),
        help="Base git reference (e.g. origin/main).",
    )
    parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Head git reference (default HEAD).",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=int(os.environ.get("PR_NUMBER", "0")) or None,
        help="Pull request number to comment on.",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub repository slug (owner/repo).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model to use for review.",
    )
    parser.add_argument(
        "--styleguide",
        type=Path,
        default=Path(".gemini/styleguide.md"),
        help="Path to styleguide markdown file.",
    )
    parser.add_argument(
        "--pr-title",
        default=os.environ.get("PR_TITLE", ""),
        help="Pull request title.",
    )
    parser.add_argument(
        "--pr-body",
        default=os.environ.get("PR_BODY", ""),
        help="Pull request description.",
    )
    return parser.parse_args(args)


def main() -> None:
    """Script entry point."""
    setup_logging()
    parsed = parse_args()
    code = run_pr_review(
        base_ref=parsed.base_ref,
        head_ref=parsed.head_ref,
        pr_number=parsed.pr_number,
        repo=parsed.repo,
        model_name=parsed.model,
        styleguide_path=parsed.styleguide,
        pr_title=parsed.pr_title,
        pr_body=parsed.pr_body,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
