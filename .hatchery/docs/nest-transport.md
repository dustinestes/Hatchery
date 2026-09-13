<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Nest Transport</h1>
<br clear="both">

How Hatchery talks to a Nest (hypervisor host) over the network — the control plane, not guest provisioning.

<br>

## Contents

- [Contents](#contents)
- [Layers](#layers)
- [SSH Default (Key Reference)](#ssh-default-key-reference)
- [Connectivity Check](#connectivity-check)
- [Remote Nest Patterns](#remote-nest-patterns)
- [Windows Nest: OpenSSH Server](#windows-nest-openssh-server)
- [Local Nests](#local-nests)

---

<br>

## Layers

| Layer | Talks to | Protocol (v1+) |
|---|---|---|
| Nest transport | Nest host (Linux / macOS / Windows) | **SSH** (default) — [#218](https://github.com/dustinestes/Hatchery/issues/218) |
| Nest transport fallback | Windows Nest when OpenSSH is unavailable | WinRM — [#220](https://github.com/dustinestes/Hatchery/issues/220) |
| Guest provision | The VM after it fledges | WinRM for Windows guests (`lib/provision.py`) — unchanged |

Module: [`lib/nest_transport.py`](../../lib/nest_transport.py).

<br>

## SSH Default (Key Reference)

Hatchery uses the host **OpenSSH client** (`ssh` on PATH). Identities are **referenced**, not stored:

| Field | Purpose |
|---|---|
| `host` | Nest hostname or IP |
| `user` | SSH user (optional; defaults to client default) |
| `port` | SSH port (default `22`) |
| `identity_file` | Path to an existing private key on the Hatchery host |
| `use_agent` | Allow `ssh-agent` (default true); set false to force the identity file only |
| `known_hosts` | `default` \| `accept-new` \| `skip` |

Private key bytes are never written into the Hatchery database for Nest auth.

<br>

## Connectivity Check

`SshNestTransport.test_connection()` runs a trivial remote command. UI label: **Test Nest connection** (not “Chirp”).

<br>

## Remote Nest Patterns

| Nest type | After SSH is up |
|---|---|
| libvirt | `virsh` / libvirt URI over SSH (`qemu+ssh://…`) |
| UTM | `utmctl` on the Mac Nest |
| Hyper-V | PowerShell Hyper-V cmdlets on the Windows Nest |

<br>

## Windows Nest: OpenSSH Server

For SSH to a Windows Hyper-V Nest, install and enable **OpenSSH Server** on that machine, allow the Hatchery host’s public key in the Nest user’s `authorized_keys`, and open TCP 22 (or your chosen port) as appropriate for the lab network.

If OpenSSH cannot be enabled, use the WinRM Nest transport fallback (#220) when it ships.

<br>

## Local Nests

`NestConnectionConfig(location="local")` needs no transport — providers talk to the hypervisor on the same machine as Hatchery.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
