"""Data-directory durability guard (#331).

Covers services/data_dir_guard.py:
- verify_durable_data_dir: creates a missing directory and returns it resolved
- unwritable directory → DataDirRefused (probe write fails)
- unwritable parent (cannot create) → DataDirRefused
- inside a container: unmounted data dir → DataDirRefused (ephemeral)
- inside a container: mounted data dir passes
- inside a container: CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1 is the escape hatch
- outside a container: plain directories pass without any mount requirement
- Foundation.start refuses before initializing any subsystem
"""

from __future__ import annotations

import os
import pathlib
import sys
from pathlib import Path

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.data_dir_guard import DataDirRefused, verify_durable_data_dir  # noqa: E402


@pytest.fixture(autouse=True)
def _outside_container(monkeypatch: pytest.MonkeyPatch):
    """Tests run as if on a host by default; container tests opt in."""
    monkeypatch.setattr(
        "services.data_dir_guard.running_in_container", lambda: False, raising=False
    )
    yield


def test_creates_missing_dir_and_returns_resolved(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "data"
    resolved = verify_durable_data_dir(target)
    assert resolved == target
    assert target.is_dir()
    # The writability probe cleaned up after itself.
    assert list(target.iterdir()) == []


def test_unwritable_dir_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    os.chmod(target, 0o500)
    try:
        with pytest.raises(DataDirRefused, match="DATA_DIR_UNWRITABLE"):
            verify_durable_data_dir(target)
    finally:
        os.chmod(target, 0o700)


def test_uncreatable_parent_is_refused(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    os.chmod(blocker, 0o500)
    try:
        with pytest.raises(DataDirRefused, match="DATA_DIR_UNWRITABLE"):
            verify_durable_data_dir(blocker / "data")
    finally:
        os.chmod(blocker, 0o700)


# --- in-container ephemerality ------------------------------------------


def _in_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.data_dir_guard.running_in_container", lambda: True, raising=False)


def test_in_container_unmounted_dir_is_refused_as_ephemeral(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _in_container(monkeypatch)
    plain_dir = tmp_path / "conductor"  # not a mount point
    plain_dir.mkdir()
    with pytest.raises(DataDirRefused, match="DATA_DIR_EPHEMERAL"):
        verify_durable_data_dir(plain_dir)


def test_in_container_mounted_dir_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _in_container(monkeypatch)
    mounted = tmp_path / "data"
    mounted.mkdir()
    monkeypatch.setattr("services.data_dir_guard.os.path.ismount", lambda p: True, raising=False)
    assert verify_durable_data_dir(mounted) == mounted


def test_escape_hatch_allows_ephemeral_but_still_probes_writability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _in_container(monkeypatch)
    monkeypatch.setenv("CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR", "1")
    plain_dir = tmp_path / "throwaway"
    plain_dir.mkdir()
    resolved = verify_durable_data_dir(plain_dir)
    assert resolved == plain_dir

    # The hatch is an acknowledgement of ephemerality, not of brokenness:
    # an unwritable dir is still refused with it set.
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    os.chmod(readonly, 0o500)
    try:
        with pytest.raises(DataDirRefused, match="DATA_DIR_UNWRITABLE"):
            verify_durable_data_dir(readonly)
    finally:
        os.chmod(readonly, 0o700)


def test_outside_container_no_mount_requirement(tmp_path: Path) -> None:
    # Host deployments keep state in plain directories like ~/.conductor;
    # the guard must not demand a mount point there.
    assert verify_durable_data_dir(tmp_path / "conductor") == tmp_path / "conductor"


# --- Foundation wiring ---------------------------------------------------


def test_foundation_start_refuses_before_touching_subsystems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from services import foundation as foundation_module

    _in_container(monkeypatch)
    bad_dir = tmp_path / "conductor"
    bad_dir.mkdir()

    started: list[str] = []

    class ExplodingFoundation(foundation_module.Foundation):
        def _init_vault(self, settings: object, data_dir: Path) -> None:
            started.append("vault")
            raise AssertionError("vault must not initialize after a refusal")

        def _init_state(self, settings: object, data_dir: Path) -> None:
            started.append("state")
            raise AssertionError("state must not initialize after a refusal")

    foundation = ExplodingFoundation()
    settings = type("S", (), {"conductor_data_dir": str(bad_dir)})()
    with pytest.raises(DataDirRefused, match="DATA_DIR_EPHEMERAL"):
        asyncio.run(foundation.start(settings))  # type: ignore[arg-type]
    assert started == []
