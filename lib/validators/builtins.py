"""Built-in validators — migrate existing syncs + stubs for follow-ups."""

from __future__ import annotations

from lib import clutch as clutch_lib
from lib import config
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
            msg = f"{base} — {req.required_for}"
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
                msg = f"{prefix} — {detail}"
                if not ctx.has_active_alert(msg):
                    ctx.resolve_alerts_by_prefix(prefix)
                    ctx.record_alert(msg)
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
        nest_key_expiry_lib.sync_nest_key_expiry_alerts(identities, tiers)
        return f"Checked {len(identities)} Nest SSH identities"


class NestCapabilityValidator(BaseValidator):
    id = "nest_capability"
    title = "Nest capability"
    description = "Verify each Nest can run as a hypervisor (Local on-box; Remote over transport)."
    scope = "nest"
    default_interval_seconds = 120
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        nests = nests_lib.list_nests()
        if ctx.nest_id:
            nests = [n for n in nests if n.get("id") == ctx.nest_id]
        if not nests:
            return "No Nests to check"

        missing_total = 0
        checked_nests = 0
        for nest in nests:
            nest_id = nest.get("id") or "?"
            nest_name = nest.get("name") or nest_id
            location = nest.get("location") or "local"
            results = req_lib.check_nest(nest, winrm_password=ctx.winrm_password)
            if not results and location == "remote" and (nest.get("transport") or "ssh") == "winrm":
                continue
            checked_nests += 1
            nest_prefix = f"{_NEST_ALERT_PREFIX} '{nest_name}' ({nest_id}):"
            for req in results:
                tool_prefix = f"{nest_prefix} '{req.name}'"
                if not req.present:
                    missing_total += 1
                    msg = f"{tool_prefix} is not available — {req.required_for}"
                    if req.install_hint and location == "local":
                        msg = f"{msg} ({req.install_hint})"
                    if not ctx.has_active_alert(msg):
                        ctx.resolve_alerts_by_prefix(tool_prefix)
                        ctx.record_alert(msg)
                else:
                    ctx.resolve_alerts_by_prefix(tool_prefix)

        if missing_total:
            return f"{missing_total} missing Nest tool(s) across {checked_nests} Nest(s)"
        return f"Nest capability OK ({checked_nests} Nest(s))"


class _StubValidator(BaseValidator):
    stub = True
    default_enabled = False
    default_interval_seconds = 120

    def run(self, ctx: ValidatorContext) -> str:
        return "Not implemented yet"


class NestReachabilityValidator(_StubValidator):
    id = "nest_reachability"
    title = "Nest reachability"
    description = "Test Nest transport connectivity (can reach). Follow-up #263."
    scope = "nest"


class LibraryConnectionsValidator(_StubValidator):
    id = "library_connections"
    title = "Library connections"
    description = "Check Library sources for reachability, auth, and token expiry. Follow-up #254."
    scope = "content"


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
    ):
        if reg.get_validator(cls.id) is None:
            register(cls())
