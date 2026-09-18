"""Validator registry."""

from __future__ import annotations

from lib.validators.base import BaseValidator

_REGISTRY: dict[str, BaseValidator] = {}


def register(validator: BaseValidator) -> BaseValidator:
    vid = validator.id
    if not vid or not vid.replace("_", "").isalnum():
        raise ValueError(f"invalid validator id: {vid!r}")
    if vid in _REGISTRY:
        raise ValueError(f"validator already registered: {vid}")
    _REGISTRY[vid] = validator
    return validator


def get_validator(validator_id: str) -> BaseValidator | None:
    return _REGISTRY.get(validator_id)


def all_validators() -> list[BaseValidator]:
    return sorted(_REGISTRY.values(), key=lambda v: v.title.lower())


def clear_registry() -> None:
    """Test helper — empty the registry."""
    _REGISTRY.clear()
