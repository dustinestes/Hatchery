#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
docker compose -f "$ROOT/compose.yml" down
echo "Stopped. Volume kept (data persists). Wipe with: $ROOT/scripts/reset.sh"
