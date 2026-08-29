"""Foundation — initializes vault, state, privilege, and reactor subsystems.

Provides a single ``Foundation`` singleton that the FastAPI lifespan
starts/stops. All routes access subsystems through ``get_foundation()``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.foundation")


class Foundation:
    """Holds references to all initialised subsystems."""

    def __init__(self) -> None:
        self.vault: object | None = None
        self.state: object | None = None
        self.privilege: object | None = None
        self.reactor: object | None = None
        self.vault_available = False
        self.state_available = False
        self.privilege_available = False
        self.reactor_available = False

    async def start(self, settings: Settings) -> None:
        data_dir = Path(settings.conductor_data_dir).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)

        self._init_vault(settings, data_dir)
        self._init_credentials(data_dir)
        self._init_state(settings, data_dir)
        self._init_privilege(settings, data_dir)
        await self._init_reactor(settings, data_dir)

    def _init_vault(self, settings: Settings, data_dir: Path) -> None:
        vault_path = settings.conductor_vault_path or str(data_dir / "secrets.age")
        identity_path = settings.conductor_identity_path or str(data_dir / "admin.key")
        # A vault file already on disk means secrets were provisioned into it;
        # failing to open it must fail closed (SPEC-003), not silently degrade
        # to env-var secrets. A fresh install with no vault file yet is fine —
        # SPEC-011's vault is optional by default until `vault.add()` is used.
        vault_provisioned = Path(vault_path).exists()
        try:
            from maistro.vault import Vault

            self.vault = Vault(
                vault_path=vault_path,
                identity_path=identity_path,
            )
            self.vault_available = True
            logger.info("Vault initialised: %s", vault_path)
        except Exception as exc:
            if vault_provisioned:
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the vault file path and exception, never secret values
                logger.error("SECRET_MISSING: vault at %s failed to open (%s)", vault_path, exc)
                raise SystemExit(f"SECRET_MISSING: vault unavailable ({exc})") from exc
            logger.info(
                "No vault provisioned yet (%s) — secrets resolve from config/env until "
                "vault.add() is used",
                exc,
            )

    def _init_credentials(self, data_dir: Path) -> None:
        from services import user_credentials as cred_svc

        cred_svc.init_credential_store(data_dir)

    def _init_state(self, settings: Settings, data_dir: Path) -> None:
        db_path = settings.conductor_state_db or str(data_dir / "state.db")
        try:
            from maistro.state import PersistedStore, State

            self.state = State(db_path=db_path)
            self.state_available = True
            logger.info("State initialised: %s", db_path)

            persisted = PersistedStore(self.state)
            persisted.initialize()

            import stores

            from services.settings_store import PersistedSettingsRecordStore
            from services.settings_store import configure as configure_settings

            stores.configure_persistence(persisted)
            stores.initialize_stores()
            configure_settings(PersistedSettingsRecordStore(persisted, self.state.flush))
            self.state.flush()
            logger.info("Stores wired to SQLite persistence")
        except Exception as exc:
            logger.warning("State unavailable (%s) — using in-memory stores", exc)
            import stores

            from services.settings_store import EphemeralSettingsRecordStore
            from services.settings_store import configure as configure_settings

            stores.initialize_stores()
            # Explicitly, so the settings surface reports `durable: false`
            # rather than letting an in-memory write wear the shape of a
            # durable one (#334). Whether reaching this branch at all should be
            # allowed is #333.
            configure_settings(EphemeralSettingsRecordStore())

    def _init_privilege(self, settings: Settings, data_dir: Path) -> None:
        if not settings.conductor_admin_public_key:
            logger.info("Privilege skipped — no admin key configured")
            return
        try:
            from maistro.privilege import PrivilegeGuard

            self.privilege = PrivilegeGuard(data_dir=str(data_dir))
            self.privilege.initialize(
                admin_public_key=settings.conductor_admin_public_key,
                user_public_key=settings.conductor_user_public_key or "",
            )
            self.privilege_available = True
            logger.info("Privilege initialised")
        except Exception as exc:
            logger.warning("Privilege unavailable (%s)", exc)

    async def _init_reactor(self, settings: Settings, data_dir: Path) -> None:
        try:
            from maistro.reactor import Reactor

            state_db = str(data_dir / "state.db") if self.state_available else None
            self.reactor = Reactor(
                state_db_path=state_db,
            )
            await self.reactor.start()
            self.reactor_available = True
            logger.info("Reactor started")
        except Exception as exc:
            logger.warning("Reactor unavailable (%s) — event loop disabled", exc)

    async def stop(self) -> None:
        if self.reactor_available and self.reactor is not None:
            await self.reactor.stop()
        if self.state_available and self.state is not None:
            self.state.close()


_singleton: Foundation | None = None


def get_foundation() -> Foundation:
    if _singleton is None:
        raise RuntimeError("Foundation not started")
    return _singleton


async def start_foundation(settings: Settings) -> Foundation:
    global _singleton
    _singleton = Foundation()
    await _singleton.start(settings)
    return _singleton


async def stop_foundation() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.stop()
        _singleton = None
