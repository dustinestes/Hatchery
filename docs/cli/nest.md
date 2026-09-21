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

Inspect registered Nests (Controller SQLite registry) and run Test Nest connection.

<br>

## Usage

```bash
uv run hatchery nest [--data-dir PATH] list
uv run hatchery nest [--data-dir PATH] test <id>
```

| Command | Source |
|---|---|
| `list` | Controller Nest registry only (no control plane) |
| `test` | Live check: Local Nest tools on this Controller, or remote Nest transport |

`--data-dir` is session-only (same rule as `serve`).

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
