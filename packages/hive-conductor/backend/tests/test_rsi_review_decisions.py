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
    (kept / f"{sha[:12]}.json").write_text(
        json.dumps(
            {
                "sha": sha,
                "target": "packages/x.py",
                "action_class": "refactor",
                "features": {"tests_delta": 1.0},
                "predicted_p": 0.7,
                "theta": 0.5,
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
