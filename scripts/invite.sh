#!/usr/bin/env bash
# Mint an invite and print its OTP, without sending an email.
#
#   ./scripts/invite.sh someone@example.com
#
# Supabase's built-in email sender only delivers to your project's team members,
# is rate-limited to a few messages an hour, and locks email-template editing
# behind custom SMTP -- so the stock invite mail carries a magic link and no
# code. This asks the admin API for the same invite directly: it returns the
# OTP that `landing`'s /verify page expects, and nothing is emailed.
#
# The address must not already exist. `generate_link` answers 422 email_exists
# for a registered user, and POST /api/v2/auth/verify-otp only accepts tokens of
# type "invite", so an existing account cannot be pushed back through this flow.
#
# `redirect_to` goes at the TOP LEVEL of the body. Nesting it under "options" is
# the supabase-js shape; this REST endpoint ignores it there and silently falls
# back to the project's Site URL, which looks exactly like an allow-list refusal.
set -euo pipefail

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
    echo "usage: $0 <email>" >&2
    exit 64
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
[ -f "$ENV_FILE" ] || { echo "no .env at $ENV_FILE" >&2; exit 1; }

# Read only the two values needed; `source`ing .env breaks on the multi-line
# PEM and on values containing spaces.
KEY=$(grep '^SUPABASE_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2-)
URL=$(grep '^SUPABASE_URL=' "$ENV_FILE" | cut -d= -f2-)
PORTAL=$(grep '^RECRUITER_PORTAL_URL=' "$ENV_FILE" | cut -d= -f2-)
PORTAL="${PORTAL:-http://localhost:3005}"
LANDING=$(grep '^NEXT_PUBLIC_LANDING_URL=' "$ENV_FILE" | cut -d= -f2-)
LANDING="${LANDING:-http://localhost:3000}"

[ -n "$KEY" ] && [ -n "$URL" ] || { echo "SUPABASE_SECRET_KEY / SUPABASE_URL missing from .env" >&2; exit 1; }

curl -sS -X POST "$URL/auth/v1/admin/generate_link" \
    -H "apikey: $KEY" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"invite\",\"email\":\"$EMAIL\",\"redirect_to\":\"$PORTAL/set-password\"}" \
| EMAIL="$EMAIL" LANDING="$LANDING" python3 -c '
import json, os, sys, urllib.parse

d = json.load(sys.stdin)
if "email_otp" not in d:
    print("failed:", d.get("msg") or json.dumps(d)[:300], file=sys.stderr)
    raise SystemExit(1)

email, landing = os.environ["EMAIL"], os.environ["LANDING"]
print("email :", email)
print("OTP   :", d["email_otp"])
print("enter it at:", f"{landing}/verify?email={urllib.parse.quote(email)}")
print()
print("or open the invite link directly:")
print(" ", d["action_link"])
'
