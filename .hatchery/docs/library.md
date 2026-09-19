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

**Connections** are the registry of how to reach content (git forge, network share/path, HTTPS, Artifactory-style API later). Each connection holds base URI and credentials (tokens/API keys) so auth is not repeated on every domain. Connections declare which **kinds** they serve (clutches, scripts, media, packages) so domain pickers only offer relevant connections.

**Bindings** are rows under each domain (Clutches, Scripts, Media). A binding picks a connection plus a locator/filter (subpath, glob, repo+pattern). Multiple bindings per domain are allowed (several git repos for scripts, different layouts). A data-dir–shaped single tree is an optional convenience (one connection + three bindings), not a requirement.

| Concept | Example |
|---|---|
| Connection | `Artifactory` — HTTPS base + token; kinds: media |
| Binding | Media → that connection + `repo=win-isos` + `**/Win11*.iso` |
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

- **Connections** — registry rows (path/share, HTTPS, git) with optional **token expiry** (day picker; when set, ≥ tomorrow). Path supports test/list/pull; HTTPS tests reachability and can pull an explicit relative file; git can be saved for later.
- **Scripts** — binding rows (connection picker filtered by artifact type + path/filter), with **Test connection** and **Test filter** (~5 sample hits)
- **Clutches** — binding rows (connection picker filtered by clutches artifact type + path/filter), pull into `clutches/`, Import dropdown when Library is on
- **Media** — binding rows with cache target (ISO / VirtIO), pull into `media/iso/` or `media/virtio/`, Import dropdown when Library is on

Each connection declares **artifact types** (scripts, clutches, media, packages) so domain pickers only offer relevant connections.

Enable Library under Settings → General. Deep links to Library Settings while the feature is off redirect to General with an enable hint.

### Connection health (#254)

The `library_connections` validator probes registered connections (via the same logic as **Test connection**) and watches optional token `expires_at` dates:

| Prefix | When |
|---|---|
| `Library connection:` | Path/HTTPS unreachable, unreadable, or auth failure |
| `Library connection token expiry:` | `expires_at` inside the Nest-style warning windows (default 30 / 7 days) or past due |

Empty `expires_at` → no token-expiry Alert for that connection. Git connections skip reachability until git list/pull lands (#251). Disabling Library or removing a connection resolves that connection’s Library-scoped Alerts. Settings → Test connection **resolves** a reachability Alert on success for a **saved** connection; it does not open Alerts on failure (validator owns opens).

Footer **Libraries** chip (when Library is enabled): muted with zero connections; green when healthy; red when any Library-scoped Alert is active. Hidden when Library is disabled (same clean-UI rule as the Library nav item). See [notifications.md — Footer vs Alerts](notifications.md#footer-vs-alerts-277).

Pull copies selected items into the normal data-dir paths (`automation/scripts/` for Scripts, `clutches/` for Clutches) so inventory, Used-by, and provisioning keep using local files by default.

<br>

## Inventory: Cache vs Catalog

**Default (cache-first):** domain panes list the operator cache only. **From library…** browses bindings and pulls chosen items into the cache.

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
