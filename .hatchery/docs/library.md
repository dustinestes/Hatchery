<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Library and Nest Cache</h1>
<br clear="both">

How Hatchery keeps a local-first operator model while supporting Library **connections**, domain **bindings**, and per-Nest content caches.

<br>

## Contents

- [Contents](#contents)
- [Planes](#planes)
- [Connections and Bindings](#connections-and-bindings)
- [Identity](#identity)
- [Settings and Import](#settings-and-import)
- [Git connections (#251)](#git-connections-251)
- [API connections (#255)](#api-connections-255)
- [Connection health (#254)](#connection-health-254)
- [Inventory: Cache vs Catalog](#inventory-cache-vs-catalog)
- [Hatch Preflight](#hatch-preflight)
- [Settings export and import](#settings-export-and-import)
- [Future: Allow Remote Content](#future-allow-remote-content)

---

<br>

## Planes

Hatchery does not become a CMS. Content moves through explicit planes:

| Plane | Role |
|---|---|
| **Library** | Product feature and Settings section (when enabled) |
| **Connections** | Named endpoints: type, base URI, auth — defined once |
| **Bindings** | Per-domain rows: connection + path/filter (Clutches, Scripts, Media) |
| **Operator cache** | This Hatchery instance’s data directory — `media/`, `automation/`, `clutches/` |
| **Nest cache** | The same layout on the Nest host that will attach or run the content |
| **Attach / run** | Hypervisor (or guest tooling) uses Nest-reachable paths |

For a **local Nest**, the operator data directory **is** the Nest cache (today’s behavior).

For a **remote Nest**, the operator cache and Nest cache are different trees. Hatchery **ensures** required files exist on the Nest (copy/verify) before hatch; it does not stream multi-GB ISOs from the operator laptop over the Nest control plane at attach time.

Shared storage that the Nest already mounts (NFS/SMB) counts as Nest cache when paths resolve on that Nest.

Nest transport (SSH default, WinRM fallback) is described in [Nest transport](nest-transport.md). Data-dir bootstrap vs SQLite Settings: [Settings storage](settings.md).

<br>

## Connections and Bindings

**Connections** are the registry of how to reach content (git forge, network share/path, HTTPS, **API catalogs** such as Artifactory). Each connection holds base URI and credentials (tokens/API keys) so auth is not repeated on every domain. Connections declare which **kinds** they serve (clutches, scripts, media, packages) so domain pickers only offer relevant connections.

**Bindings** are rows under each domain (Clutches, Scripts, Media). A binding picks a connection plus a locator/filter (subpath, glob, repo+pattern). Multiple bindings per domain are allowed (several git repos for scripts, different layouts). A data-dir–shaped single tree is an optional convenience (one connection + three bindings), not a requirement.

| Concept | Example |
|---|---|
| Connection | `Artifactory` — type API / provider Artifactory + token; kinds: media |
| Binding | Media → that connection + filter `win-isos/**/*.iso` |
| Connection | `Ops git` — forge URL + token; kinds: scripts, clutches |
| Binding | Scripts → that connection + path `automation/scripts` |

**Test connection** checks reachability/auth without a full catalog. **Test filter** applies a domain binding and returns a small sample (about five hits) so locators can be validated before rely-on-hatch.

<br>

## Identity

Content is identified by **basename + SHA-256** checksum — not a GUID catalog.

- Basename matches how Clutches already reference media and scripts (e.g. `win11.iso`)
- Checksum ensures the Nest cache has the intended bytes when multiple connections or machines are involved
- Ensure/sync and hatch preflight compare on this pair

<br>

## Settings and Import

**Settings owns Library configuration** (feature flag, connections, domain bindings). Asset panes keep an in-context control so operators shop next to Clutches, Automations, or Media.

| `library_enabled` | Import control |
|---|---|
| Off (default) | Single **Import** — file into the operator cache |
| On | Import becomes a dropdown: **From file…** \| **From library…** |

When Library is on, Settings gains a **Library** section with:

- **Connections** — registry rows (path/share, HTTPS, git, **API**) with optional **token expiry** (day picker; when set, ≥ tomorrow). Path, HTTPS, git, and API providers support test / list / pull. Each row collapses to a summary and has an **Enabled** toggle (default on). Switching Enabled saves immediately for already-stored rows (fields stay locked while off). **Test** and **Save** sit together (right-aligned); Save is dimmed until that row has unsaved field changes — Library no longer uses a page-wide Save that would write every section at once.
- **Scripts / Clutches / Media** — binding rows reuse the same collapse chrome (connection label + filter + cache target where relevant), with per-binding **Enabled** toggles (immediate save when already stored) and the same right-aligned **Test** / **Save** pattern (Save dimmed until that binding’s fields change).

### Enable / disable

Operators can park a connection or binding without deleting its config:

| Flag | Effect |
|---|---|
| Connection `enabled: false` | Skipped by the `library_connections` validator (no reachability / token-expiry Alerts while off); omitted from Import / list / pull; not offered when adding new bindings; footer **Libraries** rollup counts only **enabled** connections |
| Binding `enabled: false` | Remains in Settings; omitted from Import / From library… catalogs |

**Effective enablement** for Import / list / pull:

`binding_effective = connection.enabled AND binding.enabled`

Disabling a connection **cascades in the UI** (dependent bindings dim + note “**ConnectionName** connection is disabled”; binding Enabled control is non-operative while cascaded). Stored binding `enabled` flags are **not** rewritten when the parent connection toggles — re-enable the connection and previously-on bindings become effective again.

Missing `enabled` on export/import → treat as enabled (backward compatible).

Each connection declares **artifact types** (scripts, clutches, media, packages) so domain pickers only offer relevant connections.

Enable Library under Settings → General. Deep links to Library Settings while the feature is off redirect to General with an enable hint.

### Git connections (#251)

Strategy: **shallow clone to a Controller-side cache**, then list/pull like a path connection.

| | |
|---|---|
| **Base URI** | HTTPS (`https://github.com/org/repo.git`), SSH (`git@host:org/repo.git`), or a local repo path / `file://` |
| **Token** | Optional HTTPS PAT — embedded for `git ls-remote` / clone (GitHub: `x-access-token`; other HTTPS hosts: `oauth2`). SSH remotes use the Controller’s SSH agent/keys; token is ignored |
| **Test** | `git ls-remote --heads` (requires `git` on the Controller PATH) |
| **List / pull** | Shallow `--depth 1` checkout under `{data_dir}/library/git/{connection_id}/`; binding filter is a path glob relative to the repo root (default remote branch). Create-only pull into the domain cache with SHA-256 |
| **Limits** | Large media via git is discouraged; Git LFS is not auto-fetched — without `git-lfs`, LFS pointer files may be copied as-is |

Path and HTTPS behavior are unchanged.

### API connections (#255)

Strategy: connection **`type: api`** + **`provider`** plugin (not a vendor-named connection type). Architecture: [ADR-0001](adr/0001-library-api-adapters.md). Package: [`lib/library_api/`](../../lib/library_api/).

| | |
|---|---|
| **Type** | `api` |
| **Provider** | Registry id (first: `artifactory`) — Settings shows API + provider dropdown |
| **Shared hit** | `{ name, relative_path, sha256\|null, connection_id, source_type: "api" }` |
| **Add a vendor** | New `lib/library_api/<id>.py` implementing `BaseLibraryApiAdapter` + `register` in `register_builtins()` |

#### Artifactory provider

| | |
|---|---|
| **Base URI** | Artifactory root (e.g. `https://host/artifactory`) |
| **Token** | Optional Bearer PAT (anonymous OSS setups may omit) |
| **Test** | `GET …/api/system/ping` |
| **Filter** | `repoKey[/path/glob]` — e.g. `media-isos/**/*.iso`, `scripts/*.ps1` |
| **List** | AQL when available; Storage API walk as fallback |
| **Pull** | Download artifact; prefer `X-Checksum-Sha256` / metadata, else hash the file |
| **Local OSS test** | Contributor Docker harness: [`.hatchery/tooling/artifactory-oss/`](../tooling/artifactory-oss/) (`up` → change admin password → `seed` → Settings base URI `http://127.0.0.1:8082/artifactory`) |

`https` stays explicit single/multi path GET — not a browsable API catalog.

### Connection health (#254)

The `library_connections` validator probes registered connections (via the same logic as **Test connection**) and watches optional token `expires_at` dates:

| Prefix | When |
|---|---|
| `Library connection:` | Path/HTTPS/git/API unreachable, unreadable, or auth failure |
| `Library connection token expiry:` | `expires_at` inside the Nest-style warning windows (default 30 / 7 days) or past due |

Empty `expires_at` → no token-expiry Alert for that connection. Disabling Library or removing a connection resolves that connection’s Library-scoped Alerts. **Disabling a connection** (`enabled: false`, [#293](https://github.com/dustinestes/Hatchery/issues/293)) also skips it in the validator and resolves its Library-scoped Alerts while it stays in Settings. Settings → Test connection **resolves** a reachability Alert on success for a **saved** connection; it does not open Alerts on failure (validator owns opens).

Footer **Libraries** chip (when Library is enabled): muted with zero **enabled** connections; green when healthy; red when any Library-scoped Alert is active. Hidden when Library is disabled (same clean-UI rule as the Library nav item). See [notifications.md — Footer vs Alerts](notifications.md#footer-vs-alerts-277).

Pull copies selected items into the normal data-dir paths (`automation/scripts/` for Scripts, `clutches/` for Clutches) so inventory, Used-by, and provisioning keep using local files by default.

<br>

## Inventory browse (Cached | Library)

Domain inventory panes (Scripts, Media, Clutches) use a **Cached | Library** tab strip. Architecture: [ADR-0002](adr/0002-library-in-pane-browser.md).

| Surface | Role |
|---|---|
| **Cached** | Operator cache inventory (always shown) |
| **Library** | Binding catalog: name + muted path, connection, copyable SHA, Cached vs Library-only; filter/sort, multi-select, batch pull. Dimmed when Library is disabled in Settings |
| **Import** | From file…; Browse library… switches to the Library tab when Library is enabled |

Overlay of Library hits inside the Cached list remains [#250](https://github.com/dustinestes/Hatchery/issues/250).

<br>

## Inventory: Cache vs Catalog

**Default (cache-first):** domain panes list the operator cache on the **Cached** tab. **Browse library…** opens the in-pane **Library** tab (Scripts, Media, Clutches) and pulls chosen items into the cache.

**Optional:** Settings → Library knob to **show library results in inventory panes**. When on, panes may list binding hits with badges such as **Cached** vs **Library** (not cached). Visibility is not the same as Nest-ready: hatch still requires Nest cache (unless [allow remote content](#future-allow-remote-content) later). Actions on Library-only rows are pull/cache (and later pull-and-use), not silent remote attach.

<br>

## Hatch Preflight

Default hatch contract:

1. Resolve required content (media, answer files, scripts, and other cache-backed artifacts) for the target Nest
2. Verify each item exists in the **Nest cache** (basename; SHA-256 when ensure/Library metadata is present)
3. If missing, fail with a clear UI/API error — or run ensure/sync first when the operator requested it (`ensure_cache` on Hatch form; `POST /api/nest-cache/ensure`)
4. Only then call the provider create/attach path with Nest-local paths

**Local Nest:** preflight is a filesystem check under the operator data directory (no network ensure). Hatch Clutch POST runs this check before starting the hatch session.

**Remote Nest:** ensure/copy over Nest transport is not wired yet (#207 / #215). Preflight and ensure fail closed so Hatchery does not attach operator-only paths over WAN. APIs: `POST /api/nest-cache/preflight`, `POST /api/nest-cache/ensure`.

<br>

## Settings export and import

Live operational Settings remain in SQLite (`app_settings`). Portability across machines uses a YAML **Settings document** (`version: 1`): export from / import into the DB as a **full replace**. The same format serves personal multi-host backup/restore and light “golden” config handoff — including Library connections/bindings when present.

Bootstrap `data_dir` stays in the external bootstrap file — imports do not replace the need to know where the database lives.

### Intentional scope (UI vs tooling)

The Settings UI export/import controls are a **manual escape hatch**: what you export is what you get on import (omitted keys reset to defaults; `data_dir` never changes). They are **not** a conflict-aware merge UI and **not** the surface for fleet push or per-property updates. Richer property-level configuration belongs on Hatchery’s **CLI/API** later so Hatchery stays extensible without growing a noisy in-app config platform.

Continuous path/git watch of a Settings file is also a later enhancement — not this UI.

### UI

Settings → **General** header:

- **Export** — downloads `hatchery-settings.yaml` via the browser (Save As / downloads folder)
- **Import** — confirms, then file-selects a YAML document and **replaces** operational Settings

`data_dir` in a document (top-level or under `settings`) is **ignored** with a warning — set the data directory on each machine under General.

Validation (hard fail vs soft-ignore unknown keys) is documented under [Settings storage — Export and import](settings.md#export-and-import).

### Shape

```yaml
version: 1
exported_at: 2026-09-13T18:00:00Z   # optional metadata
settings:
  bg_interval: 60
  show_passwords: false
  display_timezone: UTC
  nest_key_alert_tiers: [...]
  nest_ssh_identities: [...]
  library_enabled: true
  library_connections: [...]
  library_script_bindings: [...]
  library_clutch_bindings: [...]
  library_media_bindings: [...]
```

API: `GET /api/settings/export`, `POST /api/settings/import` (multipart `file`, or JSON `{yaml}` / `{document}`). Import always replaces. The HTTP API is the stable contract CLI/fleet tooling should build on later.


<br>

## Future: Allow Remote Content

Orgs with high bandwidth or all-local DC networks may later opt in so a Nest can attach or run content from a remote connection **without** pre-download into the Nest cache. That flag is not the default and is not required for Library MVP.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
