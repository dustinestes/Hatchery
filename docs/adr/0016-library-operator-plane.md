# ADR-0016: First-class Library operator plane

- **Status:** Accepted
- **Date:** 2026-09-24
- **Issues:** [#375](https://github.com/dustinestes/Hatchery/issues/375); storage [#367](https://github.com/dustinestes/Hatchery/issues/367); linked/synced UX [#370](https://github.com/dustinestes/Hatchery/issues/370)
- **Supersedes:** [ADR-0002](0002-library-in-pane-browser.md) (in-pane Library catalog as the primary browse surface)
- **Related:** [ADR-0007](0007-library-nest-content-planes.md), [ADR-0012](0012-library-cache-provenance-drift.md), [ADR-0015](0015-settings-partial-writes-worker-services.md), [ADR-0017](0017-library-connections-bindings-tables.md)
- **How-to:** [library.md](../library.md)

## Context

Library started as Settings JSON plus **Cached | Library** tabs on each domain pane ([ADR-0002](0002-library-in-pane-browser.md)). That kept catalog next to cache, but:

- Scripts / Clutches / Media each grew Import, Sync, re-attach, and drift chrome (mitigated partly by shared helpers; still the wrong ownership)
- Settings → Library mixed a feature flag with a full connection/binding admin surface
- Connection/binding blobs in `app_settings` coupled Library edits to Settings writes ([ADR-0015](0015-settings-partial-writes-worker-services.md) / [#367](https://github.com/dustinestes/Hatchery/issues/367))

Operators need one Library plane for configuration and (soon) link/sync lifecycle. Domain panes should stay focused on domain inventory and edit.

## Decision

1. **Top-level Library nav** (sidebar group), placed **above Notifications**, so Clutches / Media / Automations stay adjacent. Shown only when `library_enabled` is true.

2. **Settings owns enable only.** `library_enabled` remains a General (app_settings) toggle. Settings → Library section is removed once Library → Connections ships (redirect acceptable during transition).

3. **Library → Connections** is the admin surface for **connections and bindings on one page** (today’s Settings → Library content). Chrome: **connections list on the left**, **bindings for the selected connection on the right** (admin UI, not one long vertical stack). Binding label, filter, enable, Test, media target, cascade-on-remove stay here.

4. **Domain panes keep Import** (file always). **From library…** becomes a **deep link** into the Library plane (domain filter when useful), not a second full catalog/re-attach stack. Hide From library… when Library is disabled.

5. **Library → Content** (cross-domain attributed inventory, Sync, re-attach, [#370](https://github.com/dustinestes/Hatchery/issues/370) / [#384](https://github.com/dustinestes/Hatchery/issues/384) linked/synced language) is the home for lifecycle UX. Connections configures registry; Content inspects and corrects linked Cached items. Do not grow new permanent Library lifecycle UI on domain panes (Cached may deep-link into Content).

6. **Operator cache paths stay domain trees** (`automation/scripts/`, `clutches/`, `media/…`). Do **not** introduce a second attributed inventory root under `data-dir/library/` for pulled files. `{data_dir}/library/git/` remains the git **clone** cache only ([ADR-0009](0009-library-git-checkout-cache.md)). Provenance + `library_enabled` define “cut Library out,” not a parallel file tree.

7. **Configuration storage** for connections/bindings is first-class SQLite tables ([ADR-0017](0017-library-connections-bindings-tables.md)), edited from Library → Connections - not Settings JSON blobs.

## Consequences

**Good**

- One place for Library admin; domains stop cloning Library chrome
- Clear split: Settings flag vs Library plane vs domain cache
- Aligns storage (#367) with navigation (#375)

**Neutral / follow-on**

- Content **Available** catalog ships on Library → Content ([#392](https://github.com/dustinestes/Hatchery/issues/392)); domain in-pane Library tabs remain transitional until [#397](https://github.com/dustinestes/Hatchery/issues/397)
- #370 scenario matrix and Content UX land on the Library plane
- Export/backup must document Settings YAML vs Library DB ([ADR-0017](0017-library-connections-bindings-tables.md))

**Bad / accepted cost**

- Operators leave the domain pane to shop the Library (deep link must be one click)
- ADR-0002’s “catalog next to cache” preference is sacrificed for scalability and consistency

## Alternatives

| Alternative | Why not |
|---|---|
| Keep ADR-0002 in-pane catalog forever | Does not scale; duplicates Sync/re-attach; fights domain focus |
| Settings → Library forever + tables only | Storage fix without IA fix; Settings remains the wrong home |
| `data-dir/library/{domain}` for attributed files | Dual roots across list/import/hatch/Nest/drift on every Controller OS |
| Bindings as a separate nav item | Extra hop; bindings are connection-scoped - same page is enough |
