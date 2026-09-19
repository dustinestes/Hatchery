#!/usr/bin/env bash
# Block until Artifactory /api/system/ping returns OK.
set -euo pipefail
PORT="${ARTIFACTORY_ROUTER_PORT:-8082}"
URL="http://127.0.0.1:${PORT}/artifactory/api/system/ping"
# First boot with Postgres schema init can take ~5–10 minutes on a slow machine.
TRIES="${ARTIFACTORY_WAIT_TRIES:-120}"
SLEEP_S="${ARTIFACTORY_WAIT_SLEEP:-5}"

for ((i = 1; i <= TRIES; i++)); do
  if body="$(curl -fsS "$URL" 2>/dev/null)" && [[ "$body" == "OK" ]]; then
    echo "Artifactory ready (${i} checks): $URL → OK"
    exit 0
  fi
  printf '  waiting (%d/%d)…\n' "$i" "$TRIES"
  sleep "$SLEEP_S"
done

echo "Timed out waiting for $URL" >&2
echo "Check: docker logs hatchery-artifactory" >&2
exit 1
