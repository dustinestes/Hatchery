# ADR-0037: Guest SSH known_hosts under data_dir keyed by VM UUID

- **Status:** Accepted
- **Date:** 2026-10-17
- **Issues:** [#593](https://github.com/dustinestes/Hatchery/issues/593)
- **Related:** [ADR-0029](0029-guest-ssh-bootstrap-and-guest-transport.md), [ADR-0030](0030-controller-remoting-identities.md), [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md), [#594](https://github.com/dustinestes/Hatchery/issues/594) (Nest plane sibling)
- **How-to:** [guest-transport.md](../guest-transport.md)

## Context

Guest SSH used OpenSSH `known_hosts=accept-new` against the operator personal `~/.ssh/known_hosts`. Lab Nest DHCP reuses guest IPs across hatches. A new VM at a recycled IP presents a new host key; OpenSSH reports `REMOTE HOST IDENTIFICATION HAS CHANGED`, hatch falls back to WinRM, then Guest SSH authorize fails on key verify.

Destroy-time `ssh-keygen -R <ip>` is incomplete (virsh outside Hatchery, unknown IP, lease already gone). Nest plane already has a separate `known_hosts` policy on Nest rows; guest must not share Nest trust or personal known_hosts.

## Decision

1. **Hatchery-owned guest trust file:** Controller OpenSSH guest client uses  
   `{data_dir}/remoting/known_hosts/guest` as `UserKnownHostsFile`, with `GlobalKnownHostsFile=/dev/null`, so personal and system known_hosts are not consulted for guest remoting.
2. **Key by VM UUID:** Pass `HostKeyAlias=<vm_id>` (pre-minted UUID from ADR-0036 / `hatch_vm_status.libvirt_uuid`) on guest SSH/SCP. Trust entries are namespaced by VM identity, not DHCP IP.
3. **StrictHostKeyChecking stays meaningful:** Default guest policy remains `accept-new` against the Hatchery file (first sight of an alias is trusted; changed key for the same alias still fails). Do not default to `skip` / null known_hosts.
4. **Planes stay separate:** Nest trust file and policy are out of scope here ([#594](https://github.com/dustinestes/Hatchery/issues/594)). Do not merge Nest and Guest known_hosts files.
5. **Destroy hygiene:** Best-effort `ssh-keygen -R <vm_id>` against the guest file when Destroy succeeds or hatch marks the VM destroyed. Alias + Hatchery file are the durable guard; prune is cleanup only.

## Consequences

- Recycled guest IPs no longer collide in guest trust when each hatch has a distinct `vm_id`.
- Operators’ `~/.ssh/known_hosts` is untouched by guest remoting.
- Hatch / authorize / provision paths must plumb `vm_id` into guest transport construction.
- Nest plane alignment lands in #594 under `remoting/known_hosts/nest`.

## Alternatives considered

- **Destroy-only IP prune:** Rejected as sole fix; incomplete and race-prone.
- **Default `known_hosts=skip` for guests:** Rejected as default MITM weaken; optional Settings self-heal may follow later.
- **Stable DNS / mDNS guest names:** Deferred; UUID alias works with current DHCP lab Nests.
