#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Run: $ROOT/scripts/install-docker.sh" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Cannot talk to the Docker daemon. Is it running? Are you in the docker group?" >&2
  echo "Try: sudo systemctl start docker && newgrp docker" >&2
  exit 1
fi

echo "Pulling / starting Artifactory OSS (first boot is slow)…"
docker compose -f "$ROOT/compose.yml" up -d
echo
echo "Waiting for ping…"
"$ROOT/scripts/wait-ready.sh"
echo
echo "UI:  http://127.0.0.1:${ARTIFACTORY_ROUTER_PORT:-8082}/"
echo "API: http://127.0.0.1:${ARTIFACTORY_ROUTER_PORT:-8082}/artifactory"
echo
echo "Default login is admin / password — change it on first UI visit, then:"
echo "  ARTIFACTORY_PASSWORD='YourNewPass' $ROOT/scripts/seed.sh"
