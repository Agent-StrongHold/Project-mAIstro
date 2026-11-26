"""M8-A16 research harness — Lean/Leanstral + Rust/Aeneas feasibility for a tiny
MAIstro correctness kernel.

Issue #897 (leaf of epic #880, initiative #879). Hypothesis under study: Lean
(with a model-driven autoformalization assistant) and a Rust
Charon/Aeneas translation path can provide materially stronger assurance for a
very small deterministic correctness kernel, but only if model/implementation
fidelity is credible enough to justify the added tooling complexity.

Canonical seam: the execution-state transition legality kernel of
``packages/maistro-core/src/maistro/runs/lifecycle.py`` — ``RUN_TRANSITIONS``,
``ATTEMPT_TRANSITIONS``, ``TERMINAL_RUN_STATUSES`` and
``TERMINAL_ATTEMPT_STATUSES`` plus the pure functions that consume them
(``transition_path``, ``latest_node_runs``, ``check_completion_is_earned``).
This is the issue's first candidate kernel shape, chosen because it is the
smallest deterministic decision surface on the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt spine.

What this harness DOES (all of it in deterministic CI, no external toolchain):

- mechanically extracts the transition tables from the *real production
  source* by AST parsing (text read, never an import — the extraction IS the
  first step of the "Python semantic-model path": the model is derived from
  the implementation rather than transcribed);
- equates the embedded Lean 4 kernel (``LEAN_KERNEL``) and embedded safe
  sequential Rust kernel (``RUST_KERNEL``) against that extraction — status
  universes, terminal sets and every transition row — so the artifact tables
  cannot silently drift from the production table;
- machine-checks in Python the exact propositions the Lean artifact states as
  theorems (terminal statuses absorb, no self-loops, every non-terminal status
  reaches every terminal status, path-exists-iff-reachable, path steps legal
  and shortest, deterministic exploration), one dual per theorem;
- measures the mechanically-translatable fraction of the production module
  itself (pydantic/clock boundaries vs pure decision logic), which is the
  measured answer to the issue's "what percentage of relevant logic can be
  mechanically translated";
- records the evidence-question answers, toolchain reality and the terminal
  disposition as frozen advisory records.

What this harness does NOT do (recorded, never claimed): no Lean proof is
machine-checked (no elan/lean in this repository's deterministic CI), no Rust
crate is built (no cargo), no Charon/Aeneas translation was run, and the
Leanstral free API was not exercised (no network in CI). The Lean and Rust
artifacts are real, self-contained and hand-checkable; compiling/checking them
is step 1 of the real experiment, and until that happens nothing here is
evidence of assurance — only evidence about the feasibility surface, which is
what this leaf asked to measure.

Trust boundary (the epic contract, enforced by construction):

- Every result produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control. It imports nothing from ``maistro`` at all
  (AST-checked below), so it cannot become an authority by accident (M8
  guardrails 1-2).
- The production module is read as a projection source and never written; the
  Lean/Rust artifacts are projections of that one authority, re-equated on
  every test run. There is no second authority: a table edit in production
  that is not mirrored in the artifacts fails this suite loudly, and a table
  edit mirrored here without production fails it just as loudly.
- Results are frozen records; they cannot be mutated into authorization after
  the fact (M8 guardrail 3: absence of toolchain evidence is recorded as
  absence, not simulated).

The experiment record and terminal disposition (WATCH) live in
``docs/research/897-lean-leanstral-rust-aeneas-correctness-kernel.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-A16 output as
#: authorization. No adoption routes anywhere from here: production ownership
#: of Run/NodeRun/Attempt lifecycle semantics stays with maistro-core's runs
#: package and the ADRs that govern it (ADR-081226-a66b, ADR-082426-19ed).
ADVISORY_ONLY = True

#: Terminal disposition recorded in the research note. WATCH: the equivalence
#: machinery runs and is real, but no Lean proof was machine-checked, no Rust
#: crate was built, no Aeneas translation ran, and the Leanstral API was not
#: exercised — the external technologies are not ready *for this repository's
#: deterministic evidence pipeline*, and the triggers for reassessment are
#: recorded in the research note.
RESEARCH_DISPOSITION = "WATCH"

#: Production kernel sources, read as text and never imported or written.
#: parents[0]=tests, [1]=maistro-rsi, [2]=packages, [3]=repo root.
PRODUCTION_KERNEL = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "maistro-core"
    / "src"
    / "maistro"
    / "runs"
    / "lifecycle.py"
)
#: The status enums and terminal sets are defined one module up; the tables in
#: lifecycle.py are built from them, so fidelity needs both files.
PRODUCTION_MODEL = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "maistro-core"
    / "src"
    / "maistro"
    / "runs"
    / "model.py"
)

#: Status names are canonicalized across the three languages by case-folding
#: and underscore removal: Python ``TIMED_OUT`` / Rust ``TimedOut`` / Lean
#: ``timedOut`` all canonicalize to ``timedout``. For this table, canonical
#: order agrees with production's ``sorted(..., key=lambda item: item.value)``
#: exploration order (``timed_out`` and ``timedout`` sort to the same place),
#: which is the order the Rust kernel's table slices are written in.


class KernelExtractionError(Exception):
    """The production kernel could not be extracted as a literal table.

    This is the desired failure mode under drift: if ``lifecycle.py`` stops
    defining the tables as literal frozenset rows, the mechanical extraction —
    and therefore the equivalence check between production and the Lean/Rust
    artifacts — is void, and this research suite must fail loudly rather than
    equate a stale snapshot.
    """


# ---------------------------------------------------------------------------
# Records — frozen, advisory evidence only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolchainRecord:
    """One external tool's reality at this head, recorded not simulated.

    ``available`` is an authoring-time fact about this repository's
    deterministic CI, pinned as a constant so the record is deterministic on
    any machine; ``exercised`` says whether THIS research actually ran it.
    """

    name: str
    available: bool
    exercised: bool
    reason: str


@dataclass(frozen=True)
class EquivalenceRow:
    """One transition row equated across production, Lean and Rust."""

    status: str
    production: tuple[str, ...]
    lean: tuple[str, ...]
    rust: tuple[str, ...]


@dataclass(frozen=True)
class TranslatabilityRecord:
    """One production function's mechanical-translation classification."""

    name: str
    translatable: bool
    reason: str


@dataclass(frozen=True)
class FeasibilityReport:
    """The leaf's evidence-question answers as one frozen record."""

    kernel: str
    statuses: tuple[str, ...]
    terminal_statuses: tuple[str, ...]
    attempt_statuses: tuple[str, ...]
    equivalence_rows: tuple[EquivalenceRow, ...]
    kernel_extraction_coverage: str
    module_defs_total: int
    module_defs_translatable: int
    module_translatable_pct: int
    translatability: tuple[TranslatabilityRecord, ...]
    aeneas_breakers: tuple[str, ...]
    maintenance_model: str
    defect_class_beyond_existing_testing: str
    rust_boundary_verdict: str
    second_authority_verdict: str
    leanstral: ToolchainRecord
    toolchains: tuple[ToolchainRecord, ...]
    disposition: str
    reassessment_triggers: tuple[str, ...]


# ---------------------------------------------------------------------------
# Production extraction — the "Python semantic-model path", step 1
# ---------------------------------------------------------------------------


def _canonical(status: str) -> str:
    return status.lower().replace("_", "")


def _read_production_source() -> str:
    """Read the production kernel modules as text. Never imported, never written."""
    return (
        PRODUCTION_KERNEL.read_text(encoding="utf-8")
        + "\n\n"
        + PRODUCTION_MODEL.read_text(encoding="utf-8")
    )


def _assignment_value(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if isinstance(node, ast.AnnAssign) and (
            isinstance(node.target, ast.Name) and node.target.id == name
        ):
            if node.value is None:
                break
            return node.value
    raise KernelExtractionError(f"production kernel: no literal assignment named {name!r}")


def _eval_status_set(node: ast.expr, source_name: str) -> frozenset[str]:
    """Evaluate ``frozenset({Enum.MEMBER, ...})``, ``frozenset()`` or a bare literal set."""
    inner = node
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "frozenset"
    ):
        if not node.args and not node.keywords:
            return frozenset()
        if len(node.args) != 1:
            raise KernelExtractionError(f"{source_name}: frozenset must take one literal set")
        inner = node.args[0]
    if not isinstance(inner, (ast.Set, ast.List, ast.Tuple)):
        raise KernelExtractionError(
            f"{source_name}: expected a literal set, found {type(inner).__name__}"
        )
    members: set[str] = set()
    for element in inner.elts:
        if not (
            isinstance(element, ast.Attribute)
            and isinstance(element.value, ast.Name)
            and element.value.id in {"RunStatus", "AttemptStatus"}
        ):
            raise KernelExtractionError(
                f"{source_name}: expected Enum.MEMBER members, found {ast.dump(element)}"
            )
        members.add(_canonical(element.attr))
    return frozenset(members)


def _extract_status_universe(source: str, class_name: str) -> frozenset[str]:
    """Extract an enum's member universe from its ``class X(StrEnum)`` block."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            members: set[str] = set()
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name):
                            members.add(_canonical(target.id))
            if not members:
                raise KernelExtractionError(f"{class_name}: no literal members found")
            return frozenset(members)
    raise KernelExtractionError(f"production kernel: no enum class named {class_name!r}")


def _extract_transition_table(source: str, table_name: str) -> dict[str, frozenset[str]]:
    """Extract ``RUN_TRANSITIONS``-shaped tables as literal data, or fail loudly."""
    tree = ast.parse(source)
    value = _assignment_value(tree, table_name)
    if not isinstance(value, ast.Dict):
        raise KernelExtractionError(
            f"{table_name}: expected a dict literal, found {type(value).__name__}"
        )
    table: dict[str, frozenset[str]] = {}
    for key, item in zip(value.keys, value.values, strict=True):
        if not (
            isinstance(key, ast.Attribute)
            and isinstance(key.value, ast.Name)
            and key.value.id in {"RunStatus", "AttemptStatus"}
        ):
            raise KernelExtractionError(f"{table_name}: keys must be Enum.MEMBER members")
        table[_canonical(key.attr)] = _eval_status_set(item, f"{table_name}[{key.attr}]")
    if not table:
        raise KernelExtractionError(f"{table_name}: empty table")
    return table


def _extract_status_set(source: str, name: str) -> frozenset[str]:
    return _eval_status_set(_assignment_value(ast.parse(source), name), name)


# ---------------------------------------------------------------------------
# Kernel model — the Python duals of the Lean theorems
# ---------------------------------------------------------------------------


def step_legal(table: dict[str, frozenset[str]], current: str, target: str) -> bool:
    return target in table[current]


def reference_reaches(table: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """Reflexive-transitive closure by fixpoint iteration — an independent
    oracle for the BFS path search (no shared code with ``transition_path``
    below). Reflexive, matching production semantics: ``transition_path``
    returns the empty path for ``current == target`` unconditionally."""
    closure: dict[str, set[str]] = {status: set(row) | {status} for status, row in table.items()}
    changed = True
    while changed:
        changed = False
        for row in closure.values():
            via = set()
            for reachable in row:
                via |= closure[reachable]
            if not via <= row:
                row |= via
                changed = True
    return {status: frozenset(row) for status, row in closure.items()}


def transition_path(
    table: dict[str, frozenset[str]], current: str, target: str
) -> tuple[str, ...] | None:
    """Mirror of production ``transition_path``'s search: BFS with candidates
    explored in value order. Returns ``None`` exactly where production raises
    (no legal path)."""
    if current == target:
        return ()
    parents: dict[str, str | None] = {current: None}
    frontier: deque[str] = deque([current])
    while frontier:
        status = frontier.popleft()
        for candidate in sorted(table[status]):
            if candidate in parents:
                continue
            parents[candidate] = status
            if candidate == target:
                path: list[str] = []
                walker: str | None = target
                while walker is not None:
                    path.append(walker)
                    walker = parents[walker]
                # Production's path starts *after* the current status; drop the root.
                path.pop()
                return tuple(reversed(path))
            frontier.append(candidate)
    return None


# ---------------------------------------------------------------------------
# Embedded artifacts — real, self-contained, hand-checkable; NOT compiled here
# ---------------------------------------------------------------------------

LEAN_KERNEL = """/-!
M8-A16 research artifact — issue #897 (epic #880, initiative #879).

The MAIstro Run/Attempt execution-state transition kernel, formalized.
Production authority: `packages/maistro-core/src/maistro/runs/lifecycle.py`
(`RUN_TRANSITIONS`, `ATTEMPT_TRANSITIONS`, `TERMINAL_RUN_STATUSES`,
`TERMINAL_ATTEMPT_STATUSES`). Table rows are written in production's
`sorted(..., key=value)` exploration order.

STATUS: PROOF-SKETCH ARTIFACT, NOT MACHINE-CHECKED IN THIS REPOSITORY. The
deterministic CI has no elan/Lean toolchain, so no `theorem` below has been
checked by Lean at this head; the Python dual of each theorem is
machine-checked on every test run by
`packages/maistro-rsi/tests/test_m8a16_lean_rust_kernel_research.py` (the
dual test is named in each theorem's docstring). Checking (and, if needed,
trivially repairing) this file under an elan toolchain is step 1 of the real
experiment recorded in docs/research/897-lean-leanstral-rust-aeneas-correctness-kernel.md.
Nothing here is a MAIstro release dependency and nothing here is an authority:
the production table is the only authority, and the harness equates this
artifact against it.
-/

/-- The production `RunStatus` (str) enum. -/
inductive RunStatus where
  | created | queued | running | waiting | paused
  | completed | failed | cancelled | timedOut
  deriving DecidableEq, Repr

/-- The production `AttemptStatus` (str) enum. -/
inductive AttemptStatus where
  | created | running | completed | failed | cancelled | timedOut | yielded
  deriving DecidableEq, Repr

/-- The production `TERMINAL_RUN_STATUSES`. -/
def terminalRunStatuses : List RunStatus :=
  [.cancelled, .completed, .failed, .timedOut]

/-- The production `TERMINAL_ATTEMPT_STATUSES`. -/
def terminalAttemptStatuses : List AttemptStatus :=
  [.cancelled, .completed, .failed, .timedOut, .yielded]

/-- Terminal status predicate, defined by the extracted set. -/
def isTerminal (s : RunStatus) : Bool := s ∈ terminalRunStatuses

/-- Terminal status predicate for Attempts. -/
def isTerminalAttempt (s : AttemptStatus) : Bool := s ∈ terminalAttemptStatuses

/-- The production `RUN_TRANSITIONS` table. -/
def runTransitions : RunStatus → List RunStatus
  | .created   => [.cancelled, .queued]
  | .queued    => [.cancelled, .running, .timedOut]
  | .running   => [.cancelled, .completed, .failed, .paused, .timedOut, .waiting]
  | .waiting   => [.cancelled, .paused, .queued, .running, .timedOut]
  | .paused    => [.cancelled, .queued, .timedOut]
  | .completed => []
  | .failed    => []
  | .cancelled => []
  | .timedOut  => []

/-- The production `ATTEMPT_TRANSITIONS` table. -/
def attemptTransitions : AttemptStatus → List AttemptStatus
  | .created   => [.cancelled, .running]
  | .running   => [.cancelled, .completed, .failed, .timedOut, .yielded]
  | .completed => []
  | .failed    => []
  | .cancelled => []
  | .timedOut  => []
  | .yielded   => []

/-- A step is legal exactly when the target is in the source's row. -/
def stepLegal (cur target : RunStatus) : Bool := target ∈ runTransitions cur

/-- Reflexive-transitive closure of `stepLegal`, as reachability. -/
inductive Reaches : RunStatus → RunStatus → Prop
  | refl (s : RunStatus) : Reaches s s
  | step {a b c : RunStatus} (h : stepLegal a = true) (hrec : Reaches b c) : Reaches a c

/-- A returned path is a legal walk from its start. -/
inductive LegalPath : RunStatus → List RunStatus → Prop
  | nil (s : RunStatus) : LegalPath s []
  | cons {s t : RunStatus} (ts : List RunStatus)
      (h : stepLegal s t = true) (hrec : LegalPath t ts) : LegalPath s (t :: ts)

-- Machine-checked duals live in the research harness; each docstring names it.

/-- Terminal statuses offer no moves.
Dual: test_terminal_statuses_absorb -/
theorem terminal_absorbing (s : RunStatus) (h : isTerminal s = true) :
    runTransitions s = [] := by
  cases s <;> simp [isTerminal, terminalRunStatuses, runTransitions] at h ⊢

/-- Terminal Attempts offer no moves.
Dual: test_terminal_attempt_statuses_absorb -/
theorem attempt_terminal_absorbing (s : AttemptStatus) (h : isTerminalAttempt s = true) :
    attemptTransitions s = [] := by
  cases s <;> simp [isTerminalAttempt, terminalAttemptStatuses, attemptTransitions] at h ⊢

/-- No status transitions to itself: the table has no self-loops.
Dual: test_no_status_transitions_to_itself -/
theorem no_self_loops (s : RunStatus) : ¬ (stepLegal s s = true) := by
  cases s <;> simp [stepLegal, runTransitions]

/-- Every non-terminal status reaches every terminal status; shown for
`.cancelled`, the status crash recovery and cancellation actually drive.
Dual: test_every_nonterminal_reaches_a_terminal -/
theorem nonterminal_reaches_cancelled (s : RunStatus) (h : isTerminal s = false) :
    Reaches s .cancelled := by
  cases s
  case created =>
    exact Reaches.step (by decide) (Reaches.refl .cancelled)
  case queued =>
    exact Reaches.step (by decide) (Reaches.refl .cancelled)
  case running =>
    exact Reaches.step (by decide) (Reaches.refl .cancelled)
  case waiting =>
    exact Reaches.step (by decide) (Reaches.refl .cancelled)
  case paused =>
    exact Reaches.step (by decide) (Reaches.refl .cancelled)
  case completed => exact absurd rfl h
  case failed => exact absurd rfl h
  case cancelled => exact absurd rfl h
  case timedOut => exact absurd rfl h

/-- Any legal path is a reachability witness: the path search's returned walk
never claims a transition the table does not license.
Dual: test_transition_path_steps_are_legal -/
theorem legal_path_ends_reaches {s : RunStatus} {p : List RunStatus}
    (h : LegalPath s p) : Reaches s (match p with | [] => s | _ :: _ => p.getLast!) := by
  induction h with
  | nil => exact Reaches.refl _
  | cons _ hstep hrec => exact Reaches.step hstep hrec
"""

RUST_KERNEL = """//! M8-A16 research artifact — issue #897 (epic #880, initiative #879).
//!
//! The MAIstro Run/Attempt execution-state transition kernel as safe
//! sequential Rust: the candidate for a Charon/Aeneas mechanical translation
//! into Lean. Production authority:
//! `packages/maistro-core/src/maistro/runs/lifecycle.py`. Table rows are
//! written in production's `sorted(..., key=value)` exploration order.
//!
//! STATUS: ARTIFACT, NOT BUILT IN THIS REPOSITORY. Deterministic CI has no
//! cargo toolchain, so nothing here has been compiled or tested at this head;
//! `cargo test` on this file is step 2 of the real experiment recorded in
//! docs/research/897-lean-leanstral-rust-aeneas-correctness-kernel.md. The
//! research harness mechanically equates every table below against the
//! extracted production table on every test run, so this artifact cannot
//! drift silently. It is not a MAIstro release dependency and not an
//! authority: the production table is the only authority.

use std::collections::{HashMap, VecDeque};

/// The production `RunStatus` (str) enum, declaration order preserved.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum RunStatus {
    Created,
    Queued,
    Running,
    Waiting,
    Paused,
    Completed,
    Failed,
    Cancelled,
    TimedOut,
}

/// The production `AttemptStatus` (str) enum, declaration order preserved.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum AttemptStatus {
    Created,
    Running,
    Completed,
    Failed,
    Cancelled,
    TimedOut,
    Yielded,
}

/// The production `TERMINAL_RUN_STATUSES`.
pub const TERMINAL_RUN_STATUSES: [RunStatus; 4] = [
    RunStatus::Cancelled,
    RunStatus::Completed,
    RunStatus::Failed,
    RunStatus::TimedOut,
];

/// The production `TERMINAL_ATTEMPT_STATUSES`.
pub const TERMINAL_ATTEMPT_STATUSES: [AttemptStatus; 5] = [
    AttemptStatus::Cancelled,
    AttemptStatus::Completed,
    AttemptStatus::Failed,
    AttemptStatus::TimedOut,
    AttemptStatus::Yielded,
];

pub fn is_terminal(s: RunStatus) -> bool {
    TERMINAL_RUN_STATUSES.contains(&s)
}

pub fn is_terminal_attempt(s: AttemptStatus) -> bool {
    TERMINAL_ATTEMPT_STATUSES.contains(&s)
}

/// The production `RUN_TRANSITIONS` table.
pub fn transitions(s: RunStatus) -> &'static [RunStatus] {
    match s {
        RunStatus::Created => &[RunStatus::Cancelled, RunStatus::Queued],
        RunStatus::Queued => &[RunStatus::Cancelled, RunStatus::Running, RunStatus::TimedOut],
        RunStatus::Running => &[
            RunStatus::Cancelled,
            RunStatus::Completed,
            RunStatus::Failed,
            RunStatus::Paused,
            RunStatus::TimedOut,
            RunStatus::Waiting,
        ],
        RunStatus::Waiting => &[
            RunStatus::Cancelled,
            RunStatus::Paused,
            RunStatus::Queued,
            RunStatus::Running,
            RunStatus::TimedOut,
        ],
        RunStatus::Paused => &[RunStatus::Cancelled, RunStatus::Queued, RunStatus::TimedOut],
        RunStatus::Completed => &[],
        RunStatus::Failed => &[],
        RunStatus::Cancelled => &[],
        RunStatus::TimedOut => &[],
    }
}

/// The production `ATTEMPT_TRANSITIONS` table.
pub fn attempt_transitions(s: AttemptStatus) -> &'static [AttemptStatus] {
    match s {
        AttemptStatus::Created => &[AttemptStatus::Cancelled, AttemptStatus::Running],
        AttemptStatus::Running => &[
            AttemptStatus::Cancelled,
            AttemptStatus::Completed,
            AttemptStatus::Failed,
            AttemptStatus::TimedOut,
            AttemptStatus::Yielded,
        ],
        AttemptStatus::Completed => &[],
        AttemptStatus::Failed => &[],
        AttemptStatus::Cancelled => &[],
        AttemptStatus::TimedOut => &[],
        AttemptStatus::Yielded => &[],
    }
}

/// A step is legal exactly when the target is in the source's row.
pub fn step_legal(current: RunStatus, target: RunStatus) -> bool {
    transitions(current).contains(&target)
}

/// Reachability by fixpoint iteration — the independent oracle the tests use
/// to check `transition_path`'s `None` result.
pub fn reaches(current: RunStatus, target: RunStatus) -> bool {
    let mut seen: HashMap<RunStatus, bool> = HashMap::new();
    let mut frontier: VecDeque<RunStatus> = VecDeque::new();
    frontier.push_back(current);
    seen.insert(current, true);
    while let Some(status) = frontier.pop_front() {
        if status == target {
            return true;
        }
        for candidate in transitions(status) {
            if !seen.contains_key(candidate) {
                seen.insert(*candidate, true);
                frontier.push_back(*candidate);
            }
        }
    }
    false
}

/// The production `transition_path`: BFS with candidates explored in value
/// order, returning the shortest legal walk, or `None` exactly where
/// production raises (no legal path; terminal targets other than self).
pub fn transition_path(current: RunStatus, target: RunStatus) -> Option<Vec<RunStatus>> {
    if current == target {
        return Some(Vec::new());
    }
    let mut parents: HashMap<RunStatus, Option<RunStatus>> = HashMap::new();
    parents.insert(current, None);
    let mut frontier: VecDeque<RunStatus> = VecDeque::new();
    frontier.push_back(current);
    while let Some(status) = frontier.pop_front() {
        for candidate in transitions(status) {
            if parents.contains_key(candidate) {
                continue;
            }
            parents.insert(*candidate, Some(status));
            if *candidate == target {
                let mut path = Vec::new();
                let mut walker = Some(target);
                while let Some(step) = walker {
                    path.push(step);
                    walker = parents[&step];
                }
                // Production's path starts *after* the current status; drop the root.
                path.pop();
                path.reverse();
                return Some(path);
            }
            frontier.push_back(*candidate);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_statuses_absorb() {
        for s in TERMINAL_RUN_STATUSES {
            assert!(transitions(s).is_empty(), "{s:?} must offer no moves");
        }
    }

    #[test]
    fn no_status_transitions_to_itself() {
        for s in TERMINAL_RUN_STATUSES {
            assert!(!step_legal(s, s));
        }
    }

    #[test]
    fn every_nonterminal_reaches_cancelled() {
        for s in [
            RunStatus::Created,
            RunStatus::Queued,
            RunStatus::Running,
            RunStatus::Waiting,
            RunStatus::Paused,
        ] {
            assert!(
                reaches(s, RunStatus::Cancelled),
                "{s:?} must reach cancelled",
            );
        }
    }

    #[test]
    fn path_is_some_exactly_when_reachable() {
        for s in TERMINAL_RUN_STATUSES {
            for t in TERMINAL_RUN_STATUSES {
                assert_eq!(transition_path(s, t).is_some(), reaches(s, t));
            }
        }
    }
}
"""


# ---------------------------------------------------------------------------
# Artifact parsing — mechanical, so equivalence is checked, not assumed
# ---------------------------------------------------------------------------


def _rust_enum_members(source: str, enum_name: str) -> tuple[str, ...]:
    block = re.search(rf"pub enum {enum_name} \{{(.*?)\}}", source, re.DOTALL)
    if block is None:
        raise KernelExtractionError(f"rust kernel: no enum named {enum_name}")
    return tuple(
        _canonical(member) for member in re.findall(r"^\s{4}(\w+),$", block.group(1), re.MULTILINE)
    )


def _rust_match_table(source: str, fn_name: str, enum_name: str) -> dict[str, tuple[str, ...]]:
    block = re.search(rf"pub fn {fn_name}\(s: {enum_name}\)[^{{]*\{{(.*?)\n\}}", source, re.DOTALL)
    if block is None:
        raise KernelExtractionError(f"rust kernel: no fn named {fn_name}")
    body = block.group(1)
    table: dict[str, tuple[str, ...]] = {}
    for status, targets in re.findall(rf"{enum_name}::(\w+)\s*=>\s*&\[(.*?)\]", body, re.DOTALL):
        table[_canonical(status)] = tuple(
            _canonical(member) for member in re.findall(rf"{enum_name}::(\w+)", targets)
        )
    if not table:
        raise KernelExtractionError(f"rust kernel: {fn_name} parsed to an empty table")
    return table


def _rust_const_list(source: str, const_name: str, enum_name: str) -> tuple[str, ...]:
    match = re.search(
        rf"pub const {const_name}: \[{enum_name}; \d+\] = \[(.*?)\];", source, re.DOTALL
    )
    if match is None:
        raise KernelExtractionError(f"rust kernel: no const named {const_name}")
    return tuple(
        _canonical(member) for member in re.findall(rf"{enum_name}::(\w+)", match.group(1))
    )


def _lean_def_list(source: str, def_name: str, type_name: str) -> tuple[str, ...]:
    match = re.search(rf"def {def_name} : {type_name} :=\n?\s*\[(.*?)\]", source, re.DOTALL)
    if match is None:
        raise KernelExtractionError(f"lean kernel: no def named {def_name}")
    return tuple(_canonical(member) for member in re.findall(r"\.(\w+)", match.group(1)))


def _lean_match_table(source: str, def_name: str, type_name: str) -> dict[str, tuple[str, ...]]:
    header = re.search(
        rf"def {def_name} : {type_name} → List {type_name}\n(.*?)(?=\n/-|\Z)", source, re.DOTALL
    )
    if header is None:
        raise KernelExtractionError(f"lean kernel: no def named {def_name}")
    table: dict[str, tuple[str, ...]] = {}
    for status, targets in re.findall(r"\|\s*\.(\w+)\s*=>\s*\[(.*?)\]", header.group(1), re.DOTALL):
        table[_canonical(status)] = tuple(
            _canonical(member) for member in re.findall(r"\.(\w+)", targets)
        )
    if not table:
        raise KernelExtractionError(f"lean kernel: {def_name} parsed to an empty table")
    return table


# ---------------------------------------------------------------------------
# Equivalence — production vs Lean vs Rust, mechanically
# ---------------------------------------------------------------------------


def equate_kernels() -> tuple[
    dict[str, frozenset[str]],
    dict[str, frozenset[str]],
    frozenset[str],
    frozenset[str],
    tuple[EquivalenceRow, ...],
]:
    """Extract production and equate both artifacts against it. Raises
    ``KernelExtractionError`` (via the parsers) or ``AssertionError`` naming
    the first disagreement."""
    source = _read_production_source()
    run_table = _extract_transition_table(source, "RUN_TRANSITIONS")
    attempt_table = _extract_transition_table(source, "ATTEMPT_TRANSITIONS")
    terminal_run = _extract_status_set(source, "TERMINAL_RUN_STATUSES")
    terminal_attempt = _extract_status_set(source, "TERMINAL_ATTEMPT_STATUSES")

    lean_run = _lean_match_table(LEAN_KERNEL, "runTransitions", "RunStatus")
    rust_run = _rust_match_table(RUST_KERNEL, "transitions", "RunStatus")
    lean_attempt = _lean_match_table(LEAN_KERNEL, "attemptTransitions", "AttemptStatus")
    rust_attempt = _rust_match_table(RUST_KERNEL, "attempt_transitions", "AttemptStatus")
    lean_terminal_run = frozenset(
        _lean_def_list(LEAN_KERNEL, "terminalRunStatuses", "List RunStatus")
    )
    rust_terminal_run = frozenset(
        _rust_const_list(RUST_KERNEL, "TERMINAL_RUN_STATUSES", "RunStatus")
    )
    lean_terminal_attempt = frozenset(
        _lean_def_list(LEAN_KERNEL, "terminalAttemptStatuses", "List AttemptStatus")
    )
    rust_terminal_attempt = frozenset(
        _rust_const_list(RUST_KERNEL, "TERMINAL_ATTEMPT_STATUSES", "AttemptStatus")
    )

    assert set(lean_run) == set(run_table), (
        f"lean run universe drift: {set(lean_run) ^ set(run_table)}"
    )
    assert set(rust_run) == set(run_table), (
        f"rust run universe drift: {set(rust_run) ^ set(run_table)}"
    )
    assert set(lean_attempt) == set(attempt_table), (
        f"lean attempt universe drift: {set(lean_attempt) ^ set(attempt_table)}"
    )
    assert set(rust_attempt) == set(attempt_table), (
        f"rust attempt universe drift: {set(rust_attempt) ^ set(attempt_table)}"
    )
    assert lean_terminal_run == terminal_run, "lean terminal run statuses drift"
    assert rust_terminal_run == terminal_run, "rust terminal run statuses drift"
    assert lean_terminal_attempt == terminal_attempt, "lean terminal attempt statuses drift"
    assert rust_terminal_attempt == terminal_attempt, "rust terminal attempt statuses drift"

    rows: list[EquivalenceRow] = []
    for status in sorted(run_table):
        production_row = tuple(sorted(run_table[status]))
        lean_row = tuple(lean_run[status])
        rust_row = tuple(rust_run[status])
        assert set(lean_row) == run_table[status], f"lean run row drift at {status}"
        assert set(rust_row) == run_table[status], f"rust run row drift at {status}"
        rows.append(EquivalenceRow(status, production_row, lean_row, rust_row))
    return run_table, attempt_table, terminal_run, terminal_attempt, tuple(rows)


# ---------------------------------------------------------------------------
# Translatability measurement — the module under the translation microscope
# ---------------------------------------------------------------------------

#: Curated classification of lifecycle.py's top-level functions: which are
#: pure decision logic over the lifecycle values (mechanically translatable to
#: safe sequential Rust / Charon) and which sit on boundaries Aeneas cannot
#: cross mechanically (pydantic validation, wall-clock reads, delegation into
#: those boundaries). The curation IS the human judgment being measured; the
#: tests below enforce coherence between the classification and the AST so it
#: cannot rot silently.
_TRANSLATABLE: dict[str, str] = {
    "_validate_run_transition": "pure table membership check; raise encodes as Result",
    "transition_path": "pure BFS over the enum table; deterministic by sorted exploration",
    "latest_node_runs": "pure max-by-ordinal fold over records",
    "check_completion_is_earned": (
        "pure predicate over record statuses (ADR-082426-19ed); raise encodes as Result"
    ),
    "reclaimed_attempt_error": "pure string formatting",
    "is_reclaimed_attempt": "pure prefix predicate",
    "lease_is_expired": "pure comparisons over datetimes passed in as values",
    "has_live_execution_lease": "pure existential over lease_is_expired",
    "cascaded_node_run_error": "pure string formatting",
    "refuse_completion_under_terminal_run": "pure set membership check; raise encodes as Result",
}

_UNTRANSLATABLE: dict[str, str] = {
    "_now": "wall-clock read (datetime.now) — impure at the Rust/Aeneas boundary",
    "_logical_values": "pydantic model_dump + wall clock via _now",
    "transition_run": "pydantic model_validate boundary (_logical_values)",
    "transition_attempt": "pydantic model_validate boundary",
    "_migrate_legacy_completed_node_run": (
        "pydantic model_dump/model_validate over Any-typed evidence"
    ),
    "transition_node_run": "pydantic model_validate boundary + Any-typed evidence equality",
    "renewed_lease": "pydantic model_copy boundary",
    "renew_attempt_lease": "pydantic model_copy + wall clock via _now",
    "reclaim_attempt": "delegates to transition_attempt (pydantic boundary)",
    "settle_open_node_run": "delegates to transition_node_run (pydantic boundary)",
}

#: Body markers that force a function OUT of the translatable set. A body
#: containing a pydantic model op, a wall-clock read, or a call to ``_now`` is
#: on the other side of the mechanical-translation boundary by construction.
_BOUNDARY_MARKERS = ("model_validate", "model_dump", "model_copy", "now", "datetime")


def _function_sources(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def classify_module() -> tuple[dict[str, TranslatabilityRecord], int, int, tuple[str, ...]]:
    """Verify the curated classification against the production AST.

    Returns (records, total, translatable_count, boundary-marker violations).
    Raises ``KernelExtractionError`` if the classification names a function
    the module does not define, or if a marker-bearing function is classified
    translatable (the one coherence rule enforced mechanically — everything
    else about this classification is the measured human judgment).
    """
    tree = ast.parse(PRODUCTION_KERNEL.read_text(encoding="utf-8"))
    functions = _function_sources(tree)
    known = set(_TRANSLATABLE) | set(_UNTRANSLATABLE)
    missing = known - set(functions)
    if missing:
        raise KernelExtractionError(
            f"classification names functions lifecycle.py does not define: {sorted(missing)}"
        )
    unclassified = set(functions) - known
    if unclassified:
        raise KernelExtractionError(
            "lifecycle.py defines functions the classification does not cover "
            f"(the module evolved; re-measure): {sorted(unclassified)}"
        )

    violations: list[str] = []
    for name, function in functions.items():
        # Body statements only: annotations are types, not runtime behavior
        # (a ``now: datetime`` parameter is a value, not a clock read).
        markers: set[str] = set()
        for statement in function.body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Attribute) and node.attr in _BOUNDARY_MARKERS:
                    markers.add(node.attr)
                elif isinstance(node, ast.Name) and node.id == "datetime":
                    markers.add("datetime")
        if name in _TRANSLATABLE and markers:
            violations.append(f"{name}: classified translatable but body touches {sorted(markers)}")
    if violations:
        raise KernelExtractionError("translatability incoherence: " + "; ".join(violations))

    records = {
        name: TranslatabilityRecord(name, True, reason) for name, reason in _TRANSLATABLE.items()
    } | {
        name: TranslatabilityRecord(name, False, reason) for name, reason in _UNTRANSLATABLE.items()
    }
    total = len(functions)
    translatable = len(_TRANSLATABLE)
    return records, total, translatable, tuple(violations)


def build_report() -> FeasibilityReport:
    _run_table, _attempt_table, terminal_run, _terminal_attempt, rows = equate_kernels()
    records, total, translatable, _violations = classify_module()
    return FeasibilityReport(
        kernel="execution-state transition legality (RUN_TRANSITIONS + ATTEMPT_TRANSITIONS + "
        "transition_path), extracted from packages/maistro-core/src/maistro/runs/lifecycle.py",
        statuses=tuple(sorted(_extract_status_universe(_read_production_source(), "RunStatus"))),
        terminal_statuses=tuple(sorted(terminal_run)),
        attempt_statuses=tuple(
            sorted(_extract_status_universe(_read_production_source(), "AttemptStatus"))
        ),
        equivalence_rows=rows,
        kernel_extraction_coverage=(
            "100% of the chosen kernel (both tables, step legality, path search) extracts "
            "mechanically as literal data + pure functions; nothing in the kernel required "
            "human transcription"
        ),
        module_defs_total=total,
        module_defs_translatable=translatable,
        module_translatable_pct=round(100 * translatable / total),
        translatability=tuple(records[name] for name in sorted(records)),
        aeneas_breakers=(
            "pydantic model_validate/model_dump/model_copy: record validation and immutable "
            "reconstruction are Python-runtime constructs with no Rust-native counterpart, "
            "so every transition_* wrapper sits outside mechanical translation",
            "wall-clock reads (_now / datetime.now): impurity Aeneas cannot see; would need "
            "an explicit clock parameter to become translation-shaped",
            "Any-typed JSON evidence (evidence_values_equal, model_dump(mode='python')): "
            "untyped dynamic values have no Charon-representable type",
            "exception payloads on domain errors (InvalidLifecycleTransition, "
            "UnearnedRunCompletion): encodable as Result/panic by Aeneas, but the "
            "callers' plumbing is a mechanical rewrite, not a semantic translation",
        ),
        maintenance_model=(
            "double-entry bookkeeping with loud failure: each production table change must be "
            "mirrored into two artifacts (Lean, Rust) or the equivalence tests fail naming the "
            "drifted row. The extraction tests make even a structural change to the production "
            "table (computed instead of literal) fail loudly. Measured cost at this head: 2 "
            "artifact edits per lifecycle table edit; the harness converts silent model rot "
            "into CI failure, which is the only part of proof maintenance that actually bit "
            "here."
        ),
        defect_class_beyond_existing_testing=(
            "none demonstrated at this head: no Lean proof ran, so no defect was found or "
            "prevented by this technique. The kernel's invariants (terminal absorption, "
            "no self-loops, terminal reachability, path legality/shortness/determinism) are "
            "already machine-checked here as Python duals and are adjacent to formal/ I31 "
            "stateful property testing and the #918 explicit-state model check. A machine-"
            "checked Lean kernel would add re-verification of the same invariants under an "
            "independent checker with a stronger metalogic, not a new defect class, until the "
            "kernel grows rules the table cannot express (e.g. earned completion over "
            "latest-NodeRun state)."
        ),
        rust_boundary_verdict=(
            "not justified: a safe-Rust kernel beside the Python spine would be a second "
            "implementation with its own defect surface and no product/runtime value at this "
            "head (the kernel is a few hundred bytecodes of dict/BFS work). The Rust artifact "
            "here is a translation-candidate prototype, not a boundary proposal."
        ),
        second_authority_verdict=(
            "avoidable by direction of derivation: the production module is the only "
            "authority; the Lean/Rust artifacts are projections re-equated against it on "
            "every test run (this harness), never a checked-in truth of their own. The "
            "forbidden shape — artifacts that production is then edited to match — cannot "
            "arise from this harness because it writes nothing."
        ),
        leanstral=ToolchainRecord(
            name="Leanstral (Lean autoformalization assistant, free API)",
            available=False,
            exercised=False,
            reason=(
                "no network access in deterministic CI and no pricing-independent budget: "
                "assessed qualitatively as an accelerator for the autoformalization step only. "
                "It is never the trust boundary — the Lean kernel/checker is (issue "
                "requirement) — and a free-tier dependency must not become load-bearing, so "
                "no MAIstro flow may require it."
            ),
        ),
        toolchains=(
            ToolchainRecord(
                name="elan/Lean 4",
                available=False,
                exercised=False,
                reason="not installed in this repository's deterministic CI; LEAN_KERNEL unchecked",
            ),
            ToolchainRecord(
                name="cargo/rustc",
                available=False,
                exercised=False,
                reason="not installed in deterministic CI; RUST_KERNEL not compiled",
            ),
            ToolchainRecord(
                name="Charon/Aeneas",
                available=False,
                exercised=False,
                reason="not installed; the Rust->Lean translation step was evaluated "
                "analytically against the module's measured surface, not run",
            ),
        ),
        disposition=RESEARCH_DISPOSITION,
        reassessment_triggers=(
            "elan (Lean 4) available in CI: check LEAN_KERNEL's theorems and repair the "
            "sketches — expected effort under a day for a proof engineer; a clean check is "
            "the INCUBATE gate",
            "a real autoformalization window: formalize the next-tiniest rule the table "
            "cannot express (earned completion over latest-NodeRun state) and measure the "
            "model-equivalence gap on an ordinary evolution change",
            "Aeneas/Charon runnable on the extracted kernel: measure the translation gap "
            "between RUST_KERNEL and LEAN_KERNEL mechanically instead of analytically",
        ),
    )


# ---------------------------------------------------------------------------
# Tests — mechanics on hand-checked fixtures + the production seam
# ---------------------------------------------------------------------------


def test_advisory_only_marker_is_set() -> None:
    assert ADVISORY_ONLY is True
    assert RESEARCH_DISPOSITION == "WATCH"


def test_harness_imports_no_maistro_module() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported, "sanity: the module imports something"
    assert not [name for name in imported if name.split(".")[0] == "maistro"], (
        "research harness must not import maistro: it cannot become an authority"
    )


def test_harness_uses_no_network_or_process_escalation() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden = {"socket", "ssl", "urllib", "http", "subprocess", "requests", "httpx"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not forbidden & {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden


def test_production_kernel_is_read_as_text_only() -> None:
    for source in (PRODUCTION_KERNEL, PRODUCTION_MODEL):
        assert source.is_file(), f"kernel source missing: {source}"
        assert "packages/maistro-core/src" in str(source)
    before = PRODUCTION_KERNEL.read_bytes(), PRODUCTION_MODEL.read_bytes()
    _read_production_source()
    assert (PRODUCTION_KERNEL.read_bytes(), PRODUCTION_MODEL.read_bytes()) == before, (
        "the kernel sources must never be written"
    )


def test_run_transition_table_extracts_nine_statuses() -> None:
    run_table, attempt_table, terminal_run, _terminal_attempt, rows = equate_kernels()
    assert len(run_table) == 9
    assert set(run_table) == {
        "created",
        "queued",
        "running",
        "waiting",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "timedout",
    }
    assert run_table["created"] == frozenset({"queued", "cancelled"})
    assert run_table["completed"] == frozenset()
    assert len(attempt_table) == 7
    assert terminal_run == frozenset({"completed", "failed", "cancelled", "timedout"})
    assert len(rows) == 9


def test_terminal_attempt_statuses_extract() -> None:
    _run, _attempt, _terminal_run, terminal_attempt, _rows = equate_kernels()
    assert terminal_attempt == frozenset(
        {"completed", "failed", "cancelled", "timedout", "yielded"}
    )


def test_extraction_fails_loudly_when_table_is_missing() -> None:
    try:
        _extract_transition_table("OTHER = frozenset({})\n", "RUN_TRANSITIONS")
    except KernelExtractionError as exc:
        assert "RUN_TRANSITIONS" in str(exc)
    else:
        raise AssertionError("a vanished table must fail the extraction loudly")


def test_extraction_fails_loudly_when_table_is_computed() -> None:
    computed = "RUN_TRANSITIONS = {s: frozenset({s}) for s in RunStatus}\n"
    try:
        _extract_transition_table(computed, "RUN_TRANSITIONS")
    except KernelExtractionError as exc:
        assert "dict literal" in str(exc)
    else:
        raise AssertionError("a computed table voids the extraction and must fail loudly")


def test_extraction_fails_loudly_on_structural_drift() -> None:
    """A table key that is not an Enum member (e.g. renamed to plain strings)
    is exactly the kind of silent drift the equivalence is supposed to catch."""
    drifted = "RUN_TRANSITIONS = {'created': frozenset({'cancelled'})}\n"
    try:
        _extract_transition_table(drifted, "RUN_TRANSITIONS")
    except KernelExtractionError:
        pass
    else:
        raise AssertionError("non-enum table keys must fail the extraction loudly")


def test_terminal_statuses_absorb() -> None:
    run_table, _attempt, terminal_run, _terminal_attempt, _rows = equate_kernels()
    for status in terminal_run:
        assert run_table[status] == frozenset(), f"terminal {status} must offer no moves"
    lean_run = _lean_match_table(LEAN_KERNEL, "runTransitions", "RunStatus")
    rust_run = _rust_match_table(RUST_KERNEL, "transitions", "RunStatus")
    for status in terminal_run:
        assert lean_run[status] == ()
        assert rust_run[status] == ()


def test_terminal_attempt_statuses_absorb() -> None:
    _run, attempt_table, _terminal_run, terminal_attempt, _rows = equate_kernels()
    for status in terminal_attempt:
        assert attempt_table[status] == frozenset()


def test_no_status_transitions_to_itself() -> None:
    run_table, attempt_table, _terminal_run, _terminal_attempt, _rows = equate_kernels()
    for status, row in run_table.items():
        assert status not in row
    for status, row in attempt_table.items():
        assert status not in row


def test_every_nonterminal_reaches_a_terminal() -> None:
    run_table, _attempt, terminal_run, _terminal_attempt, _rows = equate_kernels()
    closure = reference_reaches(run_table)
    for status in run_table:
        if status in terminal_run:
            continue
        for terminal in terminal_run:
            assert terminal in closure[status], f"{status} must reach {terminal}"


def test_transition_path_exists_iff_reachable() -> None:
    run_table, _attempt, _terminal_run, _terminal_attempt, _rows = equate_kernels()
    closure = reference_reaches(run_table)
    for current in run_table:
        for target in run_table:
            path = transition_path(run_table, current, target)
            reachable = target in closure[current]
            assert (path is not None) == reachable, f"{current} -> {target}"
            if current == target:
                assert path == ()


def test_transition_path_steps_are_legal_and_shortest() -> None:
    run_table, _attempt, _terminal_run, _terminal_attempt, _rows = equate_kernels()
    for current in run_table:
        for target in run_table:
            path = transition_path(run_table, current, target)
            if path is None:
                continue
            walker = current
            for step in path:
                assert step_legal(run_table, walker, step), f"{walker} -> {step} must be legal"
                walker = step
            assert walker == target
            assert len(path) == _distance(run_table, current, target), (
                f"{current} -> {target}: BFS path must be shortest"
            )


def _distance(table: dict[str, frozenset[str]], source: str, target: str) -> int:
    """Oracle shortest-path length (BFS layer count), or -1 when unreachable."""
    if source == target:
        return 0
    seen = {source}
    layer = [source]
    depth = 0
    while layer:
        depth += 1
        nxt: list[str] = []
        for status in layer:
            for candidate in sorted(table[status]):
                if candidate == target:
                    return depth
                if candidate not in seen:
                    seen.add(candidate)
                    nxt.append(candidate)
        layer = nxt
    return -1


def test_transition_path_is_deterministic() -> None:
    run_table, _attempt, _terminal_run, _terminal_attempt, _rows = equate_kernels()
    for current in run_table:
        for target in run_table:
            assert transition_path(run_table, current, target) == transition_path(
                run_table, current, target
            ), "production's search explores candidates in sorted value order; recompute must agree"


def test_lean_and_rust_attempt_tables_match_production() -> None:
    _run, attempt_table, _terminal_run, _terminal_attempt, _rows = equate_kernels()
    lean_attempt = _lean_match_table(LEAN_KERNEL, "attemptTransitions", "AttemptStatus")
    rust_attempt = _rust_match_table(RUST_KERNEL, "attempt_transitions", "AttemptStatus")
    for status, row in attempt_table.items():
        assert set(lean_attempt[status]) == row
        assert set(rust_attempt[status]) == row


def test_lean_artifact_states_the_dual_theorems() -> None:
    for theorem in (
        "terminal_absorbing",
        "attempt_terminal_absorbing",
        "no_self_loops",
        "nonterminal_reaches_cancelled",
        "legal_path_ends_reaches",
    ):
        assert f"theorem {theorem}" in LEAN_KERNEL, f"lean artifact lost theorem {theorem}"
    assert "NOT MACHINE-CHECKED IN THIS REPOSITORY" in LEAN_KERNEL, (
        "the artifact must keep its honest status header"
    )


def test_rust_artifact_carries_its_own_test_module() -> None:
    assert "#[cfg(test)]" in RUST_KERNEL and "mod tests" in RUST_KERNEL
    for check in (
        "terminal_statuses_absorb",
        "no_status_transitions_to_itself",
        "every_nonterminal_reaches_cancelled",
        "path_is_some_exactly_when_reachable",
    ):
        assert f"fn {check}" in RUST_KERNEL, f"rust artifact lost its own check {check}"
    assert "not a MAIstro release dependency" in RUST_KERNEL, (
        "the artifact must keep its honest status header"
    )


def test_translatability_classification_covers_exactly_the_module() -> None:
    records, total, translatable, violations = classify_module()
    assert violations == ()
    assert total == len(records)
    assert translatable == 10
    assert total == 20


def test_kernel_decision_functions_are_classified_translatable() -> None:
    records, _total, _translatable, _violations = classify_module()
    for name in (
        "transition_path",
        "latest_node_runs",
        "check_completion_is_earned",
        "lease_is_expired",
        "is_reclaimed_attempt",
    ):
        assert records[name].translatable, f"{name} is pure decision logic and must classify so"


def test_pydantic_and_clock_boundaries_are_classified_untranslatable() -> None:
    records, _total, _translatable, _violations = classify_module()
    for name in ("transition_run", "transition_node_run", "renew_attempt_lease", "_now"):
        assert not records[name].translatable, f"{name} sits on a boundary Aeneas cannot cross"
    assert "model_copy" in records["renewed_lease"].reason
    assert "wall-clock" in records["_now"].reason


def test_report_answers_the_evidence_questions() -> None:
    report = build_report()
    assert report.module_defs_total == 20
    assert report.module_defs_translatable == 10
    assert report.module_translatable_pct == 50
    assert report.kernel_extraction_coverage.startswith("100%")
    assert len(report.aeneas_breakers) == 4
    assert all(
        "pydantic" in breaker
        or "wall-clock" in breaker
        or "Any-typed" in breaker
        or "exception" in breaker
        for breaker in report.aeneas_breakers
    )
    assert report.defect_class_beyond_existing_testing.startswith("none demonstrated")
    assert report.rust_boundary_verdict.startswith("not justified")
    assert report.second_authority_verdict.startswith("avoidable")
    assert report.maintenance_model.startswith("double-entry")


def test_report_records_toolchains_honestly() -> None:
    report = build_report()
    assert report.leanstral.exercised is False
    assert "free-tier" in report.leanstral.reason
    assert "never the trust boundary" in report.leanstral.reason
    for tool in report.toolchains:
        assert tool.exercised is False and tool.available is False
        assert tool.reason
    assert {tool.name for tool in report.toolchains} == {
        "elan/Lean 4",
        "cargo/rustc",
        "Charon/Aeneas",
    }


def test_report_is_frozen_and_equivalence_rows_carry_all_three_representations() -> None:
    report = build_report()
    assert dataclasses.is_dataclass(report)
    try:
        report.disposition = "GRADUATE"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("the report must be frozen: records cannot be mutated into adoption")
    for row in report.equivalence_rows:
        assert row.production == row.lean == row.rust, f"row drift at {row.status}"
    assert len(report.equivalence_rows) == 9


def test_disposition_is_watch_with_recorded_triggers() -> None:
    report = build_report()
    assert report.disposition == "WATCH"
    assert len(report.reassessment_triggers) == 3
    assert any("elan" in trigger for trigger in report.reassessment_triggers)
    assert any("Aeneas" in trigger for trigger in report.reassessment_triggers)


def test_extracted_status_universes_match_the_artifacts() -> None:
    source = _read_production_source()
    assert _extract_status_universe(source, "RunStatus") == frozenset(
        _rust_enum_members(RUST_KERNEL, "RunStatus")
    )
    # The Lean inductives declare several members per line, hence no line anchor.
    assert _extract_status_universe(source, "RunStatus") == frozenset(
        _canonical(member)
        for member in re.findall(r"\|\s*(\w+)", _lean_enum_block(LEAN_KERNEL, "RunStatus"))
    )
    assert _extract_status_universe(source, "AttemptStatus") == frozenset(
        _rust_enum_members(RUST_KERNEL, "AttemptStatus")
    )
    assert _extract_status_universe(source, "AttemptStatus") == frozenset(
        _canonical(member)
        for member in re.findall(r"\|\s*(\w+)", _lean_enum_block(LEAN_KERNEL, "AttemptStatus"))
    )


def _lean_enum_block(source: str, name: str) -> str:
    match = re.search(rf"inductive {name} where\n(.*?deriving [^\n]+)", source, re.DOTALL)
    if match is None:
        raise KernelExtractionError(f"lean kernel: no inductive named {name}")
    return match.group(1)
