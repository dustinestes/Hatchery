# ADR-0009: Library git checkout cache on the Controller

- **Status:** Accepted
- **Date:** 2026-09-19
- **Issues:** [#251](https://github.com/dustinestes/Hatchery/issues/251), [#295](https://github.com/dustinestes/Hatchery/issues/295)
- **Code:** [`lib/library.py`](../../lib/library.py) (`ensure_git_checkout`, `delete_git_cache`)
- **How-to:** [library.md — Git connections](../library.md#git-connections-251)

## Context

Library `type: git` needs list and pull into the operator domain cache (Scripts / Clutches / Media) with the same basename + SHA-256 identity as path connections. Forge HTTP tree APIs differ per host and were not available for v1. Operators also need a clear story for when the shallow clone under the data directory is refreshed, and when it is removed.

## Decision

1. Keep a **Controller-side shallow clone** per connection at `{data_dir}/library/git/{connection_id}/`.
2. **Refresh on list/pull only** via `ensure_git_checkout` (clone `--depth 1` or `fetch --depth 1` + `reset --hard FETCH_HEAD`). **Test connection** uses `git ls-remote` only and does **not** refresh the checkout. There is **no** background forge sync.
3. **Connection id is stable** (Settings does not rename ids). Changing `base_uri` keeps the same cache directory. Disable ([#293](https://github.com/dustinestes/Hatchery/issues/293)) does not delete the checkout.
4. **Removing** a connection cascade-deletes domain bindings that reference it. For **git**, Settings may also delete the clone cache when the operator confirms (portable `pathlib` + `shutil.rmtree`, including Windows read-only `.git` files). That is the **clone cache**, not the operator domain cache.
5. Pulled domain files remain **create-only** — they can age independently of the checkout tip.
6. **Sparse / partial clone:** deferred for the shallow-clone path (multi-binding filters and domain extensions make ensure-time sparse non-trivial; typical script/clutch repos stay small). Prefer long-term [#307](https://github.com/dustinestes/Hatchery/issues/307) forge APIs instead of investing heavily in sparse git.
7. **Future:** forge `type` + `provider` plugins ([#307](https://github.com/dustinestes/Hatchery/issues/307) / [ADR-0010](0010-library-forge-providers.md)) list/pull via HTTP so Hatchery need not keep a working tree. Operator-cache drift vs source is [#308](https://github.com/dustinestes/Hatchery/issues/308). Dual-run: `type: git` clone path remains; forge does not supersede this ADR.

## Consequences

**Good**

- Reuses path-tree list/pull and SHA-256 identity without forge-specific parsers in v1
- Refresh cost is paid only when the operator browses or pulls
- Explicit delete prompt avoids silent disk growth and accidental wipe of domain cache

**Neutral / follow-on**

- Large monorepos remain wasteful under full shallow clone until #307
- Orphan checkouts if the operator declines delete — no GC UI in this ADR (#307 moots clone dirs)

**Bad / accepted cost**

- Disk and network for each git connection on the Controller
- Create-only domain cache can diverge from forge tip until #308

## Alternatives considered

| Alternative | Why not (for v1) |
|---|---|
| Forge Contents/Trees APIs only | Provider matrix + auth + SHA sourcing; tracked as #307 |
| Sparse checkout at ensure | Binding filters vary per domain; defer vs #307 |
| Background sync daemon | Unexpected network/disk; list/pull refresh is enough |
| Auto-update pulled domain files | Separate product (#308); create-only stays default |
