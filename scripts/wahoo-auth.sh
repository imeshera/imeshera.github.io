#!/usr/bin/env bash
# Generate a Wahoo Cloud API refresh token for GitHub Actions.
# Requires curl, python3, and your Wahoo app credentials from
# https://developers.wahooligan.com/cloud
set -euo pipefail

REDIRECT_URI="${WAHOO_REDIRECT_URI:-https://localhost}"
SCOPES="user_read workouts_read"

prompt_or_env() {
  local prompt="$1"
  local var_name="$2"
  if [ -n "${!var_name:-}" ]; then
    printf '%s\n' "${!var_name}"
    return
  fi
  printf '%s' "$prompt" >&2
  local value=""
  IFS= read -r value
  printf '%s\n' "$value"
}

CLIENT_ID="$(prompt_or_env 'Wahoo Client ID: ' WAHOO_CLIENT_ID)"
CLIENT_SECRET="$(prompt_or_env 'Wahoo Client Secret: ' WAHOO_CLIENT_SECRET)"

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  echo "Client ID and Client Secret are required." >&2
  exit 1
fi

ENCODED_REDIRECT="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REDIRECT_URI")"
ENCODED_SCOPES="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$SCOPES")"
AUTH_URL="https://api.wahooligan.com/oauth/authorize?client_id=${CLIENT_ID}&response_type=code&redirect_uri=${ENCODED_REDIRECT}&scope=${ENCODED_SCOPES}"

echo
echo "1. Open this URL, sign in to Wahoo, and authorize the app:"
echo
echo "$AUTH_URL"
echo
echo "2. You will land on a localhost URL that fails to load. That is expected."
echo "   Copy the full redirect URL (it contains ?code=...)."
echo
printf 'Paste the redirect URL: '
IFS= read -r REDIRECT_URL

AUTH_CODE="$(python3 - "$REDIRECT_URL" <<'PY'
import sys
from urllib.parse import parse_qs, urlparse
code = parse_qs(urlparse(sys.argv[1]).query).get("code", [""])[0]
if not code:
    raise SystemExit("No ?code= parameter found in that URL.")
print(code)
PY
)"

TOKEN_RESPONSE="$(curl -sS -X POST https://api.wahooligan.com/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "client_id=${CLIENT_ID}" \
  --data-urlencode "client_secret=${CLIENT_SECRET}" \
  --data-urlencode "code=${AUTH_CODE}" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "redirect_uri=${REDIRECT_URI}")"

python3 - "$TOKEN_RESPONSE" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
refresh = data.get("refresh_token")
if not refresh:
    raise SystemExit("Wahoo did not return a refresh token:\n" + json.dumps(data, indent=2))
print()
print("Refresh token:")
print(refresh)
print()
print("Next steps:")
print("1. GitHub repo → Settings → Secrets and variables → Actions")
print("2. Set WAHOO_CLIENT_ID, WAHOO_CLIENT_SECRET, and WAHOO_REFRESH_TOKEN")
print("3. Delete wahoo-token.enc if it exists")
print("4. Run the 'Update Wahoo Activities' workflow")
PY
