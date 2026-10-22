"""A PR keyword may not close what acceptance evidence cannot (#56, #1141).

#56 was an epic closed by a ``Closes`` keyword on a PR that delivered one
slice of it. #76 was closed completed by a keyword while its own acceptance
record still had every box unticked -- a locally green diff that registers one
sandbox backend proves nothing about the canonical-authority criteria. These
tests pin the keyword parsing, the structural refusals (epic tags, open
direct children), and the acceptance-record refusal, with the GitHub lookup
monkeypatched so nothing touches the network.
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
    """Fake issue table: number -> (title, state, body, open_sub_issues)."""
    table: dict[int, tuple[str, str, str, bool]] = {}

    def fake_fetch(repo: str, number: int, token: str):
        assert repo == REPO
        assert token == "test-token"
        title, state, body, open_subs = table[number]
        return gate.Target(
            number=number,
            title=title,
            state=state,
            body=body,
            has_open_sub_issues=open_subs,
        )

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


# --- acceptance-record parsing --------------------------------------------------


def test_checkbox_items_under_acceptance_heading_are_registered(gate) -> None:
    body = (
        "## Acceptance\n"
        "- [ ] one real backend is registered\n"
        "- [x] the policy matrix names each tier\n"
        "\n"
        "## Stop condition\n"
        "- [ ] this box is outside the record\n"
    )
    criteria = gate.acceptance_criteria(body)
    assert [(c.index, c.ticked) for c in criteria] == [(1, False), (2, True)]
    assert criteria[0].text == "one real backend is registered"


def test_acceptance_heading_variants_open_the_record(gate) -> None:
    for heading in ("## Acceptance", "## acceptance criteria", "### Acceptance", "Acceptance:"):
        body = f"{heading}\n- [x] only box\n"
        assert [c.index for c in gate.acceptance_criteria(body)] == [1], heading


def test_non_acceptance_headings_open_no_record(gate) -> None:
    # A heading that merely contains the word must not open the record:
    # unchecked boxes under "## Non-acceptance criteria" are out-of-scope
    # tasks, not unproven acceptance evidence that would block closure
    # (review: exclude non-acceptance headings).
    for heading in ("## Non-acceptance criteria", "## Non-acceptance", "## Scope note"):
        body = f"{heading}\n- [ ] an out-of-scope box\n"
        assert gate.acceptance_criteria(body) == [], heading


def test_bare_section_label_closes_the_record(gate) -> None:
    # A bare "Acceptance:" opens the record, so the bare "Tasks:" that
    # follows must end it: an unchecked task there is not an acceptance
    # criterion and must not block closure (review: bare section boundaries).
    body = "Acceptance:\n- [x] one real backend is registered\n\nTasks:\n- [ ] wire the runbook\n"
    criteria = gate.acceptance_criteria(body)
    assert [(c.index, c.ticked) for c in criteria] == [(1, True)]


def test_prose_line_ending_in_a_colon_does_not_close_the_record(gate) -> None:
    body = "Acceptance:\nplan: register backends in one pass\n- [ ] real box\n"
    assert [c.ticked for c in gate.acceptance_criteria(body)] == [False]


def test_prose_bullets_under_acceptance_register_nothing(gate) -> None:
    # #62 carries prose acceptance bullets ("Acceptance:"), not a checkbox
    # record; they are intent, not a machine-checkable closeout record.
    body = "Acceptance:\n- process restart can recover supported work;\n- timed waits wake;\n"
    assert gate.acceptance_criteria(body) == []


def test_boxes_before_an_acceptance_heading_are_not_criteria(gate) -> None:
    body = "- [ ] a task list up top\n\n## Acceptance\n- [x] the real one\n"
    assert [c.ticked for c in gate.acceptance_criteria(body)] == [True]


def test_every_gfm_task_list_marker_form_registers(gate) -> None:
    # GFM task lists allow ``+`` and ``*`` bullets and ordered ``1.``/``1)``
    # markers, and items nest to any depth (review: every valid marker). An
    # issue using any of these must still register its criteria.
    body = (
        "## Acceptance\n"
        "1. [ ] required proof\n"
        "    + [ ] nested plus bullet\n"
        "\t2) [x] ordered paren marker\n"
        "* [X] starred and ticked\n"
        "+ [ ] top-level plus bullet\n"
    )
    criteria = gate.acceptance_criteria(body)
    assert [(c.index, c.ticked) for c in criteria] == [
        (1, False),
        (2, False),
        (3, True),
        (4, True),
        (5, False),
    ]


# --- claimed criteria -----------------------------------------------------------


def test_claim_on_a_closing_line_is_harvested(gate) -> None:
    claims = gate.claimed_criteria("Closes #76 AC-2\nfixes #56 (AC-3)", [76, 56])
    assert claims == {76: {2}, 56: {3}}


def test_claim_in_ac_first_order_is_harvested(gate) -> None:
    assert gate.claimed_criteria("Resolves #76 — proves AC-4", [76]) == {76: {4}}


def test_progress_language_is_not_a_claim(gate) -> None:
    # Non-closing language must stay usable for slices (#1141 AC-6): a line
    # that closes nothing claims nothing, whatever AC ids it mentions.
    body = "Part of #76 AC-2 still failing. Refs #56 AC-1."
    assert gate.claimed_criteria(body, [76, 56]) == {}


# --- the refusals ---------------------------------------------------------------


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
    issues[56] = (f"{prefix} Workspace cutover", "open", "", False)
    assert _run(gate, tmp_path, "Closes #56") == 1
    assert "#56 is tagged" in capsys.readouterr().out


@pytest.mark.parametrize(
    "title",
    ["Fix the epic parser", "[BUG] epic flag ignored", "M1-D2 — one governed egress"],
)
def test_epic_word_outside_the_leading_tag_is_not_an_epic(gate, title) -> None:
    target = gate.Target(number=1, title=title, state="open", body="", has_open_sub_issues=False)
    assert gate.problems_for(target) == []


def test_issue_with_open_children_is_refused(gate, issues, tmp_path, capsys) -> None:
    issues[53] = ("P0 contract", "open", "", True)
    assert _run(gate, tmp_path, "Fixes #53") == 1
    assert "#53 has open direct children" in capsys.readouterr().out


def test_children_all_closed_do_not_block_structurally(gate, issues, tmp_path) -> None:
    # #1141 AC-2 blocks on *open* direct children only: a parent whose
    # children are all merged is not held by the structure rule (its
    # acceptance record, if any, is judged on its own).
    issues[20] = ("parent, children merged", "open", "", False)
    assert _run(gate, tmp_path, "Closes #20") == 0


def test_one_epic_among_ordinary_targets_still_fails(gate, issues, tmp_path) -> None:
    issues[10] = ("fix a typo", "open", "", False)
    issues[56] = ("[EPIC] cutover", "open", "", False)
    assert _run(gate, tmp_path, "Closes #10\nCloses #56") == 1


# --- fixtures: the confirmed false closes ---------------------------------------


def _m1d2_body() -> str:
    # #56's shape: no bracketed tag, no checkbox record, open closeout child.
    return (
        "Parent epic: #15\n\n"
        "## Fix order / direct closeout children\n\n"
        "- **#1079** — repair production composition\n"
        "- [ ] **#1084** — retire raw egress in adapters.llm_http\n"
    )


def test_fixture_56_untagged_parent_with_open_child_is_refused(
    gate, issues, tmp_path, capsys
) -> None:
    issues[56] = ("M1-D2 — Establish one governed model/harness egress", "open", _m1d2_body(), True)
    assert _run(gate, tmp_path, "Closes #56") == 1
    out = capsys.readouterr().out
    assert "#56 has open direct children" in out


def test_fixture_62_recovery_parent_with_open_children_is_refused(
    gate, issues, tmp_path, capsys
) -> None:
    # #62's acceptance is prose, so nothing registers — the open children
    # (#1151/#1192) are what the keyword may not outrun.
    issues[62] = (
        "M1-E2 — Converge checkpoints/crash recovery onto Run/NodeRun/Attempt",
        "open",
        "Acceptance:\n- every parked/resumable reason has a named reachable production waker\n",
        True,
    )
    assert _run(gate, tmp_path, "Resolves #62") == 1
    out = capsys.readouterr().out
    assert "#62 has open direct children" in out
    assert "#62's acceptance record shows" not in out


def test_fixture_465_audit_parent_with_open_child_is_refused(gate, issues, tmp_path) -> None:
    issues[465] = (
        "M1 — Audit every shipped surface for truthful canonical execution claims",
        "open",
        "## Direct child\n- #1144 Make shipped-surface discovery cover non-literal routes\n",
        True,
    )
    assert _run(gate, tmp_path, "Fixes #465") == 1


# --- the #76 fixture: unproven acceptance record --------------------------------


def _m2b1_acceptance() -> str:
    # #76's record as it stood when PR #583 closed it: every box unticked,
    # each demanding the canonical authority rather than "a backend exists".
    return (
        "## Acceptance\n"
        "- [ ] At least one real backend satisfying the selected standard "
        "production policy tier is registered by the canonical selector and "
        "launches real workloads\n"
        "- [ ] UNTRUSTED_CODE, BENCHMARK_EVAL, TRUSTED_TOOL, and "
        "BROWSER_AUTOMATION each have an explicit disposition\n"
        "- [ ] Every retained production code-execution path routes through "
        "SandboxProtocol/selector policy or an explicitly equivalent adapter\n"
        "- [ ] The support matrix names the exact backend/tier; unsupported "
        "hardware fails closed\n"
        "- [ ] Egress/network semantics have one authoritative field/policy\n"
        "- [ ] Backend lifecycle and host-process construction are safe in the "
        "async/threaded runtime\n"
        "- [ ] #77/#78/#79/#80 conformance applies to the same production "
        "backend(s)\n"
        "- [ ] Workspace/Agent/RSI/Turing/Builders code execution consumes "
        "this substrate\n"
        "- [ ] A reachability/convergence test fails if a consumer again "
        "constructs a direct sandbox implementation\n"
    )


def test_fixture_76_leaf_with_unticked_record_is_refused_despite_local_green(
    gate, issues, tmp_path, capsys
) -> None:
    # The false-complete shape (#1141 AC-8): the PR registers *one* sandbox
    # backend and its suite is green, while the record still demands that the
    # canonical runtime be the production authority with no bypasses. None of
    # that local green is an input here — the record alone refuses closure.
    issues[76] = (
        "M2-B1 — Ship a real supported unattended-isolation backend",
        "open",
        _m2b1_acceptance(),
        False,
    )
    pr_body = (
        "Fixes #76 — bubblewrap is now registered in build_selector(), so one "
        "sandbox backend exists and the unit suite is green.\n"
    )
    assert _run(gate, tmp_path, pr_body) == 1
    out = capsys.readouterr().out
    assert "#76's acceptance record shows 9 of 9 registered criteria unproven" in out
    assert "a locally green diff does not discharge them" in out


def test_fixture_76_rejects_a_claim_on_a_specific_unproven_line(
    gate, issues, tmp_path, capsys
) -> None:
    issues[76] = (
        "M2-B1 — Ship a real supported unattended-isolation backend",
        "open",
        _m2b1_acceptance(),
        False,
    )
    assert _run(gate, tmp_path, "Closes #76 AC-3") == 1
    out = capsys.readouterr().out
    assert "claims AC-3 of #76" in out
    assert "does not show it proven" in out


def test_claim_of_an_unregistered_criterion_is_rejected(gate, issues, tmp_path, capsys) -> None:
    issues[76] = (
        "M2-B1 — Ship a real supported unattended-isolation backend",
        "open",
        "## Acceptance\n- [x] the only registered criterion\n",
        False,
    )
    assert _run(gate, tmp_path, "Closes #76 AC-9") == 1
    assert "does not register" in capsys.readouterr().out


def test_ticking_every_box_makes_the_leaf_closeable_again(gate, issues, tmp_path, capsys) -> None:
    # #1141 AC-9: once the record shows every criterion proven — as it must
    # before #76 can really close — the keyword is useful again.
    issues[76] = (
        "M2-B1 — Ship a real supported unattended-isolation backend",
        "open",
        "## Acceptance\n- [x] every criterion now proven\n- [X] including this one\n",
        False,
    )
    assert _run(gate, tmp_path, "Closes #76") == 0
    assert "acceptance records are met" in capsys.readouterr().out


def test_claim_against_an_empty_record_is_still_rejected(gate, issues, tmp_path, capsys) -> None:
    # The claims check must not hinge on the record being non-empty: a closing
    # line that names AC-1 on an issue whose body registers nothing claims an
    # id no record supports, and the gate must reject it by name.
    issues[10] = ("Route table drops trailing slash", "open", "just prose", False)
    assert _run(gate, tmp_path, "Closes #10 AC-1") == 1
    assert "claims AC-1 of #10, which the acceptance record does not register" in (
        capsys.readouterr().out
    )


def test_issue_without_a_record_is_not_held_by_the_acceptance_rule(gate, issues, tmp_path) -> None:
    issues[10] = ("Route table drops trailing slash", "open", "just prose", False)
    assert _run(gate, tmp_path, "Closes #10") == 0


def test_structural_and_acceptance_problems_report_together(gate, issues, tmp_path) -> None:
    body = "## Acceptance\n- [ ] unproven\n"
    target = gate.Target(
        number=80,
        title="[EPIC] sandbox",
        state="open",
        body=body,
        has_open_sub_issues=True,
    )
    problems = gate.problems_for(target, {1})
    assert any("tagged EPIC" in p for p in problems)
    assert any("open direct children" in p for p in problems)
    assert any("unproven" in p for p in problems)
    assert any("claims AC-1" in p for p in problems)


# --- already-closed targets -----------------------------------------------------


def test_already_closed_target_is_skipped_not_refused(gate, issues, tmp_path, capsys) -> None:
    # A keyword cannot transition a closed issue, so there is nothing to
    # vouch for; the closed epic in the body neither passes nor fails here.
    issues[56] = ("[EPIC] cutover", "closed", "## Acceptance\n- [ ] unticked\n", True)
    issues[10] = ("ordinary", "open", "", False)
    assert _run(gate, tmp_path, "Closes #56\nCloses #10") == 0
    out = capsys.readouterr().out
    assert "already closed" in out


# --- ordinary and failure paths -------------------------------------------------


def test_ordinary_issue_is_allowed(gate, issues, tmp_path, capsys) -> None:
    issues[10] = ("Route table drops trailing slash", "open", "", False)
    assert _run(gate, tmp_path, "Closes #10") == 0
    assert "ok:" in capsys.readouterr().out


def test_body_without_keywords_needs_no_token(gate, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert _run(gate, tmp_path, "Part of #56") == 0


def test_missing_token_with_a_target_fails_closed(gate, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert _run(gate, tmp_path, "Closes #10") == 1


def test_api_error_fails_closed(gate, issues, monkeypatch, tmp_path) -> None:
    issues[10] = ("ordinary", "open", "", False)

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
    issues[56] = ("[EPIC] cutover", "open", "", False)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"body": "closes #56"}}))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert gate.main([]) == 1


def test_pull_request_title_is_scanned_for_squash_merge_keywords(
    gate, issues, monkeypatch, tmp_path
) -> None:
    issues[56] = ("[EPIC] cutover", "open", "", False)
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


# --- the GitHub lookup ----------------------------------------------------------


def test_fetch_target_reads_state_body_and_open_children(gate, monkeypatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        if request.full_url.endswith("/issues/53"):
            payload = {
                "title": "P0 contract",
                "number": 53,
                "state": "open",
                "body": "## Acceptance\n- [ ] one box\n",
            }
        else:
            payload = [{"number": 99, "state": "closed"}, {"number": 100, "state": "open"}]
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    target = gate.fetch_target(REPO, 53, "test-token")
    assert target.title == "P0 contract"
    assert target.state == "open"
    assert "## Acceptance" in target.body
    assert target.has_open_sub_issues is True
    assert calls[0].endswith("/repos/Agent-StrongHold/Project-mAIstro/issues/53")
    assert calls[1].endswith("/sub_issues?per_page=100&page=1")


def test_fetch_target_paginates_until_all_children_are_closed(gate, monkeypatch) -> None:
    def fake_urlopen(request, timeout=30):
        if request.full_url.endswith("/issues/53"):
            return io.BytesIO(json.dumps({"title": "t", "state": "open", "body": ""}).encode())
        if request.full_url.endswith("page=1"):
            return io.BytesIO(json.dumps([{"state": "closed"}] * 100).encode())
        return io.BytesIO(json.dumps([]).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    target = gate.fetch_target(REPO, 53, "test-token")
    assert target.has_open_sub_issues is False


def test_fetch_target_treats_missing_sub_issues_endpoint_as_empty(gate, monkeypatch) -> None:
    def fake_urlopen(request, timeout=30):
        if request.full_url.endswith("/sub_issues?per_page=100&page=1"):
            raise HTTPError(request.full_url, 404, "missing", hdrs=None, fp=None)
        return io.BytesIO(json.dumps({"title": "ordinary issue", "state": "open"}).encode())

    monkeypatch.setattr(gate.urllib.request, "urlopen", fake_urlopen)
    target = gate.fetch_target(REPO, 10, "test-token")
    assert target.has_open_sub_issues is False


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
            "/sub_issues?per_page=100&page=1"
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


def test_fetch_target_defaults_a_missing_state_to_open(gate, monkeypatch) -> None:
    # Fail-safe: an issue payload without state is judged as open, never
    # silently skipped.
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        lambda request, timeout=30: (
            io.BytesIO(json.dumps([{"state": "closed"}]).encode())
            if "sub_issues" in request.full_url
            else io.BytesIO(json.dumps({"title": "t"}).encode())
        ),
    )
    target = gate.fetch_target(REPO, 10, "test-token")
    assert target.state == "open"
