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

_REQ_WARNING_PREFIX = "Missing requirement:"
_CLUTCH_ALERT_PREFIX = "Invalid Clutch file:"


class ControllerRequirementsValidator(BaseValidator):
    id = "controller_requirements"
    title = "Controller requirements"
    description = "Check tools needed on this Hatchery Controller (host packages)."
    scope = "controller"
    default_interval_seconds = 60
    default_enabled = True

    def run(self, ctx: ValidatorContext) -> str:
        missing = 0
        for req in req_lib.check_all():
            msg = f"{_REQ_WARNING_PREFIX} '{req.name}' is not installed — {req.required_for}"
            if not req.present:
                missing += 1
                if not ctx.has_active_alert(msg):
                    ctx.record_alert(msg)
            else:
                ctx.resolve_alerts_by_prefix(msg)
        if missing:
            return f"{missing} missing requirement(s)"
        return "All checked requirements present"


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
                    # Resolve old prefix variants then record
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


class NestCapabilityValidator(_StubValidator):
    id = "nest_capability"
    title = "Nest capability"
    description = "Verify Nest can run as hypervisor host (can run as Nest). Follow-up #208."
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
