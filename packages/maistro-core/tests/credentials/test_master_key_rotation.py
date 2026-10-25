"""Master-key rotation — round-trip, failure atomicity, and crash safety.

Remediation tooling for the unauthenticated file-read disclosure (#281, #332):
the disclosed master key and ciphertext must be replaceable without ever
leaving the store unreadable by *either* key.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from maistro.credentials.store import (
    MASTER_KEY_FILENAME,
    STORE_FILENAME,
    CredentialStoreUnavailable,
    UserCredentialStore,
    generate_master_key,
    repair_interrupted_rotation,
)

_PENDING_KEY = MASTER_KEY_FILENAME + ".new"
_PENDING_STORE = STORE_FILENAME + ".new"


def _key(tmp_path: Path) -> bytes:
    return (tmp_path / MASTER_KEY_FILENAME).read_bytes()


def _ciphertext(tmp_path: Path) -> bytes:
    return (tmp_path / STORE_FILENAME).read_bytes()


def _seeded(tmp_path: Path) -> tuple[UserCredentialStore, bytes]:
    store = UserCredentialStore.open(tmp_path)
    store.set_secret("alice", "jira", "alice-jira-token")
    store.set_secret("alice", "github", "alice-github-token")
    store.set_secret("bob", "airtable", "bob-airtable-token")
    return store, _key(tmp_path)


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------


def test_rotation_round_trip_readable_under_new_key(tmp_path: Path) -> None:
    store, old_key = _seeded(tmp_path)
    new_key = generate_master_key()

    result = store.rotate_master_key(new_key)

    assert result.users == 2
    assert result.secrets == 3
    assert _key(tmp_path) == new_key

    reopened = UserCredentialStore(tmp_path, master_key=new_key)
    assert reopened.use_secret("alice", "jira", lambda v: v) == "alice-jira-token"
    assert reopened.use_secret("alice", "github", lambda v: v) == "alice-github-token"
    assert reopened.use_secret("bob", "airtable", lambda v: v) == "bob-airtable-token"
    assert old_key != new_key


def test_rotation_makes_old_key_useless(tmp_path: Path) -> None:
    store, old_key = _seeded(tmp_path)
    store.rotate_master_key(generate_master_key())

    with pytest.raises(InvalidToken):
        Fernet(old_key).decrypt(_ciphertext(tmp_path))

    stale = UserCredentialStore(tmp_path, master_key=old_key)
    with pytest.raises(CredentialStoreUnavailable):
        stale.has_secret("alice", "jira")


def test_rotated_store_still_encrypted_at_rest(tmp_path: Path) -> None:
    store, _ = _seeded(tmp_path)
    store.rotate_master_key(generate_master_key())
    assert b"alice-jira-token" not in _ciphertext(tmp_path)


def test_rotated_instance_keeps_working(tmp_path: Path) -> None:
    """The in-process store must not be left holding a stale Fernet."""
    store, _ = _seeded(tmp_path)
    store.rotate_master_key(generate_master_key())
    store.set_secret("carol", "linear", "carol-token")

    reopened = UserCredentialStore.open(tmp_path)
    assert reopened.use_secret("carol", "linear", lambda v: v) == "carol-token"
    assert reopened.use_secret("alice", "jira", lambda v: v) == "alice-jira-token"


def test_empty_store_rotates_without_error(tmp_path: Path) -> None:
    store = UserCredentialStore.open(tmp_path)
    new_key = generate_master_key()

    result = store.rotate_master_key(new_key)

    assert (result.users, result.secrets) == (0, 0)
    assert _key(tmp_path) == new_key
    reopened = UserCredentialStore.open(tmp_path)
    assert reopened.has_secret("nobody", "jira") is False
    reopened.set_secret("alice", "jira", "post-rotation")
    assert reopened.use_secret("alice", "jira", lambda v: v) == "post-rotation"


def test_key_file_permissions_are_owner_only(tmp_path: Path) -> None:
    store, _ = _seeded(tmp_path)
    store.rotate_master_key(generate_master_key())
    assert (tmp_path / MASTER_KEY_FILENAME).stat().st_mode & 0o777 == 0o600
    assert (tmp_path / STORE_FILENAME).stat().st_mode & 0o777 == 0o600


def test_no_staging_files_left_behind(tmp_path: Path) -> None:
    store, _ = _seeded(tmp_path)
    store.rotate_master_key(generate_master_key())
    assert not (tmp_path / _PENDING_KEY).exists()
    assert not (tmp_path / _PENDING_STORE).exists()
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


# --------------------------------------------------------------------------
# Loud failure, store untouched
# --------------------------------------------------------------------------


def test_undecryptable_current_key_raises_and_leaves_store_untouched(tmp_path: Path) -> None:
    store, real_key = _seeded(tmp_path)
    before = _ciphertext(tmp_path)

    wrong = UserCredentialStore(tmp_path, master_key=generate_master_key())
    with pytest.raises(CredentialStoreUnavailable):
        wrong.rotate_master_key(generate_master_key())

    assert _ciphertext(tmp_path) == before
    assert _key(tmp_path) == real_key
    assert not (tmp_path / _PENDING_KEY).exists()
    assert not (tmp_path / _PENDING_STORE).exists()
    assert store.use_secret("alice", "jira", lambda v: v) == "alice-jira-token"


def test_corrupted_ciphertext_raises_and_leaves_store_untouched(tmp_path: Path) -> None:
    store, real_key = _seeded(tmp_path)
    (tmp_path / STORE_FILENAME).write_bytes(b"not a fernet token")
    fresh = UserCredentialStore.open(tmp_path)

    with pytest.raises(CredentialStoreUnavailable):
        fresh.rotate_master_key(generate_master_key())

    assert _key(tmp_path) == real_key
    assert _ciphertext(tmp_path) == b"not a fernet token"
    assert store is not None


def test_invalid_new_key_rejected(tmp_path: Path) -> None:
    store, real_key = _seeded(tmp_path)
    before = _ciphertext(tmp_path)

    with pytest.raises(ValueError):
        store.rotate_master_key(b"not-a-fernet-key")

    assert _key(tmp_path) == real_key
    assert _ciphertext(tmp_path) == before


def test_rotating_to_the_same_key_is_rejected(tmp_path: Path) -> None:
    store, real_key = _seeded(tmp_path)
    with pytest.raises(ValueError):
        store.rotate_master_key(real_key)
    assert _key(tmp_path) == real_key


def test_failed_verification_aborts_before_touching_live_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staged ciphertext that does not round-trip must abort the rotation."""
    store, real_key = _seeded(tmp_path)
    before = _ciphertext(tmp_path)

    # _atomic_write_bytes writes through a temp file, so corrupt the staged
    # ciphertext immediately after it lands — verification must catch it.
    import maistro.credentials.store as store_mod

    real_atomic = store_mod._atomic_write_bytes

    def _atomic_then_corrupt(path: Path, data: bytes, *, mode: int = 0o600) -> None:
        real_atomic(path, data, mode=mode)
        if path.name == _PENDING_STORE:
            path.write_bytes(b"garbage that will never decrypt")

    monkeypatch.setattr(store_mod, "_atomic_write_bytes", _atomic_then_corrupt)

    with pytest.raises(CredentialStoreUnavailable):
        store.rotate_master_key(generate_master_key())

    monkeypatch.undo()
    assert _key(tmp_path) == real_key
    assert _ciphertext(tmp_path) == before
    assert not (tmp_path / _PENDING_STORE).exists()
    assert UserCredentialStore.open(tmp_path).use_secret("alice", "jira", lambda v: v) == (
        "alice-jira-token"
    )


# --------------------------------------------------------------------------
# Crash safety — the point of the whole exercise
# --------------------------------------------------------------------------


class _Boom(RuntimeError):
    """Simulated process death."""


def _crash_after_nth_replace(monkeypatch: pytest.MonkeyPatch, n: int) -> None:
    """Let the first ``n`` os.replace calls through, then die."""
    import maistro.credentials.store as store_mod

    real_replace = store_mod.os.replace
    calls = {"n": 0}

    def _replace(src: object, dst: object) -> None:
        calls["n"] += 1
        if calls["n"] > n:
            raise _Boom("process died mid-rotation")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(store_mod.os, "replace", _replace)


def test_crash_before_ciphertext_swap_leaves_old_key_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Death before the ciphertext rename: everything still reads under key A."""
    store, old_key = _seeded(tmp_path)
    before = _ciphertext(tmp_path)

    # Staging the ciphertext and the key each consume one os.replace (the temp
    # file rename inside _atomic_write_bytes). Crash on the third — the live
    # ciphertext swap.
    _crash_after_nth_replace(monkeypatch, 2)
    with pytest.raises(_Boom):
        store.rotate_master_key(generate_master_key())
    monkeypatch.undo()

    assert _key(tmp_path) == old_key
    assert _ciphertext(tmp_path) == before

    recovered = UserCredentialStore.open(tmp_path)
    assert recovered.use_secret("alice", "jira", lambda v: v) == "alice-jira-token"
    assert recovered.use_secret("bob", "airtable", lambda v: v) == "bob-airtable-token"
    # The stale staging files were cleaned up rather than left to confuse.
    assert not (tmp_path / _PENDING_KEY).exists()
    assert not (tmp_path / _PENDING_STORE).exists()


def test_crash_between_ciphertext_and_key_swap_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dangerous window: ciphertext already new, key file still old.

    The store must not be lost — the new key is durable at
    ``credential_master.key.new`` and reopening completes the swap.
    """
    store, old_key = _seeded(tmp_path)
    new_key = generate_master_key()

    _crash_after_nth_replace(monkeypatch, 3)  # 2 staging renames + ciphertext swap
    with pytest.raises(_Boom):
        store.rotate_master_key(new_key)
    monkeypatch.undo()

    # Mid-window state: live key file is stale, but the new key is on disk.
    assert _key(tmp_path) == old_key
    assert (tmp_path / _PENDING_KEY).read_bytes() == new_key
    with pytest.raises(InvalidToken):
        Fernet(old_key).decrypt(_ciphertext(tmp_path))

    # Reopening repairs it, and every secret survives.
    recovered = UserCredentialStore.open(tmp_path)
    assert _key(tmp_path) == new_key
    assert recovered.use_secret("alice", "jira", lambda v: v) == "alice-jira-token"
    assert recovered.use_secret("alice", "github", lambda v: v) == "alice-github-token"
    assert recovered.use_secret("bob", "airtable", lambda v: v) == "bob-airtable-token"
    assert not (tmp_path / _PENDING_KEY).exists()
    assert not (tmp_path / _PENDING_STORE).exists()


def test_crash_at_any_point_leaves_exactly_one_key_that_reads_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exhaustive: crash after each os.replace in turn; the store is always
    readable under some key that is discoverable on disk."""
    for crash_after in range(0, 5):
        data_dir = tmp_path / f"run{crash_after}"
        data_dir.mkdir()
        store = UserCredentialStore.open(data_dir)
        store.set_secret("alice", "jira", "alice-jira-token")

        _crash_after_nth_replace(monkeypatch, crash_after)
        with contextlib.suppress(_Boom):
            store.rotate_master_key(generate_master_key())
        monkeypatch.undo()

        recovered = UserCredentialStore.open(data_dir)
        assert recovered.use_secret("alice", "jira", lambda v: v) == "alice-jira-token", (
            f"store unreadable after crash_after={crash_after}"
        )


def test_repair_is_a_noop_when_nothing_was_interrupted(tmp_path: Path) -> None:
    _seeded(tmp_path)
    assert repair_interrupted_rotation(tmp_path) is False


def test_repair_refuses_to_guess_when_neither_key_reads_the_store(tmp_path: Path) -> None:
    """A staged key that does not decrypt the live ciphertext is not promoted."""
    _, old_key = _seeded(tmp_path)
    (tmp_path / STORE_FILENAME).write_bytes(b"corrupt beyond both keys")
    (tmp_path / _PENDING_KEY).write_bytes(generate_master_key())

    assert repair_interrupted_rotation(tmp_path) is False
    assert _key(tmp_path) == old_key
    assert (tmp_path / _PENDING_KEY).exists()


def test_rotation_preserves_exact_payload(tmp_path: Path) -> None:
    store = UserCredentialStore.open(tmp_path)
    expected = {
        "alice": {"jira": "a-1", "github": "a-2"},
        "bob": {"airtable": "b-1"},
        "carol": {"linear": "c-1"},
    }
    for user, providers in expected.items():
        for provider, secret in providers.items():
            store.set_secret(user, provider, secret)

    new_key = generate_master_key()
    store.rotate_master_key(new_key)

    decrypted = json.loads(Fernet(new_key).decrypt(_ciphertext(tmp_path)).decode())
    assert decrypted == expected
