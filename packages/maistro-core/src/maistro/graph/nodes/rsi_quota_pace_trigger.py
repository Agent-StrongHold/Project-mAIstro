"""`rsi.quota_pace_trigger` — pace RSI cycles against real quota headroom.

A sensor/trigger node, same shape as `jira.poll`/`airtable.poll` ("poll a
signal, decide"): reads how much request/token headroom the target model
currently has (`quota.rate_profile.cycles_remaining`, backed by whatever
`UsageSource` this node was wired with — no network call), combines that with
how much wall-clock time is left before a deadline, and emits exactly the
shape `agent.spawn_harness` needs so a DAG can wire this node straight into
one via a single edge.

`num_cycles = min(time_boxed_cap, quota_cap)` — the two-limb formula:
  - `time_boxed_cap`: (deadline - now) / time_per_cycle_s. However much quota
    remains, a cycle still takes wall-clock time, and the pacer shouldn't
    schedule more cycles than could possibly finish before the deadline.
  - `quota_cap`: `cycles_remaining(...)`, which is already rolling-window-
    correct per constraint (`rate_profile.py`) — this node does not assume a
    fixed "daily reset"; real providers gate on rolling windows, and
    `cycles_remaining` already accounts for that.

Fed by `config.rate_limits.resolve_rate_profile` (model alias -> profile) so
an alias with no configured profile yet gets the same permissive,
unconstrained fallback every other quota-aware code path gets, rather than
this node refusing to trigger anything.

The durable executor's `_resolve_inputs` merges a node's inputs as
`{**static_inputs, **upstream_output}` -- a flat, top-level merge. Since this
node's `context` output is itself a whole dict field, it would otherwise
*replace* (not merge with) whatever `context` a DAG author configured
statically on the downstream `agent.spawn_harness` node, silently dropping
`baseline_genome`/`candidate_genome` before dispatch. `RsiQuotaPaceTriggerIn.base_context`
is the fix: a DAG author supplies the harness-required context as *this*
node's own static input, and it's merged underneath the pacer-owned keys
(`num_cycles`, `model_alias`, `available_models`) rather than being lost.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.config.rate_limits import resolve_rate_profile
from maistro.quota.rate_profile import ModelRateProfile, UsageSource, cycles_remaining
from maistro.quota.usage_log import InMemoryUsageLog

from . import register_node
from .base import BaseNode, NodeContext


class RsiQuotaPaceTriggerIn(BaseModel):
    model_alias: str = Field(
        description="Model alias to check quota headroom for (models.toml convention, "
        "resolved via config.rate_limits.resolve_rate_profile)"
    )
    deadline_epoch_s: float = Field(
        description="Unix timestamp of the wall-clock deadline to pace cycles toward"
    )
    time_per_cycle_s: float = Field(gt=0, description="Estimated wall-clock seconds per RSI cycle")
    requests_per_cycle: float = Field(default=1.0, ge=0)
    tokens_per_cycle: float = Field(default=0.0, ge=0)
    images_per_cycle: float = Field(default=0.0, ge=0)
    scope_values: dict[str, str] = Field(
        default_factory=dict,
        description="Extra scope_key_fields values the resolved profile may need "
        "(e.g. api_key, endpoint) beyond provider/model",
    )
    base_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Harness-required context to pass through untouched (e.g. "
        "baseline_genome/candidate_genome for RsiCycleHarnessAdapter) -- the "
        "durable executor's input merge is flat, so this node's own `context` "
        "output would otherwise replace, not merge with, whatever a DAG author "
        "configured on the downstream agent.spawn_harness node.",
    )
    task: str = Field(default="RSI self-improvement cycle", description="Handed to the harness")
    harness_type: str = "rsi_cycle"
    timeout_seconds: int = Field(default=3600, description="Per-dispatch hard deadline (seconds)")


class RsiQuotaPaceTriggerOut(BaseModel):
    """Deliberately shaped like `agent_spawn_harness.SpawnHarnessIn` so a DAG
    can wire this node's output straight into that node's input via one edge —
    the executor's upstream-output-wins merge (`durable_runs/executor.py`'s
    `_resolve_inputs`) does the rest."""

    harness_type: str = "rsi_cycle"
    task: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 3600
    num_cycles: float = 0.0


@register_node
class RsiQuotaPaceTriggerNode(BaseNode[RsiQuotaPaceTriggerIn, RsiQuotaPaceTriggerOut]):
    kind: ClassVar[str] = "rsi.quota_pace_trigger"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = RsiQuotaPaceTriggerIn
    output_schema: ClassVar[type[BaseModel]] = RsiQuotaPaceTriggerOut
    cost_hint: ClassVar[float] = 0.5
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "RSI: quota-pace trigger"
    description: ClassVar[str] = (
        "Compute how many RSI cycles current quota headroom and time-to-deadline "
        "can support, and hand that count to agent.spawn_harness."
    )

    def __init__(
        self,
        source: UsageSource | None = None,
        *,
        rate_profile_resolver: Callable[[str], ModelRateProfile] = resolve_rate_profile,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        # Default-constructible like every other registered node kind
        # (`AgentSpawnHarnessNode` sets the same precedent for an unwired
        # seam): an empty, fresh InMemoryUsageLog reports zero usage so far —
        # the same state a freshly-booted process would actually have, not a
        # fabricated value.
        self._source: UsageSource = source if source is not None else InMemoryUsageLog()
        self._resolve_rate_profile = rate_profile_resolver
        self._now = now_fn

    async def _execute(
        self, inputs: RsiQuotaPaceTriggerIn, ctx: NodeContext
    ) -> RsiQuotaPaceTriggerOut:
        profile = self._resolve_rate_profile(inputs.model_alias)
        now = self._now()
        seconds_to_deadline = max(0.0, inputs.deadline_epoch_s - now)
        time_boxed_cap = seconds_to_deadline / inputs.time_per_cycle_s

        quota_cap = cycles_remaining(
            profile,
            self._source,
            requests_per_cycle=inputs.requests_per_cycle,
            tokens_per_cycle=inputs.tokens_per_cycle,
            images_per_cycle=inputs.images_per_cycle,
            scope_values=inputs.scope_values,
        )

        num_cycles = min(time_boxed_cap, quota_cap)

        return RsiQuotaPaceTriggerOut(
            harness_type=inputs.harness_type,
            task=inputs.task,
            context={
                # base_context first so pacer-owned keys always win over
                # anything accidentally duplicated there, while unrelated
                # keys (baseline_genome, candidate_genome, ...) pass through.
                **inputs.base_context,
                "num_cycles": num_cycles,
                "model_alias": inputs.model_alias,
                "available_models": [inputs.model_alias],
            },
            timeout_seconds=inputs.timeout_seconds,
            num_cycles=num_cycles,
        )
