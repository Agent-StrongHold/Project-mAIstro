"""Deterministic Goal corpus and tool world for the planning-strategy benchmark.

A Goal is a question over a fixed fact base; its *program* is the minimal
sequence of tool calls a competent model needs to answer it. Every arm of the
benchmark (ReAct, plan-and-execute, canonical Graph) works the same corpus,
the same tool semantics, and the same ledger, so any measured difference
between arms is attributable to the planning/execution structure, not the
workload.

Everything here is deterministic: no randomness, no wall-clock reads, no
network. "Latency" is a synthetic per-call constant defined in ``_harness``
and is never measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Goal classes, one per planning shape the issue names.
SINGLE_LOOKUP = "single_lookup"
MULTI_STEP = "multi_step"
FAN_OUT = "fan_out"
DEAD_END = "dead_end"

#: Deterministic fact base. ``lookup`` is the only way to read it.
FACTS: dict[str, str] = {
    "db.host": "db-1.internal",
    "secrets.api.current": "key-a-111",
    "secrets.api.next": "key-b-222",
    "inv.widget": "5",
    "inv.gear": "7",
    "inv.bolt": "11",
}


@dataclass(frozen=True)
class ProgramStep:
    """One tool invocation in a Goal's minimal competent program."""

    tool: str
    args: dict[str, Any]

    def describe(self) -> str:
        if self.tool == "lookup":
            return f'lookup("{self.args["key"]}")'
        if self.tool == "combine":
            parts = ", ".join(f'"{p}"' for p in self.args["parts"])
            return f"combine([{parts}])"
        if self.tool == "submit":
            return f'submit("{self.args["answer"]}")'
        return f"{self.tool}({self.args!r})"


@dataclass(frozen=True)
class GoalSpec:
    """One benchmark Goal: the question every arm sees, plus the oracle."""

    goal_id: str
    goal_class: str
    question: str
    steps: tuple[ProgramStep, ...]
    expected_answer: str

    @property
    def minimal_tool_calls(self) -> int:
        """Tool calls a competent execution cannot do better than."""
        return len(self.steps)


def _submit(answer: str) -> ProgramStep:
    return ProgramStep(tool="submit", args={"answer": answer})


def build_corpus() -> tuple[GoalSpec, ...]:
    """The four representative Goal classes, ordered by program length."""
    return (
        GoalSpec(
            goal_id="lookup-db-host",
            goal_class=SINGLE_LOOKUP,
            question="What host is the database on? Answer as 'host=<value>'.",
            steps=(
                ProgramStep(tool="lookup", args={"key": "db.host"}),
                _submit("host=db-1.internal"),
            ),
            expected_answer="host=db-1.internal",
        ),
        GoalSpec(
            goal_id="rotate-api-key",
            goal_class=MULTI_STEP,
            question=(
                "Pair the current and next API secrets into one rotation record "
                "joined by '+' and submit it as 'rotation=<pair>'."
            ),
            steps=(
                ProgramStep(tool="lookup", args={"key": "secrets.api.current"}),
                ProgramStep(tool="lookup", args={"key": "secrets.api.next"}),
                ProgramStep(
                    tool="combine",
                    args={"parts": ["key-a-111", "key-b-222"]},
                ),
                _submit("rotation=key-a-111+key-b-222"),
            ),
            expected_answer="rotation=key-a-111+key-b-222",
        ),
        GoalSpec(
            goal_id="inventory-audit",
            goal_class=FAN_OUT,
            question=(
                "Read the widget, gear, and bolt inventory counts, join them "
                "with '|' in that order, and submit as 'audit=<joined>'."
            ),
            steps=(
                ProgramStep(tool="lookup", args={"key": "inv.widget"}),
                ProgramStep(tool="lookup", args={"key": "inv.gear"}),
                ProgramStep(tool="lookup", args={"key": "inv.bolt"}),
                ProgramStep(tool="combine", args={"parts": ["5", "7", "11"]}),
                _submit("audit=5|7|11"),
            ),
            expected_answer="audit=5|7|11",
        ),
        GoalSpec(
            goal_id="ghost-dependency",
            goal_class=DEAD_END,
            question=(
                "Report the value of ghost.key as 'ghost=<value>'; if the key "
                "does not exist, report exactly that instead of guessing."
            ),
            steps=(ProgramStep(tool="lookup", args={"key": "ghost.key"}),),
            expected_answer="infeasible: unknown key 'ghost.key'",
        ),
    )


@dataclass
class ToolCallRecord:
    """One executed tool call, as the world observed it."""

    tool: str
    args: dict[str, Any]
    result: str
    ok: bool


@dataclass
class ToolLedger:
    """Ground truth for every tool execution, shared by all three arms.

    The benchmark's cost and error metrics are read from here -- never from a
    strategy's own bookkeeping -- so all arms are scored by the same referee.
    """

    records: list[ToolCallRecord] = field(default_factory=list)
    #: key -> remaining transient failures to inject on the next lookups
    transient_failures: dict[str, int] = field(default_factory=dict)

    def fail_next_lookup(self, key: str, times: int = 1) -> None:
        """Arm the world so the next ``times`` lookups of ``key`` fail transiently."""
        self.transient_failures[key] = self.transient_failures.get(key, 0) + times

    @property
    def tool_calls(self) -> int:
        return len(self.records)

    @property
    def tool_errors(self) -> int:
        return sum(1 for r in self.records if not r.ok)

    def calls_for(self, step: ProgramStep) -> list[ToolCallRecord]:
        return [r for r in self.records if r.tool == step.tool and r.args == step.args]

    def reset(self) -> None:
        self.records.clear()
        self.transient_failures.clear()


class GoalWorld:
    """The deterministic tool world: lookup / combine / submit."""

    def __init__(self, ledger: ToolLedger) -> None:
        self.ledger = ledger
        self.submissions: list[str] = []

    async def execute(self, tool: str, args: dict[str, Any]) -> str:
        result = self._execute(tool, args)
        ok = not result.startswith("Error")
        self.ledger.records.append(ToolCallRecord(tool=tool, args=dict(args), result=result, ok=ok))
        return result

    def _execute(self, tool: str, args: dict[str, Any]) -> str:
        if tool == "lookup":
            key = str(args.get("key", ""))
            remaining = self.ledger.transient_failures.get(key, 0)
            if remaining > 0:
                self.ledger.transient_failures[key] = remaining - 1
                return f"Error: transient fault while reading '{key}' (injected)"
            value = FACTS.get(key)
            if value is None:
                return f"Error: unknown key '{key}'"
            return value
        if tool == "combine":
            parts = list(args.get("parts", []))
            if not parts or not all(isinstance(p, str) for p in parts):
                return "Error: combine needs a non-empty list of string parts"
            return "|".join(parts)
        if tool == "submit":
            answer = str(args.get("answer", ""))
            self.submissions.append(answer)
            return f"submitted: {answer}"
        return f"Error: unknown tool '{tool}'"

    def submitted_answers(self) -> list[str]:
        return list(self.submissions)

    def reset(self) -> None:
        self.ledger.reset()
        self.submissions.clear()


#: Prefix every transient (injected) tool error carries. The policy retries
#: these once; unknown-key errors are true dead ends and are never retried.
TRANSIENT_ERROR_PREFIX = "Error: transient fault"

#: Prefix the world uses for a missing key. A competent model stops here.
UNKNOWN_KEY_PREFIX = "Error: unknown key"
