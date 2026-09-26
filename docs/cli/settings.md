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

<br>

## Exportable keys

| Key | CLI value | Notes |
|---|---|---|
| `bg_interval` | integer | Hatch status poll seconds (minimum 10) |
| `validators` | JSON object | Per-validator `{enabled, interval_seconds}` map |
| `validators_run_retention` | integer | Max run history rows per validator (10–500) |
| `show_passwords` | bool | `true`/`false`/`1`/`0`/`yes`/`no`/`on`/`off` |
| `display_timezone` | string | `UTC` or `local` |
| `nest_key_alert_tiers` | JSON list | Nest SSH expiry alert windows |
| `nest_ssh_identities` | JSON list | Tracked Nest SSH identities (legacy/alert use) |
| `library_enabled` | bool | Same tokens as `show_passwords`; also `library enable\|disable` |

**Not** Settings CLI keys: bootstrap `data_dir` (use `--data-dir` / serve), runtime `nest_reachability_status`, meta `_settings_rev`. Product meaning: [settings.md](../settings.md).

Shared writer: `lib.settings_io.set_exportable_setting` (also used by product convenience verbs such as `library enable`).

A running `hatchery serve` against the **same** data dir reloads Settings from SQLite when the `_settings_rev` meta row advances ([ADR-0023](../adr/0023-settings-sqlite-revision-reload.md); [#439](https://github.com/dustinestes/Hatchery/issues/439)). No serve restart required for `settings set` / `library enable|disable` to show in the UI on the next request or status poll (sidebar Library nav and Libraries footer chip toggle from plane-status). This is not external YAML/git watch ([#253](https://github.com/dustinestes/Hatchery/issues/253)).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
