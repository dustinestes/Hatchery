# ADR-0010: Library forge connection type + pluggable providers

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#307](https://github.com/dustinestes/Hatchery/issues/307)
- **Code:** [`lib/library_forge/`](../../lib/library_forge/)
- **How-to:** [library.md - Forge connections](../library.md#forge-connections-307)
- **Related:** [ADR-0001](0001-library-api-adapters.md) (API catalogs), [ADR-0009](0009-library-git-checkout-cache.md) (historical git shallow clone; **Superseded** by [ADR-0020](0020-library-forge-path-only.md))

## Context

Library `type: git` shallow-cloned onto the Controller ([ADR-0009](0009-library-git-checkout-cache.md)). That reused path-tree walk but cost disk and network for whole trees. HTTPS-hosted forges (GitHub first) expose Trees/Contents APIs so Hatchery can list and pull without a working tree.

Artifact HTTP catalogs already use `type: api` + `provider` ([ADR-0001](0001-library-api-adapters.md)). Folding git forges into `api` would blur Settings (Artifactory vs GitHub) and mix filter grammars. Evolving `type: git` in place would break the clone contract operators already used.

## Decision

1. Add Library connection **`type: forge`** with a required **`provider`** discriminator validated against a registry.
2. Put forge HTTP in **`lib/library_forge/<provider>.py`** modules implementing `BaseLibraryForgeAdapter` (`test`, `list_hits`, `pull_file`).
3. Keep dispatch and shared catalog hits in [`lib/library.py`](../../lib/library.py); `source_type` is `"forge"`.
4. **Originally dual-run** with `type: git` (shallow clone for existing connections; forge never wrote `{data_dir}/library/git/{id}/`). Classic git was later removed ([ADR-0020](0020-library-forge-path-only.md) / [#406](https://github.com/dustinestes/Hatchery/issues/406)).
5. **First provider: `github`**. GitLab / Bitbucket / Gitea are separate issues (#310 / #311 / #312).
6. Git blob SHAs are **not** Hatchery SHA-256 - list hits may have `sha256: null`; compute SHA-256 on pull into the operator domain cache (create-only).
7. Pull **provenance** (SQLite, orphan/re-attach UX) is **[#308](https://github.com/dustinestes/Hatchery/issues/308)** - not this ADR.

## Consequences

**Good**

- No Controller clone for forge connections
- Same plugin shape as API adapters; new forge = new module + register
- Clear Settings types: Path / HTTPS / API / Forge (classic Git clone removed by ADR-0020)

**Neutral / follow-on**

- Operators use forge for HTTPS forges and path for local/share trees
- Drift/sync and provenance (#308) build on forge list/pull SHA story

**Bad / accepted cost**

- Provider matrix and rate limits are per-adapter concerns
- (Historical) Two ways to reach the same GitHub repo until ADR-0020 removed classic git

## Alternatives considered

| Alternative | Why not |
|---|---|
| Providers under `type: api` | Confuses artifact catalogs with git forges in Settings |
| Replace `type: git` entirely in #307 | Deferred to ADR-0020 / #406 after forge shipped |
| Sparse clone only | Still localizes a working tree; deferred in ADR-0009 in favor of forge |
