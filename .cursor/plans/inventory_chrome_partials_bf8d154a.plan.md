---
name: Inventory chrome partials
overview: Drop per-pane title/subtitle chrome. Put the current page title in the topbar (admin-console style). Shared inventory partials start at the toolbar/filters/split layout, not pane_header. Locked as #390 (topbar) and #391 (partials); finish Content on #389 first.
todos:
  - id: finish-content-chrome
    content: "Finish #384/#389 Content inventory chrome only; do not strip app-wide titles here"
    status: completed
  - id: topbar-page-title
    content: "#390 feat: topbar page title from active_pane; remove pane-header title+subtitle app-wide"
    status: pending
  - id: follow-on-partials
    content: "#391 feat: inventory toolbar/filters/split Jinja partials after #390"
    status: pending
isProject: false
---

# Topbar titles + inventory chrome

## Locked issues

| Issue | Scope |
|---|---|
| [#389](https://github.com/dustinestes/Hatchery/pull/389) / [#384](https://github.com/dustinestes/Hatchery/issues/384) | Library → Content + inventory **class** chrome. Not app-wide title strip. |
| [#390](https://github.com/dustinestes/Hatchery/issues/390) | Topbar page title; remove `pane-header` title/subtitle app-wide |
| [#391](https://github.com/dustinestes/Hatchery/issues/391) | Shared inventory Jinja partials (toolbar, filters, split) after #390 |

## Product direction

Per-pane `pane-header` (h1 + subtitle) reads like a marketing/docs site. Prefer **admin console**: sidebar shows where you are; **topbar shows the current page title**; body starts with tools (section toolbar, filters, split list/detail).

Ignore `_pane_header` in any shared inventory extract. Do not reintroduce title + subtitle blocks.

## Topbar page title (#390)

Today [`templates/ui/base.html`](templates/ui/base.html) topbar is brand + Hatch / + Clutch + alerts + theme. There is no context title.

| Change | Detail |
|---|---|
| Topbar | Add a single context title (e.g. `topbar-page-title`) between brand and actions |
| Source of truth | Map `active_pane` → short label in `base.html` or context processor |
| Remove | Per-pane `pane-title` / `pane-subtitle` blocks |
| Keep | `{% block title %}` for browser tab |
| Actions | Relocate header-only actions into section toolbars or topbar secondary actions |

Out of scope for #390: breadcrumbs, subtitle under topbar title, inventory partial extract (#391).

## Shared inventory chrome (#391, no pane_header)

| Partial | Owns |
|---|---|
| `_inventory_toolbar.html` | section title + actions slot |
| `_inventory_cached_filters.html` | search + Library state + optional extras |
| Existing `_inventory_source_tabs.html` | Cached \| Library (domain panes only) |
| `_inventory_split_layout.html` | `scripts-layout` + nav/content wrappers |

Do **not** add `_pane_header.html`. Keep domain detail and Library browser in each pane.

## Rollout order

1. Finish #389 (Content class chrome) - done in follow-up commit on the PR
2. Ship #390 (topbar titles)
3. Ship #391 (inventory partials)
4. Optional later: rename `scripts-*` CSS to `inventory-*`
