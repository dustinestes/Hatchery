<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: library</h1>
<br clear="both">

Code: [`lib/cli/library.py`](../../lib/cli/library.py). Parent: [CLI index](README.md). Issues: [#434](https://github.com/dustinestes/Hatchery/issues/434), [#440](https://github.com/dustinestes/Hatchery/issues/440). ADR: [ADR-0011](../adr/0011-library-consume-only-no-clutch-roundtrip.md), [ADR-0016](../adr/0016-library-operator-plane.md), [ADR-0022](../adr/0022-dual-surface-operator-discipline.md). Product how-to: [library.md](../library.md).

<br>

## Purpose

Operator CLI for the Library plane: convenience enable/disable (Settings `library_enabled`), connection and binding CRUD on first-class tables, plus **consume** verbs for Available Content (list / connection test / pull into operator cache).

Consume-only: no forge push or Clutch round-trip ([ADR-0011](../adr/0011-library-consume-only-no-clutch-roundtrip.md)). Cache sync/reattach remain UI / follow-on.

<br>

## Usage

```bash
uv run hatchery library [--data-dir PATH] enable|disable
uv run hatchery library [--data-dir PATH] connection list|show|add|remove|test …
uv run hatchery library [--data-dir PATH] binding list|show|add|remove …
uv run hatchery library [--data-dir PATH] content list|pull …
uv run hatchery --json library connection list
uv run hatchery library connection add --help
```

| Command | Notes |
|---|---|
| `enable` / `disable` | Calls `settings_io.set_exportable_setting("library_enabled", …)` - same SoR as `settings set` |
| `connection list\|show` | Read registry (works while Library is disabled) |
| `connection add\|remove\|test` | Requires Library enabled; `add` upserts by `--id` (optional; auto-id like UI); `test` uses shared `library.test_connection` |
| `binding *` | Same enable gate on mutate; `--domain` filter on list |
| `content list` | Available Content catalog from bindings (`--domain` required); optional `--connection`, media `--target` |
| `content pull` | Create-only pull into operator cache; requires `--connection` + `--path`; media needs `--target` |

Deeper disable/excise teardown (clear links/content/registry) remains UI / follow-on ([ADR-0019](../adr/0019-library-disable-excise.md)).

Local Controller cache inventory (`hatchery scripts list` / `media list`) is **not** the Library Content catalog.

<br>

## Connection `add` flags

| Flag | Required | Accepted values |
|---|---|---|
| `--id` | no | Stable id string. Omit to auto-generate (same as UI). Pass to upsert or restore a known id for re-linking bindings |
| `--type` | yes | `path` · `https` · `api` · `forge` (classic `git` removed - ADR-0020) |
| `--base-uri` | yes | Absolute filesystem path (`path`) or HTTPS URL (`https` / `api` / `forge`) |
| `--kinds` | yes | Comma-separated from `scripts`, `clutches`, `media`, `packages` |
| `--label` | no | Display name (defaults to `--id`) |
| `--provider` | for `api` / `forge` | Adapter id: forge `github`; api `artifactory` (omit for `path` / `https`) |
| `--token` | no | Auth token for `api` / `forge` (stored in SQLite; prefer env/secret workflows later) |

`--help` on `connection add` lists the same `--type` choices. Unknown `--provider` fails with the known adapter list from the registry.

### Examples

```bash
# Local share of scripts + clutches (id auto-generated; printed on success)
uv run hatchery library enable
uv run hatchery library connection add \
  --label "Lab share" \
  --type path \
  --base-uri /path/to/share \
  --kinds scripts,clutches

# Restore / upsert a known id (e.g. re-link bindings after recreate)
uv run hatchery library connection add \
  --id local-share \
  --label "Lab share" \
  --type path \
  --base-uri /path/to/share \
  --kinds scripts,clutches

# GitHub forge (sample Hatchery Library style)
uv run hatchery library connection add \
  --id hatchery-library \
  --type forge \
  --provider github \
  --base-uri https://github.com/dustinestes/Hatchery-Library \
  --kinds scripts,clutches,media \
  --token "$GITHUB_TOKEN"

uv run hatchery library connection test local-share
```

<br>

## Binding `add` flags

| Flag | Required | Accepted values |
|---|---|---|
| `--id` | no | Stable binding id. Omit to auto-generate; pass to upsert/restore |
| `--connection-id` | yes | Existing connection id |
| `--domain` | yes | `scripts` · `clutches` · `media` |
| `--filter` | yes | Glob relative to the connection (e.g. `*.ps1`, `clutches/*.yaml`, `*`) |
| `--label` | no | Display name (defaults to `--filter`) |
| `--target` | media only | `iso` · `virtio` (default `iso`) |

The connection must already include the matching kind (e.g. `--domain scripts` needs `scripts` in `--kinds`).

### Example

```bash
uv run hatchery library binding add \
  --id scripts-all \
  --connection-id local-share \
  --domain scripts \
  --filter "*.ps1" \
  --label "All PowerShell"
```

<br>

## Content `list` / `pull`

Same shared Library lib as the UI (`catalog_*`, `pull_*`). Pull is **create-only** (second pull of the same basename fails until cache sync/overwrite lands elsewhere).

| Flag | Commands | Required | Accepted values |
|---|---|---|---|
| `--domain` | list, pull | yes | `scripts` · `clutches` · `media` |
| `--connection` | list (optional), pull (required) | pull | Connection id |
| `--path` | pull | yes | Relative path from catalog (`relative_path`) |
| `--binding-id` | pull | no | Provenance attribution |
| `--target` | list (optional), pull (media required) | media pull | `iso` · `virtio` |

### Examples

```bash
uv run hatchery library content list --domain scripts
uv run hatchery --json library content list --domain scripts --connection local-share

uv run hatchery library content pull \
  --domain scripts \
  --connection local-share \
  --path hello.ps1 \
  --binding-id scripts-all

# Media
uv run hatchery library content pull \
  --domain media \
  --connection local-share \
  --path images/guest.iso \
  --target iso
```

`--json` shapes: connection test `{connection_id, ok, message}`; content list `{domain, items: […]}`; content pull `{domain, imported, sha256, dest}`.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
