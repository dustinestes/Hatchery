"""Hatch create + hatch→fledge progression (shared by UI and operator CLI).

Does not import Flask. Callers must bootstrap Controller config/DB first.
"""

from __future__ import annotations

import atexit
import threading
import time
from typing import Callable

from lib import alerts as alerts_lib
from lib import config
from lib import hatch as hatch_lib
from lib import nests as nests_lib
from lib import provision as provision_lib
from lib.providers.base import BaseProvider
from lib.providers.factory import (
    NoNestSelectedError,
    UnknownNestError,
    UnsupportedProviderError,
    get_provider,
)

# Tracks (session_id, vm_name) pairs currently being provisioned so the sync
# loop does not spawn duplicate threads.
_provisioning: set[tuple[str, str]] = set()
_provisioning_lock = threading.Lock()

_BOOT_KEY_POLL_ATTEMPTS = 60  # poll up to 60s (1s intervals) for VM to reach running state
_BOOT_KEY_SETTLE_SECONDS = 3  # UEFI POST often trails libvirt "running"
_BOOT_KEY_BURST_ATTEMPTS = 60  # send key 60 times (0.5s intervals) = 30s burst
_BOOT_KEY_BURST_INTERVAL = 0.5

_TERMINAL_VM_STATUSES = frozenset({"fledged", "failed", "culled"})

_bg_stop_event: threading.Event | None = None


def send_boot_key(provider: BaseProvider, name: str) -> None:
    """Wait for VM running, then send KEY_ENTER repeatedly to clear the CD boot prompt.

    Libvirt reports ``running`` as soon as QEMU starts - often before firmware shows
    "Press any key to boot from CD or DVD". A short burst at that moment misses the
    prompt. After a brief settle we keep sending for tens of seconds. Transient
    ``send_key`` failures are ignored so an early miss does not abort the burst.
    """
    for _ in range(_BOOT_KEY_POLL_ATTEMPTS):
        try:
            if provider.get_status(name) == "running":
                break
        except Exception:
            pass
        time.sleep(1)
    time.sleep(_BOOT_KEY_SETTLE_SECONDS)
    for _ in range(_BOOT_KEY_BURST_ATTEMPTS):
        try:
            provider.send_key(name, "KEY_ENTER")
        except Exception:
            pass
        time.sleep(_BOOT_KEY_BURST_INTERVAL)


def run_hatch_session(
    session_id: str,
    vms: list,
    passwords: dict,
    clutch_file: str,
    storage_path: str | None = None,
) -> None:
    """Create each VM sequentially and track state in DB (may run on a worker thread)."""
    session = hatch_lib.get_session(session_id)
    nest_id = (session or {}).get("nest") or nests_lib.default_nest_id()
    try:
        if not nest_id:
            raise NoNestSelectedError()
        provider = get_provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        for vm in vms:
            hatch_lib.add_event(
                session_id, vm.name, "hatchery", "ERROR", f"VM creation failed: {exc}"
            )
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))
        return

    attach_errors = answer_file_attach_errors(provider, vms)
    if attach_errors:
        msg = "; ".join(attach_errors)
        for vm in vms:
            hatch_lib.add_event(
                session_id, vm.name, "hatchery", "ERROR", f"VM creation failed: {msg}"
            )
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=msg)
        return

    for vm in vms:
        try:
            hatch_lib.set_vm_status(session_id, vm.name, "hatching")
            cmd_desc = provider.create_command_description(vm, storage_path=storage_path)
            hatch_lib.add_event(session_id, vm.name, "hatchery", "INFO", f"Creating VM: {cmd_desc}")
            # Start boot key sender before create_vm so it can begin polling immediately.
            # virt-install takes a few seconds; starting concurrently maximises the chance
            # of hitting the BIOS "press any key" window which opens during that time.
            threading.Thread(
                target=send_boot_key,
                args=(provider, vm.name),
                daemon=True,
            ).start()
            provider.create_vm(vm, admin_password=passwords[vm.name], storage_path=storage_path)
            hatch_lib.add_event(session_id, vm.name, "hatchery", "INFO", "VM created successfully")
            try:
                provider.tag_vm_session(vm.name, session_id, clutch_file)
            except Exception:
                pass  # best-effort: metadata tagging does not block hatching
            try:
                uuid = provider.get_vm_uuid(vm.name)
                if uuid:
                    hatch_lib.set_vm_uuid(session_id, vm.name, uuid)
            except Exception:
                pass  # best-effort: UUID storage does not block hatching
        except PermissionError as exc:
            hatch_lib.add_event(
                session_id,
                vm.name,
                "hatchery",
                "ERROR",
                f"VM creation failed: {str(exc).splitlines()[0]}",
            )
            alerts_lib.record_alert(str(exc).splitlines()[0])
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))
        except Exception as exc:
            hatch_lib.add_event(
                session_id, vm.name, "hatchery", "ERROR", f"VM creation failed: {exc}"
            )
            hatch_lib.set_vm_status(session_id, vm.name, "failed", error=str(exc))


def _mark_remaining_skipped(
    session_id: str, vm_name: str, scripts: list[dict], failed_order: int
) -> None:
    for s in scripts:
        if s["run_order"] > failed_order and s["status"] == "pending":
            hatch_lib.set_script_status(session_id, vm_name, s["run_order"], "skipped")


def _reboot_guest_after_automation(
    session_id: str,
    vm_name: str,
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    script_name: str,
    identity_file: str | None = None,
    ssh_port: int = 22,
) -> None:
    """Restart the guest and wait until LastBootUpTime changes (#499)."""

    def on_event(level: str, message: str) -> None:
        hatch_lib.add_event(
            session_id,
            vm_name,
            "hatchery",
            level if level in ("INFO", "WARN", "ERROR") else "INFO",
            message,
            script_name=script_name,
        )

    with provision_lib.guest_transport_defaults(
        identity_file=identity_file,
        ssh_port=ssh_port,
    ):
        provision_lib.reboot_guest_and_wait(ip, admin_username, admin_password, on_event=on_event)


def _clutch_vm_for_session(session_id: str, vm_name: str):
    """Load the Clutch VMConfig for a hatch session VM, or None.

    Prefers the session ``clutch_snapshot`` frozen at hatch start (#514). Falls
    back to the live Clutch file only for legacy sessions without a snapshot.
    """
    from pathlib import Path

    from lib import clutch as clutch_lib

    snap_vm = hatch_lib.load_session_vm_config(session_id, vm_name)
    if snap_vm is not None:
        return snap_vm

    session = hatch_lib.get_session(session_id) or {}
    clutch_file = (session.get("clutch_file") or "").strip()
    if not clutch_file:
        return None
    path = config.data_dir() / "clutches" / Path(clutch_file).name
    try:
        clutch = clutch_lib.load(path)
    except Exception:
        return None
    for vm in clutch.vms:
        if vm.name == vm_name:
            return vm
    return None


def _guest_ssh_client_defaults(clutch_vm) -> tuple[str | None, int]:
    """Resolve Controller SSH identity path + port from Clutch remoting.ssh."""
    from lib import guest_authorize as ga
    from lib import remoting_identities as ri

    if clutch_vm is None:
        return None, 22
    ids = ga.authorize_ids_for_vm(clutch_vm)
    port = ga.ssh_port_for_vm(clutch_vm)
    if not ids:
        return None, port
    try:
        return str(ri.identity_private_path(ids[0])), port
    except ri.RemotingIdentityError:
        return None, port


def _apply_guest_ssh_authorize(
    session_id: str,
    vm_name: str,
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    password_transport,
) -> tuple[str | None, int]:
    """Inject authorize pubkeys, verify key SSH, disable password auth (#524).

    Returns ``(identity_file, ssh_port)`` for subsequent Guest transport. On hard
    failure, marks the VM failed and returns ``(None, port)``.
    """
    from lib import guest_authorize as ga
    from lib import remoting_identities as ri

    clutch_vm = _clutch_vm_for_session(session_id, vm_name)
    if clutch_vm is None:
        authorize_ids = [ri.HATCHERY_IDENTITY_ID]
        ssh_port = 22
    else:
        authorize_ids = ga.authorize_ids_for_vm(clutch_vm)
        ssh_port = ga.ssh_port_for_vm(clutch_vm)

    hatch_lib.add_event(
        session_id,
        vm_name,
        "hatchery",
        "INFO",
        f"Authorizing guest SSH keys: {', '.join(authorize_ids)} (port {ssh_port})",
    )
    try:
        result = ga.apply_guest_ssh_authorize(
            ip,
            admin_username,
            admin_password,
            authorize_ids=authorize_ids,
            ssh_port=ssh_port,
            password_transport=password_transport,
        )
    except ga.GuestAuthorizeError as exc:
        hatch_lib.add_event(
            session_id,
            vm_name,
            "hatchery",
            "ERROR",
            f"Guest SSH authorize failed: {exc}",
        )
        hatch_lib.set_vm_status(session_id, vm_name, "failed", error=str(exc))
        return None, ssh_port

    if result.skipped:
        hatch_lib.add_event(
            session_id,
            vm_name,
            "hatchery",
            "WARN",
            result.skip_reason or "Guest SSH authorize skipped",
        )
        return result.identity_file, result.ssh_port

    hatch_lib.add_event(
        session_id,
        vm_name,
        "hatchery",
        "INFO",
        f"Guest SSH authorize complete (client identity {result.client_identity_id}; "
        f"password auth {'disabled' if result.password_auth_disabled else 'still enabled'})",
    )
    return result.identity_file, result.ssh_port


def _provision_vm_thread(
    session_id: str,
    vm_name: str,
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    identity_file: str | None = None,
    ssh_port: int = 22,
) -> None:
    """Run pending automations (script|software) sequentially, updating DB per step."""
    from lib import guest_env as guest_env_lib
    from lib import software_provision as software_provision_lib
    from lib.clutch import GuestOS

    try:
        with provision_lib.guest_transport_defaults(
            identity_file=identity_file,
            ssh_port=ssh_port,
        ):
            scripts = hatch_lib.get_vm_scripts(session_id, vm_name)
            data_dir = config.data_dir()
            vm_record = hatch_lib.get_vm_record(session_id, vm_name) or {}
            guest_os = vm_record.get("guest_os") or GuestOS.WINDOWS.value
            clutch_vm = _clutch_vm_for_session(session_id, vm_name)
            user_entries = list(clutch_vm.environment) if clutch_vm else []
            user_env = clutch_vm.environment_as_process_map() if clutch_vm else {}
            script_env = guest_env_lib.merge_guest_environment(
                guest_env_lib.reserved_environment(guest_os),
                user_env,
            )

            # Persist reserved base + user persist entries once before automations (#501).
            # Hatch jobs also get process inject per step; persist is for the guest after that.
            os_key = guest_os.value if hasattr(guest_os, "value") else str(guest_os)
            if os_key in ("windows", "win10", "win11", "server2022", "server2025"):
                plan = guest_env_lib.persist_plan_summary(guest_os, user_entries)
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    "Persisting guest environment before automations "
                    "(Machine/User store; jobs also get process inject)",
                )
                for line in plan:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "INFO",
                        f"Persist: {line}",
                    )
                persist_code, persist_out = guest_env_lib.persist_guest_environment(
                    ip,
                    admin_username,
                    admin_password,
                    guest_os=guest_os,
                    entries=user_entries,
                )
                if persist_code != 0:
                    detail = (persist_out or "").strip()
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "ERROR",
                        f"Failed to persist guest environment (exit {persist_code})"
                        + (f": {detail}" if detail else ""),
                    )
                    hatch_lib.set_vm_status(
                        session_id,
                        vm_name,
                        "failed",
                        error=f"persist env failed: {persist_out or persist_code}",
                    )
                    return
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Guest environment persisted ({len(plan)} variable(s)); starting automations",
                )

            for script in scripts:
                if script["status"] == "succeeded":
                    continue

                sname = script["script_name"]
                entry_type = script.get("entry_type") or "script"
                kind_label = "software" if entry_type == "software" else "script"
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Starting {kind_label}: {sname}",
                    script_name=sname,
                )
                hatch_lib.set_script_status(session_id, vm_name, script["run_order"], "running")

                try:
                    if entry_type == "software":

                        def _on_sw_event(level: str, message: str, _name: str = sname) -> None:
                            hatch_lib.add_event(
                                session_id,
                                vm_name,
                                "software",
                                level if level in ("INFO", "WARN", "ERROR") else "INFO",
                                message,
                                script_name=_name,
                            )

                        exit_code, output, _install_reboot = (
                            software_provision_lib.run_software_entry(
                                ip,
                                admin_username,
                                admin_password,
                                package_id=sname,
                                guest_os=guest_os,
                                clean_payload_on_success=bool(
                                    script.get("clean_payload_on_success", True)
                                ),
                                on_event=_on_sw_event,
                                user_environment=user_env,
                            )
                        )
                    else:
                        script_path = data_dir / "automation" / "scripts" / sname
                        exit_code, output = provision_lib.run_script(
                            ip,
                            admin_username,
                            admin_password,
                            script_path,
                            parameters=script.get("parameters") or {},
                            environment=script_env,
                        )
                except Exception as exc:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "ERROR",
                        f"{kind_label.capitalize()} failed: {exc}",
                        script_name=sname,
                    )
                    hatch_lib.set_script_status(
                        session_id,
                        vm_name,
                        script["run_order"],
                        "failed",
                        exit_code=-1,
                        output=str(exc),
                    )
                    _mark_remaining_skipped(session_id, vm_name, scripts, script["run_order"])
                    hatch_lib.set_vm_status(session_id, vm_name, "failed")
                    return

                if entry_type != "software":
                    for event in hatch_lib.parse_hatch_event_lines(output):
                        hatch_lib.add_event(
                            session_id,
                            vm_name,
                            "script",
                            event["level"],
                            event["message"],
                            script_name=sname,
                            component=event["component"],
                            received_at=event["received_at"],
                        )

                if entry_type == "script" and exit_code != 0:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "ERROR",
                        f"Script failed: {sname} - Exit Code: {exit_code}",
                        script_name=sname,
                    )
                    hatch_lib.set_script_status(
                        session_id,
                        vm_name,
                        script["run_order"],
                        "failed",
                        exit_code=exit_code,
                        output=output,
                    )
                    _mark_remaining_skipped(session_id, vm_name, scripts, script["run_order"])
                    hatch_lib.set_vm_status(session_id, vm_name, "failed")
                    return

                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"{kind_label.capitalize()} complete: {sname} - Exit Code: {exit_code}",
                    script_name=sname,
                )
                hatch_lib.set_script_status(
                    session_id,
                    vm_name,
                    script["run_order"],
                    "succeeded",
                    exit_code=exit_code,
                    output=output,
                )

                if script["reboot_after"]:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "INFO",
                        f"Rebooting VM after {kind_label}: {sname}",
                        script_name=sname,
                    )
                    _reboot_guest_after_automation(
                        session_id,
                        vm_name,
                        ip,
                        admin_username,
                        admin_password,
                        script_name=sname,
                        identity_file=identity_file,
                        ssh_port=ssh_port,
                    )

            hatch_lib.add_event(
                session_id,
                vm_name,
                "hatchery",
                "INFO",
                "All automations succeeded - VM is fledged",
            )
            hatch_lib.set_vm_status(session_id, vm_name, "fledged")

    finally:
        with _provisioning_lock:
            _provisioning.discard((session_id, vm_name))


def spawn_provision_thread(
    session_id: str,
    vm_name: str,
    ip: str,
    admin_username: str,
    admin_password: str,
    *,
    identity_file: str | None = None,
    ssh_port: int = 22,
) -> None:
    with _provisioning_lock:
        if (session_id, vm_name) in _provisioning:
            return
        _provisioning.add((session_id, vm_name))
    t = threading.Thread(
        target=_provision_vm_thread,
        kwargs={
            "session_id": session_id,
            "vm_name": vm_name,
            "ip": ip,
            "admin_username": admin_username,
            "admin_password": admin_password,
            "identity_file": identity_file,
            "ssh_port": ssh_port,
        },
        daemon=True,
    )
    t.start()


def sync_hatch_status(
    provider_for: Callable[[str], BaseProvider | None] | None = None,
) -> None:
    """Monitor active VMs: advance through hatching→provisioning→fledged, cull if gone."""

    def _default_provider(nest_id: str) -> BaseProvider | None:
        try:
            return get_provider(nest_id)
        except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError):
            return None

    resolve = provider_for or _default_provider

    sessions: list[dict] = []
    for nest in nests_lib.list_nests():
        sessions.extend(hatch_lib.list_sessions(nest["id"]))
    monitored = [
        (
            s["id"],
            s.get("nest") or nests_lib.default_nest_id() or "",
            v["vm_name"],
            v.get("libvirt_uuid"),
            v["status"],
        )
        for s in sessions
        for v in s["vms"]
        if v["status"] in ("hatching", "provisioning", "fledged")
    ]
    if not monitored:
        return

    providers: dict[str, BaseProvider | None] = {}

    def _cached(nest_id: str) -> BaseProvider | None:
        if nest_id not in providers:
            providers[nest_id] = resolve(nest_id)
        return providers[nest_id]

    for session_id, nest_id, vm_name, libvirt_uuid, vm_status in monitored:
        if not libvirt_uuid:
            continue
        provider = _cached(nest_id)
        if provider is None:
            continue

        current_name = provider.get_vm_name_by_uuid(libvirt_uuid)
        if current_name is None:
            hatch_lib.set_vm_status(session_id, vm_name, "culled")
            hatch_lib.archive_if_terminal(session_id)
            continue

        if current_name != vm_name:
            hatch_lib.update_vm_name(session_id, vm_name, current_name)
            vm_name = current_name

        if vm_status == "hatching":
            # Windows installation sends ACPI power-off at several points (e.g. end of
            # OOBE). Restart the VM so installation continues to the desktop and WinRM.
            # Scoped to hatching only - fledged VMs are left to the user. Post-install
            # script reboots arrive as on_reboot events (not power-off), so they never
            # leave the VM in "shut off" and this branch does not interfere with them.
            try:
                is_shut_off = provider.get_status(current_name) == "shut off"
            except Exception:
                is_shut_off = False
            if is_shut_off:
                try:
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "hatchery",
                        "INFO",
                        f"Starting VM: virsh start {current_name}",
                    )
                    provider.start_vm(current_name)
                except Exception:
                    pass
                continue

            ip = provider.get_vm_ip(current_name)
            if not ip:
                continue
            if not provision_lib.guest_remoting_ready(ip):
                continue

            db_record = hatch_lib.get_vm_record(session_id, vm_name)
            admin_username = (db_record or {}).get("admin_username") or ""
            admin_password = (db_record or {}).get("admin_password") or ""

            # Gate on the setup-complete flag so automation never starts while
            # FirstLogonCommands (SSH install, WinRM config, etc.) are still running.
            # Prefers SSH ready-probe; WinRM is Windows fallback (#497 / ADR-0029).
            if not provision_lib.check_setup_complete(ip, admin_username, admin_password):
                continue

            def _guest_fallback(message: str) -> None:
                hatch_lib.add_event(session_id, vm_name, "hatchery", "WARN", message)

            remoting_kind = "winrm"
            transport = None
            try:
                transport = provision_lib._guest_transport(
                    ip,
                    admin_username,
                    admin_password,
                    on_fallback=_guest_fallback,
                )
                remoting_kind = transport.kind
            except Exception:
                pass

            # Import first-boot setup events before deleting guest artifacts.
            try:
                setup_log = provision_lib.read_setup_log(ip, admin_username, admin_password)
                for event in hatch_lib.parse_hatch_event_lines(setup_log):
                    hatch_lib.add_event(
                        session_id,
                        vm_name,
                        "script",
                        event["level"],
                        event["message"],
                        script_name="hatchery-setup.ps1",
                        component=event["component"],
                        received_at=event["received_at"],
                    )
                provision_lib.delete_setup_log(ip, admin_username, admin_password)
            except Exception:
                pass

            # Flag confirmed - delete it immediately so the guest stays clean.
            try:
                provision_lib.delete_setup_flag(ip, admin_username, admin_password)
            except Exception:
                pass

            # Guest SSH authorize: inject → verify key → disable password (#524).
            identity_file, ssh_port = _apply_guest_ssh_authorize(
                session_id,
                vm_name,
                ip,
                admin_username,
                admin_password,
                password_transport=transport,
            )
            # Authorize hard-failure marks the VM failed; do not start provisioning.
            post_auth = hatch_lib.get_vm_record(session_id, vm_name) or {}
            if post_auth.get("status") == "failed":
                continue

            scripts = hatch_lib.get_vm_scripts(session_id, vm_name)
            if scripts:
                n = len(scripts)
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Windows setup complete - guest remoting via {remoting_kind}; "
                    f"starting provisioning ({n} automation{'s' if n != 1 else ''})",
                )
                hatch_lib.set_vm_status(session_id, vm_name, "provisioning")
                spawn_provision_thread(
                    session_id,
                    vm_name,
                    ip,
                    admin_username,
                    admin_password,
                    identity_file=identity_file,
                    ssh_port=ssh_port,
                )
            else:
                hatch_lib.add_event(
                    session_id,
                    vm_name,
                    "hatchery",
                    "INFO",
                    f"Windows setup complete - guest remoting via {remoting_kind}; "
                    "no automations configured",
                )
                hatch_lib.set_vm_status(session_id, vm_name, "fledged")

        elif vm_status == "provisioning":
            # Re-spawn provision thread if app restarted mid-provisioning.
            with _provisioning_lock:
                already_running = (session_id, vm_name) in _provisioning
            if not already_running:
                ip = provider.get_vm_ip(current_name)
                if ip and provision_lib.guest_remoting_ready(ip):
                    db_record = hatch_lib.get_vm_record(session_id, vm_name)
                    hatch_lib.reset_scripts_for_retry(session_id, vm_name)
                    clutch_vm = _clutch_vm_for_session(session_id, vm_name)
                    identity_file, ssh_port = _guest_ssh_client_defaults(clutch_vm)
                    spawn_provision_thread(
                        session_id,
                        vm_name,
                        ip,
                        (db_record or {}).get("admin_username") or "",
                        (db_record or {}).get("admin_password") or "",
                        identity_file=identity_file,
                        ssh_port=ssh_port,
                    )


def _background_loop(stop_event: threading.Event) -> None:
    """Hatch lifecycle poller only - validators run on their own scheduler (#268)."""
    while not stop_event.wait(config.bg_interval()):
        sync_hatch_status()


def start_background_poller() -> threading.Event:
    """Start the hatch status poller; store the stop event on the module for tests."""
    global _bg_stop_event
    stop = threading.Event()
    _bg_stop_event = stop
    t = threading.Thread(target=_background_loop, args=(stop,), daemon=True)
    t.start()
    atexit.register(stop.set)
    return stop


def session_vms_terminal(session_id: str) -> bool:
    """Return True when every VM in the session is fledged, failed, or culled."""
    session = hatch_lib.get_session(session_id)
    if not session:
        return True
    vms = session.get("vms") or []
    if not vms:
        return True
    return all(v.get("status") in _TERMINAL_VM_STATUSES for v in vms)


def poll_session_until_terminal(
    session_id: str,
    *,
    interval: float | None = None,
    on_tick: Callable[[dict], None] | None = None,
) -> dict:
    """Run ``sync_hatch_status`` until the session reaches a terminal state.

    Returns the final session dict (or empty dict if missing). Does not enforce
    a wall-clock timeout - operators interrupt with Ctrl-C. ``interval`` defaults
    to ``config.bg_interval()``.
    """
    wait = config.bg_interval() if interval is None else interval
    while True:
        sync_hatch_status()
        session = hatch_lib.get_session(session_id) or {}
        if on_tick:
            on_tick(session)
        if session_vms_terminal(session_id):
            return session
        time.sleep(wait)


def create_and_start_hatch(
    *,
    clutch_file: str,
    clutch_obj,
    nest_id: str,
    passwords: dict,
    background: bool = True,
) -> str:
    """Insert session rows and start VM create. Returns ``session_id``.

    Caller must validate Nest, passwords, and Nest cache preflight first.
    When ``background`` is True, create runs on a daemon thread (UI). When
    False, create runs inline (CLI) before the caller polls for fledged.
    """
    session_id = hatch_lib.create_session(
        clutch_file,
        clutch_obj.name,
        nest=nest_id,
        clutch_snapshot=hatch_lib.clutch_snapshot_json(clutch_obj),
    )
    for vm in clutch_obj.vms:
        hatch_lib.add_vm(
            session_id,
            vm.name,
            admin_username=vm.admin_username or None,
            admin_password=passwords.get(vm.name),
            guest_os=vm.os.value if hasattr(vm.os, "value") else str(vm.os),
        )
        hatch_lib.add_vm_scripts(session_id, vm.name, vm.automations)
        hatch_lib.add_event(
            session_id,
            vm.name,
            "hatchery",
            "INFO",
            f"Hatching clutch: {clutch_obj.name}",
        )

    args = (session_id, clutch_obj.vms, passwords, clutch_file, clutch_obj.storage_path)
    if background:
        threading.Thread(target=run_hatch_session, args=args, daemon=True).start()
    else:
        run_hatch_session(*args)
    return session_id


def missing_passwords(vms, passwords: dict) -> list[str]:
    """Return names of VMs that have admin_username set but no password supplied."""
    return [vm.name for vm in vms if vm.admin_username and not passwords.get(vm.name)]


def answer_file_errors(vms, passwords: dict | None = None) -> list[str]:
    """Return hatch blockers for required Answer Files (empty if OK)."""
    from lib import answerfile as answerfile_lib
    from lib import config as config_lib

    automation_dir = config_lib.data_dir() / "automation" / "answerfiles"
    return answerfile_lib.validate_clutch_answer_files(
        list(vms),
        automation_dir=automation_dir,
        passwords=passwords or {},
    )


def answer_file_attach_errors(provider: BaseProvider, vms) -> list[str]:
    """Return hatch blockers when VMs need Answer File attach the Nest cannot do."""
    from lib import answerfile as answerfile_lib

    if not any(answerfile_lib.requires_answer_file(vm.os) for vm in vms):
        return []
    if getattr(provider, "supports_answer_file_attach", False):
        return []
    return [
        "This Nest does not support Answer File attach. "
        "Windows Autounattend attach works on libvirt local today; "
        "Hyper-V and UTM are Planned (see docs/providers.md)."
    ]


class RetryError(Exception):
    """Raised when a provisioning retry cannot start."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code  # not_found | not_failed | provider


def retry_failed_vm(session_id: str, vm_name: str) -> dict:
    """Reset failed scripts and queue provision if the guest WinRM port is up.

    Returns ``{"queued": bool, "message": str | None}``.
    Raises ``RetryError`` when the VM/session cannot be retried.
    """
    db_record = hatch_lib.get_vm_record(session_id, vm_name)
    if db_record is None:
        raise RetryError("VM not found", code="not_found")
    if db_record["status"] != "failed":
        raise RetryError("VM is not in a failed state", code="not_failed")

    hatch_lib.reset_scripts_for_retry(session_id, vm_name)
    hatch_lib.set_vm_status(session_id, vm_name, "provisioning")
    hatch_lib.add_event(session_id, vm_name, "hatchery", "INFO", "Retry initiated")

    session = hatch_lib.get_session(session_id)
    nest_id = (session or {}).get("nest") or nests_lib.default_nest_id()
    try:
        if not nest_id:
            raise NoNestSelectedError()
        provider = get_provider(nest_id)
    except (NoNestSelectedError, UnknownNestError, UnsupportedProviderError) as exc:
        raise RetryError(str(exc), code="provider") from exc

    try:
        ip = provider.get_vm_ip(vm_name)
    except Exception:
        ip = None

    if ip and provision_lib.guest_remoting_ready(ip):
        clutch_vm = _clutch_vm_for_session(session_id, vm_name)
        identity_file, ssh_port = _guest_ssh_client_defaults(clutch_vm)
        spawn_provision_thread(
            session_id,
            vm_name,
            ip,
            db_record.get("admin_username") or "",
            db_record.get("admin_password") or "",
            identity_file=identity_file,
            ssh_port=ssh_port,
        )
        return {"queued": True, "message": None}

    return {
        "queued": False,
        "message": "VM unreachable - will retry on next sync",
    }
