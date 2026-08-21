"""Encrypted per-user credential store."""

from __future__ import annotations

import contextlib
import json

import pytest
from cryptography.fernet import Fernet
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from maistro.credentials.store import (
    CredentialNotFound,
    CredentialStoreUnavailable,
    UserCredentialStore,
)


@pytest.fixture()
def store(tmp_path):
    return UserCredentialStore.open(tmp_path)


def test_set_and_use_secret(store: UserCredentialStore) -> None:
    store.set_secret("alice", "jira", "token-alice")
    seen: list[str] = []

    def _capture(value: str) -> str:
        seen.append(value)
        return "ok"

    assert store.use_secret("alice", "jira", _capture) == "ok"
    assert seen == ["token-alice"]


def test_users_isolated(store: UserCredentialStore) -> None:
    store.set_secret("alice", "jira", "alice-token")
    store.set_secret("bob", "jira", "bob-token")

    assert store.use_secret("alice", "jira", lambda v: v) == "alice-token"
    assert store.use_secret("bob", "jira", lambda v: v) == "bob-token"


def test_encrypted_file_not_plaintext(store: UserCredentialStore, tmp_path) -> None:
    store.set_secret("alice", "github", "ghp_supersecret")
    raw = (tmp_path / "user_credentials.enc").read_bytes()
    assert b"ghp_supersecret" not in raw


def test_missing_raises(store: UserCredentialStore) -> None:
    with pytest.raises(CredentialNotFound):
        store.use_secret("nobody", "jira", lambda v: v)


class TestWorkspaceScopedConnections:
    """Persona/Workspace Phase F: (user_id, provider, workspace_id, connection_name)."""

    def test_default_scope_is_backward_compatible_with_unscoped_calls(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        """A secret set with no scope args round-trips through explicit
        default-scope args, and lands on-disk under the exact bare-provider
        key pre-Phase-F code used -- zero format change for the common case."""
        store.set_secret("alice", "jira", "token-alice")
        assert store.has_secret("alice", "jira", workspace_id="default", connection_name="default")
        assert (
            store.use_secret(
                "alice", "jira", lambda v: v, workspace_id="default", connection_name="default"
            )
            == "token-alice"
        )
        raw = json.loads(
            Fernet(_master_key(tmp_path)).decrypt((tmp_path / "user_credentials.enc").read_bytes())
        )
        assert raw["alice"] == {"jira": "token-alice"}

    def test_two_connections_of_the_same_provider_coexist(self, store: UserCredentialStore) -> None:
        store.set_secret(
            "alice", "jira", "team-a-token", workspace_id="ws-a", connection_name="team_a"
        )
        store.set_secret(
            "alice", "jira", "team-b-token", workspace_id="ws-a", connection_name="team_b"
        )
        assert (
            store.use_secret(
                "alice", "jira", lambda v: v, workspace_id="ws-a", connection_name="team_a"
            )
            == "team-a-token"
        )
        assert (
            store.use_secret(
                "alice", "jira", lambda v: v, workspace_id="ws-a", connection_name="team_b"
            )
            == "team-b-token"
        )

    def test_legacy_unscoped_secret_still_resolves_at_default_scope(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        """A record written before Phase F (bare-provider key, no scoping at
        all) must resolve exactly as "the default workspace's default
        connection" with no migration step required."""
        store.set_secret("alice", "jira", "pre-phase-f-token")
        fresh = UserCredentialStore.open(tmp_path)
        assert fresh.has_secret("alice", "jira")  # unscoped call
        assert fresh.has_secret("alice", "jira", workspace_id="default", connection_name="default")
        assert (
            fresh.use_secret("alice", "jira", lambda v: v, workspace_id="default")
            == "pre-phase-f-token"
        )

    def test_scoped_connection_does_not_shadow_the_legacy_default(
        self, store: UserCredentialStore
    ) -> None:
        store.set_secret("alice", "jira", "legacy-token")
        store.set_secret("alice", "jira", "scoped-token", workspace_id="ws-a", connection_name="x")
        assert store.use_secret("alice", "jira", lambda v: v) == "legacy-token"
        assert (
            store.use_secret("alice", "jira", lambda v: v, workspace_id="ws-a", connection_name="x")
            == "scoped-token"
        )

    def test_delete_is_scoped_and_does_not_touch_other_connections(
        self, store: UserCredentialStore
    ) -> None:
        store.set_secret("alice", "jira", "legacy-token")
        store.set_secret("alice", "jira", "scoped-token", workspace_id="ws-a", connection_name="x")
        assert (
            store.delete_secret("alice", "jira", workspace_id="ws-a", connection_name="x") is True
        )
        assert store.has_secret("alice", "jira", workspace_id="ws-a", connection_name="x") is False
        assert store.has_secret("alice", "jira") is True  # legacy default untouched

    def test_list_providers_for_user_is_scoped(self, store: UserCredentialStore) -> None:
        store.set_secret("alice", "jira", "legacy-token")
        store.set_secret(
            "alice", "github", "scoped-token", workspace_id="ws-a", connection_name="x"
        )

        default_scope = store.list_providers_for_user("alice")
        assert set(default_scope) == {"jira"}

        scoped = store.list_providers_for_user("alice", workspace_id="ws-a", connection_name="x")
        assert set(scoped) == {"github"}


def _master_key(tmp_path) -> bytes:
    return (tmp_path / "credential_master.key").read_bytes()


def _write_forged_store(tmp_path, ciphertext: bytes) -> None:
    (tmp_path / "user_credentials.enc").write_bytes(ciphertext)


class TestCorruptedStoreFile:
    """Adversarial payloads written directly to the .enc file — must degrade to
    CredentialStoreUnavailable, never an uncaught exception (binascii.Error,
    TypeError, AttributeError, etc.)."""

    def test_corrupted_base64_raises_unavailable(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")  # forces store creation
        _write_forged_store(tmp_path, b"!!! not valid fernet/base64 !!!")
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_empty_file_raises_unavailable(self, store: UserCredentialStore, tmp_path) -> None:
        store.set_secret("alice", "jira", "seed")
        _write_forged_store(tmp_path, b"")
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_valid_fernet_but_json_array_raises_unavailable(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        fernet = Fernet(_master_key(tmp_path))
        _write_forged_store(tmp_path, fernet.encrypt(json.dumps([1, 2, 3]).encode()))
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_valid_fernet_but_json_scalar_raises_unavailable(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        fernet = Fernet(_master_key(tmp_path))
        _write_forged_store(tmp_path, fernet.encrypt(json.dumps(42).encode()))
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_valid_fernet_but_non_json_payload_raises_unavailable(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        fernet = Fernet(_master_key(tmp_path))
        _write_forged_store(tmp_path, fernet.encrypt(b"not json at all {{{"))
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_wrong_key_decrypt_raises_unavailable(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        wrong_key_fernet = Fernet(Fernet.generate_key())
        payload = json.dumps({"alice": {"jira": "token"}}).encode()
        _write_forged_store(tmp_path, wrong_key_fernet.encrypt(payload))
        fresh = UserCredentialStore.open(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")

    def test_non_dict_user_values_are_filtered_not_crashed(
        self, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        fernet = Fernet(_master_key(tmp_path))
        payload = json.dumps(
            {
                "alice": {"jira": "alice-token"},
                "bob": "not-a-dict",
                "carol": ["also", "not", "a", "dict"],
                "dave": None,
            }
        ).encode()
        _write_forged_store(tmp_path, fernet.encrypt(payload))
        fresh = UserCredentialStore.open(tmp_path)
        assert fresh.has_secret("alice", "jira") is True
        assert fresh.has_secret("bob", "jira") is False
        assert fresh.has_secret("carol", "jira") is False
        assert fresh.has_secret("dave", "jira") is False

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(garbage=st.binary(max_size=500))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_arbitrary_bytes_never_raise_unexpected_type(
        self, garbage: bytes, store: UserCredentialStore, tmp_path
    ) -> None:
        store.set_secret("alice", "jira", "seed")
        _write_forged_store(tmp_path, garbage)
        fresh = UserCredentialStore.open(tmp_path)

        with contextlib.suppress(CredentialStoreUnavailable):
            fresh.has_secret("alice", "jira")  # the only acceptable failure mode
