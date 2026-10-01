"""RSI API routes -- start/stop self-improvement runs, inspect cycles,
review patches (approve/deny → trains Ralph), auto-PR approved changes.

Cleanup mode (entry A) drives ``LocalRsiLoop`` against a repo + test command.
Greenfield mode (entry B, benchmark tournament) is scaffolded.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

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
    #: Accepted only to be refused. These three named host directories the
    #: loop WRITES to and, for the export child, deletes `*.patch` and
    #: `manifest.json` from -- so containing `repo_path` while forwarding these
    #: verbatim left three doors open beside the one being shut (#305). They
    #: are derived server-side now; a request that sets them is rejected rather
    #: than silently ignored, because a caller who names an output directory
    #: and gets a different one is being misled.
    work_root: str | None = None
    report_dir: str | None = None
    export_dir: str | None = None
    genome_models: str | None = None
    roster_size: int = 1
    scout: bool = False


class ReviewDecisionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: #110: the inbox takes the full deterministic decision set — approve /
    #: reject / revise / resume. "deny" stays as the v1 alias of "reject" so
    #: existing clients keep working unchanged.
    decision: Literal["approve", "reject", "revise", "resume", "deny"]
    reason: str | None = None
    #: Accepted only to be refused. Approving a review runs `git am` and opens a
    #: pull request against this path, and it reached that code unvalidated
    #: while the run route next door resolved its `repo_path` through
    #: `rsi_execution_policy` -- so the containment on the run was reachable
    #: around, one route over (#305). A patch belongs to the run that produced
    #: it, so the run's own resolved repository is the only correct answer and
    #: an override has nothing legitimate to express.
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

    caller_paths = [
        name
        for name, value in (
            ("work_root", body.work_root),
            ("report_dir", body.report_dir),
            ("export_dir", body.export_dir),
        )
        if value is not None
    ]
    if caller_paths:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(caller_paths)} is no longer accepted — the loop writes to "
                f"these directories, and the export child has its *.patch files and "
                f"manifest.json deleted on each promotion. They are derived from the "
                f"run id under the server's own working root."
            ),
        )

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


def _locate_review(report_dir: Path, sha: str) -> tuple[dict[str, Any], Path] | None:
    """The review metadata + the directory (kept/ or flagged/) holding it."""
    for d in (report_dir / "kept", report_dir / "flagged"):
        meta = d / f"{sha[:12]}.json"
        if meta.is_file():
            return json.loads(meta.read_text(encoding="utf-8")), d
    return None


def _decided_response(sha: str, review_data: dict[str, Any], decision_file: Path) -> dict[str, Any]:
    """The settled outcome for an already-decided review — no model touch."""
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


def _apply_review_verb(
    review_dir: Path,
    export_dir: Path,
    state_path: Path,
    sha: str,
    verb: str,
    reason: str,
    review_data: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """Apply one verb through the shared core, capturing the RLPHD weight
    delta (for the UI) around the call."""
    from maistro_rsi.promotion_review import (
        RlphdStateStore,
        explain_prediction,
        resolve_review,
    )

    store = RlphdStateStore(state_path)
    action_class = review_data["action_class"]
    before_weights = dict(store.model_for(action_class).feature_weights)
    before_theta = store.theta_for(action_class)
    resolved = resolve_review(review_dir, export_dir, state_path, sha, verb, reason=reason)
    # snapshot after → delta (only a verdict moves the model)
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
    return weight_delta, resolved


def _review_http_error(sha: str, exc: Exception) -> HTTPException:
    """Map core review errors onto API semantics.

    - FileNotFoundError: nothing to decide on → 404;
    - ValueError: an unknown verb → 400;
    - TypeError: metadata the strict reviewer parser cannot read (a foreign
      or pre-schema file) → 409 — refused, not half-applied: a decision made
      on evidence the reviewer cannot parse would be undeterministic.
    """
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(
        status_code=409, detail=f"review metadata unreadable for {sha[:12]}: {exc}"
    )


@router.post("/runs/{run_id}/reviews/{sha}")
def decide_review(run_id: str, sha: str, body: ReviewDecisionBody) -> dict:
    """Rule on a promotion in the review inbox (#110).

    Deterministic per verb: approve/reject are verdicts (train RLPHD, settle
    the item; approve also opens a PR); revise sends the candidate back for
    another attempt (slot stays open, nothing trained or exported); resume
    re-queues the reverted patch for harvest WITHOUT a verdict (review stays
    open). The file-level mechanics live in ``maistro_rsi.promotion_review``
    so the CLI, this API and any future surface cannot drift apart.
    """
    from services.rsi import get_rsi_service

    from maistro_rsi.promotion_review import normalize_decision

    run = get_rsi_service().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    report_dir = Path(run.report_dir or "")
    state_path = report_dir / "rlphd_state.json"
    verb = normalize_decision(body.decision)

    located = _locate_review(report_dir, sha)
    if located is None:
        raise HTTPException(status_code=404, detail=f"no review for sha {sha[:12]}")
    review_data, review_dir = located
    if not {"action_class", "features", "predicted_p", "theta"} <= set(review_data):
        # Metadata the strict reviewer parser cannot read (a foreign or
        # pre-schema file). Refused, not half-applied: a decision made on
        # evidence the reviewer cannot parse would be undeterministic.
        raise HTTPException(status_code=409, detail=f"review metadata unreadable for {sha[:12]}")

    if body.repo_path is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "repo_path is no longer accepted here — approving a review applies "
                "the patch and opens a pull request against the repository the run "
                "was authorized for, which the run already recorded. Refused rather "
                "than ignored: a caller who names a repository and gets a different "
                "one is being misled."
            ),
        )

    # ── 0. idempotency: a decided review is settled ──
    # Every POST used to retrain Ralph before checking for an existing
    # decision, so a double-click or client retry applied the same feature
    # vector repeatedly (drifting weights and theta) and could overwrite an
    # earlier decision with the opposite one. First decision wins; repeats get
    # the recorded outcome back without touching the model.
    decision_file = review_dir / f"{sha[:12]}.decision.json"
    if decision_file.exists():
        return _decided_response(sha, review_data, decision_file)

    # ── 1. apply the verb through the shared core, capturing the RLPHD delta ──
    try:
        weight_delta, resolved = _apply_review_verb(
            review_dir,
            report_dir / "export",
            state_path,
            sha,
            verb,
            body.reason or "",
            review_data,
        )
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise _review_http_error(sha, exc) from exc
    trained = verb in ("approve", "reject")

    # ── 2. on approve: open a PR ──
    pr_url = None
    if verb == "approve":
        patch_file = review_dir / f"{sha[:12]}.patch"
        repo = run.config.get("repo_path", "")
        if patch_file.is_file() and repo:
            pr_url = _create_pr_from_patch(patch_file, sha, review_data, repo)

    return {
        "sha": sha[:12],
        "decision": verb,
        "target": review_data.get("target", ""),
        "pr_url": pr_url,
        "rlphd_updated": trained,
        "weight_delta": weight_delta,
        "resumed": resolved.resumed if (verb == "resume" and resolved) else None,
        "revision": resolved.revision if (verb == "revise" and resolved) else None,
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
        # Decision/event sidecars are bookkeeping, not inbox items.
        if meta_file.name.endswith((".decision.json", ".revise.json", ".resume.json")):
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
