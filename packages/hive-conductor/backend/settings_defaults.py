"""Hive UI settings defaults — PM POC vs engineering."""

from __future__ import annotations

import os

from config import get_settings
from models.schemas import SettingsModel

_LEGACY_MODELS = frozenset({"gpt-4", "gpt-4.1", "gpt-3.5-turbo"})


def is_pm_poc_mode() -> bool:
    return os.getenv("MAISTRO_POC_MODE", os.getenv("HIVE_POC_MODE", "")).strip().lower() == "pm"


def default_settings(*, pm_poc: bool | None = None) -> SettingsModel:
    """Sensible 2026 defaults aligned with hive config and setup wizard."""
    cfg = get_settings()
    router_model = cfg.chat_default_model or "cerebras-qwen-3-235b-a22b-2507"
    api_host = os.getenv("HIVE_PUBLIC_URL", "http://127.0.0.1:8101").rstrip("/")
    pm = is_pm_poc_mode() if pm_poc is None else pm_poc

    if pm:
        return SettingsModel(
            api_base_url=api_host,
            default_model=router_model,
            temperature=0.2,
            max_tokens=8192,
            stream_responses=True,
            theme="system",
            notifications_enabled=False,
            auto_save_sessions=True,
            telemetry_enabled=False,
            log_level="debug",
        )

    return SettingsModel(
        api_base_url=api_host,
        default_model=router_model,
        temperature=0.5,
        max_tokens=8192,
        stream_responses=True,
        theme="system",
        notifications_enabled=True,
        auto_save_sessions=True,
        telemetry_enabled=False,
        log_level="info",
    )


def is_legacy_settings(current: SettingsModel) -> bool:
    """Detect pre-2026 placeholder defaults still in memory."""
    return (
        current.default_model in _LEGACY_MODELS
        or current.api_base_url == "http://localhost:8101"
        or (is_pm_poc_mode() and current.log_level == "info" and current.temperature == 0.7)
    )


def apply_default_settings_if_needed() -> SettingsModel:
    """Repair pre-2026 placeholder settings at startup. Never on a read path.

    This used to run on every ``GET /api/settings`` and rebind an in-memory
    object. Now that the record is durable (ADR-082926-0b72) the repair is a
    real write, so it belongs where it can be attempted once — ``main.py``'s
    startup — rather than on a request a reader expects to be free of writes.

    A store that refuses the repair does not fail startup. The stored values are
    still readable and still the operator's; the placeholders they carry are a
    cosmetic defect, and blocking boot over one would trade a small wrong value
    for no Conductor at all. The failure is logged with the reason.
    """
    import logging

    from services import settings_store

    stored = settings_store.record()
    if not is_legacy_settings(stored.values):
        return stored.values
    try:
        return settings_store.save(default_settings()).values
    except (settings_store.SettingsPersistenceError, settings_store.SettingsConflictError) as exc:
        logging.getLogger("hive.settings_store").warning(
            "legacy settings left in place; the repair write did not land (%s)", exc
        )
        return stored.values
