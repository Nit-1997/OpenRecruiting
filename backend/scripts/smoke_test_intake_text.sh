#!/usr/bin/env bash
# Smoke test: POST a text message and watch SSE stream back.
# Requires: API_URL, TEST_USER_JWT, SESSION_ID (a ready/active session created
# via Phase 1 form flow).
#
# Usage:
#   API_URL=http://localhost:8004 TEST_USER_JWT=<jwt> SESSION_ID=<uuid> \
#     ./scripts/smoke_test_intake_text.sh "hello, ready to start"

set -euo pipefail

API_URL="${API_URL:-http://localhost:8004}"
JWT="${TEST_USER_JWT:?must set TEST_USER_JWT}"
SESSION_ID="${SESSION_ID:?must set SESSION_ID (a ready/active intake session)}"
MESSAGE="${1:-Hello}"

echo "==> POSTing text message to $API_URL/api/v2/intake/sessions/$SESSION_ID/text/messages"
echo "    message: $MESSAGE"
echo

curl -N -s \
    -X POST \
    -H "Authorization: Bearer $JWT" \
    -H "Content-Type: application/json" \
    -H "Accept: text/event-stream" \
    -d "$(jq -n --arg msg "$MESSAGE" '{message:$msg}')" \
    "$API_URL/api/v2/intake/sessions/$SESSION_ID/text/messages"

echo
echo "==> Stream ended."
