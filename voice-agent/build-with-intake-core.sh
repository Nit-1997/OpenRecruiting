#!/usr/bin/env bash
set -euo pipefail

# Stage the intake-core package next to the Dockerfile so COPY can grab it,
# then delegate the actual build to docker compose (which uses the same context),
# then clean up the staging dir.
#
# EC2 deploy workflow:
#   cd voice-agent && ./build-with-intake-core.sh
#   cd deploy-config/backend-deploy && docker compose up -d voice-agent
#
# NOTE: do NOT pass --build to docker compose up — the image is already built
# by this script and intake-core-pkg is cleaned up before compose up runs.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "==> Staging intake-core"
rm -rf intake-core-pkg
# Copy the full intake-core directory (pyproject.toml + intake_core/) so pip install works.
mkdir -p intake-core-pkg
cp -r ../intake-core/pyproject.toml intake-core-pkg/
cp -r ../intake-core/intake_core intake-core-pkg/intake_core
cp ../intake-core/README.md intake-core-pkg/ 2>/dev/null || true

echo "==> Building voice-agent via docker compose"
(
  cd ../deploy-config/backend-deploy
  docker compose build voice-agent
)

echo "==> Cleanup"
rm -rf intake-core-pkg

echo "==> Done"
