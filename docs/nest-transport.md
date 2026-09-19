<br><br>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/icons/hatchery-icon-dark.svg">
  <img align="right" src="../.hatchery/branding/icons/hatchery-icon-light.svg" height="30" alt="Hatchery">
</picture>
<h1>Nest Transport</h1>
<br clear="both">

How Hatchery talks to a Nest (hypervisor host) over the network — the control plane, not guest provisioning.

<br>

## Contents

- [Contents](#contents)
- [Layers](#layers)
- [SSH Default (Key Reference)](#ssh-default-key-reference)
- [WinRM Fallback](#winrm-fallback)
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
| Nest transport fallback | Windows Nest when OpenSSH is unavailable or WinRM is preferred | **WinRM** — [#220](https://github.com/dustinestes/Hatchery/issues/220) |
| Guest provision | The VM after it fledges | WinRM for Windows guests (`lib/provision.py`) — unchanged |

Module: [`lib/nest_transport.py`](../../lib/nest_transport.py).

Per-Nest choice: `NestConnectionConfig.transport` is `ssh` (default) or `winrm`.

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

## WinRM Fallback

Use when a Windows Nest cannot (or should not) expose OpenSSH. `WinrmNestTransport` runs **PowerShell** on the Nest via pywinrm (NTLM by default, same family as guest provision).

| Field | Purpose |
|---|---|
| `host` | Nest hostname or IP |
| `username` | WinRM user |
| `password` | Session password (in-memory for the transport; encrypt at rest when Nest registry persists it — #110) |
| `port` | WinRM port (default `5985`; `5986` typical for HTTPS) |
| `use_ssl` | Use `https://…/wsman` when true |
| `auth_transport` | pywinrm auth transport (default `ntlm`) |

Guest WinRM in `lib/provision.py` is separate and unchanged.

<br>

## Connectivity Check

`nest_reachability` (validator) and **Test Nest connection** use one contract with a **diagnostic split** on the result (not two validators):

| Stage | Meaning | ``failure_class`` |
|---|---|---|
| **Endpoint** | TCP connect to Nest `host:port` succeeds | `endpoint` when it fails |
| **Nest transport** | Authenticated SSH / WinRM session runs a trivial command | `transport` when endpoint is up but session fails |

Local Nests skip both (co-located). Alerts and Test connection messages carry the class label so operators know whether to fix network/address vs Nest SSH/WinRM setup — hard contracts documented here, not transient magic.

**Test Nest connection** side effects ([#283](https://github.com/dustinestes/Hatchery/issues/283)):

| Nest row | Snapshot | Reachability Alerts |
|---|---|---|
| **Draft / unsaved** (id not in registry) | no write | no open / no resolve |
| **Saved** — failure | update (footer / Nests status) | **do not open** (validator owns opens) |
| **Saved** — success | update | **resolve** open Alert for that Nest |

The Settings button always refreshes UI status surfaces after the request so bell/footer catch up without waiting for the next poll.

`SshNestTransport` / `WinrmNestTransport.test_connection()` remain the transport-session probe. UI label: **Test Nest connection**.

<br>

## Remote Nest Patterns

| Nest type | After transport is up |
|---|---|
| libvirt | `virsh` / libvirt URI over SSH (`qemu+ssh://…`) |
| UTM | `utmctl` on the Mac Nest (SSH) |
| Hyper-V | PowerShell Hyper-V cmdlets (SSH or WinRM Nest transport) |

<br>

## Windows Nest: OpenSSH Server

For SSH to a Windows Hyper-V Nest, install and enable **OpenSSH Server** on that machine, allow the Hatchery host’s public key in the Nest user’s `authorized_keys`, and open TCP 22 (or your chosen port) as appropriate for the lab network.

If OpenSSH cannot be enabled, set the Nest transport to **WinRM** and open the WinRM listener (typically TCP 5985).

<br>

## Local Nests

`NestConnectionConfig(location="local")` needs no transport — providers talk to the hypervisor on the same machine as Hatchery.

<br>

---

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../.hatchery/branding/logos/hatchery-logo-dark.svg">
  <img align="left" src="../.hatchery/branding/logos/hatchery-logo-light.svg" height="48" alt="Hatchery">
</picture>
<div align="right">Hatch. Provision. Scale.</div>
<br clear="both">
