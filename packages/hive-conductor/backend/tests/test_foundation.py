"""Boy Scout coverage: services/foundation.py (was 28%).

Covers:
- get_foundation: raises when not started, returns when started
- start/stop singleton lifecycle
- Foundation.__init__: every flag starts False, every ref starts None
- _init_vault: success path + exception swallowed → vault_available=False
- _init_state: success path with PersistedStore + flush
- _init_state: exception degrades rather than falling back (#333)
- _init_privilege: skipped when admin_public_key empty
- _init_privilege: success path
- _init_privilege: exception swallowed
- _init_reactor: success path
- _init_reactor: exception swallowed → reactor_available=False
- stop: cleans up reactor + state when available
- stop: skips when not available (defensive)
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _reset_singleton():
    import services.foundation as f
    import stores

    prev = f._singleton
    f._singleton = None
    # Snapshot the stores singleton state so foundation tests don't leak
    # their stub PersistedStore into the rest of the suite.
    prev_persisted = stores._persisted
    # Snapshot user data so we don't wipe the conftest's seeded testuser
    user_snapshot = dict(stores.users._data)
    yield
    # `_init_state` can now degrade every store (#333). Left set, that would
    # make the rest of the suite refuse writes for a failure it never had.
    stores.restore_all()
    from services import durability, settings_store

    durability.reset()
    settings_store.reset()
    f._singleton = prev
    # Restore persistence binding so subsequent tests see in-memory stores.
    stores._persisted = prev_persisted
    for store in stores._all_model_stores:
        store._persisted = prev_persisted
    for store in stores._all_json_stores:
        store._persisted = prev_persisted
    # Restore seeded users (foundation init may have reset the dict).
    stores.users._data.clear()
    stores.users._data.update(user_snapshot)


# --- singleton lifecycle -------------------------------------------------


def test_get_foundation_raises_when_not_started() -> None:
    from services.foundation import get_foundation

    with pytest.raises(RuntimeError, match="not started"):
        get_foundation()


async def test_start_then_get_returns_instance(tmp_path: Path) -> None:
    from services.foundation import Foundation, get_foundation, start_foundation

    settings = _StubSettings(tmp_path)
    inst = await start_foundation(settings)
    assert isinstance(inst, Foundation)
    assert get_foundation() is inst


async def test_stop_clears_singleton(tmp_path: Path) -> None:
    import services.foundation as f
    from services.foundation import start_foundation, stop_foundation

    await start_foundation(_StubSettings(tmp_path))
    assert f._singleton is not None
    await stop_foundation()
    assert f._singleton is None


async def test_stop_when_not_started_is_noop() -> None:
    import services.foundation as f
    from services.foundation import stop_foundation

    assert f._singleton is None
    await stop_foundation()
    assert f._singleton is None


# --- Foundation.__init__ -----------------------------------------------


def test_foundation_init_zero_state() -> None:
    from services.foundation import Foundation

    fnd = Foundation()
    assert fnd.vault is None
    assert fnd.state is None
    assert fnd.privilege is None
    assert fnd.reactor is None
    assert fnd.vault_available is False
    assert fnd.state_available is False
    assert fnd.privilege_available is False
    assert fnd.reactor_available is False


# --- _init_vault --------------------------------------------------------


def _StubSettings(tmp_path: Path) -> Any:
    return SimpleNamespace(
        conductor_data_dir=str(tmp_path),
        conductor_vault_path="",
        conductor_identity_path="",
        conductor_state_db="",
        conductor_durability="durable",
        conductor_admin_public_key="",
        conductor_user_public_key="",
    )


def test_init_vault_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    class _Vault:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    vault_mod = types.ModuleType("maistro.vault")
    vault_mod.Vault = _Vault  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.vault", vault_mod)

    fnd = Foundation()
    fnd._init_vault(_StubSettings(tmp_path), tmp_path)
    assert fnd.vault_available is True
    assert isinstance(fnd.vault, _Vault)


def test_init_vault_exception_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Vault import fails and no vault file was ever provisioned, degrade quietly."""
    import types

    from services.foundation import Foundation

    broken = types.ModuleType("maistro.vault")

    def _broken_attr(name: str) -> Any:
        raise ImportError(f"synthetic no {name}")

    broken.__getattr__ = _broken_attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.vault", broken)

    fnd = Foundation()
    fnd._init_vault(_StubSettings(tmp_path), tmp_path)
    assert fnd.vault_available is False
    assert fnd.vault is None


def test_init_vault_provisioned_but_unopenable_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SPEC-003: a provisioned vault that fails to open must not silently fall
    back to env-var secrets — it fails closed (SystemExit), not a swallowed warning."""
    import types

    from services.foundation import Foundation

    vault_path = tmp_path / "secrets.age"
    vault_path.write_bytes(b"age-encrypted-blob")

    broken = types.ModuleType("maistro.vault")

    def _broken_attr(name: str) -> Any:
        raise ImportError(f"synthetic no {name}")

    broken.__getattr__ = _broken_attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.vault", broken)

    fnd = Foundation()
    settings = _StubSettings(tmp_path)
    settings.conductor_vault_path = str(vault_path)
    with pytest.raises(SystemExit, match="SECRET_MISSING"):
        fnd._init_vault(settings, tmp_path)


# --- _init_state -------------------------------------------------------


_state_flush_count = [0]


class _StubState:
    def __init__(self, **kw: Any) -> None:
        pass

    def flush(self) -> None:
        _state_flush_count[0] += 1

    def close(self) -> None:
        pass


class _StubPersist:
    def __init__(self, *a: Any) -> None:
        pass

    def initialize(self) -> None:
        pass

    def list_all(self, store_name: str, model_class: Any) -> list[Any]:
        return []

    def list_all_raw(self, store_name: str) -> list[Any]:
        return []

    def put(self, *a: Any, **kw: Any) -> None:
        pass

    def put_raw(self, *a: Any, **kw: Any) -> None:
        pass

    def delete(self, *a: Any, **kw: Any) -> None:
        pass


def test_init_state_success_wires_persisted_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    _state_flush_count[0] = 0

    state_mod = types.ModuleType("maistro.state")
    state_mod.State = _StubState  # type: ignore[attr-defined]
    state_mod.PersistedStore = _StubPersist  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.state", state_mod)

    fnd = Foundation()
    fnd._init_state(_StubSettings(tmp_path), tmp_path)
    assert fnd.state_available is True
    assert _state_flush_count[0] == 1


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
def test_init_state_exception_degrades_rather_than_falling_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This used to assert the fallback. The fallback is the defect (#333).

    A durable deployment whose state fails now records the failure and refuses
    writes; it does not quietly become an in-memory deployment reporting healthy.
    """
    import types

    from services import durability
    from services.foundation import Foundation

    broken = types.ModuleType("maistro.state")

    def _broken_attr(name: str) -> Any:
        raise ImportError(f"synthetic no {name}")

    broken.__getattr__ = _broken_attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.state", broken)

    fnd = Foundation()
    fnd._init_state(_StubSettings(tmp_path), tmp_path)

    assert fnd.state_available is False
    recorded = durability.status()
    assert recorded is not None
    assert recorded.requested == "durable"
    assert recorded.durable is False
    assert recorded.writes_refused is True
    assert "synthetic no" in (recorded.error or "")


# --- _init_privilege ---------------------------------------------------


def test_init_privilege_skipped_without_admin_key(tmp_path: Path) -> None:
    from services.foundation import Foundation

    fnd = Foundation()
    settings = _StubSettings(tmp_path)
    settings.conductor_admin_public_key = ""
    fnd._init_privilege(settings, tmp_path)
    assert fnd.privilege_available is False


def test_init_privilege_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    class _Guard:
        def __init__(self, *, data_dir: str) -> None:
            self.dd = data_dir

        def initialize(self, **kw: Any) -> None:
            pass

    priv_mod = types.ModuleType("maistro.privilege")
    priv_mod.PrivilegeGuard = _Guard  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.privilege", priv_mod)

    fnd = Foundation()
    settings = _StubSettings(tmp_path)
    settings.conductor_admin_public_key = "ssh-ed25519 AAA...admin"
    fnd._init_privilege(settings, tmp_path)
    assert fnd.privilege_available is True


def test_init_privilege_exception_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    broken = types.ModuleType("maistro.privilege")

    def _broken_attr(name: str) -> Any:
        raise ImportError("synthetic")

    broken.__getattr__ = _broken_attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.privilege", broken)

    fnd = Foundation()
    settings = _StubSettings(tmp_path)
    settings.conductor_admin_public_key = "ssh-ed25519 AAA"
    fnd._init_privilege(settings, tmp_path)
    assert fnd.privilege_available is False


# --- _init_reactor ----------------------------------------------------


async def test_init_reactor_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    started = [0]
    stopped = [0]

    class _Reactor:
        def __init__(self, **kw: Any) -> None:
            pass

        async def start(self) -> None:
            started[0] += 1

        async def stop(self) -> None:
            stopped[0] += 1

    reactor_mod = types.ModuleType("maistro.reactor")
    reactor_mod.Reactor = _Reactor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.reactor", reactor_mod)

    fnd = Foundation()
    fnd.state_available = True
    await fnd._init_reactor(_StubSettings(tmp_path), tmp_path)
    assert fnd.reactor_available is True
    assert started[0] == 1


async def test_init_reactor_exception_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    from services.foundation import Foundation

    broken = types.ModuleType("maistro.reactor")

    def _broken_attr(name: str) -> Any:
        raise ImportError("synthetic")

    broken.__getattr__ = _broken_attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.reactor", broken)

    fnd = Foundation()
    await fnd._init_reactor(_StubSettings(tmp_path), tmp_path)
    assert fnd.reactor_available is False


# --- stop ---------------------------------------------------------------


async def test_stop_calls_subsystems_when_available() -> None:
    from services.foundation import Foundation

    closed = [0]
    stopped = [0]

    class _R:
        async def stop(self) -> None:
            stopped[0] += 1

    class _St:
        def close(self) -> None:
            closed[0] += 1

    fnd = Foundation()
    fnd.reactor = _R()
    fnd.reactor_available = True
    fnd.state = _St()
    fnd.state_available = True
    await fnd.stop()
    assert stopped[0] == 1
    assert closed[0] == 1


async def test_stop_skips_unavailable_subsystems() -> None:
    from services.foundation import Foundation

    fnd = Foundation()
    fnd.reactor = None
    fnd.reactor_available = False
    fnd.state = None
    fnd.state_available = False
    await fnd.stop()  # no exception
