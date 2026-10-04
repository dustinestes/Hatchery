# ADR-0029: Guest SSH bootstrap and Guest transport plane

- **Status:** Accepted
- **Date:** 2026-10-03
- **Issues:** [#509](https://github.com/dustinestes/Hatchery/issues/509) (planning), epic [#202](https://github.com/dustinestes/Hatchery/issues/202)
- **Implementation / follow-on:** [#518](https://github.com/dustinestes/Hatchery/issues/518) (MSI bootstrap), [#519](https://github.com/dustinestes/Hatchery/issues/519) (guest key identity planning), [#497](https://github.com/dustinestes/Hatchery/issues/497) (`guest_transport`)
- **Related:** [#517](https://github.com/dustinestes/Hatchery/issues/517) (Library release-asset → Software), [#508](https://github.com/dustinestes/Hatchery/issues/508) (Drivers media), [#475](https://github.com/dustinestes/Hatchery/issues/475) / [#131](https://github.com/dustinestes/Hatchery/issues/131) (offline staging), [ADR-0003](0003-nest-registry-provider-factory.md), [ADR-0021](0021-controller-embeddable-operator-plane.md)
- **How-to:** [orchestration.md](../orchestration.md) (first-boot / ready-gate), [guest-transport.md](../guest-transport.md), [nest-transport.md](../nest-transport.md) (Nest plane only)

## Context

Guest first-boot on Windows installed OpenSSH via `Add-WindowsCapability -Online` (Windows Update FoD). Lab hatches spent ~15–20 minutes on that step alone (TiWorker / update catalog), while the payload is only a few MB. A timed smoke test of the [PowerShell/Win32-OpenSSH](https://github.com/PowerShell/Win32-OpenSSH) Win64 MSI (`ADDLOCAL=Server`) completed download + install + service/firewall in ~9 seconds. A hatch with FoD SSH steps removed reached fledged in ~8m 41s.

Nest remoting is already SSH-primary ([`lib/nest_transport.py`](../../lib/nest_transport.py)). Guest remoting is SSH-primary with WinRM Windows fallback ([`lib/guest_transport.py`](../../lib/guest_transport.py) / [#497](https://github.com/dustinestes/Hatchery/issues/497)). Cross-platform guests need SSH on the guest, and the Controller keeps Nest and Guest planes separate (ADR-0021).

## Decision

### 1. Ready-gate

`hatchery-ready` means first-boot finished with OpenSSH Server installed, `sshd` listening, and TCP 22 open. Until #497, the Controller may still **probe the flag over WinRM**. Hatch auth in that window remains admin username/password. After #497, prefer SSH for ready-probe and provision; WinRM stays Windows-only fallback. No separate winrm-ready / ssh-ready flags for v1.

### 2. Windows OpenSSH install (reject FoD default)

Default first-boot path (`hatchery-setup.ps1`):

1. Resolve the **latest** Win64 Server MSI from PowerShell/Win32-OpenSSH (`/releases/latest` or equivalent → `OpenSSH-Win64-*.msi`).
2. `msiexec /i … ADDLOCAL=Server /qn` → `C:\Program Files\OpenSSH` (not FoD under System32).
3. Automatic `sshd`, start service, firewall TCP 22, then write `hatchery-ready`.

**Do not** use `Add-WindowsCapability -Online` or FoD CAB/`-LimitAccess -Source` as the default hatch path.

**Release channel note:** After early semver, Win32-OpenSSH has only shipped Beta then Preview tags; “latest” is often ~a year old and still labeled Preview. Hatchery still tracks **latest** (not a frozen older Beta SHA) and documents that oddity for operators. Smoke evidence used `v9.5.0.0p1-Beta`; implementation resolves latest at hatch time.

**Offline staging** of the MSI is owned by [#475](https://github.com/dustinestes/Hatchery/issues/475) / [#131](https://github.com/dustinestes/Hatchery/issues/131), not this ADR’s bootstrap slice. **Library** packaging of GitHub release assets into Software packages is [#517](https://github.com/dustinestes/Hatchery/issues/517).

Drivers attachable media ([#508](https://github.com/dustinestes/Hatchery/issues/508)) remains for VirtIO / guest tools, not OpenSSH.

### 3. Nest transport ≠ Guest transport

| Plane | Module | Target | Protocol |
|---|---|---|---|
| Nest transport | `lib/nest_transport.py` | Nest host | SSH default, WinRM Nest fallback |
| Guest transport | `lib/guest_transport.py` (#497; Scripts/Software via `lib/provision.py`) | Guest VM | SSH primary, WinRM Windows fallback |

Naming is intentional and parallel. Do not call Nest transport from guest hatch paths. Do not reuse Nest `identity_file` as the guest authorized key by default. Extract shared OpenSSH **client** helpers (identity path reference, known_hosts, run/copy) for both planes; do not merge Nest and guest credentials into one module.

### 4. Guest key identity (deferred)

Controller pubkey injection, `guest_ssh_identities`, Clutch `remoting.ssh.authorize`, and purpose-built Hatchery guest keys are **not** locked here. Follow-on planning issue. Until then, MSI bootstrap only brings `sshd` up; hatch continues with admin password.

### 5. Install matrix (who)

| Family | Bootstrap | Source (now) |
|---|---|---|
| windows | Answer File companion | Latest GitHub MSI download |
| linux | Deferred with [#217](https://github.com/dustinestes/Hatchery/issues/217) | distro packages / cloud-init |
| macos | Deferred with UTM / [#210](https://github.com/dustinestes/Hatchery/issues/210) | Remote Login / sshd enable |

## Consequences

- Lab hatches avoid multi-minute FoD stalls when GitHub is reachable from the guest.
- Operators see a Preview/Beta-only upstream channel; docs explain why Hatchery still uses latest.
- #497 lands `guest_transport` with clear nouns and shared SSH client helpers (`lib/openssh_client.py`).
- Offline and Library-packaged OpenSSH remain follow-ons (#475 / #517).

## Alternatives considered

- **Keep FoD / offline FoD ISO on Drivers media:** rejected for default path after ~20 min vs ~9 s MSI evidence; Drivers stay for VirtIO (#508).
- **Freeze a specific Beta MSI SHA forever:** rejected; track latest with documented channel oddity.
- **Collapse Nest and guest into one transport module:** rejected; different targets, configs, and identity (ADR-0021).
- **Require guest keys in this ADR:** deferred; needs separate product design.
