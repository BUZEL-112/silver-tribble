"""Pre-deployment security audit scanner for newsroom_ai.

Validates that no credentials, tokens, .env files, private keys,
or unindexed sensitive binaries are staged or tracked in git before pushing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Patterns indicating potential credential leakage
SECRET_PATTERNS = [
    (r"AIzaSy[0-9A-Za-z\-_]{33}", "Google API Key"),
    (r"sk-proj-[0-9A-Za-z\-_]{32,}", "OpenAI Project Key"),
    (r"sk-[0-9A-Za-z]{32,}", "Generic Secret Key"),
    (r"ghp_[0-9A-Za-z]{36}", "GitHub Personal Access Token"),
    (r"xox[baprs]-[0-9A-Za-z\-]+", "Slack Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----", "Private Key"),
]

BLOCKED_FILES = [
    ".env",
    ".env.local",
    "config.yaml",
    "id_rsa",
    "id_ed25519",
]


def check_git_status() -> list[str]:
    """Inspect git status for blocked files or untracked sensitive assets."""
    violations: list[str] = []
    res = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        return ["Failed to execute git status"]

    lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
    for line in lines:
        if not line.strip():
            continue
        filepath = line[3:].strip()
        path_obj = Path(filepath)

        # Check against blocked filenames
        if path_obj.name in BLOCKED_FILES:
            violations.append(f"Blocked file detected in status: {filepath}")

        # Check against dangerous file extensions
        if path_obj.suffix in [".pem", ".key", ".p12", ".pfx", ".db", ".sqlite3"]:
            violations.append(f"Sensitive extension detected: {filepath}")

    return violations


def scan_diff_for_secrets() -> list[str]:
    """Inspect git diff for accidental secret insertions."""
    violations: list[str] = []
    res = subprocess.run(["git", "diff", "HEAD"], capture_output=True, text=True, check=False)
    if res.returncode != 0:
        # Fallback to plain diff if HEAD not initialized
        res = subprocess.run(["git", "diff"], capture_output=True, text=True, check=False)

    diff_lines = res.stdout.split("\n")
    for line in diff_lines:
        if not line.startswith("+") or line.startswith("+++"):
            continue

        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, line):
                # Ignore mock or placeholder documentation strings
                lower_line = line.lower()
                if any(k in lower_line for k in ("your_", "dummy", "placeholder")):
                    continue
                violations.append(f"Detected potential {label} in added line: {line[:60]}...")

    return violations


def main() -> int:
    """Run all pre-deployment security checks."""
    print("Running newsroom_ai pre-deployment security audit...")
    all_violations: list[str] = []

    status_violations = check_git_status()
    all_violations.extend(status_violations)

    diff_violations = scan_diff_for_secrets()
    all_violations.extend(diff_violations)

    if all_violations:
        print("[FAIL] Security audit failed. The following risks were detected:")
        for v in all_violations:
            print(f"  - {v}")
        print("Resolve these issues before pushing to GitHub.")
        return 1

    print("[OK] Security audit passed. No secrets or blocked files detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
