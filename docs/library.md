<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
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
- [Forge connections (#307)](#forge-connections-307)
- [API connections (#255)](#api-connections-255)
- [Connection health (#254)](#connection-health-254)
- [Cache provenance and drift (#308)](#cache-provenance-and-drift-308)
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
| **Library** | Product feature and first-class sidebar plane when enabled ([ADR-0016](adr/0016-library-operator-plane.md)) |
| **Connections** | Named endpoints: type, base URI, auth - defined once |
| **Bindings** | Per-domain rows: connection + path/filter (Clutches, Scripts, Media) |
| **Operator cache** | This Hatchery instance’s data directory - `media/`, `automation/`, `clutches/` |
| **Nest cache** | The same layout on the Nest host that will attach or run the content |
| **Attach / run** | Hypervisor (or guest tooling) uses Nest-reachable paths |

For a **local Nest**, the operator data directory **is** the Nest cache (today’s behavior).

For a **remote Nest**, the operator cache and Nest cache are different trees. Hatchery **ensures** required files exist on the Nest (copy/verify) before hatch; it does not stream multi-GB ISOs from the operator laptop over the Nest control plane at attach time.

Shared storage that the Nest already mounts (NFS/SMB) counts as Nest cache when paths resolve on that Nest.

Nest transport (SSH default, WinRM fallback) is described in [Nest transport](nest-transport.md). Data-dir bootstrap vs SQLite Settings: [Settings storage](settings.md).

<br>

## Connections and Bindings

**Connections** are the registry of how to reach content (git forge, network share/path, HTTPS, **API catalogs** such as Artifactory). Each connection holds base URI and credentials (tokens/API keys) so auth is not repeated on every domain. Connections declare which **kinds** they serve (clutches, scripts, media, packages) so domain pickers only offer relevant connections.

**Bindings** are rows under each domain (Clutches, Scripts, Media). A binding picks a connection plus a locator/filter (subpath, glob, repo+pattern), and an optional operator **label** for display ([#359](https://github.com/dustinestes/Hatchery/issues/359)). When label is empty, Hatchery stores and shows the filter string. Multiple bindings per domain are allowed (several forge repos for scripts, different layouts). A data-dir–shaped single tree is an optional convenience (one connection + three bindings), not a requirement.

| Concept | Example |
|---|---|
| Connection | `Artifactory` - type API / provider Artifactory + token; kinds: media |
| Binding | Media → that connection + label `Win ISOs` + filter `win-isos/**/*.iso` |
| Connection | `Ops forge` - forge URL + token; kinds: scripts, clutches |
| Binding | Scripts → that connection + label `Automation scripts` + path `automation/scripts` |

**Test connection** checks reachability/auth without a full catalog. **Test filter** applies a domain binding and returns a small sample (about five hits) so locators can be validated before rely-on-hatch.

<br>

## Identity

Content is identified by **basename + SHA-256** checksum - not a GUID catalog.

- Basename matches how Clutches already reference media and scripts (e.g. `win11.iso`)
- Checksum ensures the Nest cache has the intended bytes when multiple connections or machines are involved
- Ensure/sync and hatch preflight compare on this pair

<br>

## Settings and Import

**Settings owns the Library feature flag** (`library_enabled` under General). Connection/binding **configuration** is stored in SQLite tables `library_connections`, `library_connection_kinds`, and `library_bindings` ([ADR-0017](adr/0017-library-connections-bindings-tables.md), [#367](https://github.com/dustinestes/Hatchery/issues/367)) and edited from **Library → Connections** ([ADR-0016](adr/0016-library-operator-plane.md), [#375](https://github.com/dustinestes/Hatchery/issues/375)).

Asset panes keep an in-context **Import** control. When Library is on, **From library…** deep-links to Library → Content **Available** (optionally filtered with `?tab=available&domain=scripts|clutches|media`). Domain panes show operator-cache inventory only; catalog browse and linked-item lifecycle live on **Library → Content**.

**Backup / restore:** copy or reconnect the Controller **data directory** (includes `hatchery.db` and domain caches). Settings YAML export/import covers app settings only (including `library_enabled`) and is **not** the Library registry vehicle. Legacy `library_connections` / binding arrays in an old document are ignored with a warning and do **not** replace the SQLite registry.

| `library_enabled` | Import control |
|---|---|
| Off (default) | Single **Import** - file into the operator cache |
| On | Import becomes a dropdown: **From file…** \| **From library…** |

When Library is on, the sidebar gains a **Library** group (above Notifications) with **Content** and **Connections**:

- **Content** - **Linked | Available** tabs (#392). **Linked** is attributed Cached inventory with Sync / re-attach / Remove (default). **Available** is the cross-domain Library catalog (filter by domain / connection / in-cache, multi-select pull into domain operator caches). Deep-link Linked with `?domain=scripts|clutches|media&name=…` (optional `media_target`); open Available with `?tab=available&domain=…`. Domain Cached panes link **Content** when the selected file is linked.
- **Left (Connections):** connection list (+ Add). **Right:** selected connection editor and Clutches / Media / Scripts bindings for that connection only.
- **Connections** - registry rows (path/share, HTTPS, **API**, Forge) with optional **token expiry** (day picker; when set, ≥ tomorrow). Path, HTTPS, API, and Forge providers support test / list / pull. Each connection has an **Enabled** toggle (default on). Switching Enabled saves immediately for already-stored rows (fields stay locked while off). **Test** and **Save** sit together; Save is dimmed until that row has unsaved field changes.
- **Clutches / Media / Scripts** - binding rows reuse collapse chrome (binding label + filter + cache target where relevant). Binding **Label** is optional and defaults to the filter when blank. Re-attach pickers show `Label (filter)` when they differ. Per-binding **Enabled** toggles (immediate save when already stored) and the same **Test** / **Save** pattern.

### Enable / disable Library (#379)

Architecture: [ADR-0019](adr/0019-library-disable-excise.md).

| State | Meaning |
|---|---|
| **Enabled** | `library_enabled` on - Library nav, Connections, From library… |
| **Disabled** | Flag off - includes never enabled and soft disable after enable |

Turning **Enable Library** off under Settings → General opens a confirm modal ([#407](https://github.com/dustinestes/Hatchery/issues/407)):

| Control | Default | Effect |
|---|---|---|
| **Clear Connections** (checkbox) | off | Remove all Library connections and bindings |
| **Linked Cached files** (radio) | Leave as-is | Soft: keep links. **Clear Content** deletes linked files. **Clear Links** keeps files as local inventory |

Soft disable = Clear Connections off + Leave as-is. While Disabled, linked Cached items keep a quiet **Linked** cue (no Sync / re-attach); files stay hatchable ([#408](https://github.com/dustinestes/Hatchery/issues/408)). Re-enable restores normal linked/synced chrome after evaluate.

Classic **`type: git`** and `{data_dir}/library/git/` are removed ([ADR-0020](adr/0020-library-forge-path-only.md) / [#406](https://github.com/dustinestes/Hatchery/issues/406)). Recreate remote SCM as **forge**; local trees as **path**. Leftover clone dirs are deleted when the connection is removed.

### Enable / disable (connection and binding)

Operators can park a connection or binding without deleting its config:

| Flag | Effect |
|---|---|
| Connection `enabled: false` | Skipped by the `library_connections` validator (no reachability / token-expiry Alerts while off); omitted from Import / list / pull; not offered when adding new bindings; footer **Libraries** rollup counts only **enabled** connections |
| Binding `enabled: false` | Remains in Library → Connections; omitted from Import / From library… catalogs |

**Effective enablement** for Import / list / pull:

`binding_effective = connection.enabled AND binding.enabled`

Disabling a connection **cascades in the UI** (dependent bindings dim + note “**ConnectionName** connection is disabled”; binding Enabled control is non-operative while cascaded). Stored binding `enabled` flags are **not** rewritten when the parent connection toggles - re-enable the connection and previously-on bindings become effective again.

Missing `enabled` on export/import → treat as enabled (backward compatible).

Each connection declares **artifact types** (scripts, clutches, media, packages) so domain pickers only offer relevant connections.

Enable Library under Settings → General. Deep links to Library → Content or Connections while the feature is off redirect to General with an enable hint. `/settings/library` redirects to `/library/connections` when enabled. `/library` redirects to `/library/content`.

### Forge connections (#307)

Strategy: connection **`type: forge`** + **`provider`** plugin - list/pull via forge HTTP APIs with **no** Controller working tree. Architecture: [ADR-0010](adr/0010-library-forge-providers.md). Package: [`lib/library_forge/`](../../lib/library_forge/). Classic `type: git` clone cache was removed ([ADR-0020](adr/0020-library-forge-path-only.md)).

| | |
|---|---|
| **Type** | `forge` |
| **Provider** | Registry id (first: `github`) - Settings shows Forge + provider dropdown |
| **Shared hit** | `{ name, relative_path, sha256\|null, connection_id, source_type: "forge" }` |
| **SHA-256** | Git blob SHAs are not Hatchery identity - list may omit `sha256`; pull hashes file contents |
| **Add a vendor** | New `lib/library_forge/<id>.py` + `register` in `register_builtins()` - follow-ons: [#310](https://github.com/dustinestes/Hatchery/issues/310) GitLab, [#311](https://github.com/dustinestes/Hatchery/issues/311) Bitbucket, [#312](https://github.com/dustinestes/Hatchery/issues/312) Gitea |

#### GitHub provider

| | |
|---|---|
| **Base URI** | `https://github.com/owner/repo` (optional `.git`) or `owner/repo` |
| **Token** | Optional Bearer PAT (private repos / rate limits) |
| **Test** | `GET /repos/{owner}/{repo}` |
| **Filter** | Path glob under the default branch - e.g. `*.ps1`, `scripts/**/*.ps1` |
| **List** | Git Trees API (`recursive=1`); truncated trees fail closed |
| **Pull** | Raw content download; SHA-256 of bytes written to the domain cache |

Library stays **consume-only** - no Clutch↔forge round-trip or push back to remotes ([ADR-0011](adr/0011-library-consume-only-no-clutch-roundtrip.md)). A sample public catalog for demos is tracked as [#315](https://github.com/dustinestes/Hatchery/issues/315) (`hatchery_catalog`).

### API connections (#255)

Strategy: connection **`type: api`** + **`provider`** plugin (not a vendor-named connection type). Architecture: [ADR-0001](adr/0001-library-api-adapters.md). Package: [`lib/library_api/`](../../lib/library_api/).

| | |
|---|---|
| **Type** | `api` |
| **Provider** | Registry id (first: `artifactory`) - Settings shows API + provider dropdown |
| **Shared hit** | `{ name, relative_path, sha256\|null, connection_id, source_type: "api" }` |
| **Add a vendor** | New `lib/library_api/<id>.py` implementing `BaseLibraryApiAdapter` + `register` in `register_builtins()` |

#### Artifactory provider

| | |
|---|---|
| **Base URI** | Artifactory root (e.g. `https://host/artifactory`) |
| **Token** | Optional Bearer PAT (anonymous OSS setups may omit) |
| **Test** | `GET …/api/system/ping` |
| **Filter** | `repoKey[/path/glob]` - e.g. `media-isos/**/*.iso`, `scripts/*.ps1` |
| **List** | AQL when available; Storage API walk as fallback |
| **Pull** | Download artifact; prefer `X-Checksum-Sha256` / metadata, else hash the file |
| **Local OSS test** | Contributor Docker harness: [`.hatchery/tooling/artifactory-oss/`](../.hatchery/tooling/artifactory-oss/) (`up` → change admin password → `seed` → Settings base URI `http://127.0.0.1:8082/artifactory`) |

`https` stays explicit single/multi path GET - not a browsable API catalog.

### Cache provenance and drift (#308)

Architecture: [ADR-0012](adr/0012-library-cache-provenance-drift.md); reachability + sync axes: [ADR-0018](adr/0018-library-drift-scenario-matrix.md). First Library **pull** writes a SQLite provenance row linking the Cached basename to `connection_id` / optional `binding_id` / `relative_path`. Files never pulled via Library stay **local** (no sync, no orphan).

Evaluate answers **two** questions in **one** pass (same tip fetch; no second network round-trip for “sync check”):

1. **`source_status`** - can we resolve the attributed tip?
2. **`sync_state`** - if yes, do cache and tip agree? (validator/evaluate only; not an operator edit)

| Column prefix | Meaning |
|---|---|
| `cache_sha256` / `cache_sha256_synced` | Observed vs last-sync Hatchery SHA-256 of the Cached file |
| `source_digest` / `source_digest_synced` | Observed vs last-sync Library tip |
| `source_digest_kind` | Tip alphabet (`sha256`, `git_blob`, `size_mtime`) |
| `source_status` | Reachability / attribution (see below) |
| `source_status_message` | Catalog or detail text for the current `source_status` |
| `sync_state` | `in_sync` / `out_of_sync` when `source_status == ok`; otherwise **`unevaluated`** (never null in API payloads) |

| `source_status` | Meaning |
|---|---|
| `ok` | Tip resolved |
| `missing` | Tip check succeeded; path/object absent (remote rename/delete) |
| `orphan` | Connection or binding id missing from the registry |
| `disabled` | Connection is disabled |
| `rate_limited` | Tip check hit 403/429 |
| `unreachable` | Other transport / tip-index failure |
| `unconfirmable` | Tip cannot be confirmed without downloading the body |

| `sync_state` | Meaning |
|---|---|
| `in_sync` | `source_status == ok` and digests/anchors agree (UI: synced) |
| `out_of_sync` | `source_status == ok` and cache and/or tip drifted |
| `unevaluated` | `source_status != ok` - sync was **not** compared (reason is `source_status` + message) |

| | |
|---|---|
| **Out of sync when** | Source reachable **and** (cache bytes changed since sync, **or** Library tip moved since sync, **or** content-addressable live cache identity ≠ live tip) |
| **Sync** | Overwrites the Cached file from the source, then **evaluates that row** (evaluate owns digests, `source_status`, `sync_state`, message, and Alerts). Sync does not force `in_sync` by itself. Enabled only when **`source_status == ok`** and **`sync_state == out_of_sync`** - never while status is `missing` / `rate_limited` / etc. |
| **Source missing** | `source_status=missing` → warning; correction set: **Re-attach** or **Remove** (drop provenance; optional cull Cached file). Not counted in domain “N out of sync” Alerts; Sync disabled until evaluate reaches `ok` again |
| **Orphan** | `source_status=orphan` → warning on Cached views; shared re-attach modal ([#364](https://github.com/dustinestes/Hatchery/issues/364)): connection + **binding** + fixed Cached filename, Test, then rewrite ids. Path basename must match the Cached name (rename → re-import). Relative path must match the selected binding filter ([#360](https://github.com/dustinestes/Hatchery/issues/360)). Re-attach only rewrites provenance ids/path, then runs single-file drift evaluate (it does not mark the file in sync). A binding is always required ([#363](https://github.com/dustinestes/Hatchery/issues/363)); if the connection has none for this domain, add one under Library → Connections first. Binding remove can then cascade-delete attributed cache ([#357](https://github.com/dustinestes/Hatchery/issues/357)) |
| **Delete connection/binding** | Default: leave Cached files (orphans). Optional confirm toggle deletes attributed files (binding cascade matches `binding_id`; connection cascade matches `connection_id`) |
| **Validator** | `library_cache_drift` - Settings interval + optional **auto-sync**. Manual mode: one Alert per domain with a count of **`sync_state == out_of_sync` only**. Auto-sync on: overwrite out-of-sync files then evaluate; no drift Alerts |

#### Drift scenario matrix (#370)

Locked desired states ([ADR-0018](adr/0018-library-drift-scenario-matrix.md)). Schema/evaluate and UX ship in follow-on issues under [#370](https://github.com/dustinestes/Hatchery/issues/370).

| Scenario | Local | Remote | `source_status` | `sync_state` | Primary action |
|---|---|---|---|---|---|
| Unchanged | Exists, same anchors | Tip resolves, same tip | `ok` | `in_sync` | None |
| Content changed (local) | Bytes ≠ sync anchor | Tip unchanged | `ok` | `out_of_sync` | Sync |
| Content changed (remote) | Unchanged | Tip digest moved (same path) | `ok` | `out_of_sync` | Sync |
| Both changed | Bytes drifted | Tip moved | `ok` | `out_of_sync` | Sync (source wins) |
| Renamed (remote) | Old basename cached | Old path missing; new name elsewhere | `missing` | `unevaluated` | Re-attach / re-import / Remove |
| Renamed (local) | Cache file renamed/moved | Provenance mismatch | Ghost / Cleaner ([#361](https://github.com/dustinestes/Hatchery/issues/361)) | - | Cleaner |
| Missing (remote) | Cache present | Tip path deleted | `missing` | `unevaluated` | Re-attach or Remove |
| Missing (local) | Cache file gone | Tip may exist | `ok` (if tip resolves) | `out_of_sync` | Sync or Cleaner |
| Connection/binding removed | Cache present | Ids gone | `orphan` | `unevaluated` | Re-attach |
| Rate limited | Cache present | 403/429 | `rate_limited` | `unevaluated` | Wait / fix token |
| Network / tip-index failure | Cache present | Transport error | `unreachable` | `unevaluated` | Fix connectivity |
| Connection disabled | Cache present | Skipped | `disabled` | `unevaluated` | Enable connection |
| No cheap digest | Cache present | HTTPS/API without tip | `unconfirmable` | `unevaluated` | Add checksum / accept limit |
| Basename mismatch on re-attach | - | - | API reject ([#364](https://github.com/dustinestes/Hatchery/issues/364)) | - | Re-import |

**Vocabulary:** UI may say **linked** (has provenance) and **synced** (`sync_state == in_sync` with `source_status == ok`). Problems use warn chrome plus `source_status_message`. Prefer landing lifecycle chrome on **Library → Content** ([ADR-0016](adr/0016-library-operator-plane.md)) rather than growing permanent Sync/re-attach stacks on every domain pane.

#### Library status cues (#387)

Shared cue map (Python [`lib/library_status_cues.py`](../lib/library_status_cues.py) + JS [`static/library_status_cues.js`](../static/library_status_cues.js)) so Cached panes and Library → Content stay 1:1.

| Cue id | When | Short label (rail) | Severity | Primary action |
|---|---|---|---|---|
| `local` | No provenance | (none) | muted | - |
| `synced` | `ok` + `in_sync` | synced | ok | - |
| `out_of_sync` | `ok` + `out_of_sync` | out of sync | action | Sync |
| `orphan` | `source_status=orphan` | orphaned | warn | Re-attach |
| `missing` | `source_status=missing` | source missing | warn | Re-attach / Remove |
| `communication` | `rate_limited` or `unreachable` | rate limited / unreachable | warn | Fix connection / wait |
| `disabled` | `disabled` | connection disabled | muted | Enable connection |
| `unconfirmable` | `unconfirmable` (and similar) | tip unconfirmable | muted | Add checksum / accept |

Filter rollups use cue ids (e.g. **Communication** = `rate_limited` ∪ `unreachable`). Detail shows full `source_status_message` when non-empty (not hover-only).

#### How tip identity works (one story per connection type)

Hatchery never downloads a file body **only** to compare digests. Tip identity is:

| Type | Tip check (Scripts, Clutches, and Media alike) |
|---|---|
| **path** | Source file **size + mtime** (no live cache↔tip equality; anchors only) |
| **api** | Catalog/metadata **SHA-256** (e.g. Artifactory); missing → `unconfirmable` |
| **forge** | Git **blob SHA** from Trees/Contents (not Hatchery content SHA-256) |
| **https** | Checksum header on HEAD if present; else `unconfirmable` |

Cached Nest identity remains **SHA-256 of bytes on disk** (`cache_sha256`).

**Sync integrity:** downloads that claim a content-addressable tip must match pulled bytes before evaluate can promote anchors. Forge pulls use the GitHub Contents API (blob sha + body), not `raw.githubusercontent.com` CDN.

**Scripts inventory filters (#320 / #391):** Automations → Scripts has a filter bar (search, language, Library state) so operators can narrow the rail without leaving the pane. Media and Clutches filter bars match that layout via shared macros (search + Library state; Clutches also filters by language for future control-plane formats). Library → Content **Linked** uses the same filter shell with Domain instead of Local.

#### Forge / GitHub rate limits

Each full validator pass uses about **one Trees request per forge connection** (plus a repo metadata call), not one Trees request per attributed file. Single-file Sync uses Contents metadata for that path when possible.

GitHub still rate-limits aggressive intervals (especially without a PAT: ~60 requests/hour unauthenticated). Prefer a longer `library_cache_drift` interval in production, and attach a token on forge connections. On 403/429, affected rows become `source_status=rate_limited` with `sync_state=unevaluated` (no retry storm).

### Connection health (#254)

The `library_connections` validator probes registered connections (via the same logic as **Test connection**) and watches optional token `expires_at` dates:

| Prefix | When |
|---|---|
| `Library connection:` | Path/HTTPS/API/Forge unreachable, unreadable, or auth failure |
| `Library connection token expiry:` | `expires_at` inside the Nest-style warning windows (default 30 / 7 days) or past due |

Empty `expires_at` → no token-expiry Alert for that connection. Disabling Library or removing a connection resolves that connection’s Library-scoped Alerts. **Disabling a connection** (`enabled: false`, [#293](https://github.com/dustinestes/Hatchery/issues/293)) also skips it in the validator and resolves its Library-scoped Alerts while it stays in Settings. Settings → Test connection **resolves** a reachability Alert on success for a **saved** connection; it does not open Alerts on failure (validator owns opens).

Footer **Libraries** chip (when Library is enabled): muted with zero **enabled** connections; green when healthy; red when any Library-scoped Alert is active. Hidden when Library is disabled (same clean-UI rule as the Library nav item). See [notifications.md - Footer vs Alerts](notifications.md#footer-vs-alerts-277).

Pull copies selected items into the normal data-dir paths (`automation/scripts/` for Scripts, `clutches/` for Clutches) so inventory, Used-by, and provisioning keep using local files by default.

<br>

## Inventory browse (Content + domain cache)

**Library → Content** is the catalog + linked lifecycle surface ([ADR-0016](adr/0016-library-operator-plane.md), [#392](https://github.com/dustinestes/Hatchery/issues/392)):

| Surface | Role |
|---|---|
| **Linked** | Attributed Cached items; Sync / re-attach / Remove (default tab) |
| **Available** | Union catalog across enabled connections/bindings; domain / connection / in-cache filters; multi-select pull into domain caches (`GET /api/library/content/catalog`; pull via existing domain `/pull` APIs) |
| **Import → From library…** | Deep-links to Content Available (`?tab=available&domain=…`) when Library is enabled |

Domain inventory panes (Scripts, Media, Clutches) list the **operator cache only** ([#397](https://github.com/dustinestes/Hatchery/issues/397)). In-pane Library catalog tabs are removed; ADR-0002’s browser UX lives on Content Available.

**Shared inventory chrome (#321 / #391 / #404):** Scripts, Media, Clutches, and Library → Content **Linked** use the same inventory grammar - left rail + detail, non-button rail warn for out of sync / orphan, header Sync / orphan re-attach control, icon deep-link to Library Content when attributed, and live rail refresh on the status-surfaces tick. Media keeps Path-only copy (binary, icon dropdown); Scripts and Clutches offer Path / Contents. Clutches detail includes Language (between Path and Modified) and a Content section. Filter bars sit full-width above the rail and detail pane. Shared Jinja macros live in `_inventory_toolbar.html`, `_inventory_cached_filters.html`, and `_inventory_split_layout.html` (plus `_library_content_tabs.html` for Linked | Available).

An optional overlay of Library hits inside the Cached list was considered ([#250](https://github.com/dustinestes/Hatchery/issues/250)) and **closed as superseded**.

<br>

## Inventory: Cache vs Catalog

**Default (cache-first):** domain panes list the operator cache. **From library…** opens Library → Content **Available** (domain filter when useful). Linked-item Sync / re-attach / Remove live on Content **Linked**. Domain Cached headers deep-link attributed items to Content via an icon control (Open in Library Content) - inventory keeps lightweight linked/synced cues only.

Visibility in Content Available is not the same as Nest-ready: hatch still requires Nest cache (unless [allow remote content](#future-allow-remote-content) later).

<br>

## Hatch Preflight

Default hatch contract:

1. Resolve required content (media, answer files, scripts, and other cache-backed artifacts) for the target Nest
2. Verify each item exists in the **Nest cache** (basename; SHA-256 when ensure/Library metadata is present)
3. If missing, fail with a clear UI/API error - or run ensure/sync first when the operator requested it (`ensure_cache` on Hatch form; `POST /api/nest-cache/ensure`)
4. Only then call the provider create/attach path with Nest-local paths

**Local Nest:** preflight is a filesystem check under the operator data directory (no network ensure). Hatch Clutch POST runs this check before starting the hatch session.

**Remote Nest:** ensure/copy over Nest transport is not wired yet (#207 / #215). Preflight and ensure fail closed so Hatchery does not attach operator-only paths over WAN. APIs: `POST /api/nest-cache/preflight`, `POST /api/nest-cache/ensure`.

<br>

## Settings export and import

Live operational Settings remain in SQLite (`app_settings`). Portability across machines uses a YAML **Settings document** (`version: 1`): export from / import into the DB as a **full replace**. The same format serves personal multi-host backup/restore and light “golden” config handoff - including Library connections/bindings when present.

Bootstrap `data_dir` stays in the external bootstrap file - imports do not replace the need to know where the database lives.

### Intentional scope (UI vs tooling)

The Settings UI export/import controls are a **manual escape hatch**: what you export is what you get on import (omitted keys reset to defaults; `data_dir` never changes). They are **not** a conflict-aware merge UI and **not** the surface for fleet push or per-property updates. Richer property-level configuration belongs on Hatchery’s **CLI/API** later so Hatchery stays extensible without growing a noisy in-app config platform.

Continuous path watch of a Settings file is also a later enhancement - not this UI.

### UI

Settings → **General** header:

- **Export** - downloads `hatchery-settings.yaml` via the browser (Save As / downloads folder)
- **Import** - confirms, then file-selects a YAML document and **replaces** operational Settings

`data_dir` in a document (top-level or under `settings`) is **ignored** with a warning - set the data directory on each machine under General.

Validation (hard fail vs soft-ignore unknown keys) is documented under [Settings storage - Export and import](settings.md#export-and-import).

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
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
