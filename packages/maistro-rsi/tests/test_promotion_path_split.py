"""#110 / M4-A3: the split between the mechanical non-judgment promotion path
and the judgment (escalation) path.

The common safe path — quarantine-clean surface, protected correctness gates
and mechanical ratchets green, decisive evidence — must proceed with NO judge
at all (no RLPHD prediction, no revert, no human). Only sensitive/ambiguous
promotions escalate to the review inbox, where approve/reject/revise/resume
behave deterministically and every decision persists its policy/evidence
snapshot, linked into the promotion record.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.local_loop import CycleOutcome, LocalRsiConfig, LocalRsiLoop, LocalRsiResult, _git
from maistro_rsi.promotion_review import (
    MECHANICAL_COMPOSITE_FLOOR,
    PendingReview,
    PromotionRecord,
    classify_promotion,
    flag_for_review,
    load_pending_reviews,
    load_promotion_record,
    normalize_decision,
    resolve_review,
    write_promotion_record,
)
from maistro_rsi.sensitive_paths import matches_sensitive_pattern
from maistro_rsi.trace_notes import RewardVector, TraceNote, write_trace_note

# ── classification: which path, and fail-closed ─────────────────────────────


def test_mechanical_when_quarantine_clean_gates_green_and_decisive() -> None:
    c = classify_promotion(
        touched_paths=["README.md", "docs/guide.md"],
        judge_score=0.95,
        composite=0.9,
    )
    assert c.review_path == "mechanical"
    assert c.sensitive_paths == ()


def test_sensitive_surface_takes_the_judgment_path_even_when_decisive() -> None:
    touched = ["src/maistro_rsi/local_loop.py"]
    c = classify_promotion(touched_paths=touched, judge_score=0.95, composite=0.95)
    assert c.review_path == "judgment"
    assert c.sensitive_paths == ("src/maistro_rsi/local_loop.py",)
    # the SAME matcher the quarantine gate escalates on — one policy, not two
    assert [p for p in touched if matches_sensitive_pattern(p)] == list(c.sensitive_paths)


def test_governance_override_takes_the_judgment_path() -> None:
    c = classify_promotion(
        touched_paths=["app.py"],
        judge_score=0.95,
        composite=0.95,
        governance_override=True,
    )
    assert c.review_path == "judgment"
    assert "override" in c.reason


def test_weak_composite_is_ambiguous_and_escalates() -> None:
    c = classify_promotion(touched_paths=["app.py"], judge_score=0.5, composite=0.5)
    assert c.review_path == "judgment"
    assert "weak_mechanical_evidence" in c.reason
    # the floor is the system's existing "confident enough to act without a
    # human" bar (RLPHD's cold-start theta)
    assert MECHANICAL_COMPOSITE_FLOOR == 0.7
    assert (
        classify_promotion(
            touched_paths=["app.py"], judge_score=0.5, composite=MECHANICAL_COMPOSITE_FLOOR
        ).review_path
        == "mechanical"
    )


def test_undeterminable_touch_surface_fails_closed_to_judgment() -> None:
    c = classify_promotion(touched_paths=[], judge_score=0.95, composite=0.95)
    assert c.review_path == "judgment"
    assert "no_file_evidence" in c.reason


def test_normalize_decision_maps_deny_and_rejects_unknown() -> None:
    assert normalize_decision("deny") == "reject"
    assert normalize_decision("approve") == "approve"
    with pytest.raises(ValueError):
        normalize_decision("nuke")


# ── loop-level: the checkpoint pass applies the split ────────────────────────


def _git_run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git_run(path, "init", "-q")
    _git_run(path, "config", "user.email", "rsi@test.local")
    _git_run(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git_run(path, "add", "-A")
    _git_run(path, "commit", "-q", "-m", "init")
    return path


def _loop(tmp_path: Path) -> LocalRsiLoop:
    repo = _make_repo(tmp_path / "src")
    config = LocalRsiConfig(
        repo_path=str(repo),
        test_command="exit 0",
        work_root=str(tmp_path / "work"),
        max_cycles=1,
        report_dir=str(tmp_path / "reports"),
    )
    loop = LocalRsiLoop(config, apply_patch=None)
    loop._setup_baseline()
    loop._last_reviewed_ref = loop._start_ref
    return loop


def _commit_file(loop: LocalRsiLoop, filename: str, content: str, message: str) -> str:
    path = loop._baseline / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(loop._baseline, "add", "-A")
    _git(loop._baseline, "commit", "-q", "-m", message)
    return _git(loop._baseline, "rev-parse", "HEAD").stdout.strip()


def _outcome(sha: str, *, composite: float, judge: float | None) -> CycleOutcome:
    return CycleOutcome(
        index=1,
        changed=True,
        tests_passed=True,
        promoted=True,
        target="target.py",
        composite=composite,
        sha=sha,
        kind=ImprovementKind.DOC,
        regression_judge_score=judge,
    )


def _review(tmp_path: Path, loop: LocalRsiLoop, outcome: CycleOutcome) -> Path:
    report_dir = Path(loop._config.report_dir)
    loop._review_promotions(LocalRsiResult(cycles=[outcome]), report_dir)
    return report_dir


def test_mechanical_promotion_needs_no_judge(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(loop, "README.md", "docs\n", "cycle 1: decisive doc work")
    report_dir = _review(tmp_path, loop, _outcome(sha, composite=0.9, judge=0.95))

    # No revert, no flagged item.
    log = _git(loop._baseline, "log", "--oneline").stdout
    assert "Revert" not in log
    assert not (report_dir / "flagged").exists()
    # And NO judgment machinery ran: no RLPHD state file is even written.
    assert not (report_dir / "rlphd_state.json").exists()
    kept_meta = list((report_dir / "kept" / f"{sha[:12]}.json").read_text(encoding="utf-8"))
    assert kept_meta  # the keep is still recorded for post-hoc override

    record = load_promotion_record(report_dir / "promotions", sha)
    assert record is not None
    assert record.candidate["sha"] == sha
    assert record.classification["review_path"] == "mechanical"
    assert record.decision["outcome"] == "auto_keep_mechanical"
    assert record.version["resulting_ref"] == sha


def test_sensitive_promotion_escalates_even_when_decisive(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(
        loop,
        "maistro_rsi/local_loop.py",
        "x = 1\n",
        "cycle 1: touches the agent's own cage",
    )
    report_dir = _review(tmp_path, loop, _outcome(sha, composite=0.95, judge=0.95))

    # Cold-start judgment path: reverted pending a human ruling.
    log = _git(loop._baseline, "log", "--oneline").stdout
    assert "Revert" in log
    meta = json.loads((report_dir / "flagged" / f"{sha[:12]}.json").read_text(encoding="utf-8"))
    assert meta["review_path"] == "judgment"
    assert meta["sensitive_paths"] == ["maistro_rsi/local_loop.py"]
    assert meta["classification_reason"].startswith("sensitive_surface")

    record = load_promotion_record(report_dir / "promotions", sha)
    assert record is not None
    assert record.decision["outcome"] == "escalated"
    # The resulting version is the revert — the lineage WITHOUT the candidate.
    assert record.version["resulting_ref"] != sha
    # And the escalation is linked to the evaluation evidence from the run.
    assert record.evaluation["composite"] == 0.95


def test_weak_evidence_escalates_on_the_judgment_path(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(loop, "app.py", "x = 1\n", "cycle 1: weak composite")
    report_dir = _review(tmp_path, loop, _outcome(sha, composite=0.5, judge=0.5))

    assert (report_dir / "flagged" / f"{sha[:12]}.json").is_file()
    record = load_promotion_record(report_dir / "promotions", sha)
    assert record is not None
    assert record.classification["reason"].startswith("weak_mechanical_evidence")


def test_governance_override_escalates_via_the_trace_note(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha = _commit_file(loop, "app.py", "x = 1\n", "cycle 1: shrink authorized by governance")
    write_trace_note(
        loop._baseline,
        sha,
        TraceNote(
            cycle=1,
            target="app.py",
            accepted=True,
            kind="doc",
            model="m",
            files_touched=1,
            reward=RewardVector(composite=0.95),
            gates={"protected_test_inventory": True},
            inventory={"override": True, "deleted_count": 1},
        ),
    )
    report_dir = _review(tmp_path, loop, _outcome(sha, composite=0.95, judge=0.95))

    # A promotion that needed a governance judgment call on its own oracle is
    # exactly the "ambiguous" class — it may not ride the mechanical path.
    assert (report_dir / "flagged" / f"{sha[:12]}.json").is_file()
    record = load_promotion_record(report_dir / "promotions", sha)
    assert record is not None
    assert record.classification["review_path"] == "judgment"
    assert record.classification["governance_override"] is True


def test_mechanical_superseded_promotion_still_needs_no_judge(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    sha1 = _commit_file(loop, "README.md", "v1\n", "cycle 1")
    _commit_file(loop, "README.md", "v2\n", "cycle 2: supersedes cycle 1")
    report_dir = _review(tmp_path, loop, _outcome(sha1, composite=0.9, judge=0.95))

    assert not (report_dir / "flagged").exists()
    assert not (report_dir / "rlphd_state.json").exists()
    record = load_promotion_record(report_dir / "promotions", sha1)
    assert record is not None
    assert record.decision["outcome"] == "auto_keep_mechanical"


# ── the inbox: deterministic approve / reject / revise / resume ─────────────


def _flag(tmp_path: Path, sha: str = "abc123def456") -> tuple[Path, Path, Path]:
    flagged = tmp_path / "flagged"
    export = tmp_path / "export"
    review = PendingReview(
        sha=sha,
        index=2,
        target="audit.py",
        kind="spec",
        action_class="rsi_promotion",
        features={"bias": 1.0},
        predicted_p=0.5,
        theta=0.7,
        flagged_at="2026-07-04T00:00:00+00:00",
        review_path="judgment",
        classification_reason="sensitive_surface:maistro_rsi/gate.py",
        sensitive_paths=["maistro_rsi/gate.py"],
    )
    flag_for_review(flagged, review, "the original diff\n")
    return flagged, export, tmp_path / "rlphd_state.json"


def test_revise_keeps_the_slot_open_and_trains_nothing(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    review = resolve_review(flagged, export, state, "abc123def456", "revise", reason="too broad")

    # Stays pending — the inbox keeps a slot for the revised candidate.
    pending = load_pending_reviews(flagged)
    assert [r.sha for r in pending] == ["abc123def456"]
    assert review.revision == 1
    assert "too broad" in review.note
    # Nothing exported, nothing trained.
    assert not export.exists()
    assert not state.exists()  # no RLPHD file even written
    # Deterministic under retries: the second revise is a no-op.
    again = resolve_review(flagged, export, state, "abc123def456", "revise")
    assert again.revision == 1
    event = json.loads((flagged / "abc123def456.revise.json").read_text(encoding="utf-8"))
    assert event["policy_snapshot"]["sensitive_paths"] == ["maistro_rsi/gate.py"]


def test_resume_requeues_the_patch_but_the_review_stays_open(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    review = resolve_review(flagged, export, state, "abc123def456", "resume")

    assert review.resumed is True
    assert load_pending_reviews(flagged) != []  # still open — no verdict yet
    exported = list(export.glob("*.patch"))
    assert len(exported) == 1
    assert exported[0].read_text(encoding="utf-8") == "the original diff\n"
    assert not state.exists()  # resume is not a verdict: nothing trained
    event = json.loads((flagged / "abc123def456.resume.json").read_text(encoding="utf-8"))
    assert event["export_patch"] == exported[0].name
    # Idempotent: resuming again must not duplicate the export.
    resolve_review(flagged, export, state, "abc123def456", "resume")
    assert len(list(export.glob("*.patch"))) == 1


def test_approve_resolves_and_trains_and_requeues(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    resolve_review(flagged, export, state, "abc123def456", "approve", reason="ok")

    assert load_pending_reviews(flagged) == []
    exported = list(export.glob("*.patch"))
    assert len(exported) == 1
    # A verdict trains RLPHD (approve lifts the present features' weights).
    weights = json.loads(state.read_text(encoding="utf-8"))["models"]["rsi_promotion"][
        "feature_weights"
    ]
    assert weights["bias"] > 0
    # The durable decision record embeds the policy/evidence snapshot.
    decision = json.loads((flagged / "abc123def456.decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "approve"
    assert decision["reason"] == "ok"
    assert decision["rlphd_trained"] is True
    assert decision["review"]["sha"] == "abc123def456"
    assert decision["policy_snapshot"]["predicted_p"] == 0.5
    assert decision["policy_snapshot"]["theta"] == 0.7
    assert decision["policy_snapshot"]["review_path"] == "judgment"
    assert decision["policy_snapshot"]["sensitive_paths"] == ["maistro_rsi/gate.py"]


def test_approve_after_resume_does_not_duplicate_the_export(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    resolve_review(flagged, export, state, "abc123def456", "resume")
    resolve_review(flagged, export, state, "abc123def456", "approve")
    assert len(list(export.glob("*.patch"))) == 1
    assert load_pending_reviews(flagged) == []


def test_reject_via_deny_alias_stays_reverted(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    resolve_review(flagged, export, state, "abc123def456", "deny")
    assert load_pending_reviews(flagged) == []
    assert not export.exists()  # denied — nothing re-enters the forward path
    assert (flagged / "abc123def456.patch").is_file()  # audit trail
    decision = json.loads((flagged / "abc123def456.decision.json").read_text(encoding="utf-8"))
    assert decision["decision"] == "reject"


def test_reviewer_decision_links_into_the_promotion_record(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    records = tmp_path / "promotions"
    write_promotion_record(
        records,
        PromotionRecord(
            candidate={"sha": "abc123def456", "cycle": 2, "target": "audit.py", "kind": "spec"},
            evaluation={"composite": 0.95, "judge_score": 0.95},
            classification={"review_path": "judgment", "reason": "sensitive_surface:x"},
            decision={"outcome": "escalated"},
            version={"built_on": "parent", "resulting_ref": "revert"},
        ),
    )

    resolve_review(
        flagged, export, state, "abc123def456", "approve", reason="lgtm", records_dir=records
    )
    record = load_promotion_record(records, "abc123def456")
    assert record is not None
    assert record.decision["outcome"] == "approve"
    assert record.decision["reason"] == "lgtm"
    # The decision links the resulting version: the exported patch the harvest
    # machinery will apply.
    exported = list(export.glob("*.patch"))
    assert record.version["export_patch"] == exported[0].name


def test_resume_links_the_forward_path_into_the_record(tmp_path: Path) -> None:
    flagged, export, state = _flag(tmp_path)
    records = tmp_path / "promotions"
    write_promotion_record(
        records,
        PromotionRecord(
            candidate={"sha": "abc123def456", "cycle": 2, "target": "audit.py", "kind": "spec"},
            evaluation={},
            classification={"review_path": "judgment", "reason": "sensitive_surface:x"},
            decision={"outcome": "escalated"},
            version={"built_on": "parent", "resulting_ref": "revert"},
        ),
    )
    resolve_review(flagged, export, state, "abc123def456", "resume", records_dir=records)
    record = load_promotion_record(records, "abc123def456")
    assert record is not None
    assert record.decision["outcome"] == "resumed"
    assert "export_patch" in record.version


# ── the CLI dispatches the same verbs through the same core ────────────────


def test_a_decision_never_leaks_across_candidate_shas(tmp_path: Path) -> None:
    """Approvals are keyed by the artifact (the content-addressed commit sha):
    a decision recorded for one candidate must not settle — or substitute for
    — a review of a different one (#110: re-evaluation after candidate/
    evidence changes re-runs on the new artifact's own evidence)."""
    flagged, export, state = _flag(tmp_path, sha="aaaa11111111")
    other = PendingReview(
        sha="bbbb22222222",
        index=3,
        target="other.py",
        kind="doc",
        action_class="rsi_promotion",
        features={"bias": 1.0},
        predicted_p=0.4,
        theta=0.7,
        flagged_at="2026-07-04T00:00:00+00:00",
        review_path="judgment",
        classification_reason="sensitive_surface:maistro_rsi/other.py",
        sensitive_paths=["maistro_rsi/other.py"],
    )
    flag_for_review(flagged, other, "the other candidate's diff\n")

    resolve_review(flagged, export, state, "aaaa11111111", "approve")

    # The approve settled ONLY its own artifact: the other candidate is still
    # open, on its own evidence.
    assert [r.sha for r in load_pending_reviews(flagged)] == ["bbbb22222222"]
    resolved = resolve_review(flagged, export, state, "bbbb22222222", "reject")
    assert resolved.sha == "bbbb22222222"
    first = json.loads((flagged / "aaaa11111111.decision.json").read_text(encoding="utf-8"))
    second = json.loads((flagged / "bbbb22222222.decision.json").read_text(encoding="utf-8"))
    assert first["decision"] == "approve"
    assert second["decision"] == "reject"


def test_cli_review_resume_dispatches_the_shared_core(tmp_path: Path, capsys: object) -> None:
    from maistro_rsi.__main__ import main

    flagged, export, state = _flag(tmp_path)
    code = main(["review", "--report-dir", str(tmp_path), "resume", "abc123def456"])

    assert code == 0
    exported = list(export.glob("*.patch"))
    assert len(exported) == 1
    assert not state.exists()  # resume is not a verdict: nothing trained
    assert load_pending_reviews(flagged) != []  # the review stays open
    assert "resumed" in capsys.readouterr().out


def test_cli_review_maps_a_core_missing_review_to_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    import maistro_rsi.promotion_review as promotion_review
    from maistro_rsi.__main__ import main

    _flag(tmp_path)
    # The inbox slot exists when the CLI checks it, then the core cannot resolve
    # it (a concurrent settle). The CLI maps the core's FileNotFoundError onto
    # exit 2 + a stderr message — never a traceback and never exit 0.

    def vanish(*args: object, **kwargs: object) -> PendingReview:
        raise FileNotFoundError("no pending review for sha 'abc123def456'")

    monkeypatch.setattr(promotion_review, "resolve_review", vanish)
    code = main(["review", "--report-dir", str(tmp_path), "approve", "abc123def456"])

    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_review_unknown_sha_reports_and_exits_2(tmp_path: Path, capsys: object) -> None:
    from maistro_rsi.__main__ import main

    _flag(tmp_path)  # a review exists — but not for this sha
    code = main(["review", "--report-dir", str(tmp_path), "approve", "ffffffffffff"])

    assert code == 2
    assert "no review found" in capsys.readouterr().err
