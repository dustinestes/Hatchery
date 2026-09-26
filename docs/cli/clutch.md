<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: clutch</h1>
<br clear="both">

Code: [`lib/cli/clutch.py`](../../lib/cli/clutch.py). Parent: [CLI index](README.md). Issue: [#23](https://github.com/dustinestes/Hatchery/issues/23) (inspect slice). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

List and show Clutch files under the effective Controller `data_dir` (operator inspect surface).

<br>

## Usage

```bash
uv run hatchery clutch [--data-dir PATH] list
uv run hatchery clutch [--data-dir PATH] show <file>
uv run hatchery --json clutch list
uv run hatchery --json clutch show <file>
```

With `--json`, stdout is machine-readable (field names in [CLI index](README.md#machine-readable-output---json)).

Reads `data_dir/clutches/*.yaml` on the Controller. Does not reach Nest transport.

Inspect is read-only: the data directory must already exist. A missing `--data-dir` path exits with an error and does **not** create folders or `hatchery.db` (unlike `serve`).

<br>

## Examples

```bash
uv run hatchery clutch list
uv run hatchery clutch --data-dir .temp/hatchery-sandbox show lab.yaml
```

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
