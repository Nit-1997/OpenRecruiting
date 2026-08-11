#!/usr/bin/env bash
set -euo pipefail

# Stage the shared packages next to the Dockerfile so COPY can grab them, then
# delegate the actual build to docker compose (which uses the same context),
# then clean up the staging dirs.
#
# EC2 deploy workflow:
#   cd voice-agent && ./build-with-intake-core.sh
#   cd deploy-config/backend-deploy && docker compose up -d voice-agent
#
# NOTE: do NOT pass --build to docker compose up — the image is already built
# by this script and the *-pkg staging dirs are cleaned up before compose up runs.
#
# ── THIS SCRIPT IS NOT THE COMPOSE BUILD, AND IT COULD NOT BE RUN HERE ────────
# The docker-compose.yml at the repo root builds voice-agent with the REPO ROOT
# as context and copies intake-core/ and llm-core/ straight from the tree
# (voice-agent/Dockerfile:27-35) — it needs no staging at all. This script
# targets a DIFFERENT compose file, deploy-config/backend-deploy/docker-compose.yml,
# which is not present in this checkout. Its Dockerfile therefore cannot be read
# or built here, and this script was NOT executed as part of phase 7.
#
# llm-core staging was added in phase 7 to repair a break introduced in PHASE 3,
# when the intake coverage tracker started importing llm_core (src/main.py) —
# from that commit until this one, this path could only ever produce an image
# that raised ModuleNotFoundError at the first intake turn. Phase 7 adds a second
# reason: src/pipeline/services.py imports llm_core.settings to reach the gateway.
# Staged rather than deleted per CHECKPOINT's B5 rule — `aws sts
# get-caller-identity` cannot authenticate here, so no deploy path can be PROVEN
# dead, and fixing one is always safe where deleting one is not.
#
# The staged layout mirrors what the compose Dockerfile expects to install, but
# the deploy-config Dockerfile's own COPY lines are unverified from here. If that
# file copies `intake-core-pkg` only, it needs one more COPY for `llm-core-pkg`.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo "==> Staging intake-core"
rm -rf intake-core-pkg
# Copy the full intake-core directory (pyproject.toml + intake_core/) so pip install works.
mkdir -p intake-core-pkg
cp -r ../intake-core/pyproject.toml intake-core-pkg/
cp -r ../intake-core/intake_core intake-core-pkg/intake_core
cp ../intake-core/README.md intake-core-pkg/ 2>/dev/null || true

echo "==> Staging llm-core"
rm -rf llm-core-pkg
# Same shape as intake-core above: pyproject.toml + the package dir, so that a
# plain `pip install ./llm-core-pkg` resolves. Required since phase 3 — see the
# header. Fail loudly rather than build an image that dies on the first turn.
if [ ! -d ../llm-core/llm_core ]; then
  echo "ERROR: ../llm-core/llm_core not found. voice-agent imports llm_core in" >&2
  echo "       src/main.py (coverage tracker) and src/pipeline/services.py" >&2
  echo "       (gateway settings); an image built without it raises" >&2
  echo "       ModuleNotFoundError at the first intake turn." >&2
  exit 1
fi
mkdir -p llm-core-pkg
cp -r ../llm-core/pyproject.toml llm-core-pkg/
cp -r ../llm-core/llm_core llm-core-pkg/llm_core
cp ../llm-core/README.md llm-core-pkg/ 2>/dev/null || true

echo "==> Building voice-agent via docker compose"
(
  cd ../deploy-config/backend-deploy
  docker compose build voice-agent
)

echo "==> Cleanup"
rm -rf intake-core-pkg llm-core-pkg

echo "==> Done"
