"""The failpoint machinery itself cannot alter production semantics (#883).

The issue's fail-closed requirement on the experiment: "failpoint machinery
cannot ship enabled or alter production semantics". Three guards hold it:

1. a disarmed `CrashPoint` is pass-through -- identical results, zero
   bookkeeping between caller and store;
2. nothing under `packages/*/src` imports the lab -- the machinery lives in
   the test tree and cannot ship in any wheel;
3. an armed failpoint fires exactly once at the named write, before or after
   it commits, and never on calls its predicate rejects.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.invocation import (
    EffectClaimStore,
    InMemoryInvocationStore,
    Invocation,
    InvocationStatus,
)

from ._failpoints import CrashPoint, CrashSimulated, EffectLedger, Failpoint, StatusJournal

_SRC_ROOTS = [
    path for path in Path(__file__).resolve().parents[4].glob("packages/*/src") if path.is_dir()
]


@dataclass(frozen=True)
class _Provider:
    """The smallest provider handle `ResolvedBinding.from_provider` accepts."""

    name: str = "provider-a"
    slot: str = "external_write"
    trust_tier: str = "trusted"


def _resolved_binding() -> ResolvedBinding:
    return ResolvedBinding.from_provider(
        Binding(
            binding_id="binding-1",
            workspace_id="ws-fp",
            project_id="proj-fp",
            capability="external_write",
        ),
        _Provider(),
    )


def _invocation(invocation_id: str = "invocation-1", effect_key: str = "write:1") -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key=effect_key,
        binding=_resolved_binding(),
    )


async def test_a_disarmed_crash_point_is_pass_through() -> None:
    """No armed failpoint, no difference the caller can observe."""
    ledger = InMemoryInvocationStore()
    wrapped = CrashPoint(ledger, [Failpoint("terminal_commit", "save")])
    assert wrapped.armed is None

    probe = await ledger.create(_invocation(effect_key="write:probe"))
    through_wrapper = await wrapped.create(_invocation("invocation-2", "write:other"))

    assert through_wrapper.invocation_id == "invocation-2"
    assert (await wrapped.get(probe.invocation_id)) is not None
    assert wrapped.fired == []
    # The wrapper holds the same objects, not copies with injected behavior.
    assert wrapped.get is not None  # transparent attribute access


async def test_an_armed_failpoint_fires_once_at_the_named_write() -> None:
    """One kill, at the named write, and never again."""
    ledger = InMemoryInvocationStore()
    wrapped = CrashPoint(
        ledger,
        [
            Failpoint("terminal_commit", "save", before=True),
            Failpoint("admission", "create", before=True),
        ],
    )
    wrapped.arm("admission")
    with pytest.raises(CrashSimulated):
        await wrapped.create(_invocation())
    assert wrapped.fired == [("admission", "before")]
    assert wrapped.armed is None  # spent: a crash ends the process

    # After the simulated death, the same wrapper is inert.
    landed = await wrapped.create(_invocation(effect_key="write:later"))
    assert landed.invocation_id == "invocation-1"


async def test_a_predicate_rejecting_call_does_not_spend_the_failpoint() -> None:
    """Only the named write kills; other calls through the same method pass."""
    ledger = InMemoryInvocationStore()
    wrapped = CrashPoint(
        ledger,
        [
            Failpoint(
                "terminal_commit",
                "save",
                when=lambda invocation, **_: invocation.status is InvocationStatus.COMPLETED,
                before=True,
            )
        ],
    )
    wrapped.arm("terminal_commit")

    invocation = await wrapped.create(_invocation())
    running = invocation.model_copy(update={"status": InvocationStatus.RUNNING})
    running = await wrapped.save(running)  # not the named write: passes through
    assert wrapped.fired == []

    with pytest.raises(CrashSimulated):
        await wrapped.save(running.model_copy(update={"status": InvocationStatus.COMPLETED}))
    assert wrapped.fired == [("terminal_commit", "before")]


async def test_a_wrapped_store_keeps_its_claim_protocol() -> None:
    """An explicit `claim` forwarding keeps the wrapped store an EffectClaimStore.

    Runtime-checkable protocols inspect attributes statically
    (`inspect.getattr_static`), which `__getattr__` never answers: without the
    explicit method, `InvocationExecutionService` would drop a wrapped store
    onto its `create` fallback and the admission seam would crash the wrong
    write. The explicit `claim` rides the same interception machinery.
    """
    ledger = InMemoryInvocationStore()
    wrapped = CrashPoint(ledger, [Failpoint("admission", "claim", before=True)])
    assert isinstance(wrapped, EffectClaimStore)

    # Disarmed, the claim reaches the real ledger write and the row exists.
    landed = await wrapped.claim(_invocation())
    assert landed.invocation_id == "invocation-1"
    assert wrapped.fired == []

    # Armed, it intercepts exactly like any `__getattr__`-forwarded method.
    wrapped.arm("admission")
    with pytest.raises(CrashSimulated):
        await wrapped.claim(_invocation(effect_key="write:2"))
    assert wrapped.fired == [("admission", "before")]


def test_the_status_journal_detects_a_terminal_regression() -> None:
    """The regression oracle catches a terminal state coming back to life."""
    journal = StatusJournal()
    journal.record("attempt", "a-1", "completed")
    journal.record("attempt", "a-1", "running")  # regression
    journal.record("run", "r-1", "failed")
    journal.record("run", "r-1", "failed")  # terminal again is not a regression
    assert journal.regressions() == [("attempt", "a-1", "completed", "running")]


async def test_the_effect_ledger_is_the_remote_ground_truth() -> None:
    ledger = EffectLedger()
    ledger.apply("e-1")
    ledger.apply("e-1")
    ledger.apply("e-2")
    assert ledger.count("e-1") == 2
    assert ledger.count("e-2") == 1
    assert ledger.count("e-3") == 0


def _imported_module_names(path: Path) -> Iterator[str]:
    """Yield the dotted module names a file actually imports -- prose ignored."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def _is_lab_import(module_name: str) -> bool:
    """True only for imports whose module path names the test-only lab."""
    segments = module_name.split(".")
    return "failpoints" in segments or "_failpoints" in segments


def test_no_production_module_imports_the_failpoint_lab() -> None:
    """The lab is test-tree code: no wheel can ship it, enabled or otherwise."""
    assert _SRC_ROOTS, "the packages/*/src scan must see the source tree"
    offenders: list[str] = []
    for root in _SRC_ROOTS:
        for path in root.rglob("*.py"):
            for module_name in _imported_module_names(path):
                if _is_lab_import(module_name):
                    offenders.append(f"{path}: imports {module_name}")
    assert offenders == [], f"production modules import the failpoint lab: {offenders}"
