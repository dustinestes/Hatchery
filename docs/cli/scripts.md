<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: scripts</h1>
<br clear="both">

Code: [`lib/cli/scripts.py`](../../lib/cli/scripts.py). Parent: [CLI index](README.md). Issue: [#425](https://github.com/dustinestes/Hatchery/issues/425). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

List local automation scripts under `automation/scripts/` on the Controller data directory (same root as the Scripts pane). Read-only; no Library Sync or Content catalog.

<br>

## Usage

```bash
uv run hatchery scripts [--data-dir PATH] list
uv run hatchery --json scripts list
```

With `--json`, field names are documented in [CLI index](README.md#machine-readable-output---json).

Inspect bootstrap: the data directory must already exist.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
