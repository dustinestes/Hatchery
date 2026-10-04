# Guest transport

Controller → **guest VM** remoting for ready-probe, Scripts, Software staging/install/detect, and related hatch steps.

This is **not** Nest transport. Nest SSH/WinRM talks to the Nest hypervisor host; Guest transport talks to the VM after first-boot. Shared OpenSSH **client** helpers live in [`lib/openssh_client.py`](../lib/openssh_client.py); credentials and configs stay separate ([ADR-0029](adr/0029-guest-ssh-bootstrap-and-guest-transport.md)).

## Preference

| Channel | Role |
|---|---|
| **SSH** | Primary (run PowerShell + SCP file put) |
| **WinRM** | Windows fallback when SSH TCP/auth is unavailable |

Resolve path: [`lib/guest_transport.py`](../lib/guest_transport.py) (`resolve_guest_transport`). Callers in [`lib/provision.py`](../lib/provision.py) and [`lib/software_provision.py`](../lib/software_provision.py) go through that seam - do not open a second WinRM/SSH path for Scripts vs Software.

## Auth (today)

Hatch admin username/password (stored on the hatch VM row for the session). Password SSH uses Controller `sshpass` when present, otherwise a short-lived `SSH_ASKPASS` helper. Guest key identity / `authorized_keys` is deferred ([#519](https://github.com/dustinestes/Hatchery/issues/519)). Do **not** reuse Nest `identity_file` as the guest key by default.

## Ready-gate

`hatchery-ready` still means first-boot finished with OpenSSH up (ADR-0029). The Controller probes the flag over Guest transport (SSH preferred). See [orchestration](orchestration.md).

## Operator visibility

When SSH cannot be used, hatch events record a WARN fallback reason and INFO notes the chosen remoting kind (`ssh` / `winrm`).

## Related

- Nest plane: [nest-transport.md](nest-transport.md)
- Software staging: [software.md](software.md)
- Issue: [#497](https://github.com/dustinestes/Hatchery/issues/497)
