#!/bin/sh
# Recreate compose services on request. The ONLY way .env changes take effect.
#
# WHY THIS EXISTS AS A SEPARATE CONTAINER. docker-compose reads env_file at
# container CREATE time, so `docker restart` reuses the environment baked in
# when the container was made — a saved .env change appears to apply and does
# not. Applying it requires RECREATION, which over the Docker API means
# POST /containers/create. That is precisely the call the socket proxy forbids,
# after it was proven to allow a privileged container bind-mounting /.
#
# So setup-ui never gets that power. It writes a REQUEST FILE; this container
# reads it and runs one fixed command shape. It listens on no port and accepts
# no network input. A compromised setup-ui can already write .env, so being able
# to recreate this project's own services adds little — while create rights
# would hand it the host.
#
# Service names are validated against the project's own list before use, so a
# crafted request cannot become arbitrary compose arguments.

set -eu

REQUEST=/state/apply-request.json
RESULT=/state/apply-result.json
# The repo at its HOST path — see the compose comment. Compose must run from
# here or the bind paths it generates are meaningless to the daemon.
PROJECT_DIR="${APPLIER_PROJECT_DIR:-/repo}"

echo "applier: watching $REQUEST"

while true; do
  if [ -f "$REQUEST" ]; then
    id=$(sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$REQUEST")
    services=$(sed -n 's/.*"services"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' "$REQUEST" \
               | tr -d '" ' | tr ',' ' ')
    rm -f "$REQUEST"

    cd "$PROJECT_DIR"
    known=$(docker compose config --services 2>/dev/null || true)

    valid=""
    rejected=""
    for s in $services; do
      if echo "$known" | grep -qx -- "$s"; then valid="$valid $s"; else rejected="$rejected $s"; fi
    done

    if [ -n "$rejected" ]; then
      echo "applier: rejecting unknown service(s):$rejected"
    fi

    if [ -z "$valid" ]; then
      printf '{"id":"%s","ok":false,"detail":"no valid services in request","services":""}\n' \
        "$id" > "$RESULT"
    else
      echo "applier: recreating$valid"
      # --no-build: apply configuration, never rebuild images. A setup save must
      # not silently kick off a multi-minute image build.
      if out=$(docker compose up -d --no-build $valid 2>&1); then
        printf '{"id":"%s","ok":true,"detail":"recreated","services":"%s"}\n' \
          "$id" "$(echo $valid)" > "$RESULT"
        echo "applier: ok$valid"
      else
        esc=$(echo "$out" | tail -3 | tr '\n' ' ' | sed 's/"/\\"/g')
        printf '{"id":"%s","ok":false,"detail":"%s","services":"%s"}\n' \
          "$id" "$esc" "$(echo $valid)" > "$RESULT"
        echo "applier: FAILED$valid"
      fi
    fi
  fi
  sleep 1
done
