"""Builder pipeline — chained agent execution for issue-to-merge flow.

Faithful recreation of the Stronghold Epic-15 builder pipeline on maistro:
stage ordering, skipping, and post-completion hooks are declared on
:class:`~maistro.builders.graph.PipelineNode`;
:class:`~maistro.builders.graph_executor.GraphPipelineExecutor` drives
execution. New since Epic-15: the review stage is a verifiable gate that
routes back to implement (bounded verify-and-revise) instead of relying
solely on a downstream cleanup stage.

Default pipeline:
  1. decompose (quartermaster) — decompose epic into atomic issues
     (skip if already atomic)
  2. scaffold  (archie)        — scaffold protocols, fakes, file structure
  3. implement (mason)         — TDD: write tests, then implementation
  4. review    (auditor)       — review PR; gate: violations send the run
     back to implement with feedback (skip if implement output is clean)
  5. cleanup   (gatekeeper)    — final lint/format/merge-readiness check
     (skip if review is clean)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar

from maistro.builders.contracts import RunRequest, RunStatus, WorkerName
from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import (
    DispatchResult,
    GraphPipelineExecutor,
    PipelineDispatcher,
)
from maistro.builders.runtime import BuildersRuntime

logger = logging.getLogger("maistro.builders.pipeline")

_SPEC_SUMMARY_LIMIT = 2000
_CLEAN_SIGNALS = ("no violations", "lgtm", "approved", "all checks pass", "clean")

# Words that negate a clean signal appearing shortly after them, e.g. "not
# clean", "isn't approved", "never lgtm". Substring matching on _CLEAN_SIGNALS
# alone is a weak self-attestation check to begin with (see _is_clean's
# docstring) -- this at least keeps it from being flipped by the negation of
# its own keywords, which an implementer (human or LLM) could otherwise
# trivially trigger by writing e.g. "this is NOT clean, needs work".
_NEGATION_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "without",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "hasn't",
        "haven't",
        "hadn't",
        "doesn't",
        "don't",
        "didn't",
        "won't",
        "can't",
        "cannot",
        "n't",
    }
)
# How many words immediately before a clean-signal match to scan for a
# negation word, e.g. "definitely not entirely clean" (2 words between).
_NEGATION_WINDOW = 4
_WORD_RE = re.compile(r"[a-z']+")


def build_spec_summary(spec: Any) -> str:
    """Build a text summary of a Spec for injection into pipeline prompts."""
    parts: list[str] = [f"Spec: {spec.title}"]

    if spec.protocols_touched:
        parts.append(f"Protocols: {', '.join(spec.protocols_touched)}")

    if spec.invariants:
        inv_lines = [f"  - {inv.name}: {inv.description}" for inv in spec.invariants]
        parts.append("Invariants:\n" + "\n".join(inv_lines))

    if spec.acceptance_criteria:
        crit_lines = [f"  - {c}" for c in spec.acceptance_criteria]
        parts.append("Acceptance criteria:\n" + "\n".join(crit_lines))

    summary = "\n".join(parts)
    if len(summary) > _SPEC_SUMMARY_LIMIT:
        summary = summary[: _SPEC_SUMMARY_LIMIT - 3] + "..."
    return summary


def _emit_spec(issue_number: int, title: str, body: str) -> Any:
    """Create a Spec from issue metadata via the spec emitter."""
    from maistro.builders.spec_emitter import emit_spec

    return emit_spec(issue_number=issue_number, title=title, body=body)


def _enrich_spec_with_property_tests(spec: Any) -> Any:
    """Generate property tests for a Spec's invariants and return updated Spec."""
    from maistro.builders.property_gen import generate_property_tests

    tests = generate_property_tests(spec)
    return replace(spec, property_tests=tuple(tests))


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStage:
    """A single stage in the builder pipeline (kept for run reporting)."""

    name: str
    agent_name: str
    prompt_template: str
    status: StageStatus = StageStatus.PENDING
    result: dict[str, Any] | None = None
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineRun:
    """A complete pipeline execution for one issue."""

    id: str
    issue_number: int
    title: str
    repo: str
    stages: list[PipelineStage] = field(default_factory=list)
    status: str = "pending"
    context: RunContext = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)
    failed_stage_error: str = ""
    revisions: dict[str, int] = field(default_factory=dict)
    gate_exhausted: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "issue_number": self.issue_number,
            "title": self.title,
            "repo": self.repo,
            "status": self.status,
            "stages": [s.to_dict() for s in self.stages],
            "skipped_stages": list(self.skipped_stages),
            "revisions": dict(self.revisions),
            "gate_exhausted": list(self.gate_exhausted),
            "created_at": self.created_at.isoformat(),
        }


# ── skip_if predicates and gates ─────────────────────────────────────────────


def _is_clean(text: str) -> bool:
    """True if ``text`` contains an unnegated clean signal.

    Plain substring matching against ``_CLEAN_SIGNALS`` would treat "not
    clean" or "isn't approved" as a pass, which is trivial for the IMPLEMENT
    stage's own output (possibly LLM-generated) to trigger by accident or
    design. This adds a negation check over the few words preceding each
    match; it is still a free-text heuristic, not a structural verdict --
    see the module docstring's gate description for the stronger, structured
    alternative this stands in for.
    """
    lowered = text.lower()
    for sig in _CLEAN_SIGNALS:
        start = 0
        while (pos := lowered.find(sig, start)) != -1:
            start = pos + 1
            preceding_words = _WORD_RE.findall(lowered[:pos])[-_NEGATION_WINDOW:]
            negated = any(w in _NEGATION_WORDS or w.endswith("n't") for w in preceding_words)
            if not negated:
                return True
    return False


def _decompose_skip_if(ctx: RunContext) -> bool:
    return bool(ctx.get("skip_decompose", False))


def _review_skip_if(ctx: RunContext) -> bool:
    return _is_clean(str(ctx.get("implement", "")))


def _review_gate(ctx: RunContext) -> bool:
    """Verifiable acceptance: the reviewer signed off, with no unwaived structural violation."""
    if _has_critical_extracted_finding(ctx):
        return False
    return _is_clean(str(ctx.get("review", "")))


def _has_critical_extracted_finding(ctx: RunContext) -> bool:
    from maistro.types.feedback import ClaimProvenance, Severity

    findings = ctx.get("structural_findings", [])
    return any(
        f.provenance is ClaimProvenance.EXTRACTED and f.severity is Severity.CRITICAL
        for f in findings
    )


def _cleanup_skip_if(ctx: RunContext) -> bool:
    return _is_clean(str(ctx.get("review", "")))


# ── on_complete hooks ────────────────────────────────────────────────────────


async def _decompose_on_complete(run: PipelineRun, output: str) -> None:
    """Emit and persist spec from decompose output."""
    spec_store = run.context.get("_spec_store")
    if spec_store is None:
        return
    if run.context.get("_spec") is not None:
        return
    spec = _emit_spec(run.issue_number, run.title, output)
    await spec_store.save(spec)
    run.context["_spec"] = spec
    run.context["spec"] = spec.to_dict()
    run.context["verifications"] = []
    run.context["spec_summary"] = build_spec_summary(spec)


async def _scaffold_on_complete(run: PipelineRun, output: str) -> None:
    """Enrich spec with property tests after scaffold."""
    spec_store = run.context.get("_spec_store")
    spec = run.context.get("_spec")
    if spec_store is None or spec is None:
        return
    enriched = _enrich_spec_with_property_tests(spec)
    await spec_store.save(enriched)
    run.context["_spec"] = enriched
    run.context["spec"] = enriched.to_dict()
    run.context["spec_summary"] = build_spec_summary(enriched)


async def _review_on_complete(run: PipelineRun, output: str) -> None:
    """Build a structural snapshot of the implemented code and check it for violations.

    Runs on ``review`` (not ``scaffold``) because the index must reflect the
    *implemented* code. A no-op (empty findings) when no ``code_index`` is
    configured or no ``workspace_path`` was given — this is what keeps the
    hard-fail gate backward-compatible with callers who opt out.
    """
    code_index = run.context.get("_code_index")
    workspace_path = run.context.get("workspace_path", "")
    if code_index is None or not workspace_path:
        run.context["structural_findings"] = []
        return

    from maistro.codebase.violations import check_structural_violations

    report = await code_index.build(workspace_path)
    run.context["_code_structure_report"] = report
    findings = check_structural_violations(report)
    run.context["structural_findings"] = findings
    if findings:
        run.context["structural_findings_summary"] = "\n".join(
            f"- [{f.category}] {f.description}: {f.suggestion}" for f in findings
        )


# ── Default pipeline nodes ───────────────────────────────────────────────────

BUILDER_PIPELINE: list[PipelineNode] = [
    PipelineNode(
        name="decompose",
        agent_name="quartermaster",
        skip_if=_decompose_skip_if,
        on_complete=_decompose_on_complete,
        prompt_template=(
            "Decompose this epic into atomic, implementable sub-issues. "
            "Each sub-issue must have:\n"
            "- A clear title\n"
            "- Acceptance criteria (testable)\n"
            "- File paths that will be touched\n"
            "- Estimated complexity (S/M/L)\n\n"
            "Epic: {title}\n"
            "Issue: https://github.com/{repo}/issues/{issue_number}\n\n"
            "Output a numbered list of sub-issues with details."
        ),
    ),
    PipelineNode(
        name="scaffold",
        agent_name="archie",
        depends_on=("decompose",),
        on_complete=_scaffold_on_complete,
        prompt_template=(
            "Read issue #{issue_number}: {title}\n\n"
            "{spec_summary}\n\n"
            "Create the scaffolding for this implementation:\n"
            "1. Define any new protocols in maistro/protocols/\n"
            "2. Add fake implementations for tests\n"
            "3. Create empty module files with docstrings\n"
            "4. Generate property test stubs from spec invariants\n\n"
            "Previous stage output:\n{decompose}\n\n"
            "DO NOT write implementation code. Only structure."
        ),
    ),
    PipelineNode(
        name="implement",
        agent_name="mason",
        depends_on=("scaffold",),
        prompt_template=(
            "Implement issue #{issue_number}: {title}\n\n"
            "Repository: https://github.com/{repo}\n\n"
            "{spec_summary}\n\n"
            "Follow your TDD pipeline:\n"
            "1. Write failing tests based on acceptance criteria and spec invariants\n"
            "2. Implement minimum code to pass tests\n"
            "3. Verify all spec invariants hold via property tests\n"
            "4. Run quality gates: pytest, ruff, mypy, bandit\n"
            "5. Create a PR when all gates pass\n\n"
            "Scaffold from previous stage:\n{scaffold}\n\n"
            "Reviewer feedback from a prior pass (fix everything listed, if any):\n"
            "{review_feedback}\n\n"
            "Structural violations found by the code-structure index "
            "(fix everything listed, if any):\n"
            "{structural_findings_summary}\n\n"
            "Create a focused PR with your changes."
        ),
    ),
    PipelineNode(
        name="review",
        agent_name="auditor",
        depends_on=("implement",),
        skip_if=_review_skip_if,
        on_complete=_review_on_complete,
        gate=_review_gate,
        revise_target="implement",
        max_revisions=2,
        gate_exhausted="continue",
        prompt_template=(
            "Review the PR created for issue #{issue_number}: {title}\n\n"
            "{spec_summary}\n\n"
            "Check for:\n"
            "- Spec invariant coverage (all invariants must have property tests)\n"
            "- Test coverage and quality\n"
            "- Security issues (injection, XSS, SSRF)\n"
            "- Protocol compliance (DI, no direct imports)\n"
            "- Code quality (naming, complexity, duplication)\n\n"
            "Previous stage output:\n{implement}\n\n"
            "If everything passes, reply with APPROVED. Otherwise list each "
            "violation with a ViolationCategory tag."
        ),
    ),
    PipelineNode(
        name="cleanup",
        agent_name="gatekeeper",
        depends_on=("review",),
        skip_if=_cleanup_skip_if,
        prompt_template=(
            "Final cleanup for issue #{issue_number}: {title}\n\n"
            "The auditor found these issues:\n{review}\n\n"
            "Fix all violations:\n"
            "1. Run ruff check --fix && ruff format\n"
            "2. Fix any mypy --strict errors\n"
            "3. Ensure all tests pass\n"
            "4. Push fixes to the existing PR branch\n\n"
            "Do NOT create a new PR. Push to the existing branch."
        ),
    ),
]


class RuntimeDispatcher:
    """Adapt the Builders 2.0 stage runtime to the pipeline dispatcher seam.

    Pipeline nodes name agents (quartermaster, mason, …); the runtime keys
    handlers by (WorkerName, stage). Stages are registered under the node
    name, and agents map onto the three runtime roles.
    """

    DEFAULT_WORKERS: ClassVar[dict[str, WorkerName]] = {
        "quartermaster": WorkerName.FRANK,
        "archie": WorkerName.FRANK,
        "frank": WorkerName.FRANK,
        "mason": WorkerName.MASON,
        "auditor": WorkerName.AUDITOR,
        "gatekeeper": WorkerName.AUDITOR,
    }

    def __init__(
        self,
        runtime: BuildersRuntime,
        *,
        workers: dict[str, WorkerName] | None = None,
        branch: str = "",
        workspace_ref: str = "",
    ) -> None:
        self._runtime = runtime
        self._workers = dict(workers) if workers is not None else dict(self.DEFAULT_WORKERS)
        self._branch = branch
        self._workspace_ref = workspace_ref

    def supports(self, agent_name: str, node_name: str) -> bool:
        worker = self._workers.get(agent_name)
        return worker is not None and self._runtime.supports(worker, node_name)

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        worker = self._workers[agent_name]
        request = RunRequest(
            run_id=f"{run_id}-{node_name}",
            worker=worker,
            stage=node_name,
            repo=str(context.get("repo", "")),
            issue_number=int(context.get("issue_number", 0)),
            branch=self._branch,
            workspace_ref=self._workspace_ref,
            context={"prompt": prompt},
        )
        result = await self._runtime.execute(request)
        if result.status in {RunStatus.FAILED, RunStatus.BLOCKED}:
            return DispatchResult(ok=False, error=result.summary)
        return DispatchResult(ok=True, output=result.summary)


class BuilderPipeline:
    """Executes the full issue-to-merge pipeline via GraphPipelineExecutor.

    Usage:
        pipeline = BuilderPipeline(dispatcher)
        run = await pipeline.execute(
            issue_number=42, title="Add caching", repo="acme/widget",
        )

    With spec-driven verification:
        pipeline = BuilderPipeline(dispatcher, spec_store=store, spec_verifier=verifier)
    """

    def __init__(
        self,
        dispatcher: PipelineDispatcher,
        *,
        spec_store: Any | None = None,
        spec_verifier: Any | None = None,
        code_index: Any | None = None,
        nodes: list[PipelineNode] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._spec_store = spec_store
        self._spec_verifier = spec_verifier
        self._code_index = code_index
        self._nodes = list(nodes) if nodes is not None else list(BUILDER_PIPELINE)
        self._runs: dict[str, PipelineRun] = {}

    async def execute(
        self,
        *,
        issue_number: int,
        title: str,
        repo: str,
        skip_decompose: bool = True,
        workspace_path: str = "",
    ) -> PipelineRun:
        """Run the full pipeline for an issue."""
        run_id = f"pipeline-{issue_number}"
        stages = [
            PipelineStage(
                name=node.name,
                agent_name=node.agent_name,
                prompt_template=node.prompt_template,
            )
            for node in self._nodes
        ]
        run = PipelineRun(
            id=run_id,
            issue_number=issue_number,
            title=title,
            repo=repo,
            stages=stages,
        )
        self._runs[run_id] = run

        # Populate context with pipeline parameters accessible to hooks and templates
        run.context.update(
            {
                "skip_decompose": skip_decompose,
                "issue_number": issue_number,
                "title": title,
                "repo": repo,
                "_spec_store": self._spec_store,
                "_spec_verifier": self._spec_verifier,
                "workspace_path": workspace_path,
                "_code_index": self._code_index,
            }
        )

        # Load spec if store is available
        spec = None
        if self._spec_store is not None:
            spec = await self._spec_store.get(issue_number)
            if spec is not None:
                run.context["_spec"] = spec
                run.context["spec"] = spec.to_dict()
                run.context["verifications"] = []

        # Emit spec immediately when decompose will be skipped (atomic issue)
        if self._spec_store is not None and spec is None and skip_decompose:
            spec = _emit_spec(issue_number, title, "")
            await self._spec_store.save(spec)
            run.context["_spec"] = spec
            run.context["spec"] = spec.to_dict()
            run.context["verifications"] = []

        run.context["spec_summary"] = build_spec_summary(spec) if spec is not None else ""

        # Wrap each node's on_complete with spec verification if configured
        nodes = self._wrap_nodes_with_verification(self._nodes)
        graph = PipelineGraph(nodes)
        executor = GraphPipelineExecutor(self._dispatcher)

        await executor.execute(graph, run)

        self._reconcile_stages(run)
        return run

    def _wrap_nodes_with_verification(self, nodes: list[PipelineNode]) -> list[PipelineNode]:
        """Return nodes whose on_complete also runs spec verification."""
        if self._spec_verifier is None:
            return list(nodes)

        result = []
        for node in nodes:
            original = node.on_complete

            async def _hook(
                run: PipelineRun,
                output: str,
                _orig: Any = original,
                _name: str = node.name,
            ) -> None:
                if _orig is not None:
                    await _orig(run, output)
                spec = run.context.get("_spec")
                verifier = run.context.get("_spec_verifier")
                if spec is None or verifier is None:
                    return
                verification = await verifier.verify(spec, _name, {})
                run.context.setdefault("verifications", []).append(verification.to_dict())
                if not verification.passed:
                    run.status = f"failed at {_name}"
                    run.failed_stage_error = (
                        f"Spec verification failed: {', '.join(verification.failures)}"
                    )

            result.append(replace(node, on_complete=_hook))
        return result

    def _reconcile_stages(self, run: PipelineRun) -> None:
        """Update PipelineStage statuses from executor results."""
        failed_name = ""
        if run.status.startswith("failed at "):
            failed_name = run.status[len("failed at ") :]

        for stage in run.stages:
            if stage.name == failed_name:
                stage.status = StageStatus.FAILED
                stage.error = run.failed_stage_error
            elif stage.name in run.context:
                stage.status = StageStatus.COMPLETED
            elif stage.name in run.skipped_stages:
                stage.status = StageStatus.SKIPPED
            # else: PENDING (default)

    def get_run(self, run_id: str) -> PipelineRun | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, object]]:
        return [r.to_dict() for r in self._runs.values()]
