# Nest transport (historical)

The Nest-plane transport module (`lib/nest_transport.py`) and Remote Nest SSH/WinRM product path were removed from free HEAD ([#620](https://github.com/dustinestes/Hatchery/issues/620), [ADR-0044](adr/0044-free-head-local-nest-only.md)).

Free Controllers use **Local Nest** only (co-located hypervisor). Remote Nest control plane for Enterprise is Nest Agent, not Nest SSH on free.

Shared OpenSSH helpers remain in `lib/openssh_client.py` for the **guest** plane. See [guest transport](guest-transport.md).
