from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.ci_base_revision import (
    BaseRevisionError,
    load_event_payload,
    main,
    resolve_base_revision,
    resolve_base_revision_from_env,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def test_pull_request_resolves_exact_base_sha() -> None:
    assert (
        resolve_base_revision("pull_request", {"pull_request": {"base": {"sha": SHA_A}}})
        == SHA_A
    )


def test_merge_group_resolves_exact_base_sha() -> None:
    assert (
        resolve_base_revision("merge_group", {"merge_group": {"base_sha": SHA_B}})
        == SHA_B
    )


def test_push_resolves_before_sha() -> None:
    assert resolve_base_revision("push", {"before": SHA_A}) == SHA_A


def test_pull_request_does_not_fall_back_to_merge_group_base() -> None:
    with pytest.raises(BaseRevisionError, match=r"pull_request\.base\.sha"):
        resolve_base_revision(
            "pull_request",
            {"merge_group": {"base_sha": SHA_B}, "pull_request": {"base": {}}},
        )


def test_missing_pull_request_object_fails_closed() -> None:
    with pytest.raises(
        BaseRevisionError, match=r"pull_request.*missing or is not an object"
    ):
        resolve_base_revision("pull_request", {})


def test_non_object_pull_request_base_fails_closed() -> None:
    with pytest.raises(
        BaseRevisionError, match=r"pull_request.base.*missing or is not an object"
    ):
        resolve_base_revision("pull_request", {"pull_request": {"base": "develop"}})


def test_non_string_sha_fails_closed() -> None:
    with pytest.raises(BaseRevisionError, match="missing or is not a SHA"):
        resolve_base_revision("push", {"before": 123})


def test_uppercase_sha_is_normalized() -> None:
    assert resolve_base_revision("push", {"before": "A" * 40}) == SHA_A


def test_null_push_sha_is_not_a_base_revision() -> None:
    with pytest.raises(BaseRevisionError, match="null SHA"):
        resolve_base_revision("push", {"before": "0" * 40})


def test_malformed_sha_fails_closed() -> None:
    with pytest.raises(BaseRevisionError, match="valid commit SHA"):
        resolve_base_revision(
            "merge_group", {"merge_group": {"base_sha": "not-a-sha"}}
        )


def test_unsupported_event_fails_closed() -> None:
    with pytest.raises(BaseRevisionError, match="no defined base-revision contract"):
        resolve_base_revision("workflow_dispatch", {})


def test_event_payload_must_exist(tmp_path: Path) -> None:
    with pytest.raises(BaseRevisionError, match="could not read GitHub event payload"):
        load_event_payload(tmp_path / "missing.json")


def test_event_payload_must_be_valid_json(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text("{", encoding="utf-8")
    with pytest.raises(BaseRevisionError, match="is not valid JSON"):
        load_event_payload(event)


def test_event_payload_root_must_be_an_object(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text("[]", encoding="utf-8")
    with pytest.raises(BaseRevisionError, match="is not a JSON object"):
        load_event_payload(event)


def test_environment_resolver_reads_the_github_event_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"merge_group": {"base_sha": SHA_B}}), encoding="utf-8"
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert resolve_base_revision_from_env() == SHA_B


def test_environment_resolver_requires_event_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "event.json"))
    with pytest.raises(BaseRevisionError, match="GITHUB_EVENT_NAME is not set"):
        resolve_base_revision_from_env()


def test_environment_resolver_requires_event_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(BaseRevisionError, match="GITHUB_EVENT_PATH is not set"):
        resolve_base_revision_from_env()


def test_cli_main_prints_resolved_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": SHA_A}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert main() == 0
    assert capsys.readouterr().out.strip() == SHA_A


def test_cli_main_reports_fail_closed_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert main() == 2
    assert "FAIL: GITHUB_EVENT_NAME is not set" in capsys.readouterr().err
