#!/usr/bin/env bash
# Stop containers and delete the named volume (fresh admin/password next up).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
docker compose -f "$ROOT/compose.yml" down -v
rm -f "$ROOT/.token" "$ROOT/.admin-password"
echo "Stopped and wiped Artifactory data volume + local token files."
