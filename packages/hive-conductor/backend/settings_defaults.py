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
    import stores

    if is_legacy_settings(stores.settings):
        stores.settings = default_settings()
    return stores.settings
