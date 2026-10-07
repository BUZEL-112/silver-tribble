#!/usr/bin/env bash
# Deploy or mirror client layer static interface to Hugging Face Static Space
# Usage: ./scripts/deploy_huggingface_space.sh <hf-username>/<space-name>

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <username/space-name>"
  echo "Example: $0 myuser/ai-video-static"
  exit 1
fi

SPACE_REPO="$1"
TEMP_DIR="/tmp/hf-space-deploy-$$"

echo "Cloning Hugging Face Space repository: ${SPACE_REPO}..."
git clone "https://huggingface.co/spaces/${SPACE_REPO}" "${TEMP_DIR}"

echo "Copying static entrypoints..."
cp index.html "${TEMP_DIR}/index.html"
cp huggingface/README.md "${TEMP_DIR}/README.md"

cd "${TEMP_DIR}"
git add index.html README.md
if git diff --staged --quiet; then
  echo "No changes to deploy. Hugging Face Space is already up to date."
else
  git commit -m "Deploy static interface to Hugging Face Space"
  echo "Pushing changes to Hugging Face..."
  git push origin main
  echo "Successfully deployed client layer to Hugging Face Space: ${SPACE_REPO}"
fi

rm -rf "${TEMP_DIR}"
