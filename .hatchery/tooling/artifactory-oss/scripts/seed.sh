#!/usr/bin/env bash
# Upload Hatchery fixtures and mint a Bearer access token.
#
# Artifactory OSS cannot create repositories via REST (Pro-only). Seed uses the
# built-in ``example-repo-local`` generic repo that ships with OSS.
#
# Prerequisites: container up and ping OK; admin password already changed
# (Artifactory forces this on first UI login).
#
#   ARTIFACTORY_PASSWORD='…' ./seed.sh
#
# Optional:
#   ARTIFACTORY_USER=admin
#   ARTIFACTORY_ROUTER_PORT=8082
#   ARTIFACTORY_REPO=example-repo-local
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ARTIFACTORY_ROUTER_PORT:-8082}"
BASE="http://127.0.0.1:${PORT}/artifactory"
USER="${ARTIFACTORY_USER:-admin}"
PASS="${ARTIFACTORY_PASSWORD:-}"
REPO="${ARTIFACTORY_REPO:-example-repo-local}"

if [[ -z "$PASS" ]]; then
  if [[ -f "$ROOT/.admin-password" ]]; then
    PASS="$(tr -d '\r\n' <"$ROOT/.admin-password")"
  fi
fi
if [[ -z "$PASS" ]]; then
  cat >&2 <<EOF
Set ARTIFACTORY_PASSWORD to the admin password (after first UI change), e.g.:

  ARTIFACTORY_PASSWORD='YourNewPass' $ROOT/scripts/seed.sh

Or write it once to $ROOT/.admin-password (gitignored).
EOF
  exit 1
fi

"$ROOT/scripts/wait-ready.sh"

auth_curl() {
  curl -fsS -u "${USER}:${PASS}" "$@"
}

echo "Using OSS local repo: ${REPO}"
get_code="$(curl -sS -o /dev/null -w "%{http_code}" -u "${USER}:${PASS}" \
  "$BASE/api/repositories/${REPO}" || true)"
if [[ "$get_code" != "200" ]]; then
  cat >&2 <<EOF
Repository '${REPO}' not found (HTTP ${get_code}).
OSS ships with example-repo-local. Create another generic local repo in the UI
if you need a custom key, then re-run with ARTIFACTORY_REPO=your-key.
EOF
  exit 1
fi

echo "Uploading fixtures…"
auth_curl -X PUT "$BASE/${REPO}/samples/tiny.iso" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @"$ROOT/fixtures/media/tiny.iso" >/dev/null
echo "  ${REPO}/samples/tiny.iso"
auth_curl -X PUT "$BASE/${REPO}/samples/hello.ps1" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @"$ROOT/fixtures/scripts/hello.ps1" >/dev/null
echo "  ${REPO}/samples/hello.ps1"

echo "Minting access token (legacy /api/security/token — Basic auth works on OSS)…"
# Access /api/v1/tokens rejects Basic ("Unsupported authentication method Basic").
token_json="$(auth_curl -X POST "$BASE/api/security/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=${USER}" \
  --data-urlencode "scope=member-of-groups:*" \
  --data-urlencode "expires_in=0")"

token="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' <<<"$token_json")"
printf '%s\n' "$token" >"$ROOT/.token"
chmod 600 "$ROOT/.token"
printf '%s\n' "$PASS" >"$ROOT/.admin-password"
chmod 600 "$ROOT/.admin-password"

echo
echo "=== Hatchery Settings ==="
echo "Library: enabled"
echo "Type: API"
echo "Provider: Artifactory"
echo "Base URI: ${BASE}"
echo "Token: (saved to $ROOT/.token — paste into Settings)"
echo
echo "Example bindings:"
echo "  media   filter: ${REPO}/**/*.iso"
echo "  scripts filter: ${REPO}/**/*.ps1"
echo
echo "Quick ping with token:"
echo "  curl -fsS -H \"Authorization: Bearer \$(cat $ROOT/.token)\" ${BASE}/api/system/ping && echo"
