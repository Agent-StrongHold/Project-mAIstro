"""Host-side file transfer cannot race its own containment check (#1198, #18).

`write_file`/`read_file` run on the host — they are how work gets in and
results come out — so their path containment is a security boundary, not a
convenience. A resolve-then-open implementation validates the path once and
opens it later, and a symlink swapped into that window redirects the open:
the bubblewrap backend had exactly that check-to-open gap.

The tests below pin the implementation that closes the window. `read_beneath`
/`write_beneath` walk directory file descriptors with `O_NOFOLLOW`, so the
kernel refuses a symlink at `open` time — there is no check-then-open gap
left to win, which is what the active race test (the reason this file exists)
exercises against the production backend seam.

These need no bubblewrap: transfer is host-side; only `exec` runs `bwrap`.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend
from maistro.sandbox.paths import read_beneath, write_beneath
from maistro.sandbox.protocol import SandboxConfig

_SENTINEL = b"host secret - the sandbox must never touch this"


def _backend(tmp_path: Path) -> BubblewrapSandboxBackend:
    return BubblewrapSandboxBackend(root=tmp_path, bwrap="/usr/bin/bwrap")


def _sentinel(outside: Path) -> Path:
    secret = outside / "host-secret"
    secret.write_bytes(_SENTINEL)
    return secret


# --- the kernel refuses the symlink at open time ------------------------------


def test_a_symlink_at_the_final_component_is_refused_not_followed(tmp_path: Path) -> None:
    """The exact escape the resolve-based check could only catch at check time."""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = _sentinel(outside)

    root = tmp_path / "work"
    root.mkdir()
    (root / "victim").symlink_to(secret)

    with pytest.raises(OSError):
        read_beneath(root, "victim")
    with pytest.raises(OSError):
        write_beneath(root, "victim", b"owned")

    assert secret.read_bytes() == _SENTINEL
    assert not (outside / "victim").exists()


def test_a_symlink_at_an_intermediate_component_is_refused_not_followed(
    tmp_path: Path,
) -> None:
    """Every walked component is O_NOFOLLOW, not just the final one."""
    outside = tmp_path / "outside"
    outside.mkdir()
    _sentinel(outside)

    root = tmp_path / "work"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "real").mkdir()
    write_beneath(root, "real/keep", b"ok")  # sanity: normal writes still work

    with pytest.raises(OSError):
        read_beneath(root, "link/host-secret")
    with pytest.raises(OSError):
        write_beneath(root, "link/planted", b"owned")

    assert not (outside / "planted").exists()


# --- and the same through the production backend seam -------------------------


async def test_backend_transfer_refuses_a_symlink_swapped_onto_a_valid_path(
    tmp_path: Path,
) -> None:
    """A path that validated as a regular file becomes a symlink, then is used.

    This is the race window, held open deterministically: the old
    resolve-then-open transfer passed this sequence (resolve saw the regular
    file, open followed the symlink); the O_NOFOLLOW transfer cannot.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = _sentinel(outside)

    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    workdir = Path(instance.metadata["workdir"])
    await backend.write_file(instance, "victim", b"regular file")

    (workdir / "victim").unlink()
    (workdir / "victim").symlink_to(secret)

    with pytest.raises(OSError):
        await backend.read_file(instance, "victim")
    with pytest.raises(OSError):
        await backend.write_file(instance, "victim", b"owned")

    assert secret.read_bytes() == _SENTINEL
    await backend.destroy(instance)


async def test_backend_transfer_wins_the_race_never_the_attacker(
    tmp_path: Path,
) -> None:
    """The race itself: a thread swaps the path between a regular file and a
    symlink to a host sentinel while the backend transfers through it.

    Safety property, checked throughout: the sentinel is never modified and no
    read ever returns its content. Transfers either succeed on the regular
    file or fail with the kernel's ELOOP — the swap thread cannot win because
    there is no window left to win.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = _sentinel(outside)

    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    victim = Path(instance.metadata["workdir"]) / "victim"
    victim.write_bytes(b"regular file")

    stop = threading.Event()
    swapped = threading.Event()

    def swap_loop() -> None:
        make_link = True
        while not stop.is_set():
            try:
                victim.unlink(missing_ok=True)
                if make_link:
                    victim.symlink_to(secret)
                else:
                    victim.write_bytes(b"regular file")
            except (FileExistsError, FileNotFoundError):
                pass  # the workload recreated it mid-swap — that IS the race
            make_link = not make_link
            swapped.set()

    swapper = threading.Thread(target=swap_loop, daemon=True)
    swapper.start()
    try:
        assert swapped.wait(timeout=5), "swapper never started"
        deadline = time.monotonic() + 3.0
        transfers = 0
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                # refused at open time — the intended outcome
                await backend.write_file(instance, "victim", b"payload")
            try:
                data = await backend.read_file(instance, "victim")
            except OSError:
                data = b""
            else:
                assert data != _SENTINEL, "a read came back through the symlink"
            transfers += 1
            assert secret.read_bytes() == _SENTINEL, "the sentinel was modified"
        assert transfers > 10, f"transfers never actually raced ({transfers})"
    finally:
        stop.set()
        swapper.join(timeout=5)
        await backend.destroy(instance)
