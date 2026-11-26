"""Adaptive escalation/routing vs fixed-routing baselines on one workload (M4-I).

Epic #106's comparison exit evidence: quality-triggered escalation and
text/image observation selection must be *compared with a fixed-routing
baseline on the same workload*, recording task success, cost, latency and
failure cases. This module is that comparison, run end to end through the
production path — the real ``llm.summarize`` node, the governed Binding ->
Invocation egress, and the durable executor's supervision fold — against a
deterministic model-dependent stub gateway.

Determinism contract: every number the comparison records (quality, cost,
latency, failure cases) is a function of the workload, the stub's
model-dependent behavior, and the registry's price/latency metadata. Cost is
computed with the production ``compute_cost_cents`` over the tokens the stub
reports; latency is the registry's per-model ``latency_p50_ms`` summed over
physical requests — modeled per-request latency, not wall-clock. The recorded
table in ``docs/benchmarks/m4i-adaptive-vs-fixed-baseline.md`` is this
module's output.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import InMemoryDurableRunStore, run_durable_graph
from maistro.graph.nodes.llm_summarize import LlmSummarizeNode
from maistro.graph.verification.quality import summarize_quality
from maistro.graph.verification.routing import classify_observation
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata, compute_cost_cents
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

#: The workload's declared success bar: the final accepted summary must score
#: at least this under the production ``summarize_quality`` scorer. The
#: adaptive arm declares the same number as its escalation ``quality_floor``.
QUALITY_BAR = 0.7

_MODEL_META: dict[str, ModelMetadata] = {
    meta.name: meta
    for meta in (
        ModelMetadata(
            name="flash-lite",
            provider="benchmark-gateway",
            cost_per_1k_input=0.075,
            cost_per_1k_output=0.30,
            latency_p50_ms=100,
        ),
        ModelMetadata(
            name="pro",
            provider="benchmark-gateway",
            cost_per_1k_input=0.60,
            cost_per_1k_output=2.40,
            latency_p50_ms=900,
        ),
        ModelMetadata(
            name="vision-pro",
            provider="benchmark-gateway",
            cost_per_1k_input=0.45,
            cost_per_1k_output=1.80,
            latency_p50_ms=500,
        ),
    )
}

#: The governed node routes through the same registry metadata the record
#: prices and times the workload with.
REGISTRY = InMemoryProviderRegistry(models=tuple(_MODEL_META.values()))

_VISION_ALIASES = frozenset({"vision-pro"})
_SALIENT = re.compile(r"[A-Za-z0-9]{5,}")
_FILLER = "we sat and had tea, then ate cake at four pm. "

_EASY_1_HEAD = (
    "Status dispatch: the migration cutover finished smoothly; the "
    "observability dashboard rollout reached production, and incident "
    "response improved everywhere. "
)
_EASY_2_HEAD = (
    "Quarterly summary: infrastructure spending decreased after "
    "consolidation, while deployment frequency increased across regions. "
)
_EASY_3_HEAD = (
    "Customer feedback: the onboarding walkthrough reduced confusion, and "
    "support tickets dropped following documentation improvements. "
)
_HARD_TAIL = (
    "Escalation report: the deployment rollback triggered overnight, because "
    "the canary signaled failure; incident response documented the upgrade "
    "pipeline afterwards. "
)
_VERY_HARD_TAIL = (
    "Late entries: alpha bravo china delta india oscar romeo tango victor "
    "yankee quebec sierra logged. "
)
_IMAGE_NOTE = (
    "Companion note: the screenshot shows the deployment console after the upgrade finished. "
)
_SCREENSHOT_URI = "data:image/png;base64,QUJDREVG"

#: One workload, four difficulty shapes; every arm runs exactly this.
#: ``easy``: the salient payload sits in the first half and survives even the
#: truncating cheap model. ``hard``: the salient payload sits in the second
#: half, so the cheap model's truncation misses it and supervision escalates.
#: ``very_hard``: salient tokens are all 5-6 characters, which every strong
#: rung's >=7-character retention drops — the ladder exhausts and accepts a
#: bounded shortfall. ``image``: an image observation that only a vision alias
#: may serve.
WORKLOAD: tuple[dict[str, Any], ...] = (
    {"task": "easy-standup", "text": _EASY_1_HEAD + _FILLER * 10},
    {"task": "easy-quarterly", "text": _EASY_2_HEAD + _FILLER * 10},
    {"task": "easy-feedback", "text": _EASY_3_HEAD + _FILLER * 10},
    {"task": "hard-incident", "text": _FILLER * 10 + _HARD_TAIL},
    {
        "task": "image-screenshot",
        "text": "Describe what changed.",
        "observations": [_SCREENSHOT_URI, _IMAGE_NOTE],
    },
    {"task": "very-hard-callsigns", "text": _FILLER * 10 + _VERY_HARD_TAIL},
)


@dataclass
class ServedRequest:
    """One physical completion the stub gateway served."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    had_image_part: bool


@dataclass
class TaskOutcome:
    """One task's result under one routing arm."""

    task: str
    run_status: RunStatus
    quality: float
    requests: list[ServedRequest] = field(default_factory=list)
    node_runs: int = 0

    @property
    def success(self) -> bool:
        return self.run_status is RunStatus.COMPLETED and self.quality >= QUALITY_BAR

    @property
    def failure_case(self) -> str | None:
        if self.success:
            return None
        if self.run_status is not RunStatus.COMPLETED:
            return "refused"
        return "shortfall"

    @property
    def cost_cents(self) -> float:
        return sum(
            compute_cost_cents(_MODEL_META[req.model], req.prompt_tokens, req.completion_tokens)
            for req in self.requests
        )

    @property
    def latency_ms(self) -> int:
        return sum(_MODEL_META[req.model].latency_p50_ms for req in self.requests)


@dataclass
class ArmResult:
    """One routing arm's outcome over the whole workload."""

    arm: str
    tasks: dict[str, TaskOutcome]

    @property
    def successes(self) -> set[str]:
        return {task for task, outcome in self.tasks.items() if outcome.success}

    @property
    def failures(self) -> dict[str, str]:
        return {
            task: outcome.failure_case or ""
            for task, outcome in self.tasks.items()
            if outcome.failure_case is not None
        }

    @property
    def cost_cents(self) -> float:
        return sum(outcome.cost_cents for outcome in self.tasks.values())

    @property
    def latency_ms(self) -> int:
        return sum(outcome.latency_ms for outcome in self.tasks.values())


class _StubResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _StubGateway:
    """Deterministic, model-dependent completions at the governed wire.

    ``flash-lite`` truncates its input at the halfway mark — the classic
    cheap-model early-stop. ``pro`` and ``vision-pro`` answer with a bullet
    list of the salient tokens they retain, but only tokens of seven or more
    characters: short distinctive tokens fall through every strong rung, which
    is exactly what the ``very_hard`` workload shape probes. A vision alias
    serves image content parts; a text-only alias asked for one fails like a
    provider would.

    The summary behavior is a function of the *user* text only — the source
    the quality scorer measures — never of the system prompt.
    """

    def __init__(self) -> None:
        self.served: list[ServedRequest] = []

    #: The pooled shared-client cache probes ``is_closed``; the stub is
    #: always open, so every governed call reuses it.
    is_closed = False

    async def __aenter__(self) -> _StubGateway:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def post(self, url: str, *, json: Any = None, headers: Any = None) -> Any:
        model = str(json["model"])
        system = json["messages"][0]["content"]
        user = json["messages"][1]["content"]
        parts: list[Any] = [user] if isinstance(user, str) else list(user)
        text_parts = [
            part if isinstance(part, str) else part["text"]
            for part in parts
            if isinstance(part, str) or (isinstance(part, dict) and part.get("type") == "text")
        ]
        has_image = any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in parts
        )
        if has_image and model not in _VISION_ALIASES:
            return _StubResponse(400, {"error": "image content part to a text-only model"})
        source = "\n".join(text_parts)
        summary = self._summary(model, source)
        prompt_chars = len(source) + len(system) + (30 if has_image else 0)
        served = ServedRequest(
            model=model,
            prompt_tokens=math.ceil(prompt_chars / 4),
            completion_tokens=math.ceil(len(summary) / 4),
            had_image_part=has_image,
        )
        self.served.append(served)
        return _StubResponse(
            200,
            {
                "model": model,
                "choices": [{"message": {"content": summary}}],
                "usage": {
                    "prompt_tokens": served.prompt_tokens,
                    "completion_tokens": served.completion_tokens,
                },
            },
        )

    @staticmethod
    def _summary(model: str, text: str) -> str:
        if model == "flash-lite":
            cut = text[: max(1, len(text) // 2)]
            boundary = cut.rfind(" ")
            return cut[:boundary] if boundary > 0 else cut
        retained = [
            token for token in dict.fromkeys(_SALIENT.findall(text.lower())) if len(token) >= 7
        ]
        return "\n".join(f"- {token}" for token in retained)


class _StubClientFactory:
    """Stand in for ``httpx.AsyncClient``: any construction yields the stub."""

    def __init__(self, stub: _StubGateway) -> None:
        self._stub = stub

    def __call__(self, *args: Any, **kwargs: Any) -> _StubGateway:
        return self._stub


@contextmanager
def install_stub_gateway() -> Iterator[_StubGateway]:
    """Serve every governed completion from the deterministic stub.

    Also points the node's gateway configuration at the stub, so the
    comparison needs no live provider: the governed egress still crosses the
    full Binding -> Invocation boundary — only the far side of the wire is
    deterministic.
    """
    import httpx

    stub = _StubGateway()
    original_client = httpx.AsyncClient
    saved_env = {
        name: os.environ.get(name) for name in ("MAISTRO_LLM_BASE_URL", "MAISTRO_LLM_API_KEY")
    }
    httpx.AsyncClient = _StubClientFactory(stub)  # type: ignore[assignment]
    os.environ["MAISTRO_LLM_BASE_URL"] = "http://benchmark-gateway:4000"
    os.environ["MAISTRO_LLM_API_KEY"] = "benchmark-key"
    try:
        yield stub
    finally:
        httpx.AsyncClient = original_client  # type: ignore[assignment]
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _arm_configs() -> dict[str, dict[str, Any]]:
    """The four routing arms compared over the workload.

    Only the routing configuration differs — never the workload. ``adaptive``
    declares the cheap-first escalation ladder plus a vision alias for image
    observations; the fixed arms pin exactly one alias for everything, which
    is what a non-adaptive deployment does.
    """
    return {
        "adaptive": {
            "model": "flash-lite",
            "image_model": "vision-pro",
            "policies": {
                "max_attempts": 2,
                "escalation_ladder": {
                    "models": ["flash-lite", "pro"],
                    "quality_floor": QUALITY_BAR,
                },
            },
        },
        "fixed-cheap": {"model": "flash-lite", "image_model": "", "policies": {}},
        "fixed-strong": {"model": "pro", "image_model": "", "policies": {}},
        "fixed-vision": {"model": "vision-pro", "image_model": "vision-pro", "policies": {}},
    }


async def _governed_node(project_id: str) -> LlmSummarizeNode:
    """A real ``llm.summarize`` node over a fresh governed effect context."""
    from datetime import UTC, datetime

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.providers.llm_gateway import (
        DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )
    from maistro.credentials.types import CredentialRecord

    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            binding_id="m4i-baseline-binding",
            workspace_id="w1",
            project_id=project_id,
            capability="model.chat",
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        )
    )
    effects.credentials.add(
        workspace_id="w1",
        project_id=project_id,
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="benchmark-key",
        ),
    )
    return LlmSummarizeNode(
        registry=REGISTRY, router=CostAwareRouter(REGISTRY), effect_context=effects
    )


def _resolver_for(node: LlmSummarizeNode) -> Any:
    """A node resolver closing over one node instance (loop-safe binding)."""

    def resolve(_node_id: str, _graph: Any) -> LlmSummarizeNode:
        return node

    return resolve


async def run_comparison() -> dict[str, ArmResult]:
    """Run the same workload under every arm; collect the comparison record."""
    results: dict[str, ArmResult] = {}
    with install_stub_gateway() as stub:
        for arm, config in _arm_configs().items():
            projects = InMemoryProjectScopeStore()
            root = await projects.create_root("w1")
            project = await projects.create(
                workspace_id="w1", parent_project_id=root.project_id, name="w1"
            )
            node = await _governed_node(project.project_id)
            run_store = InMemoryRunStore(project_store=projects)
            outcomes: dict[str, TaskOutcome] = {}
            for work in WORKLOAD:
                graph = Graph(
                    workspace_id="w1",
                    project_id=project.project_id,
                    name=f"{arm}-{work['task']}",
                    nodes=[
                        Node(
                            node_id="step",
                            node_type="llm.summarize",
                            inputs={
                                "text": work["text"],
                                "observations": list(work.get("observations", [])),
                                "model": config["model"],
                                "image_model": config["image_model"],
                                "binding_id": "m4i-baseline-binding",
                            },
                            policies=dict(config["policies"]),
                        )
                    ],
                )
                admitted = await run_store.create_run(
                    graph,
                    initial_status=RunStatus.QUEUED,
                    actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
                )
                served_before = len(stub.served)
                record = await run_durable_graph(
                    graph,
                    store=InMemoryDurableRunStore(),
                    node_resolver=_resolver_for(node),
                    run_id=admitted.run_id,
                    run_store=run_store,
                )
                final = record.node_runs[-1].result if record.node_runs else None
                summary = str(final.get("summary", "")) if isinstance(final, dict) else ""
                # The same source the node measures against: the text input
                # plus the text half of any observations — an image payload is
                # not text and cannot be covered by a text summary.
                text_payloads = [
                    payload
                    for payload in work.get("observations", [])
                    if classify_observation(payload) == "text"
                ]
                source_for_quality = "\n\n".join([*text_payloads, work["text"]]).strip()
                outcomes[work["task"]] = TaskOutcome(
                    task=work["task"],
                    run_status=record.status,
                    quality=summarize_quality(source_for_quality, summary),
                    requests=list(stub.served[served_before:]),
                    node_runs=len(record.node_runs),
                )
            results[arm] = ArmResult(arm=arm, tasks=outcomes)
    return results


def render_markdown_table(results: dict[str, ArmResult]) -> str:
    """The recorded comparison: success, cost, latency, failure cases per arm."""
    lines = [
        "| arm | tasks succeeded | cost (cents) | modeled latency (ms) | failure cases |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arm, result in results.items():
        failures = ", ".join(f"{task}:{kind}" for task, kind in sorted(result.failures.items()))
        lines.append(
            f"| {arm} | {len(result.successes)}/{len(result.tasks)} "
            f"| {result.cost_cents:.3f} | {result.latency_ms} | {failures or 'none'} |"
        )
    return "\n".join(lines)


async def test_adaptive_matches_the_strongest_fixed_baseline_on_success() -> None:
    """Adaptive routing recovers every task the all-vision baseline does."""
    results = await run_comparison()
    expected = {
        "easy-standup",
        "easy-quarterly",
        "easy-feedback",
        "hard-incident",
        "image-screenshot",
    }
    assert results["adaptive"].successes == expected
    assert results["fixed-vision"].successes == expected
    # The very-hard task defeats every rung: both arms accept a bounded
    # shortfall rather than looping — the floor is a floor, not a verdict.
    very_hard = results["adaptive"].tasks["very-hard-callsigns"]
    assert very_hard.failure_case == "shortfall"
    assert very_hard.run_status is RunStatus.COMPLETED


async def test_fixed_routing_failure_cases() -> None:
    """What each fixed alias loses on the same workload."""
    results = await run_comparison()
    assert results["fixed-cheap"].failures == {
        "hard-incident": "shortfall",
        "image-screenshot": "refused",
        "very-hard-callsigns": "shortfall",
    }
    assert results["fixed-strong"].failures == {
        "image-screenshot": "refused",
        "very-hard-callsigns": "shortfall",
    }
    # The refusal is the loud one: the run fails rather than re-encoding the
    # image observation as text, and no model call crossed the wire.
    refused = results["fixed-cheap"].tasks["image-screenshot"]
    assert refused.run_status is RunStatus.FAILED
    assert refused.requests == []


async def test_adaptive_spends_less_than_the_all_vision_baseline() -> None:
    """Cheap-first escalation plus modality routing costs less than vision
    everywhere on this workload: easy tasks bill the cheap rung, and only
    quality shortfalls pay for a stronger one."""
    results = await run_comparison()
    adaptive, fixed_vision = results["adaptive"], results["fixed-vision"]
    assert adaptive.cost_cents < fixed_vision.cost_cents
    assert adaptive.latency_ms < fixed_vision.latency_ms


async def test_escalation_pays_double_on_the_tasks_it_escalates() -> None:
    """The honest trade-off, recorded: an escalated task runs twice — its
    cheap visit was already billed — so it costs and waits more than routing
    it straight to the strong alias would have."""
    results = await run_comparison()
    for task in ("hard-incident", "very-hard-callsigns"):
        adaptive_task = results["adaptive"].tasks[task]
        vision_task = results["fixed-vision"].tasks[task]
        assert len(adaptive_task.requests) == 2
        assert {req.model for req in adaptive_task.requests} == {"flash-lite", "pro"}
        assert adaptive_task.cost_cents > vision_task.cost_cents
        assert adaptive_task.latency_ms > vision_task.latency_ms
    # Easy tasks never escalate: one cheap visit each.
    for task in ("easy-standup", "easy-quarterly", "easy-feedback"):
        outcome = results["adaptive"].tasks[task]
        assert [req.model for req in outcome.requests] == ["flash-lite"]
        assert outcome.node_runs == 1


async def test_escalation_stays_within_budget_on_the_workload() -> None:
    """Supervision is bounded: every task, escalated or not, stays within the
    declared two-visit budget, with one physical request per visit."""
    results = await run_comparison()
    for task in ("hard-incident", "very-hard-callsigns"):
        outcome = results["adaptive"].tasks[task]
        assert outcome.node_runs == 2
        assert len(outcome.requests) == outcome.node_runs
    for outcome in results["adaptive"].tasks.values():
        assert outcome.node_runs <= 2
        assert len(outcome.requests) <= 2


async def test_the_recorded_table_covers_all_four_measures() -> None:
    """The comparison artifact records success, cost, latency, failures."""
    results = await run_comparison()
    table = render_markdown_table(results)
    rows = [line for line in table.splitlines() if line.startswith("| ")]
    assert len(rows) == len(results) + 2  # header + separator + one row per arm
    expected_success_counts = {
        "adaptive": "5/6",
        "fixed-cheap": "3/6",
        "fixed-strong": "4/6",
        "fixed-vision": "5/6",
    }
    for arm, succeeded in expected_success_counts.items():
        row = next(line for line in rows if line.startswith(f"| {arm} "))
        assert succeeded in row
        assert "shortfall" in row or "none" in row


@pytest.mark.contract("behavioral")
async def test_forcing_fixed_routing_records_the_failures_adaptivity_avoids() -> None:
    """The comparison is load-bearing: without the adaptive arm's escalation
    and vision routing, the same workload records the failures the issue's
    exit evidence names — shipped shortfalls and refused image tasks."""
    results = await run_comparison()
    cheap = results["fixed-cheap"]
    shortfall = [task for task, kind in cheap.failures.items() if kind == "shortfall"]
    refused = [task for task, kind in cheap.failures.items() if kind == "refused"]
    assert "hard-incident" in shortfall
    assert "image-screenshot" in refused
