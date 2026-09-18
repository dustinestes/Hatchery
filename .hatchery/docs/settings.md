<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Settings Storage</h1>
<br clear="both">

How Hatchery splits the external bootstrap file from Settings stored in SQLite.

<br>

## Contents

- [Contents](#contents)
- [Why Two Places](#why-two-places)
- [Bootstrap File](#bootstrap-file)
- [Database Settings](#database-settings)
- [Upgrade From Legacy config.yaml](#upgrade-from-legacy-configyaml)
- [Settings UI](#settings-ui)
- [Export and import](#export-and-import)

---

<br>

## Why Two Places

Hatchery must know the **data directory** before it can open `hatchery.db`. That pointer cannot live only inside the database. Everything else that the Settings panes edit can — and should — live next to other app state in SQLite (Nest registry, secrets later, expiry tiers today).

| Concern | Store |
|---|---|
| Where is the data directory / DB? | Bootstrap file (and later CLI `--data-dir`, [#22](https://github.com/dustinestes/Hatchery/issues/22)) |
| Operational Settings | SQLite `app_settings` |

<br>

## Bootstrap File

Default location (XDG):

```
~/.config/hatchery/config.yaml
```

Override the config home with `XDG_CONFIG_HOME`. The file is intentionally minimal:

```yaml
data_dir: /home/you/.local/share/hatchery
```

Default data directory (XDG):

```
~/.local/share/hatchery
```

Override with `XDG_DATA_HOME`. Inside that directory: `hatchery.db`, `clutches/`, `media/`, `automation/`.

<br>

## Database Settings

Table: `app_settings` (`key` TEXT PRIMARY KEY, `value` TEXT JSON).

| Key | Settings section | Notes |
|---|---|---|
| `bg_interval` | General | Hatch status poll interval seconds (minimum 10) |
| `validators` | General | Per-validator `{enabled, interval_seconds}` map (JSON) |
| `validators_run_retention` | General | Max run history rows per validator (10–500, default 50) |
| `show_passwords` | Security | VM inventory password visibility |
| `nest_key_alert_tiers` | Security | Nest SSH expiry alert windows |
| `display_timezone` | Display | `UTC` or `local` for Events |
| `library_enabled` | General | Feature flag for Library Settings + Import from library |
| `library_connections` | Library | Connection registry |
| `library_script_bindings` | Library | Scripts domain bindings |
| `library_clutch_bindings` | Library | Clutches domain bindings |
| `library_media_bindings` | Library | Media domain bindings (include cache target) |

Nest **connections** (including SSH identity file path, optional cert path, and optional identity expiry) live in the `nests` table — see [schema/database.md — nests](schema/database.md#nests). Security keeps Nest SSH **alert tiers** only.

Managed by `lib/config.py` after `db.init_db` via `bind_db()` / `save()`.

<br>

## Upgrade From Legacy config.yaml

Older installs stored every setting in `config.yaml`. On first load after upgrade:

1. Hatchery reads any non-`data_dir` keys from the YAML into memory
2. Rewrites the bootstrap file to **only** `data_dir`
3. After `init_db`, `bind_db()` writes those values into `app_settings` if the table is empty

Existing installs keep their Settings without manual edits.

<br>

## Settings UI

- **General** — edits `data_dir` (bootstrap), Hatch status poll (`bg_interval`), Validators (enable/interval/retention), and Library enable (DB). Changing the data directory re-opens `hatchery.db` under the new path. Header **Export** / **Import** back up and restore operational Settings as YAML (full replace; manual escape hatch — property-level / fleet tooling should use CLI/API later). Never changes `data_dir` on import.
- **Security** / **Display** — write only to SQLite; bootstrap is unchanged. Security holds password visibility and Nest SSH **alert tiers** (identity paths/expiry are on Nest rows).
- **Nests** — Nest connection registry (`nests` table): add/edit/remove; SSH identity file + optional expiry; Test Nest connection. Export/import YAML does **not** include Nest rows.
- **Library** — connections and domain bindings (when Library is enabled).

The disabled “Bootstrap file” field on General shows the path to the external YAML pointer.

Product framing (escape hatch vs CLI/API) also lives under [Library and Nest cache — Settings export and import](library.md#settings-export-and-import).

<br>

## Export and import

Manual backup/restore of operational Settings as a YAML **Settings document** (`version: 1`). Implemented in `lib/settings_io.py`; HTTP: `GET /api/settings/export`, `POST /api/settings/import`.

### Contract

| Behavior | Detail |
|---|---|
| **Replace** | Import starts from defaults for every exportable key, then applies keys present in the file. Omitted known keys reset to defaults. |
| **`data_dir`** | Never applied from the file (top-level or under `settings`). Local bootstrap path stays; import warns if the file included it. |
| **Allowlist** | Only keys in the [Database Settings](#database-settings) table are written. |

Shape (export includes optional `exported_at` metadata):

```yaml
version: 1
exported_at: 2026-09-13T18:00:00Z
settings:
  bg_interval: 60
  # …other exportable keys…
```

### Validation

**Hard fail** (import rejected — API `400`, UI error toast):

- Empty / non-YAML / not a mapping
- `version` missing, not an integer, or not `1`
- `settings` present but not a mapping
- A **known** key with an invalid value (e.g. `bg_interval` below 10, `display_timezone` not `UTC`/`local`, Library connections/bindings failing `lib/library` parsers, Nest tiers/identities failing their parsers)

**Soft ignore** (import proceeds; warning returned in the response / toast):

- Unknown keys under `settings` — not written (`"Unknown settings key ignored: …"`)
- `data_dir` anywhere in the document — ignored as above

Extra top-level fields that are not settings (e.g. `exported_at`) are harmless. If the file has no `settings:` map, only top-level keys that match exportable names are considered.

This is intentionally a simple document replace — not a merge or conflict UI. Per-property / fleet updates belong on CLI/API later.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
