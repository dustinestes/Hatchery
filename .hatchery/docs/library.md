<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Library and Nest Cache</h1>
<br clear="both">

How Hatchery keeps a local-first operator model while supporting shared Library sources and per-Nest content caches.

<br>

## Contents

- [Contents](#contents)
- [Planes](#planes)
- [Identity](#identity)
- [Settings and Import](#settings-and-import)
- [Hatch Preflight](#hatch-preflight)
- [Settings Profiles](#settings-profiles)
- [Future: Allow Remote Content](#future-allow-remote-content)

---

<br>

## Planes

Hatchery does not become a CMS. Content moves through explicit planes:

| Plane | Role |
|---|---|
| **Library** | Product feature: shared/org content you can browse and pull from |
| **Sources** | Named endpoints inside Library (git forge, NAS/share, HTTPS/artifacts) — field language in Settings |
| **Operator cache** | This Hatchery instance’s data directory — `media/`, `automation/`, `clutches/` |
| **Nest cache** | The same layout on the Nest host that will attach or run the content |
| **Attach / run** | Hypervisor (or guest tooling) uses Nest-reachable paths |

For a **local Nest**, the operator data directory **is** the Nest cache (today’s behavior).

For a **remote Nest**, the operator cache and Nest cache are different trees. Hatchery **ensures** required files exist on the Nest (copy/verify) before hatch; it does not stream multi-GB ISOs from the operator laptop over the Nest control plane at attach time.

Shared storage that the Nest already mounts (NFS/SMB) counts as Nest cache when paths resolve on that Nest.

Nest transport (SSH default, WinRM fallback) is described in [Nest transport](nest-transport.md). Data-dir bootstrap vs SQLite Settings: [Settings storage](settings.md).

<br>

## Identity

Content is identified by **basename + SHA-256** checksum — not a GUID catalog.

- Basename matches how Clutches already reference media and scripts (e.g. `win11.iso`)
- Checksum ensures the Nest cache has the intended bytes when multiple sources or machines are involved
- Ensure/sync and hatch preflight compare on this pair

<br>

## Settings and Import

**Settings owns Library configuration** (feature flag and source definitions). Asset panes keep an in-context control so operators shop next to Clutches, Automations, or Media.

| `library_enabled` | Import control |
|---|---|
| Off (default) | Single **Import** — file into the operator cache |
| On | Import becomes a dropdown: **From file…** \| **From library…** |

When Library is on, Settings gains a **Library** section (same sidebar section pattern as General / Security / Display). That section lists and edits **sources** (where content is pulled from). Deep links to Library Settings while the feature is off should redirect or prompt to enable Library first.

Pull copies selected items into the normal data-dir paths so inventory, Used-by, and provisioning keep using local files.

<br>

## Hatch Preflight

Default hatch contract:

1. Resolve required content (media, and other cache-backed artifacts as applicable) for the target Nest
2. Verify each item exists in the **Nest cache** (basename; SHA-256 when ensure/Library metadata is present)
3. If missing, fail with a clear UI/API error — or run ensure/sync first when the operator requested it
4. Only then call the provider create/attach path with Nest-local paths

Local Nest preflight is a filesystem check under the data directory (no network ensure).

<br>

## Settings Profiles

Live operational Settings remain in SQLite (`app_settings`). Portability across machines uses a **profile** document (YAML, `version: 1`): export from / import into the DB (merge or replace). The same format serves personal multi-host use and light enterprise “golden” config.

Bootstrap `data_dir` stays in the external bootstrap file — profiles do not replace the need to know where the database lives. Continuous path/git watch of a profile is a later enhancement; export/import is the first step.

<br>

## Future: Allow Remote Content

Orgs with high bandwidth or all-local DC networks may later opt in so a Nest can attach or run content from a remote source **without** pre-download into the Nest cache. That flag is not the default and is not required for Library MVP.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
