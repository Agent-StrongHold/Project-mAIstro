"""Episodic memory-decay cadence for the conductor process (SPEC-080126-9e42).

`README.md` says episodic memory "decays without reinforcement"; CLAUDE.md decision
#5 is "Memory must forget". Both were false at runtime — `tiers.tick_decay()` had
no production caller (#344). This module gives it one.

Shape follows `services/scheduler.py`: a module-level singleton started from the
app lifespan and stopped on shutdown. Decay is a **system cadence**, not a
user-created schedule, so it needs no persisted schedule record — a background task
whose lifetime is the process's is exactly right, and it deliberately does not go
through `/v1/schedules`.

Disabling (`MEMORY_DECAY_INTERVAL_S <= 0`) is a loud degraded mode, matching the F3
precedent used for `ALLOW_STUB_LLM`: a warning at startup plus `degraded: true` and
`memory_decay.state: "disabled"` on /health. Silence would be indistinguishable
from the bug this closes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.memory_decay")

__all__ = [
    "get_decay_driver",
    "memory_decay_status",
    "start_memory_decay",
    "stop_memory_decay",
]

_driver: Any = None


def _resolve_episodic_store() -> Any:
    try:
        from services.engine import get_engine

        return get_engine().episodic_store
    except Exception as exc:
        logger.warning("memory_decay_store_lookup_failed: %s", exc)
        return None


async def start_memory_decay(settings: Settings | None = None) -> Any:
    """Build and start the decay driver. Idempotent; returns the driver."""
    global _driver
    if _driver is not None:
        return _driver

    if settings is None:
        from config import get_settings

        settings = get_settings()

    from maistro.memory.episodic import EpisodicDecayDriver

    _driver = EpisodicDecayDriver(
        _resolve_episodic_store(),
        interval_s=settings.memory_decay_interval_s,
        setting_name="MEMORY_DECAY_INTERVAL_S",
    )
    started = await _driver.start()
    if not started and _driver.enabled:
        # Enabled but not running: no episodic store in this process. Say so —
        # "configured on but doing nothing" is the failure mode being fixed.
        logger.warning(
            "memory_decay_not_running state=%s — episodic memory will not decay in this process",
            _driver.state(),
        )
    return _driver


async def stop_memory_decay() -> None:
    global _driver
    if _driver is None:
        return
    driver = _driver
    _driver = None
    await driver.stop()


def get_decay_driver() -> Any:
    return _driver


def memory_decay_status() -> dict[str, Any]:
    """Observable decay state for /health. Never raises — /health is a probe."""
    if _driver is not None:
        try:
            return dict(_driver.status())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("memory_decay_status_failed: %s", exc)
            return {"enabled": False, "state": "unavailable"}
    # Not started yet (or already stopped): report from configuration so the
    # signal is honest before the lifespan has run.
    try:
        from config import get_settings

        interval = get_settings().memory_decay_interval_s
    except Exception:
        return {"enabled": False, "state": "unavailable"}
    return {
        "enabled": interval > 0,
        "state": "disabled" if interval <= 0 else "stopped",
        "interval_s": float(interval),
        "ticks": 0,
        "last_tick": None,
    }
