# ADR-0001: Library API connection type + pluggable providers

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issue:** [#255](https://github.com/dustinestes/Hatchery/issues/255)
- **Code:** [`lib/library_api/`](../../lib/library_api/)
- **How-to:** [library.md — API connections](../library.md#api-connections-255)

## Context

Library connections already support `path`, `https`, and `git`. Orgs also keep media and scripts in **HTTP API catalogs** (Artifactory first for Hatchery’s author; others later). APIs differ per product, so a single “Artifactory connection type” would paint us into a vendor corner and force parallel types for Nexus, Harbor, etc.

We needed a shape that:

1. Lets operators configure base URI + auth once and bind filters per domain
2. Maps vendor payloads into Hatchery’s shared catalog hit (`name`, `relative_path`, `sha256`, …)
3. Allows adding or removing a product without editing path/HTTPS/git or sibling vendors

## Decision

1. Add one Library connection **`type: api`**
2. Require a **`provider`** discriminator (e.g. `artifactory`) validated against a registry
3. Put vendor HTTP, auth, and filter grammar in **`lib/library_api/<provider>.py`** modules that implement `BaseLibraryApiAdapter` (`test`, `list_hits`, `pull_file`)
4. Keep dispatch and shared catalog contracts in [`lib/library.py`](../../lib/library.py); register builtins at import/use time (same idea as validators / Nest providers)

Artifactory is the **first adapter**, not the product model. Settings labels: type **API**, provider **Artifactory**.

## Consequences

**Good**

- New catalogs = new module + `register` — isolation by default
- Settings provider dropdown is registry-driven
- Path / HTTPS / git remain unchanged

**Neutral / follow-on**

- Filter grammar is per-adapter (documented in `library.md`); richer browse UX ([ADR-0002](0002-library-in-pane-browser.md)) consumes shared hits only
- Token encryption remains [#110](https://github.com/dustinestes/Hatchery/issues/110)

**Bad / accepted cost**

- Contributors must not put vendor JSON parsing in `library.py` or cross-import adapters
- Operators must pick the correct provider; wrong type (e.g. path + Artifactory URL) fails with a path error

## Alternatives considered

| Alternative | Why not |
|---|---|
| Connection type `artifactory` | Does not scale; invents a type per vendor |
| Scrape generic HTTPS directory indexes | Fragile; not a real catalog API; `https` stays explicit-path GET |
| One mega-adapter with vendor `if` branches | Couples products; high regression risk |

## How to add a provider

1. Implement `BaseLibraryApiAdapter` in `lib/library_api/<id>.py`
2. Register in `lib/library_api.register_builtins()`
3. Document filter/auth in `library.md`
4. Add adapter-focused tests with mocked HTTP
