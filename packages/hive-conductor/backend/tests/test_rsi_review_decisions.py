"""Promotion-review decisions must be idempotent.

Codex P1 on #262: every POST retrained Ralph before checking for an existing
decision sidecar, so a browser double-click or client retry applied the same
feature vector repeatedly — drifting weights and theta — and a later POST
could overwrite an earlier decision with the opposite result.
"""

from __future__ import annotations

import json

import pytest


def _seed_run_with_review(tmp_path, sha: str) -> str:
    from services.rsi import RunState, get_rsi_service

    svc = get_rsi_service()
    run = RunState(run_id="testrun-idem", mode="cleanup", config={})
    run.report_dir = str(tmp_path)
    svc._runs[run.run_id] = run

    kept = tmp_path / "kept"
    kept.mkdir()
    # The exact metadata + patch shape `flag_for_review`/`save_kept_review`
    # write — the only shape real inbox files ever carry.
    (kept / f"{sha[:12]}.patch").write_text("the seeded diff\n", encoding="utf-8")
    (kept / f"{sha[:12]}.json").write_text(
        json.dumps(
            {
                "sha": sha,
                "index": 1,
                "target": "packages/x.py",
                "kind": "spec",
                "action_class": "refactor",
                "features": {"tests_delta": 1.0},
                "predicted_p": 0.7,
                "theta": 0.5,
                "flagged_at": "2026-07-04T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return run.run_id


def test_second_decision_returns_recorded_outcome_without_retraining(admin_client, tmp_path):
    sha = "abc123def4567890"
    run_id = _seed_run_with_review(tmp_path, sha)

    first = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "approve"})
    assert first.status_code == 200
    assert first.json()["decision"] == "approve"
    assert first.json().get("already_decided") is None

    # The retry — with the OPPOSITE decision, the worst case the old code
    # allowed to win.
    second = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "deny"})
    assert second.status_code == 200
    body = second.json()
    assert body["already_decided"] is True
    assert body["decision"] == "approve"  # the first decision stands
    assert body["rlphd_updated"] is False
    assert body["weight_delta"] == {}


@pytest.mark.ac("SPEC-082926-a6ab/AC-8")
def test_a_caller_supplied_repository_is_refused_not_ignored(admin_client, tmp_path):
    """Approving a review runs `git am` and opens a PR against this path.

    It reached that code unvalidated while the run route next door resolved
    its `repo_path` through `rsi_execution_policy` — so the containment on the
    run was reachable around, one route over (Codex, #305). A patch belongs to
    the run that produced it, so the run's own resolved repository is the only
    correct answer.
    """
    sha = "beef0011223344556677"
    run_id = _seed_run_with_review(tmp_path, sha)

    response = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}",
        json={"decision": "approve", "repo_path": str(tmp_path / "somewhere-else")},
    )

    assert response.status_code == 400
    assert "repo_path is no longer accepted" in response.json()["detail"]


@pytest.mark.ac("SPEC-082926-a6ab/AC-8")
def test_the_refusal_happens_before_anything_is_recorded(admin_client, tmp_path):
    """Refused early, or the decision sidecar lands and the retry is settled.

    A guard placed after the write would leave the review marked decided by a
    request the server rejected — and idempotency would then make the honest
    retry a no-op.
    """
    sha = "beef99887766554433"
    run_id = _seed_run_with_review(tmp_path, sha)

    admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}",
        json={"decision": "approve", "repo_path": str(tmp_path)},
    )

    assert not (tmp_path / "kept" / f"{sha[:12]}.decision.json").exists()

    accepted = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "approve"}
    )
    assert accepted.status_code == 200
    assert accepted.json().get("already_decided") is None


# ── #110: the inbox exposes the full deterministic decision set ─────────────


def test_revise_keeps_the_item_pending_and_trains_nothing(admin_client, tmp_path):
    sha = "abcdef1234567890"
    run_id = _seed_run_with_review(tmp_path, sha)

    first = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "revise", "reason": "too broad"}
    )
    assert first.status_code == 200
    assert first.json()["decision"] == "revise"
    assert first.json()["revision"] == 1

    # Still pending — the slot stays open for the revised candidate.
    listed = admin_client.get(f"/v1/rsi/runs/{run_id}/reviews").json()
    assert listed["kept"][0]["resolved"] is False
    # No RLPHD state file was even written: a revise is not a verdict.
    assert not (tmp_path / "rlphd_state.json").exists()

    # Deterministic under retries: the repeat does not bump again.
    second = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "revise"})
    assert second.status_code == 200
    assert second.json()["revision"] == 1


def test_resume_requeues_the_patch_but_the_review_stays_open(admin_client, tmp_path):
    sha = "resume0123456789"
    run_id = _seed_run_with_review(tmp_path, sha)

    first = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "resume"})
    assert first.status_code == 200
    assert first.json()["decision"] == "resume"
    assert first.json()["resumed"] is True

    exported = list((tmp_path / "export").glob("*.patch"))
    assert len(exported) == 1
    assert not (tmp_path / "rlphd_state.json").exists()

    # Still open for a later approve/reject.
    listed = admin_client.get(f"/v1/rsi/runs/{run_id}/reviews").json()
    assert listed["kept"][0]["resolved"] is False

    # Idempotent: resuming again must not duplicate the export.
    second = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "resume"})
    assert second.status_code == 200
    assert len(list((tmp_path / "export").glob("*.patch"))) == 1


def test_approve_after_resume_does_not_duplicate_the_export(admin_client, tmp_path):
    sha = "apprres123456789"
    run_id = _seed_run_with_review(tmp_path, sha)

    assert (
        admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "resume"})
    ).status_code == 200
    decided = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "approve"}
    )
    assert decided.status_code == 200
    assert decided.json()["rlphd_updated"] is True
    assert len(list((tmp_path / "export").glob("*.patch"))) == 1
    assert (tmp_path / "rlphd_state.json").is_file()  # the verdict trained


def test_an_unknown_verb_is_refused_by_validation(admin_client, tmp_path):
    sha = "unknown012345678"
    run_id = _seed_run_with_review(tmp_path, sha)
    response = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "ship-it"}
    )
    assert response.status_code == 422


def test_unreadable_metadata_is_refused_not_half_applied(admin_client, tmp_path):
    sha = "unreadabl1234567"
    run_id = _seed_run_with_review(tmp_path, sha)
    # Corrupt the metadata the strict reviewer parser would reject.
    (tmp_path / "kept" / f"{sha[:12]}.json").write_text(json.dumps({"sha": sha}), encoding="utf-8")

    response = admin_client.post(f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "deny"})

    assert response.status_code == 409
    assert "unreadable" in response.json()["detail"]
    # Nothing settled by the refused request.
    assert not (tmp_path / "kept" / f"{sha[:12]}.decision.json").exists()


# ── #110 repair: the route's error mapping is API semantics, not an accident ─


def test_an_unknown_sha_is_refused_404_not_500(admin_client, tmp_path):
    """A decision for a sha the inbox never flagged is a 404, and seeds
    nothing (the locator's miss path must not half-create state)."""
    run_id = _seed_run_with_review(tmp_path, "abc123def4567890")

    response = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/ffffffffffff", json={"decision": "approve"}
    )

    assert response.status_code == 404
    assert "no review for sha" in response.json()["detail"]
    assert not (tmp_path / "rlphd_state.json").exists()


def test_core_error_classes_map_onto_their_api_semantics():
    """The core's exceptions are the route's contract: missing evidence is
    404, a bad verb is 400, unreadable metadata is 409 (refused, not
    half-applied) — whatever exception class the core raises."""
    import routes.rsi as rsi_routes

    sha = "abc123def456"
    cases = [
        (FileNotFoundError("no pending review for sha 'abc123def456'"), 404),
        (ValueError("unknown review decision 'ship-it'"), 400),
        (TypeError("'str'unsupported for feature 'tests_delta'"), 409),
    ]
    for exc, expected_status in cases:
        http_error = rsi_routes._review_http_error(sha, exc)
        assert http_error.status_code == expected_status, exc
    # The 409 mapping is a refusal of THIS sha's metadata, not a generic 500.
    unreadable = rsi_routes._review_http_error(sha, TypeError("bad metadata"))
    assert "unreadable" in unreadable.detail
    assert sha[:12] in unreadable.detail


def test_garbage_feature_values_are_refused_409_through_the_route(admin_client, tmp_path):
    """Metadata whose feature VALUES are not numbers passes the route's
    key-subset check but cannot reach the RLPHD update — the core raises
    TypeError and the route must refuse the decision (409), not 500 and not
    a half-applied verdict."""
    sha = "garbage01234567"
    run_id = _seed_run_with_review(tmp_path, sha)
    meta = json.loads((tmp_path / "kept" / f"{sha[:12]}.json").read_text(encoding="utf-8"))
    meta["features"] = {"tests_delta": "lots"}
    (tmp_path / "kept" / f"{sha[:12]}.json").write_text(json.dumps(meta), encoding="utf-8")

    response = admin_client.post(
        f"/v1/rsi/runs/{run_id}/reviews/{sha}", json={"decision": "approve"}
    )

    assert response.status_code == 409
    assert "unreadable" in response.json()["detail"]
    # Nothing settled by the refused request.
    assert not (tmp_path / "kept" / f"{sha[:12]}.decision.json").exists()
    assert not (tmp_path / "rlphd_state.json").exists()
