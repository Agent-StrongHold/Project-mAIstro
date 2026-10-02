"""A PR may not close an epic by keyword (#56, Workspace Cutover S0.2).

#56 was an epic closed by a ``Closes`` keyword on a PR that delivered one
slice of it. These pin the keyword parsing and the refusal, with the GitHub
lookup monkeypatched so nothing touches the network.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-closure-targets.py"
REPO = "Agent-StrongHold/Project-mAIstro"


def _gate():
    spec = importlib.util.spec_from_file_location("check_closure_targets", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _gate()


@pytest.fixture
def issues(gate, monkeypatch):
    """Fake issue table: number -> (title, has_sub_issues)."""
    table: dict[int, tuple[str, bool]] = {}

    def fake_fetch(repo: str, number: int, token: str):
        assert repo == REPO
        assert token == "test-token"
        title, has_subs = table[number]
        return gate.Target(number=number, title=title, has_sub_issues=has_subs)

    monkeypatch.setattr(gate, "fetch_target", fake_fetch)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    return table


def _run(gate, tmp_path: Path, body: str) -> int:
    path = tmp_path / "body.md"
    path.write_text(body)
    return gate.main(["--body-file", str(path)])


# --- keyword parsing -----------------------------------------------------------


def test_every_closing_keyword_form_is_recognised(gate) -> None:
    body = (
        "close #1, closes #2, Closed #3\n"
        "FIX #4 fixes #5 fixed #6\n"
        "resolve #7 Resolves: #8 resolved #9"
    )
    assert gate.closing_targets(body, REPO) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_reference_without_a_closing_keyword_is_not_a_target(gate) -> None:
    assert gate.closing_targets("Part of #53. Refs #56. See #12.", REPO) == []


def test_keyword_must_be_a_whole_word(gate) -> None:
    assert gate.closing_targets("encloses #4 and prefixes #5", REPO) == []


def test_duplicates_collapse_in_first_seen_order(gate) -> None:
    assert gate.closing_targets("Fixes #9\nCloses #3\nResolves #9", REPO) == [9, 3]


def test_cross_repo_reference_is_ignored_unless_it_names_this_repo(gate) -> None:
    body = "Closes other-org/other-repo#7\nFixes agent-stronghold/project-maistro#8"
    assert gate.closing_targets(body, REPO) == [8]


def test_full_url_closing_reference_is_recognised_for_this_repo(gate) -> None:
    body = f"Closes https://github.com/{REPO}/issues/56"
    assert gate.closing_targets(body, REPO) == [56]


def test_full_url_closing_reference_for_another_repo_is_ignored(gate) -> None:
    body = "Fixes https://github.com/other-org/other-repo/issues/56"
    assert gate.closing_targets(body, REPO) == []


def test_code_fenced_keyword_still_counts(gate) -> None:
    assert gate.closing_targets("```\nCloses #11\n```", REPO) == [11]


# --- the refusal ---------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    [
        "[EPIC]",
        "[MILESTONE]",
        "[INITIATIVE]",
        "[epic]",
        # The shapes this repository's epics actually carry.
        "[EPIC M1-B]",
        "[MILESTONE M4]",
        "[MASTER INITIATIVE]",
    ],
)
def test_epic_title_is_refused(gate, issues, tmp_path, capsys, prefix) -> None:
    issues[56] = (f"{prefix} Workspace cutover", False)
    assert _run(gate, tmp_path, "Closes #56") == 1
    assert "#56 is tagged" in capsys.readouterr().out


@pytest.mark.parametrize(
    "title",
    ["Fix the epic parser", "[BUG] epic flag ignored", "M1-D2 — one governed egress"],
)
def test_epic_word_outside_the_leading_tag_is_not_an_epic(gate, title) -> None:
    assert gate.problems_for(gate.Target(number=1, title=title, has_sub_issues=False)) == []


def test_issue_with_sub_issues_is_refused(gate, issues, tmp_path, capsys) -> None:
    issues[53] = ("P0 contract", True)
    assert _run(gate, tmp_path, "Fixes #53") == 1
    assert "#53 has sub-issues" in capsys.readouterr().out


def test_one_epic_among_ordinary_targets_still_fails(gate, issues, tmp_path) -> None:
    issues[10] = ("fix a typo", False)
    issues[56] = ("[EPIC] cutover", False)
    assert _run(gate, tmp_path, "Closes #10\nCloses #56") == 1


def test_ordinary_issue_is_allowed(gate, issues, tmp_path, capsys) -> None:
    issues[10] = ("Route table drops trailing slash", False)
    assert _run(gate, tmp_path, "Closes #10") == 0
    assert "ok:" in capsys.readouterr().out


def test_body_without_keywords_needs_no_token(gate, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert _run(gate, tmp_path, "Part of #56") == 0


# --- fail closed ---------------------------------------------------------------


def test_missing_token_with_a_target_fails_closed(gate, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert _run(gate, tmp_path, "Closes #10") == 1


def test_api_error_fails_closed(gate, issues, monkeypatch, tmp_path) -> None:
    def broken(repo: str, number: int, token: str):
        raise gate.GitHubError("HTTP 502")

    monkeypatch.setattr(gate, "fetch_target", broken)
    assert _run(gate, tmp_path, "Closes #10") == 1


# --- event handling ------------------------------------------------------------


@pytest.mark.parametrize("event_name", ["push", "merge_group", ""])
def test_non_pull_request_event_skips(gate, monkeypatch, tmp_path, capsys, event_name) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": "Closes #56"}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert gate.main([]) == 0
    assert "skip:" in capsys.readouterr().out


def test_pull_request_event_body_is_judged(gate, issues, monkeypatch, tmp_path) -> None:
    issues[56] = ("[EPIC] cutover", False)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": "closes #56"}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert gate.main([]) == 1


def test_pull_request_title_is_scanned_for_squash_merge_keywords(
    gate, issues, monkeypatch, tmp_path
) -> None:
    issues[56] = ("[EPIC] cutover", False)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"title": "Fixes #56", "body": "Part of #56."}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert gate.main([]) == 1


def test_pull_request_with_empty_body_passes(gate, issues, monkeypatch, tmp_path) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": None}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert gate.main([]) == 0


def test_pull_request_event_without_a_pull_request_object_skips(
    gate, monkeypatch, tmp_path, capsys
) -> None:
    event = tmp_path / "event.json"
    event.write_text("{}")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert gate.main([]) == 0
    assert "skip:" in capsys.readouterr().out


def test_missing_repository_argument_fails(gate, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert _run(gate, tmp_path, "Closes #10") == 1


def test_fetch_target_reads_title_and_sub_issues(gate, monkeypatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        payload = (
            {"title": "P0 contract", "number": 53}
            if request.full_url.endswith("/issues/53")
            else [{"number": 99}]
        )
        body = json.dumps(payload).encode()
        return io.BytesIO(body)

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    target = gate.fetch_target(REPO, 53, "test-token")
    assert target == gate.Target(number=53, title="P0 contract", has_sub_issues=True)
    assert calls[0].endswith("/repos/Agent-StrongHold/Project-mAIstro/issues/53")
    assert calls[1].endswith("/sub_issues?per_page=1")


def test_fetch_target_treats_missing_sub_issues_endpoint_as_empty(gate, monkeypatch) -> None:
    def fake_urlopen(request, timeout=30):
        if request.full_url.endswith("/sub_issues?per_page=1"):
            raise HTTPError(request.full_url, 404, "missing", hdrs=None, fp=None)
        return io.BytesIO(json.dumps({"title": "ordinary issue"}).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    target = gate.fetch_target(REPO, 10, "test-token")
    assert target == gate.Target(number=10, title="ordinary issue", has_sub_issues=False)


@pytest.mark.parametrize(
    "side_effect",
    [
        URLError("network down"),
        json.JSONDecodeError("bad json", "{}", 0),
        HTTPError("https://api.github.com/x", 500, "boom", hdrs=None, fp=None),
    ],
)
def test_fetch_target_network_and_shape_errors_raise(gate, monkeypatch, side_effect) -> None:
    def fake_urlopen(request, timeout=30):
        if isinstance(side_effect, HTTPError) and request.full_url.endswith(
            "/sub_issues?per_page=1"
        ):
            raise side_effect
        if isinstance(side_effect, HTTPError):
            raise side_effect
        raise side_effect

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(gate.GitHubError):
        gate.fetch_target(REPO, 10, "test-token")


def test_fetch_target_rejects_a_non_object_issue_payload(gate, monkeypatch) -> None:
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        lambda request, timeout=30: io.BytesIO(json.dumps([]).encode()),
    )
    with pytest.raises(gate.GitHubError, match="unexpected response shape"):
        gate.fetch_target(REPO, 10, "test-token")
