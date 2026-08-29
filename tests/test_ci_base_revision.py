from __future__ import annotations

import json

import pytest

from scripts.ci_base_revision import (
    BaseRevisionError,
    resolve_base_revision,
    resolve_base_revision_from_env,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def test_pull_request_resolves_exact_base_sha() -> None:
    payload = {"pull_request": {"base": {"sha": SHA_A}}}

    assert resolve_base_revision("pull_request", payload) == SHA_A


def test_merge_group_resolves_exact_base_sha() -> None:
    payload = {"merge_group": {"base_sha": SHA_B}}

    assert resolve_base_revision("merge_group", payload) == SHA_B


def test_push_resolves_before_sha() -> None:
    assert resolve_base_revision("push", {"before": SHA_A}) == SHA_A


def test_pull_request_does_not_fall_back_to_merge_group_base() -> None:
    payload = {"merge_group": {"base_sha": SHA_B}, "pull_request": {"base": {}}}

    with pytest.raises(BaseRevisionError, match="pull_request.base.sha"):
        resolve_base_revision("pull_request", payload)


def test_null_push_sha_is_not_a_base_revision() -> None:
    with pytest.raises(BaseRevisionError, match="null SHA"):
        resolve_base_revision("push", {"before": "0" * 40})


def test_malformed_sha_fails_closed() -> None:
    with pytest.raises(BaseRevisionError, match="valid commit SHA"):
        resolve_base_revision("merge_group", {"merge_group": {"base_sha": "not-a-sha"}})


def test_unsupported_event_fails_closed() -> None:
    with pytest.raises(BaseRevisionError, match="no defined base-revision contract"):
        resolve_base_revision("workflow_dispatch", {})


def test_environment_resolver_reads_the_github_event_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"merge_group": {"base_sha": SHA_B}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))

    assert resolve_base_revision_from_env() == SHA_B
