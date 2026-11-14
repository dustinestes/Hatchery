# ADR-0047: Destroy removes Nest VM storage

- **Status:** Accepted
- **Date:** 2026-11-14
- **Issues:** [#120](https://github.com/dustinestes/Hatchery/issues/120), Wave 0 in [#628](https://github.com/dustinestes/Hatchery/issues/628)
- **Related:** [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md), [ADR-0039](0039-nest-health-gate-and-nest-storage.md), [#592](https://github.com/dustinestes/Hatchery/issues/592), [#601](https://github.com/dustinestes/Hatchery/issues/601), [#552](https://github.com/dustinestes/Hatchery/issues/552)
- **How-to:** [providers/](../providers/), [cli/vm.md](../cli/vm.md)

## Context

Early [#120](https://github.com/dustinestes/Hatchery/issues/120) proposed **opt-in** disk deletion on Cull (prompt, or a Settings “always delete” toggle), gated on a blank-by-default storage path. Product since then:

- Verb is **Destroy**, not Cull ([#552](https://github.com/dustinestes/Hatchery/issues/552))
- Guest disks and answer media live under `{nest_storage}/{vm_id}/` ([ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md))
- Libvirt and Hyper-V Local Destroy already remove guest disks and Nest VM dir leftovers
- Shared catalog OS/VirtIO ISOs must survive Destroy ([#601](https://github.com/dustinestes/Hatchery/issues/601))

Wave 0 free MVP needs a single cross-provider contract so Tart/UTM and remotes do not reintroduce “keep orphan disks by default.”

## Decision

1. **`BaseProvider.destroy_vm` removes Nest VM storage.** Implementations must delete guest-allocated disks attached to the VM and best-effort clear `{nest_storage}/{vm_id}/` leftovers (answer media, stray files, empty dir). Legacy `nest-work` answer paths may be deleted when found by name.
2. **Shared Nest catalog media is never Destroy fodder.** Eject or otherwise protect OS/VirtIO (and similar) catalog sources before hypervisor bulk-remove so `--remove-all-storage` (or equivalent) cannot delete shared ISOs ([#601](https://github.com/dustinestes/Hatchery/issues/601)).
3. **Safety gate is Destroy itself** (UI confirm / intentional CLI `hatchery vm destroy`). No Settings “keep disk on Destroy” and no second “also delete disk?” prompt for free MVP.
4. **Future Local providers** (Tart, UTM, …) inherit this contract when they implement `destroy_vm`.

This ADR does **not** change ADR-0036 layout; it locks Destroy semantics that 0036’s cleanup clause assumed.

## Consequences

**Good**

- Operators get honest teardown: Destroy means the Nest VM footprint is gone
- Matrix / Wave 0 honesty: no provider-specific “disk left behind” footgun
- Original #120 opt-in design is explicitly rejected (issue closes on this lock)

**Neutral / follow-on**

- Recovering a disk after Destroy requires Nest-side backups outside Hatchery
- Remote Nest Destroy (Enterprise) must meet the same contract over Nest Agent jobs

**Bad / accepted cost**

- Mistaken Destroy is more destructive than “undefine only” - mitigated by confirm / CLI intent

## Alternatives

| Alternative | Why not |
|---|---|
| Opt-in delete + Settings always-delete (#120 original) | Orphans fill Nest storage; two mental models; conflicts with Destroy naming |
| Keep disks, delete only domain/VM object | Invisible leftovers; failed Wave 0 storage contract |
| Supersede ADR-0036 for cleanup only | Layout and Destroy semantics are separate decisions; keep 0036 |
