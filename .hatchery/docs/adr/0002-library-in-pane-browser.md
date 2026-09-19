# ADR-0002: In-pane Library browser (Cached | Library tabs)

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#244](https://github.com/dustinestes/Hatchery/issues/244), [#297](https://github.com/dustinestes/Hatchery/issues/297)
- **How-to:** [library.md — Inventory browse](../library.md#inventory-browse-cached--library)

## Context

Library catalogs outgrew the compact **Import → From library…** modal checklist. Operators need connection/path metadata, filter/sort, and batch pull — without losing a fast file Import path. Two shapes were on the table:

1. Richer **tabbed browse on each domain inventory page** (Scripts, later Media/Clutches)
2. A **dedicated Library browser route** plus per-domain quick Import

Maintaining both a full standalone browser and per-domain quick import adds IA/route cost. Domain panes already own cache inventory; keeping catalog browse next to cache preserves context for “pull what I need here.”

## Decision

1. Use **Cached | Library** tabs on domain inventory panes (Scripts, Media, Clutches) — not a separate Library browser route
2. Keep the in-pane **Import** control: file upload always; **Browse library…** switches to the Library tab when Library is enabled
3. Keep the tab strip **always visible**: Cached stays labeled; Library is interactive when Settings enables Library, otherwise dimmed/disabled (stable chrome for later tabs)
4. Library rows reuse Cached’s **name + muted path** pattern; connection column; SHA as copy-to-clipboard when known; no Source column in the browse table (connection type stays Settings/config)

Shared UI: `hatchery.bindInventoryTabs` / `hatchery.bindLibraryBrowser` (+ ByPrefix). Overlay of Library hits inside the Cached list remains [#250](https://github.com/dustinestes/Hatchery/issues/250).

## Consequences

**Good**

- One pattern across domains; catalog stays next to cache
- Quick Import stays obvious; no extra top-level nav
- Tab chrome remains familiar when Library is off

**Neutral / follow-on**

- Media/Clutches parity landed with Scripts (#297)
- Optional cache+catalog overlay (#250) is separate from this browse decision

**Bad / accepted cost**

- Domain templates each host a Library panel (mitigated with shared partials / JS helpers)
- Large catalogs still load in-pane (filters required; dedicated route deferred unless scale forces it)

## Alternatives considered

| Alternative | Why not |
|---|---|
| Dedicated `/library` browser + modal quick import | Two UIs to maintain; leaves domain panes without a stable “this is cached” story |
| Keep modal only, enrich columns | Poor fit for large catalogs; little room for filter/sort |
| Hide entire tab strip when Library is off | Breaks familiar chrome; weakens “Cached” as a standing label |
