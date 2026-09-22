"""Conformance tests for principal-scoped Airtable configuration consumers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import hive_conductor.stores as stores
from hive_conductor.routes import widgets
from hive_conductor.services import chat_completion
from hive_conductor.services import user_credentials as cred_svc


class _NonIterableConfig(dict[str, object]):
    """Catch regressions that enumerate the process-wide config store."""

    def __iter__(self) -> Any:
        raise AssertionError("provider config must be read by principal key")


class _CredentialStore:
    def __init__(self, secrets: dict[tuple[str, str], str]) -> None:
        self.secrets = secrets

    def has_secret(self, user_id: str, provider_id: str) -> bool:
        return (user_id, provider_id) in self.secrets

    def use_secret(self, user_id: str, provider_id: str, callback):  # type: ignore[no-untyped-def]
        return callback(self.secrets[(user_id, provider_id)])


def _request(user_id: str) -> Any:
    return SimpleNamespace(state=SimpleNamespace(user={"id": user_id}))


@pytest.fixture
def scoped_airtable(monkeypatch: pytest.MonkeyPatch) -> _NonIterableConfig:
    config = _NonIterableConfig()
    credentials = _CredentialStore(
        {
            ("alice", "airtable"): "alice-token",
            ("bob", "airtable"): "bob-token",
        }
    )
    monkeypatch.setattr(stores, "user_provider_config", config)
    monkeypatch.setattr(cred_svc, "get_credential_store", lambda: credentials)
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize("insertion_order", [("bob", "alice"), ("alice", "bob")])
async def test_chat_and_widgets_bind_base_to_authenticated_principal(
    monkeypatch: pytest.MonkeyPatch,
    scoped_airtable: _NonIterableConfig,
    insertion_order: tuple[str, str],
) -> None:
    """Two users never inherit a base from store insertion order."""
    for user_id in insertion_order:
        scoped_airtable[f"{user_id}:airtable"] = {
            "base_id": f"app-{user_id.upper()}/view",
            "name": f"{user_id.title()} Base",
        }

    record_calls: list[tuple[str, str]] = []

    async def records(**kwargs: Any) -> dict[str, Any]:
        record_calls.append((kwargs["token"], kwargs["base_id"]))
        return {"records": [{"id": "rec-1", "fields": {"Owner": kwargs["base_id"]}}]}

    async def tables(**kwargs: Any) -> dict[str, Any]:
        record_calls.append((kwargs["token"], kwargs["base_id"]))
        return {"tables": [{"id": "tbl-1", "name": kwargs["base_id"]}]}

    monkeypatch.setattr(widgets, "get_airtable_records_json", records)
    monkeypatch.setattr(widgets, "get_airtable_base_tables_json", tables)
    monkeypatch.setattr(chat_completion, "get_airtable_records_json", records)
    monkeypatch.setattr(chat_completion, "get_airtable_base_tables_json", tables)

    for user_id in ("alice", "bob"):
        request = _request(user_id)
        token, base_id = chat_completion._get_airtable_creds(user_id)
        assert (token, base_id) == (f"{user_id}-token", f"app-{user_id.upper()}")

        widget_result = await widgets.widget_airtable(request, table="T")
        assert widget_result["table_data"][0]["Owner"] == f"app-{user_id.upper()}"

        fields_result = await widgets.widget_airtable_fields(request, table="T")
        assert fields_result["fields"] == ["Owner"]

        # A client-selected base cannot bypass the principal's configured base.
        rejected_tables = await widgets.widget_airtable_tables(
            request, base_id=f"app-{('bob' if user_id == 'alice' else 'alice').upper()}"
        )
        assert rejected_tables["tables"] == []
        assert "not configured" in rejected_tables["error"]
        tables_result = await widgets.widget_airtable_tables(
            request, base_id=f"app-{user_id.upper()}"
        )
        assert tables_result == {
            "tables": [{"id": "tbl-1", "name": f"app-{user_id.upper()}"}],
            "base_id": f"app-{user_id.upper()}",
        }

        bases_result = await widgets.widget_airtable_bases(request)
        assert bases_result["bases"] == [
            {"id": f"app-{user_id.upper()}", "name": f"{user_id.title()} Base"}
        ]

        query_result = await chat_completion._tool_airtable_query(
            {"table_name": "T"}, user_id=user_id, jira_pat=None
        )
        assert query_result["records"][0]["Owner"] == f"app-{user_id.upper()}"

        describe_result = await chat_completion._tool_airtable_describe(
            {}, user_id=user_id, jira_pat=None
        )
        assert describe_result["base_id"] == f"app-{user_id.upper()}"

    assert record_calls == [
        ("alice-token", "app-ALICE"),
        ("alice-token", "app-ALICE"),
        ("alice-token", "app-ALICE"),
        ("alice-token", "app-ALICE"),
        ("alice-token", "app-ALICE"),
        ("bob-token", "app-BOB"),
        ("bob-token", "app-BOB"),
        ("bob-token", "app-BOB"),
        ("bob-token", "app-BOB"),
        ("bob-token", "app-BOB"),
    ]


@pytest.mark.asyncio
async def test_bases_without_selection_use_only_current_token_metadata(
    monkeypatch: pytest.MonkeyPatch,
    scoped_airtable: _NonIterableConfig,
) -> None:
    scoped_airtable["alice:airtable"] = {"base_id": "app-ALICE"}

    async def metadata(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["token"] == "bob-token"
        return {"bases": [{"id": "app-BOB-METADATA", "name": "Bob Metadata"}]}

    monkeypatch.setattr(widgets, "get_airtable_bases_json", metadata)
    bob_request = _request("bob")
    result = await widgets.widget_airtable_bases(bob_request)
    tables = await widgets.widget_airtable_tables(bob_request, base_id="app-BOB-METADATA")
    records = await widgets.widget_airtable(bob_request, table="T")
    fields = await widgets.widget_airtable_fields(bob_request, table="T")
    query = await chat_completion._tool_airtable_query(
        {"table_name": "T"}, user_id="bob", jira_pat=None
    )
    describe = await chat_completion._tool_airtable_describe({}, user_id="bob", jira_pat=None)

    assert result == {"bases": [{"id": "app-BOB-METADATA", "name": "Bob Metadata"}]}
    assert tables["tables"] == []
    assert tables["error"] == "No base_id configured."
    assert records == {"error": "No base_id configured.", "records": []}
    assert fields == {"fields": []}
    assert query == {"error": "Airtable base_id not configured. Set it in Credentials → Airtable."}
    assert describe == {"error": "Airtable base_id not configured."}


@pytest.mark.parametrize("multi_user", [True, False])
def test_legacy_airtable_env_is_explicitly_single_user_only(
    monkeypatch: pytest.MonkeyPatch,
    multi_user: bool,
) -> None:
    monkeypatch.setenv("AIRTABLE_SINGLE_USER_MODE", "true")
    monkeypatch.setenv("AIRTABLE_TOKEN", "legacy-token")
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app-LEGACY")
    principals = {"alice": object(), "bob": object()} if multi_user else {"alice": object()}
    monkeypatch.setattr(stores, "users", principals)

    assert chat_completion._get_airtable_creds("alice") == (
        (None, None) if multi_user else ("legacy-token", "app-LEGACY")
    )


def test_legacy_airtable_env_fails_closed_if_principal_store_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIRTABLE_SINGLE_USER_MODE", "true")

    class BrokenUsers:
        def keys(self) -> object:
            raise RuntimeError("principal store unavailable")

    monkeypatch.setattr(stores, "users", BrokenUsers())

    assert chat_completion._single_user_airtable_env_enabled("alice") is False
