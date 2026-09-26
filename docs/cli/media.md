<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: media</h1>
<br clear="both">

Code: [`lib/cli/media.py`](../../lib/cli/media.py). Parent: [CLI index](README.md). Issue: [#425](https://github.com/dustinestes/Hatchery/issues/425). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md).

<br>

## Purpose

List local ISO / VirtIO media under the Controller data directory (same roots as the Media panes). Read-only; no Library Sync.

<br>

## Usage

```bash
uv run hatchery media [--data-dir PATH] list [--type iso|virtio]
uv run hatchery --json media list
```

| Flag | Notes |
|---|---|
| `--type` | Limit to `iso` (`media/iso/`) or `virtio` (`media/virtio/`); omit to list both |
| `--json` | Machine-readable shape in [CLI index](README.md#machine-readable-output---json) |

Inspect bootstrap: the data directory must already exist.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
