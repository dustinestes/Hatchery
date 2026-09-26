<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: session</h1>
<br clear="both">

Code: [`lib/cli/session.py`](../../lib/cli/session.py). Parent: [CLI index](README.md). Issue: [#421](https://github.com/dustinestes/Hatchery/issues/421). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Inspect hatch **sessions** stored in the Controller database (distinct from live Nest VM inventory and from `hatchery hatch`).

<br>

## Usage

```bash
uv run hatchery session [--data-dir PATH] list [--nest <id>]
uv run hatchery session [--data-dir PATH] show <session-id>
uv run hatchery session [--data-dir PATH] retry <session-id> <vm-name>
uv run hatchery --json session list
uv run hatchery --json session show <session-id>
```

`list` / `show` honor global `--json` (field names in [CLI index](README.md#machine-readable-output---json)). `retry` stays text-only.

| Command | Notes |
|---|---|
| `list` | Active (non-archived) sessions; all registered Nests unless `--nest` is set |
| `show` | Clutch/nest metadata, per-VM status, last ~10 events per VM |
| `retry` | Re-run failed provisioning for one VM (same path as the UI retry API) |

Inspect (`list` / `show`) is read-only: the data directory must already exist. `retry` may create Controller state via mutate bootstrap when needed - it uses the same inspect bootstrap today (existing data dir).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
