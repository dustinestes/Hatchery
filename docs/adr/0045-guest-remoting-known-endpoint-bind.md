# ADR-0045: Guest remoting known-endpoint bind

- **Status:** Accepted
- **Date:** 2026-11-11
- **Issues:** [#621](https://github.com/dustinestes/Hatchery/issues/621)
- **Related:** [ADR-0029](0029-guest-ssh-bootstrap-and-guest-transport.md), [ADR-0036](0036-pre-mint-vm-uuid-nest-storage.md), [ADR-0037](0037-guest-ssh-known-hosts-hostkeyalias.md), [ADR-0044](0044-free-head-local-nest-only.md)
- **How-to:** [guest-transport.md](../guest-transport.md)

## Context

Guest remoting accepted any host/IP as long as credentials worked. `vm_id` was optional and used only as OpenSSH `HostKeyAlias` (ADR-0037). Two free Controllers (or a smuggled DB row) could drive remoting at arbitrary guest IPs without proving the VM belongs to this Controller's Nest inventory - hierarchy-lite via the guest plane (EH-10).

## Decision

1. Every authenticated guest remoting session (`resolve_guest_transport` / `get_guest_transport` / guest SSH authorize) requires a stable **`vm_id`** (pre-minted UUID).
2. Before connect, the Controller verifies via Nest provider APIs: UUID resolves on a Nest in **this** registry, live `get_vm_ip(name)` matches the intended host, and hatch status (when present) is not `destroyed`.
3. TCP-only probes (`guest_health`, `guest_remoting_ready`) may stay Nest-name / raw-IP cheap checks; they must not become a second authenticated remoting path.
4. WinRM is not an escape hatch - the same bind applies.
5. Implementation: `lib/guest_endpoint.py` (`assert_guest_host_bound` / `resolve_known_guest`).

## Consequences

- Hatch / authorize / provision must plumb `vm_id` (and preferably `nest_id`) into guest transport construction.
- Foreign IPs and missing UUIDs fail closed with clear operator messages.
- Legitimate Local Nest hatch → authorize → provision still works when Nest reports matching UUID and IP.
- Nest Agent / Remote Nest hierarchy remain Enterprise; this only hardens free guest remoting.

## Alternatives considered

- HostKeyAlias alone as authorization: rejected (trust namespace ≠ inventory bind).
- Hypervisor-channel-only remoting: out of scope (#621 non-goal).
