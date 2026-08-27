"""RSI API routes -- start/stop self-improvement runs, inspect cycles,
review patches (approve/deny → trains Ralph), auto-PR approved changes.

Cleanup mode (entry A) drives ``LocalRsiLoop`` against a repo + test command.
Greenfield mode (entry B, benchmark tournament) is scaffolded.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from services import rsi_execution_policy

router = APIRouter(tags=["rsi"])


class StartRunBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = "cleanup"
    repo_path: str
    #: The NAME of a server-held test profile, not a command (#305). A profile
    #: resolves to an argument vector, so nothing the caller sends is ever
    #: interpreted by a shell.
    test_profile: str = "pytest"
    #: Accepted only so the route can refuse it out loud. `extra="ignore"`
    #: would drop an old client's command silently and run a different one,
    #: which is the failure mode most likely to be mistaken for success.
    test_command: str | None = None
    cycles: int = 10
    agent_turns: int = 2
    model: str | None = None
    objective: str | None = None
    targets: list[str] | None = None
    fitness: bool = True
    coverage_source: str | None = None
    coverage_pytest_args: str | None = None
    work_root: str | None = None
    report_dir: str | None = None
    export_dir: str | None = None
    genome_models: str | None = None
    roster_size: int = 1
    scout: bool = False


class ReviewDecisionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: Literal["approve", "deny"]
    reason: str | None = None
    repo_path: str | None = None


# ─── service status ─────────────────────────────────────────────────────


@router.get("/status")
def rsi_status() -> dict:
    from services.rsi import status

    return status()


@router.get("/models")
def available_models() -> dict:
    """Models the operator can pick from in the UI."""
    return {
        "models": [
            {"id": "glm-4.7", "label": "GLM-4.7 (Sonnet-level, 1x quota)", "tier": "open"},
            {"id": "glm-5.2", "label": "GLM-5.2 (Opus-level, 2x quota)", "tier": "premium"},
            {
                "id": "oss120-cerebras",
                "label": "Cerebras gpt-oss-120b (free, daily cap)",
                "tier": "free",
            },
            {"id": "gemini-flash", "label": "Gemini Flash (free, 5 RPM)", "tier": "free"},
        ]
    }


@router.get("/test-profiles")
def rsi_test_profiles() -> dict:
    """The test commands this deployment will run, for the UI to choose from.

    The list is the policy: a caller can only start a run with a name that
    appears here, so this endpoint is also the honest answer to "what can an
    RSI run execute on this host?" (#305).
    """
    try:
        profiles = rsi_execution_policy.test_profiles()
    except rsi_execution_policy.RsiPolicyError as refusal:
        raise HTTPException(status_code=500, detail=str(refusal)) from refusal
    return {"profiles": [{"name": p.name, "argv": list(p.argv)} for p in profiles]}


# ─── run lifecycle ─────────────────────────────────────────────────────


@router.get("/runs")
def list_runs() -> list[dict]:
    from services.rsi import get_rsi_service

    return get_rsi_service().list_runs()


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    from services.rsi import get_rsi_service

    run = get_rsi_service().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run.to_dict()


@router.post("/runs")
async def start_run(body: StartRunBody) -> dict:
    from services.rsi import get_rsi_service

    svc = get_rsi_service()
    if not svc.available:
        raise HTTPException(status_code=503, detail="maistro-rsi is not installed in this process")
    if body.mode not in ("cleanup", "greenfield"):
        raise HTTPException(status_code=400, detail="mode must be 'cleanup' or 'greenfield'")
    if body.test_command is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "test_command is no longer accepted — it was executed with a shell on "
                "this host. Pick a test_profile; GET /v1/rsi/test-profiles lists them."
            ),
        )
    if body.mode == "cleanup" and not body.repo_path:
        raise HTTPException(status_code=400, detail="cleanup mode requires repo_path")

    # Resolve every execution decision HERE, at the trust boundary, so what the
    # service receives is already the operator's policy rather than the
    # caller's description of it (#305).
    try:
        repo = rsi_execution_policy.resolve_repo(body.repo_path)
        profile = rsi_execution_policy.resolve_test_profile(body.test_profile)
        isolation = rsi_execution_policy.require_isolation()
    except rsi_execution_policy.RsiPolicyError as refusal:
        raise HTTPException(status_code=400, detail=str(refusal)) from refusal

    config = {
        "repo_path": str(repo),
        "test_profile": profile.name,
        "test_argv": list(profile.argv),
        "isolation": isolation,
        "cycles": body.cycles,
        "agent_turns": body.agent_turns,
        "model": body.model,
        "objective": body.objective,
        "targets": body.targets or [],
        "fitness": body.fitness,
        "coverage_source": body.coverage_source,
        "coverage_pytest_args": body.coverage_pytest_args,
        "work_root": body.work_root,
        "report_dir": body.report_dir,
        "export_dir": body.export_dir,
        "genome_models": body.genome_models,
        "roster_size": body.roster_size,
        "scout": body.scout,
    }
    run = svc.start_run(body.mode, config)
    return run.to_dict()


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    from services.rsi import get_rsi_service

    ok = get_rsi_service().stop_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    return {"run_id": run_id, "status": "stopped"}


# ─── patch review (trains Ralph) ───────────────────────────────────────


@router.get("/runs/{run_id}/reviews")
def list_reviews(run_id: str) -> dict:
    """List all promotions (kept + flagged) for a run, with their RLPHD data."""
    from services.rsi import get_rsi_service

    run = get_rsi_service().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report_dir = Path(run.report_dir or "")
    kept_dir = report_dir / "kept"
    flagged_dir = report_dir / "flagged"
    kept = _load_reviews(kept_dir)
    flagged = _load_reviews(flagged_dir)
    return {"kept": kept, "flagged": flagged}


@router.post("/runs/{run_id}/reviews/{sha}")
def decide_review(run_id: str, sha: str, body: ReviewDecisionBody) -> dict:
    """Approve or deny a promotion. Trains Ralph + (on approve) opens a PR."""
    from services.rsi import get_rsi_service

    run = get_rsi_service().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report_dir = Path(run.report_dir or "")
    state_path = report_dir / "rlphd_state.json"

    # find the review in kept/ or flagged/
    review_data = None
    review_dir = None
    for d in (report_dir / "kept", report_dir / "flagged"):
        meta = d / f"{sha[:12]}.json"
        if meta.is_file():
            review_data = json.loads(meta.read_text(encoding="utf-8"))
            review_dir = d
            break
    if review_data is None:
        raise HTTPException(status_code=404, detail=f"no review for sha {sha[:12]}")

    # ── 0. idempotency: a decided review is settled ──
    # Every POST used to retrain Ralph before checking for an existing
    # decision, so a double-click or client retry applied the same feature
    # vector repeatedly (drifting weights and theta) and could overwrite an
    # earlier decision with the opposite one. First decision wins; repeats get
    # the recorded outcome back without touching the model.
    decision_file = review_dir / f"{sha[:12]}.decision.json"
    if decision_file.exists():
        prior = json.loads(decision_file.read_text(encoding="utf-8"))
        return {
            "sha": sha[:12],
            "decision": prior.get("decision"),
            "target": review_data.get("target", ""),
            "pr_url": None,
            "rlphd_updated": False,
            "weight_delta": {},
            "already_decided": True,
            "resolved_at": prior.get("resolved_at"),
        }

    # ── 1. train Ralph — capture weight delta for the UI ──
    weight_delta = {}
    try:
        from maistro_rsi.promotion_review import RlphdStateStore, explain_prediction

        store = RlphdStateStore(state_path)
        # snapshot before
        action_class = review_data["action_class"]
        before_weights = dict(store.model_for(action_class).feature_weights)
        before_theta = store.theta_for(action_class)
        store.record_decision(
            action_class,
            review_data["features"],
            review_data["predicted_p"],
            review_data["theta"],
            body.decision,
        )
        # snapshot after → delta
        after_weights = store.model_for(action_class).feature_weights
        after_theta = store.theta_for(action_class)
        weight_delta = {
            "theta": {"before": before_theta, "after": after_theta},
            "weights": {
                k: {"before": before_weights.get(k, 0.0), "after": after_weights.get(k, 0.0)}
                for k in set(before_weights) | set(after_weights)
            },
            # explain the ORIGINAL prediction (why Ralph kept/reverted)
            "prediction_explanation": explain_prediction(review_data["features"], before_weights),
        }
    except Exception:
        pass

    # mark resolved + store reason
    from datetime import datetime

    decision_file.write_text(
        json.dumps(
            {
                "decision": body.decision,
                "reason": body.reason,
                "resolved_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── 2. on approve: open a PR ──
    pr_url = None
    if body.decision == "approve":
        patch_file = review_dir / f"{sha[:12]}.patch"
        repo = body.repo_path or run.config.get("repo_path", "")
        if patch_file.is_file() and repo:
            pr_url = _create_pr_from_patch(patch_file, sha, review_data, repo)

    return {
        "sha": sha[:12],
        "decision": body.decision,
        "target": review_data.get("target", ""),
        "pr_url": pr_url,
        "rlphd_updated": True,
        "weight_delta": weight_delta,
    }


@router.get("/runs/{run_id}/rlphd")
def get_rlphd_state(run_id: str) -> dict:
    """Current Ralph state — theta + feature weights."""
    from services.rsi import get_rsi_service

    run = get_rsi_service().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    state_path = Path(run.report_dir or "") / "rlphd_state.json"
    if not state_path.is_file():
        return {"thetas": {}, "models": {}, "decisions": 0}
    return json.loads(state_path.read_text(encoding="utf-8"))


# ─── helpers ───────────────────────────────────────────────────────────


def _load_reviews(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    out = []
    for meta_file in sorted(directory.glob("*.json")):
        if meta_file.name.endswith(".decision.json"):
            continue
        decision_file = meta_file.with_suffix(".decision.json")
        resolved = decision_file.exists()
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            data["resolved"] = resolved
            data["decision"] = (
                json.loads(decision_file.read_text(encoding="utf-8")).get("decision")
                if resolved
                else None
            )
            # include the patch diff for preview
            patch_file = directory / f"{data['sha'][:12]}.patch"
            if patch_file.is_file():
                diff = patch_file.read_text(encoding="utf-8")
                data["diff"] = diff[:4000]
                data["diff_lines"] = diff.count("\n")
            out.append(data)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return out


def _create_pr_from_patch(
    patch_file: Path, sha: str, review_data: dict, repo_path: str
) -> str | None:
    """Apply a patch to a fresh branch and open a PR via gh."""
    try:
        short_sha = sha[:12]
        target = review_data.get("target", "improvement")
        branch_name = f"rsi/{short_sha}"
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        am = subprocess.run(
            ["git", "am", "--3way", str(patch_file)],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if am.returncode != 0:
            # A conflicting patch used to fall through to push/PR anyway,
            # leaving the operator's checkout stuck mid-`git am`. Abort to
            # restore the original branch state, clean up, and report failure.
            subprocess.run(["git", "am", "--abort"], cwd=repo_path, capture_output=True, timeout=30)
            subprocess.run(["git", "checkout", "-"], cwd=repo_path, capture_output=True, timeout=30)
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=repo_path,
                capture_output=True,
                timeout=30,
            )
            return None
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        title = f"RSI: {Path(target).name} ({short_sha})"
        body_text = (
            f"Self-improvement patch for `{target}`.\n\nComposite: {review_data.get('note', 'N/A')}"
        )
        pr_result = subprocess.run(
            ["gh", "pr", "create", "--title", title, "--body", body_text, "--label", "rsi"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if pr_result.returncode == 0:
            return pr_result.stdout.strip()
    except Exception:
        pass
    return None
