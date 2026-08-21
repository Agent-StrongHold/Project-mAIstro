"""Gap-filling coverage for UserCredentialStore not exercised by
test_credential_store.py: master-key resolution branches, open() reusing an
existing key, decrypt-failure/format-validation branches in _load, and the
list/delete/has_secret/empty-secret paths."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from maistro.credentials.store import (
    CredentialStoreUnavailable,
    UserCredentialStore,
)


class TestResolveMasterKey:
    def test_explicit_key_takes_precedence(self, tmp_path) -> None:
        key = Fernet.generate_key()
        store = UserCredentialStore(tmp_path, master_key=key)
        store.set_secret("alice", "jira", "tok")
        assert store.use_secret("alice", "jira", lambda v: v) == "tok"

    def test_env_key_used_when_no_explicit_key(self, tmp_path, monkeypatch) -> None:
        key = Fernet.generate_key()
        monkeypatch.setenv("HIVE_CREDENTIALS_MASTER_KEY", key.decode())
        store = UserCredentialStore(tmp_path)
        store.set_secret("alice", "jira", "tok")
        assert store.use_secret("alice", "jira", lambda v: v) == "tok"

    def test_existing_key_file_used_when_no_explicit_or_env_key(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.delenv("HIVE_CREDENTIALS_MASTER_KEY", raising=False)
        key = Fernet.generate_key()
        (tmp_path / "credential_master.key").write_bytes(key)
        store = UserCredentialStore(tmp_path)
        store.set_secret("alice", "jira", "tok")
        assert store.use_secret("alice", "jira", lambda v: v) == "tok"

    def test_no_key_anywhere_raises(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("HIVE_CREDENTIALS_MASTER_KEY", raising=False)
        with pytest.raises(CredentialStoreUnavailable):
            UserCredentialStore(tmp_path)


class TestOpen:
    def test_open_generates_key_on_first_call(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        assert (tmp_path / "credential_master.key").exists()
        store.set_secret("alice", "jira", "tok")

    def test_open_reuses_existing_key(self, tmp_path) -> None:
        first = UserCredentialStore.open(tmp_path)
        first.set_secret("alice", "jira", "tok")

        second = UserCredentialStore.open(tmp_path)
        assert second.use_secret("alice", "jira", lambda v: v) == "tok"


class TestLoad:
    def test_missing_store_file_returns_empty(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        assert store.list_providers_for_user("anyone") == {}

    def test_corrupted_store_raises_unavailable(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        (tmp_path / "user_credentials.enc").write_bytes(b"not-a-valid-fernet-token")
        with pytest.raises(CredentialStoreUnavailable):
            store.list_providers_for_user("alice")

    def test_decrypted_non_dict_payload_raises_unavailable(self, tmp_path) -> None:
        key = Fernet.generate_key()
        (tmp_path / "credential_master.key").write_bytes(key)
        fernet = Fernet(key)
        (tmp_path / "user_credentials.enc").write_bytes(fernet.encrypt(json.dumps([1, 2]).encode()))

        store = UserCredentialStore(tmp_path)
        with pytest.raises(CredentialStoreUnavailable):
            store.list_providers_for_user("alice")

    def test_non_dict_user_entries_are_skipped(self, tmp_path) -> None:
        key = Fernet.generate_key()
        (tmp_path / "credential_master.key").write_bytes(key)
        fernet = Fernet(key)
        payload = json.dumps({"alice": {"jira": "tok"}, "bob": "not-a-dict"}).encode()
        (tmp_path / "user_credentials.enc").write_bytes(fernet.encrypt(payload))

        store = UserCredentialStore(tmp_path)
        assert store.has_secret("alice", "jira") is True
        assert store.list_providers_for_user("bob") == {}


class TestSetSecret:
    def test_empty_secret_raises(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        with pytest.raises(ValueError, match="empty"):
            store.set_secret("alice", "jira", "   ")


class TestListProvidersForUser:
    def test_lists_configured_providers_without_values(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        store.set_secret("alice", "jira", "tok")
        result = store.list_providers_for_user("alice")
        assert "jira" in result
        assert result["jira"]["configured"] is True
        assert "tok" not in json.dumps(result)


class TestDeleteSecret:
    def test_deletes_existing_secret_and_removes_empty_bucket(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        store.set_secret("alice", "jira", "tok")
        assert store.delete_secret("alice", "jira") is True
        assert store.has_secret("alice", "jira") is False
        assert store.list_providers_for_user("alice") == {}

    def test_deletes_one_of_several_keeps_bucket(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        store.set_secret("alice", "jira", "tok1")
        store.set_secret("alice", "github", "tok2")
        assert store.delete_secret("alice", "jira") is True
        assert store.has_secret("alice", "github") is True

    def test_deleting_missing_secret_returns_false(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        assert store.delete_secret("alice", "jira") is False


class TestHasSecret:
    def test_false_for_unknown_user(self, tmp_path) -> None:
        store = UserCredentialStore.open(tmp_path)
        assert store.has_secret("nobody", "jira") is False
