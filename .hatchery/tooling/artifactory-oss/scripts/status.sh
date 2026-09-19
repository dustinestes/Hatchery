#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BASE="http://127.0.0.1:${ARTIFACTORY_ROUTER_PORT:-8082}/artifactory"

echo "compose:"
docker compose -f "$ROOT/compose.yml" ps || true
echo
echo "ping:"
curl -fsS "$BASE/api/system/ping" && echo || echo "(not ready)"
if [[ -f "$ROOT/.token" ]]; then
  echo
  echo "token file: $ROOT/.token ($(wc -c <"$ROOT/.token") bytes)"
fi
