<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: nest</h1>
<br clear="both">

Code: [`lib/cli/nest.py`](../../lib/cli/nest.py). Parent: [CLI index](README.md). Issue: [#23](https://github.com/dustinestes/Hatchery/issues/23) (inspect slice). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

Inspect registered Nests (Controller SQLite registry), run Nest Health / nest_cache sync, and Test Nest connection.

<br>

## Usage

```bash
uv run hatchery nest [--data-dir PATH] list
uv run hatchery nest [--data-dir PATH] test <id>
uv run hatchery nest [--data-dir PATH] health <id>
uv run hatchery nest [--data-dir PATH] cache-sync <id>
uv run hatchery --json nest list
uv run hatchery --json nest test <id>
uv run hatchery --json nest health <id>
uv run hatchery --json nest cache-sync <id>
```

With `--json`, stdout is machine-readable (field names in [CLI index](README.md#machine-readable-output---json)).

| Command | Source |
|---|---|
| `list` | Controller Nest registry only (no control plane) |
| `test` | Live check: Nest Health for registered Nests; draft-style reachability + capability message |
| `health` | Nest Health gather (gate + CPU/memory/disks/prerequisites); see [nest-health.md](../nest-health.md) |
| `cache-sync` | Nest cache sync check (Local content scan / Remote unavailable stub); see [ADR-0040](../adr/0040-nest-reported-nest-cache-sync.md) |

`--data-dir` is session-only (same rule as `serve`). Inspect does not create a missing data directory or database.

<br>

## Examples

```bash
uv run hatchery nest list
uv run hatchery nest --data-dir .temp/hatchery-sandbox list
uv run hatchery nest test local
```

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
