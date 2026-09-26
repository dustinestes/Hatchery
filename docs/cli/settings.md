<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>CLI: settings</h1>
<br clear="both">

Code: [`lib/cli/settings.py`](../../lib/cli/settings.py). Parent: [CLI index](README.md). Issue: [#344](https://github.com/dustinestes/Hatchery/issues/344). ADR: [ADR-0013](../adr/0013-hatchery-cli-launch-and-operator.md), [ADR-0022](../adr/0022-dual-surface-operator-discipline.md). Storage: [settings.md](../settings.md).

<br>

## Purpose

Read and **persist** exportable Controller Settings (`app_settings` in SQLite). Distinct from session-only launch overrides on [`serve`](serve.md). Does not CRUD Library connections/bindings ([#434](https://github.com/dustinestes/Hatchery/issues/434)).

<br>

## Usage

```bash
uv run hatchery settings [--data-dir PATH] get [KEY...]
uv run hatchery settings [--data-dir PATH] set <KEY> <VALUE>
uv run hatchery --json settings get library_enabled
uv run hatchery settings set library_enabled true
```

| Command | Notes |
|---|---|
| `get` | Omit keys to list all exportable Settings; data dir must already exist |
| `set` | Partial write (`update_settings`); creates Controller state under `--data-dir` when needed |
| Values | `true`/`false` for booleans; integers for intervals; JSON strings for maps/lists (`validators`, tiers) |

`data_dir` is **not** a Settings CLI key (bootstrap / `--data-dir` only). Runtime cache keys such as `nest_reachability_status` are not exportable.

Shared writer: `lib.settings_io.set_exportable_setting` (also used by product convenience verbs such as `library enable`).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
