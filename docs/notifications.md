<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Notifications</h1>
<br clear="both">

Umbrella for operator-facing signals in Hatchery: **Alerts** (conditions that need attention), **Events** (hatch/provision transcript), and a future **Audit** trail. The sidebar group is labeled Notifications; each child concern has its own module, API, and pane.

<br>

## Contents

- [Contents](#contents)
- [Overview](#overview)
- [Separation of concerns](#separation-of-concerns)
- [Status surfaces](#status-surfaces)
- [Toasts](#toasts)
- [Alerts](#alerts)
  - [UI surfaces](#ui-surfaces)
  - [Lifecycle](#lifecycle)
  - [Background sync](#background-sync)
  - [Contributor tooling](#contributor-tooling)
- [Events](#events)
- [Audit (v2)](#audit-v2)

---

<br>

## Overview

Use **notifications** only where grouping the concerns makes sense (sidebar parent label, umbrella docs, `/notifications/...` route prefix). Alert-specific UI, code, and APIs use **alerts** — including the topbar bell and tray. Ephemeral **toasts** are a separate UI channel (`hatchery.showToast`) that never show Events or Audit. Hatch lifecycle uses **events** (`hatch_events`); inventory/CRUD history will use **audit** when v2 lands.

| Concern | What belongs | Surface |
|---|---|---|
| **Alerts** | Conditions that threaten Hatchery working: missing host tools, invalid Clutches, rare fundamental failures | Bell, tray, toasts (when new alerts arrive), Alerts pane, footer Hatchery chip |
| **Toasts** | Ephemeral UI feedback (copy succeeded, import conflict, etc.) — **not** persisted | Bottom-right overlay via `hatchery.showToast` |
| **Events** | Under-the-hood hatch/provision transcript (`hatch_events`, including `Write-HatchEvent` script lines) | Events pane ([#114](https://github.com/dustinestes/Hatchery/issues/114)) |
| **Audit (v2)** | Who/what changed Clutches; VM removed/renamed; session archived | Not implemented yet — not toast spam |

<br>

---

<br>

## Separation of concerns

```
Notifications (sidebar group)
  ├─ Alerts   — validation / health (`/notifications/alerts`, `GET /api/alerts`)
  └─ Events   — hatch lifecycle feed (`/notifications/events` — UI in #114)
```

Umbrella routes stay under `/notifications/...`. Alert CRUD lives in `lib/alerts.py`. Event writers stay in `lib/hatch.py` (`add_event`).

**Toast vs Alerts tray:** painting a toast never inserts an Alerts DB row by itself. Alert polling may call `hatchery.showToast` when a *new* alert arrives so operators notice it; Import/copy/delete panes also call `showToast` for short-lived UI feedback without touching the tray. Alerts store the same **tier** vocabulary as toasts (`info` / `warning` / `alert`) via `record_alert(message, tier=...)`; polling passes that tier through to `showToast` and the tray badge.

<br>

---

<br>

## Status surfaces

Controller UI health display is a three-layer contract ([#282](https://github.com/dustinestes/Hatchery/issues/282)) — not a SPA framework and not WebSockets in v1:

| Layer | Role | Examples |
|---|---|---|
| **Gather** | Probe / check the world | Validators ([validators.md](validators.md)); Hatch lifecycle poller stays separate |
| **Store** | Persist findings and thin status | `alerts` table; `validator_runs`; Nest reachability snapshot in settings (`nest_reachability_status`) |
| **Surface** | Read/poll stored state; decide what to show | Bell, tray, toasts-on-new-alert, footer chips, later Libraries |

Surfaces **do not** invent health logic or re-run checks. They call APIs over stored state (`GET /api/alerts`, `GET /api/plane-status`, …) and ask whether anything related to them should be shown.

### Client bus (`static/app.js`)

| API | Purpose |
|---|---|
| `hatchery.refreshStatusSurfaces()` | Official refresh — fetches Alerts + plane status, updates built-in surfaces, then notifies tick listeners. Called every **15s** and after Settings → Test Nest connection |
| `hatchery.onStatusTick(fn)` | Register a callback; receives `{ alerts, planeStatus }` after each refresh. Returns an unsubscribe function. Prefer this over a new `setInterval` |

Built-in consumers today: Alerts bell / tray / toast-once, footer **Hatchery** + **Nests** + **Libraries** (Libraries only when Library is enabled - [#254](https://github.com/dustinestes/Hatchery/issues/254)), **Alerts pane** table, **Validators** pane run history (filters / finding tiers - [#280](https://github.com/dustinestes/Hatchery/issues/280)), and the **Dashboard** Nest tile (from `planeStatus`) plus VM tile via `GET /api/dashboard-summary` on the same tick ([#329](https://github.com/dustinestes/Hatchery/issues/329)). Do not put VM inventory on `/api/plane-status` (that endpoint is polled on every pane).

```js
// Pane example — no new timer
var off = hatchery.onStatusTick(function (payload) {
  // payload.alerts, payload.planeStatus — or fetch pane-specific APIs here
});
// off() when leaving the pane if needed
```

### Rollups and shadow state

Footer rollups prefer **Alerts** (+ live Nest registry) where practical (`lib/plane_status.py`). Nest reachability also keeps a thin **snapshot** so the Nests chip can show unreachable counts between validator ticks — document that dual read; do not invent a third store for new chips. A future `GET /api/status-bundle` or SSE is optional and not required for v1.

Non-goals: JS framework rewrite; WebSockets as the first step; folding hatch lifecycle Events into validators; making validators push to the DOM.

<br>

---

<br>

## Toasts

Fixed bottom-right stack (`#toast-container` in `templates/ui/base.html`). Implemented in `static/app.js` as `hatchery.showToast` and styled in `static/style.css` (`.toast*`).

### API

```js
hatchery.showToast(message, tier?, durationMs?)
```

| Argument | Notes |
|---|---|
| `message` | Plain text shown in the toast body |
| `tier` | `'info'` \| `'warning'` \| `'alert'` (alias `'error'` → `alert`). Default `'alert'` |
| `durationMs` | Optional hold time before dismiss. Defaults: info **2200**, warning **4500**, alert **5000** |

Each toast shows a **tier label** (Info / Warning / Alert) plus an icon so meaning is not color-only. Alert-tier toasts use `role="alert"`; info/warning use `role="status"`. The container keeps `aria-live="polite"`. Enter/exit motion respects `prefers-reduced-motion`.

### When to use which

| Use | Prefer |
|---|---|
| Condition that needs attention until fixed (missing tool, invalid Clutch, import in progress) | `lib.alerts.record_alert` (bell + tray + pane); toast may appear via alert polling |
| Short UI confirmation or rejection (path copied, file exists, delete failed) | `hatchery.showToast` only |
| Hatch/provision transcript | Events pane — not toasts |

<br>

---

<br>

## Alerts

Alerts are stored in the `alerts` table in `hatchery.db`. The browser refreshes Alerts and plane status together via `hatchery.refreshStatusSurfaces` every **15 seconds** ([#278](https://github.com/dustinestes/Hatchery/issues/278), [#282](https://github.com/dustinestes/Hatchery/issues/282)) so the bell, tray, toasts, and footer stay in sync without a full page refresh. Settings → Test Nest connection also triggers an immediate refresh. Test Nest connection does **not** open reachability Alerts for draft/unsaved Nest rows, and does not open them on failure for saved Nests either — only the `nest_reachability` validator opens those; a successful Test **resolves** an open reachability Alert for that Nest ([#283](https://github.com/dustinestes/Hatchery/issues/283)).

### UI surfaces

**Toast overlay** — brief banner in the bottom-right when a *new* alert arrives (via `hatchery.showToast`). Each alert **row** is toasted at most once (persisted in `localStorage` as id → `created_at`) so navigation does not re-fire toasts, and wiping `hatchery.db` (sqlite id reuse) still toasts the new row ([#288](https://github.com/dustinestes/Hatchery/issues/288)). “New” means unresolved and newer than the last tray-open time (parsed timestamps), or the same numeric id with a different `created_at`. Nest reachability keeps **one** active Alert per Nest id (renames / detail text must not stack duplicates). Auto-dismiss uses the alert-tier default (~5s). Same component as UI-only toasts.

**Bell badge** — small red **dot** (no count) when there are unresolved alerts newer than the last time the tray was opened. Opening the tray clears the badge; active alerts remain listed in the tray / Alerts pane.
**Tray dropdown** — headed **Alerts**; recent alerts; “View all” links to `/notifications/alerts`.

**Alerts pane** — alert history, reverse-chronological (UI shows the newest 500; older rows remain in the DB). Uses a **list shell** shared with Events and Validators ([#298](https://github.com/dustinestes/Hatchery/issues/298)): title + filter bar stay put; the table scrolls in a bounded region. Filters: tier and status (Active / Resolved). Subscribes to `hatchery.onStatusTick` and refreshes from `GET /api/alerts?limit=500` so new rows appear without a full page reload (same bus as Validators — [#282](https://github.com/dustinestes/Hatchery/issues/282)). Route: `/notifications/alerts`.

![Alerts pane — full table view](assets/screenshot_notifications_pane.png)

### Lifecycle

Alerts are written by calling `lib.alerts.record_alert(message, tier="alert")`. This inserts a row into the `alerts` table with:

- `created_at` — UTC ISO 8601 timestamp ending in `Z` (e.g. `2026-09-18T20:55:01Z`)
- `message` — human-readable description
- `tier` — `info` \| `warning` \| `alert` (same as `hatchery.showToast`; default `alert`)
- `resolved = 0`, `resolved_at = NULL`

An alert is **active** while `resolved = 0`. It is **resolved** by the system (never by the user) when the condition that triggered it no longer exists. Resolution sets `resolved = 1` and `resolved_at` to the resolution timestamp.

Resolved alerts remain as historical records. They appear in the Alerts pane with a “Resolved” status badge and are excluded from the active alert count used by the bell badge and footer indicator. Hatchery does not auto-delete alert rows by count or age.

**Nest removed from Settings** ([#275](https://github.com/dustinestes/Hatchery/issues/275)): saving the Nest registry after deleting a Nest resolves Nest-scoped findings that embed that Nest’s id (`Nest reachability:`, `Nest capability:`, `Nest SSH identity expiry:`). Rows stay resolved for history; the bell clears. Reachability snapshot entries for removed Nest ids are pruned so Nest plane rollups stay honest.

**Library connection removed / Library disabled** ([#254](https://github.com/dustinestes/Hatchery/issues/254)): saving Library Settings after deleting a connection resolves Library-scoped findings for that connection id. Disabling Library under General resolves all Library-scoped Alerts and hides the Libraries footer chip. **Connection `enabled: false`** ([#293](https://github.com/dustinestes/Hatchery/issues/293)) skips that row in the Library validator and resolves its Library-scoped Alerts while the row remains in Settings; the footer **Libraries** rollup counts only enabled connections.

| State | Rendered as |
|---|---|
| `resolved = 0` | Active badge |
| `resolved = 1` | Resolved badge + timestamp |

### Background sync

Health and content checks run as **pluggable validators** ([validators.md](validators.md), [#268](https://github.com/dustinestes/Hatchery/issues/268)). Each validator has its own enable flag and interval under Settings → General. Run history is stored in `validator_runs` and shown under **Notifications → Validators** (filters sticky above a scrollable run table — [#298](https://github.com/dustinestes/Hatchery/issues/298); filters: validator / status / tier). Runs that detect problems use `status=findings` and a non-`info` tier ([#280](https://github.com/dustinestes/Hatchery/issues/280)). Library connection health is `library_connections` ([#254](https://github.com/dustinestes/Hatchery/issues/254)).

**Findings** still use the Alerts table (bell / tray). Examples:

- `controller_requirements` — Controller-plane tools (`Controller requirement:`)
- `nest_reachability` — Nest endpoint / transport (`Nest reachability:` with `endpoint` vs `transport` reason on the result)
- `nest_capability` — Nest hypervisor tools (`Nest capability:`). On Remotes, gated by reachability ([#286](https://github.com/dustinestes/Hatchery/issues/286)) — unreachable Nests skip capability and clear those Alerts
- `clutch_files` — invalid Clutch YAML (`Invalid Clutch file:`)
- `nest_key_expiry` — Nest SSH identity windows

The Hatch lifecycle poller (`_sync_hatch_status`) remains separate and uses the **Hatch status poll** interval (`bg_interval`).

### Footer vs Alerts (#277)

| Surface | Meaning |
|---|---|
| **Bell / Alerts pane** | All active findings (Controller, Nest reachability, Nest capability, Library connections, Clutches, …) |
| **Footer Hatchery** | Controller-plane rollup — green when no Controller-scoped alerts (excl. info); red when requirements / invalid Clutches / etc. need attention |
| **Footer Nests** | Nest-plane rollup — muted when no Nests registered; green when all registered Nests are OK; red when any unreachable or Nest-scoped alert is active |
| **Footer Libraries** | Content-plane rollup ([#254](https://github.com/dustinestes/Hatchery/issues/254)) — **hidden** when Library is disabled; muted when enabled with zero connections; green when connections exist and no Library-scoped alerts; red when any Library connection / token-expiry Alert is active |

Status is glanceable only (no tray, no nav). Payload comes from `GET /api/plane-status` (live Nest registry + Library flag/connections + alerts + reachability snapshot). The Libraries chip stays in the DOM (`hidden` when off) so enabling Library updates visibility on the next status poll without a full page reload. The same status-surfaces bus as Alerts (`refreshStatusSurfaces` / `onStatusTick`) keeps footer and bell aligned ([#278](https://github.com/dustinestes/Hatchery/issues/278), [#282](https://github.com/dustinestes/Hatchery/issues/282)).

Library prefixes: `Library connection:`, `Library connection token expiry:` — see [library.md — Connection health](library.md#connection-health-254).

### Observability decision (#263)

Keep health checks as **pluggable validators** ([validators.md](validators.md), [#268](https://github.com/dustinestes/Hatchery/issues/268)) rather than a second Host-plane registry. Nest reachability is `nest_reachability`; do not extend a private `_background_loop` catch-all. Hatch status polling stays a separate orchestration poller.

#### Import copies (`lib/import_files.py`)

UI **Import** on Clutches, Media (ISO / VirtIO), and Automations → Scripts uploads files into the data directory. While the Nest is writing a batch, Hatchery records an active alert prefixed with `"Import in progress:"` at tier **info**. When the request finishes, that alert is resolved and a `"Import finished:"` trail alert is recorded as already resolved (history only — it does not keep the bell active) at tier **info** on full success or **warning** when files were skipped/failed. Conflicts refuse overwrite and never replace an existing basename.

The result: alert state in the database always reflects the current environment. If a missing tool is installed or a broken Clutch file is fixed, the alert is resolved on the next sync cycle without requiring a restart.

### Contributor tooling

A seed script inserts sample alerts for UI validation and screenshot capture. Seeded records are marked with `[seed]` so they can be identified and removed without touching real alert history.

```bash
# Insert the next curated alert (cycles through samples with each call)
uv run python .hatchery/tooling/seed_alerts.py seed

# Insert a custom message
uv run python .hatchery/tooling/seed_alerts.py seed "Controller requirement: 'ssh' is not installed"

# Insert all curated samples
uv run python .hatchery/tooling/seed_alerts.py seed all

# Remove all seeded alerts
uv run python .hatchery/tooling/seed_alerts.py clean
```

The script requires Hatchery to have been started at least once (so `hatchery.db` exists). It reads the same data directory configuration as the app.

<br>

---

## Events

Hatch / provision lifecycle and `Write-HatchEvent` script lines are stored in `hatch_events` and shown on the Events pane under `/notifications/events` ([#114](https://github.com/dustinestes/Hatchery/issues/114)). The pane uses the same list shell as Alerts/Validators ([#298](https://github.com/dustinestes/Hatchery/issues/298)): a **VM** filter selects among active hatch VMs, and the event table scrolls below. Polls `GET /api/sessions/.../events`. Events do not drive the Alerts bell, tray, or toasts. Event rows for a session are purged when that session is archived — see [events.md — Retention](events.md#retention).

See [events.md](events.md) and [orchestration.md](orchestration.md).

<br>

---

## Audit (v2)

Clutch create/save/delete, VM cull/rename, and session archive are **not** alerts and are **not** written as toast-driving activity. A future audit trail will cover inventory and authoring changes without mixing them into the Alerts surfaces — tracked in [#164](https://github.com/dustinestes/Hatchery/issues/164).

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
