# Local Artifactory OSS (Library API manual test)

Contributor tooling to run [JFrog Artifactory OSS](https://jfrog.com/community/download-artifactory-oss/) in Docker so you can exercise Hatchery’s Library connection **type API / provider Artifactory** without a corporate instance. Product docs: [library.md — Artifactory](../../docs/library.md#artifactory-provider).

Not for consumer Controller installs (#273).

## One-time: install Docker

If Docker was removed (or never installed):

```bash
.hatchery/tooling/artifactory-oss/scripts/install-docker.sh
```

Then **log out and back in** (or `newgrp docker`) so your user can talk to the daemon without `sudo`.

Needs free disk for the images (~2–4 GiB) and roughly **3–4 GiB RAM** while Artifactory + Postgres are running. Artifactory 7.90+ **requires PostgreSQL** (this compose includes `postgres:15-alpine`). On public Wi‑Fi, Docker’s bridge/iptables can still surprise some networks — stop the stack when you do not need it (`scripts/down.sh`).

## Start / seed / stop

From the repo root:

```bash
# Start (pull image + wait until /api/system/ping is OK)
.hatchery/tooling/artifactory-oss/scripts/up.sh

# First boot only: open the UI and change the default password
#   http://127.0.0.1:8082/   →  admin / password
# Then seed repos + fixtures + Bearer token:
ARTIFACTORY_PASSWORD='YourNewPass' .hatchery/tooling/artifactory-oss/scripts/seed.sh

# Optional: keep the password for re-seed (gitignored)
# echo 'YourNewPass' > .hatchery/tooling/artifactory-oss/.admin-password

# Status / stop (keep data) / wipe everything
.hatchery/tooling/artifactory-oss/scripts/status.sh
.hatchery/tooling/artifactory-oss/scripts/down.sh
.hatchery/tooling/artifactory-oss/scripts/reset.sh
```

`seed.sh` writes a Bearer token to `.hatchery/tooling/artifactory-oss/.token` (gitignored).

## Hatchery Settings

| Field | Value |
|---|---|
| Library | enabled |
| Type | **API** |
| Provider | **Artifactory** |
| Base URI | `http://127.0.0.1:8082/artifactory` |
| Token | contents of `.token` from seed |
| Binding (media) | connection above, filter `example-repo-local/**/*.iso` |
| Binding (scripts) | filter `example-repo-local/**/*.ps1` |

Then **Test connection** (expects ping OK), browse/pull from Library.

Smoke check outside Hatchery:

```bash
BASE=http://127.0.0.1:8082/artifactory
TOKEN=$(cat .hatchery/tooling/artifactory-oss/.token)
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/api/system/ping" && echo
```

## What seed creates

OSS cannot create repositories via REST (Pro-only). Seed uses the built-in **`example-repo-local`** repo.

| Path | Artifact |
|---|---|
| `example-repo-local/samples/tiny.iso` | media fixture |
| `example-repo-local/samples/hello.ps1` | scripts fixture |

Token is minted via `POST …/artifactory/api/security/token` (Access `/api/v1/tokens` rejects Basic auth on this OSS build).

Optional: create another generic local repo in the UI, then `ARTIFACTORY_REPO=your-key ./scripts/seed.sh`.

## Ports / image

| | Default |
|---|---|
| Router / UI / API front door | `8082` (`ARTIFACTORY_ROUTER_PORT`) |
| Artifactory service | `8081` (`ARTIFACTORY_HTTP_PORT`) |
| Image | `releases-docker.jfrog.io/jfrog/artifactory-oss:7.104.14` (`ARTIFACTORY_VERSION`) + `postgres:15-alpine` |

Override via env when calling the scripts, e.g. `ARTIFACTORY_ROUTER_PORT=18082 ./scripts/up.sh`.

## Troubleshooting

| Symptom | What to try |
|---|---|
| `permission denied` talking to Docker | `newgrp docker` or re-login after install |
| Ping never becomes OK | `docker logs hatchery-artifactory` — first start can take several minutes; ensure Postgres is healthy (`docker ps`) |
| `DB Type derby is not allowed` | You are on an old single-container compose — use this repo’s compose (includes Postgres) and `./scripts/reset.sh` |
| Seed auth fails | Use the **new** admin password after the forced UI change; default `password` stops working |
| Port in use | Set `ARTIFACTORY_ROUTER_PORT` / `ARTIFACTORY_HTTP_PORT` and use that host port in Hatchery base URI |
| Need a clean slate | `./scripts/reset.sh` then `up` + password change + `seed` again |
