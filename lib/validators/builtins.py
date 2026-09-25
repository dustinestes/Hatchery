"""Built-in validators — migrate existing syncs + stubs for follow-ups."""

from __future__ import annotations

from lib import clutch as clutch_lib
from lib import config
from lib import library as library_lib
from lib import nest_key_expiry as nest_key_expiry_lib
from lib import nests as nests_lib
from lib import requirements as req_lib
from lib.validators.base import BaseValidator
from lib.validators.context import ValidatorContext
from lib.validators.registry import register

_CONTROLLER_ALERT_PREFIX = req_lib.CONTROLLER_ALERT_PREFIX
_NEST_ALERT_PREFIX = req_lib.NEST_ALERT_PREFIX
_CLUTCH_ALERT_PREFIX = "Invalid Clutch file:"


class ControllerRequirementsValidator(BaseValidator):
    id = "controller_requirements"
    title = "Controller requirements"
    description = "Check tools needed on this Hatchery Controller (not Nest hypervisor packages)."
    scope = "controller"
    default_interval_seconds = 60
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        req_lib.resolve_legacy_requirement_alerts(ctx.resolve_alerts_by_prefix)
        missing = 0
        for req in req_lib.check_controller():
            base = f"{_CONTROLLER_ALERT_PREFIX} '{req.name}' is not installed"
            msg = f"{base} - {req.required_for}"
            if req.optional:
                if req.present:
                    ctx.resolve_alerts_by_prefix(base)
                continue
            if not req.present:
                missing += 1
                if req.install_hint:
                    msg = f"{msg} ({req.install_hint})"
                if not ctx.has_active_alert(msg):
                    ctx.resolve_alerts_by_prefix(base)
                    ctx.record_alert(msg)
                else:
                    ctx.note_finding("alert")
            else:
                ctx.resolve_alerts_by_prefix(base)
        if missing:
            return f"{missing} missing Controller requirement(s)"
        return "Controller requirements OK"


class ClutchFilesValidator(BaseValidator):
    id = "clutch_files"
    title = "Clutch files"
    description = "Validate Clutch YAML files in the data directory."
    scope = "content"
    default_interval_seconds = 60
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        clutches_dir = ctx.data_dir() / "clutches"
        if not clutches_dir.exists():
            return "No clutches directory"
        invalid = 0
        checked = 0
        for path in sorted(clutches_dir.glob("*.yaml")):
            checked += 1
            prefix = f"{_CLUTCH_ALERT_PREFIX} '{path.name}'"
            try:
                clutch_lib.load(path)
                ctx.resolve_alerts_by_prefix(prefix)
            except Exception as exc:
                invalid += 1
                detail = _clutch_error_detail(path.name, str(exc))
                msg = f"{prefix} - {detail}"
                if not ctx.has_active_alert(msg):
                    ctx.resolve_alerts_by_prefix(prefix)
                    ctx.record_alert(msg)
                else:
                    ctx.note_finding("alert")
        if invalid:
            return f"{invalid} of {checked} Clutch file(s) invalid"
        return f"{checked} Clutch file(s) valid"


def _clutch_error_detail(filename: str, error: str) -> str:
    file_header = f"Invalid Clutch file '{filename}':\n"
    if error.startswith(file_header):
        lines = error[len(file_header) :].splitlines()
        parts = [
            line.strip().removeprefix("clutch: ").removeprefix("Value error, ")
            for line in lines
            if line.strip()
        ]
        return "; ".join(parts)
    return error


class NestKeyExpiryValidator(BaseValidator):
    id = "nest_key_expiry"
    title = "Nest SSH identity expiry"
    description = "Alert when Nest SSH identities are nearing expiry."
    scope = "nest"
    default_interval_seconds = 60
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        identities = nests_lib.identities_for_expiry()
        tiers = nest_key_expiry_lib.parse_tiers(config.nest_key_alert_tiers())
        recorded = nest_key_expiry_lib.sync_nest_key_expiry_alerts(identities, tiers)
        if recorded:
            # Newly filed expiry Alerts — warning unless already expired (alert tier).
            for msg in recorded:
                tier = "alert" if "expired" in msg.lower() else "warning"
                ctx.note_finding(tier)
        return f"Checked {len(identities)} Nest SSH identities"


class NestCapabilityValidator(BaseValidator):
    id = "nest_capability"
    title = "Nest capability"
    description = "Verify each Nest can run as a hypervisor (Local on-box; Remote over transport)."
    scope = "nest"
    default_interval_seconds = 120
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        from lib import nest_reachability as nr

        nests = nests_lib.list_nests()
        if ctx.nest_id:
            nests = [n for n in nests if n.get("id") == ctx.nest_id]
        if not nests:
            return "No Nests to check"

        missing_total = 0
        checked_nests = 0
        skipped_unreachable = 0
        for nest in nests:
            nest_id = nest.get("id") or "?"
            nest_name = nest.get("name") or nest_id
            location = nest.get("location") or "local"
            nest_prefix = f"{_NEST_ALERT_PREFIX} '{nest_name}' ({nest_id}):"

            # Reachability gates capability on Remotes (#286): failed transport
            # must not become "missing Nest tools" Alerts.
            if not nr.is_reachable_for_capability(nest):
                skipped_unreachable += 1
                ctx.resolve_alerts_by_prefix(nest_prefix)
                continue

            results = req_lib.check_nest(nest, winrm_password=ctx.winrm_password)
            if not results and location == "remote" and (nest.get("transport") or "ssh") == "winrm":
                continue
            checked_nests += 1
            for req in results:
                tool_prefix = f"{nest_prefix} '{req.name}'"
                if not req.present:
                    missing_total += 1
                    msg = f"{tool_prefix} is not available - {req.required_for}"
                    if req.install_hint and location == "local":
                        msg = f"{msg} ({req.install_hint})"
                    if not ctx.has_active_alert(msg):
                        ctx.resolve_alerts_by_prefix(tool_prefix)
                        ctx.record_alert(msg)
                    else:
                        ctx.note_finding("alert")
                else:
                    ctx.resolve_alerts_by_prefix(tool_prefix)

        parts: list[str] = []
        if missing_total:
            parts.append(f"{missing_total} missing Nest tool(s) across {checked_nests} Nest(s)")
        elif checked_nests:
            parts.append(f"Nest capability OK ({checked_nests} Nest(s))")
        if skipped_unreachable:
            parts.append(f"skipped {skipped_unreachable} unreachable Nest(s)")
        if not parts:
            return "No Nests to check"
        return "; ".join(parts)


class NestReachabilityValidator(BaseValidator):
    id = "nest_reachability"
    title = "Nest reachability"
    description = "Probe Nest transport connectivity (Local co-located; Remote via Nest transport)."
    scope = "nest"
    default_interval_seconds = 60
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        from lib import nest_reachability as nr

        snap = nr.run_probes(
            nest_id=ctx.nest_id,
            winrm_password=ctx.winrm_password,
            sync_alerts=True,
        )
        last = snap.get("last_run") or {}
        checked = int(last.get("checked") or 0)
        down = int(last.get("down") or 0)
        if checked == 0:
            return "No Nests probed"
        if down:
            ctx.note_findings(down, "alert")
            return f"{down} of {checked} Nest(s) unreachable"
        return f"All {checked} Nest(s) reachable"


class LibraryConnectionsValidator(BaseValidator):
    id = "library_connections"
    title = "Library connections"
    description = "Check Library sources for reachability, auth, and token expiry."
    scope = "content"
    default_interval_seconds = 120
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        from lib import library_health as lh

        if not config.library_enabled():
            lh.resolve_all_library_alerts()
            return "Library disabled"

        raw = config.library_connections()
        try:
            connections = library_lib.parse_connections(raw, enforce_expiry_future=False)
        except ValueError as exc:
            ctx.record_alert(
                f"{lh.CONNECTION_ALERT_PREFIX} registry invalid - {exc}",
                tier="alert",
            )
            return f"Library connection registry invalid: {exc}"

        lh.prune_alerts_for_removed_connections({c["id"] for c in connections})

        # Disabled connections stay in Settings but are skipped for health probes
        # and token-expiry Alerts; resolve any leftover Alerts for those rows (#293).
        for conn in connections:
            if not library_lib.connection_is_enabled(conn):
                lh.resolve_alerts_for_connection_id(str(conn.get("id") or ""))

        active = library_lib.enabled_connections(connections)

        def _note(tier: str) -> None:
            ctx.note_finding(tier)

        probe = lh.sync_connection_alerts(active, note_finding=_note)
        recorded_expiry = lh.sync_token_expiry_alerts(active, note_finding=_note)

        parts: list[str] = []
        if probe["checked"] == 0 and not active:
            return "No Library connections"
        if probe["down"]:
            parts.append(f"{probe['down']} of {probe['checked']} connection(s) unhealthy")
        elif probe["checked"]:
            parts.append(f"All {probe['checked']} connection(s) reachable")
        if recorded_expiry:
            parts.append(f"{len(recorded_expiry)} token expiry finding(s)")
        return "; ".join(parts) if parts else "Library connections OK"


class LibraryCacheDriftValidator(BaseValidator):
    id = "library_cache_drift"
    title = "Library cache drift"
    description = (
        "Bidirectional drift: Cached file SHA and Library tip vs last sync "
        "(no body download for compare). Optional auto-sync overwrites then re-evaluates. "
        "Forge/GitHub: about one Trees call per connection per pass; watch API rate limits."
    )
    scope = "content"
    default_interval_seconds = 300
    default_enabled = True
    supports_auto_sync = True
    default_auto_sync = False

    def run(self, ctx: ValidatorContext) -> str:
        from lib import library_drift as drift
        from lib.validators.settings import get_validator_config

        if not config.library_enabled():
            from lib import alerts as alerts_lib

            for label in ("Scripts", "Clutches", "Media"):
                alerts_lib.resolve_alerts_by_prefix(f"{drift.DRIFT_ALERT_PREFIX} {label}")
            return "Library disabled"

        cfg = get_validator_config(self.id)
        auto_sync = bool(cfg.get("auto_sync"))
        summary = drift.run_drift_pass(auto_sync=auto_sync)
        out = int(summary.get("out_of_sync") or 0)
        if out:
            ctx.note_findings(out, "warning")
        checked = int(summary.get("checked") or 0)
        if checked == 0:
            return "No Library-attributed cache files"
        parts = [f"{checked} attributed file(s)"]
        if summary.get("synced"):
            parts.append(f"auto-synced {summary['synced']}")
        if out:
            parts.append(f"{out} out of sync")
        orphans = int(summary.get("orphan") or 0)
        if orphans:
            parts.append(f"{orphans} orphan(s)")
        rate = int(summary.get("rate_limited") or 0)
        if rate:
            parts.append(f"{rate} rate-limited")
        by_status = summary.get("by_source_status") or {}
        missing = int(by_status.get("missing") or 0)
        if missing:
            parts.append(f"{missing} source missing")
        return "; ".join(parts)


def register_builtins() -> None:
    """Idempotent registration of built-in validators."""
    from lib.validators import registry as reg

    for cls in (
        ControllerRequirementsValidator,
        ClutchFilesValidator,
        NestKeyExpiryValidator,
        NestReachabilityValidator,
        NestCapabilityValidator,
        LibraryConnectionsValidator,
        LibraryCacheDriftValidator,
    ):
        if reg.get_validator(cls.id) is None:
            register(cls())
