#!/usr/bin/env bash
set -euo pipefail

# AI Video Universal Skill Installer
TARGET_DIR="${1:-.cursor/skills/ai-video}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/../skills/ai-video" && pwd)"

echo "Installing AI Video Agent Skill into: ${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"
cp -r "${SOURCE_DIR}/"* "${TARGET_DIR}/"

echo "Skill installed successfully."
echo "Agents can now interact with the AI Video Production Studio via SKILL.md."
