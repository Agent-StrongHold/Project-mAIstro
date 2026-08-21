"""Promotion-review decisions must be idempotent.

Codex P1 on #262: every POST retrained Ralph before checking for an existing
decision sidecar, so a browser double-click or client retry applied the same
feature vector repeatedly — drifting weights and theta — and a later POST
could overwrite an earlier decision with the opposite result.
"""

from __future__ import annotations

import json


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
