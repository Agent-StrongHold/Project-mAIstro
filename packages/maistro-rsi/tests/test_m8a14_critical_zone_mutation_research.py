"""M8-A14 research harness — critical-zone mutation strategy for architectural invariants.

Issue #894 (epic #880, initiative #879). Hypothesis under test: mutation testing
provides more value when concentrated on high-consequence invariant code than when
uniformly maximizing mutation score across the repository.

This module is a RESEARCH ARTIFACT, not product code. It encodes, as executable
checks, the instruments the leaf's deliverable asks for:

1. **Critical-zone selection criteria** — a deterministic classifier that decides
   whether a module belongs in the mutation zone, from explicit facts (authority
   adjacency, narrow test resolvability, bounded mutant budget, fail-safe shape).
2. **Operator semantic-risk taxonomy** — cosmic-ray 8.7's operator families
   classified by the risk of the mutation they perform, *per syntactic context*.
   The prototype run showed risk is context-dependent: the same binary-operator
   family is a magnitude change with security consequence on a runtime TTL
   (``time.time() + TTL`` -> ``*``: grants never expire) and an
   equivalent-by-construction no-op on a PEP 563 type annotation.
3. **Survivor taxonomy** — the five-way classification of mutation survivors,
   applied to every survivor of the recorded prototype run, plus a miniature
   deterministic mutation engine that reproduces the killer/survivor mechanism
   for representative recorded survivors on a hand-checked deny-by-default guard.

The recorded run data below is REAL EXPERIMENTAL OUTPUT, not a fixture: a
cosmic-ray 8.7.0 session (local distributor, serial, 60 s timeout) over
``packages/maistro-core/src/maistro/security/trust_boundary.py`` against its
mirror suite ``packages/maistro-core/tests/security/test_trust_boundary.py``
(2026-10-08; 103 mutants, 53 killed, 50 survived, ~2.3 s/mutant serial; every
worker outcome NORMAL). The reproduction procedure is documented in
``docs/research/894-critical-zone-mutation-strategy.md``. Two flagship survivors
(the L106 deny-all-fallback flip and the L32 fail-safe-default flip) were
additionally hand-verified: the mutated module was run against the mirror suite
directly, and all 17 tests passed under each mutant.

Trust boundary (the epic's contract, enforced by construction): every number
produced here is ADVISORY EVIDENCE. Nothing in this module reads or writes a
Goal, a Run authority, a routing decision, or a Warden/HITL/delegation control.
It imports nothing from ``maistro`` at all, so it cannot become an authority by
accident (M8 guardrails 1 and 2). The experiment record and terminal disposition
live in ``docs/research/894-critical-zone-mutation-strategy.md``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-A14 output as
#: authorization (ADR-068 authorization paths and Warden/HITL remain canonical).
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Recorded prototype run (real experimental output, 2026-10-08)
# ---------------------------------------------------------------------------

ENGINE = "cosmic-ray 8.7.0"
ZONE_MODULE = "packages/maistro-core/src/maistro/security/trust_boundary.py"
MIRROR_TESTS = "packages/maistro-core/tests/security/test_trust_boundary.py"

#: Session totals, from the session SQLite database (work_items / work_results).
TOTAL_MUTANTS = 103
KILLED = 53
SURVIVED = 50
#: Wall-clock of ``cosmic-ray exec`` (local distributor, serial).
EXEC_WALL_SECONDS = 239.0
#: Baseline mirror-suite wall time (``uv run pytest … -x -q``, 17 passed).
BASELINE_WALL_SECONDS = 3.6
BASELINE_TESTS = 17

#: cosmic-ray 8.7 operator families with their variant counts, as listed by
#: ``cosmic-ray operators`` (213 variants over 16 families).
OPERATOR_FAMILY_VARIANTS: dict[str, int] = {
    "ReplaceBinaryOperator": 132,
    "ReplaceComparisonOperator": 56,
    "ReplaceUnaryOperator": 12,
    "ZeroIterationForLoop": 1,
    "VariableReplacer": 1,
    "VariableInserter": 1,
    "ReplaceTrueWithFalse": 1,
    "ReplaceOrWithAnd": 1,
    "ReplaceFalseWithTrue": 1,
    "ReplaceContinueWithBreak": 1,
    "ReplaceBreakWithContinue": 1,
    "ReplaceAndWithOr": 1,
    "RemoveDecorator": 1,
    "NumberReplacer": 1,
    "ExceptionReplacer": 1,
    "AddNot": 1,
}

#: Mutant counts by enclosing definition, from the session database.
MUTANTS_BY_DEFINITION = {
    "check_permission": 63,
    "PermissionGrant": 14,
    "validate_spec": 14,
    "create_grant_for_task": 12,
}


class SurvivorCategory(StrEnum):
    """Why a mutant survived. The leaf's survivor taxonomy (five classes)."""

    #: Language semantics make the mutant observably identical: PEP 563 string
    #: annotations are never evaluated. Not actionable; exclude at generation
    #: time with annotation-aware operator configuration.
    EQUIVALENT_BY_CONSTRUCTION = "equivalent_by_construction"
    #: Extensionally equal over the type's closed member set — StrEnum members
    #: compare lexicographically, so some relational swaps coincide on
    #: {'read', 'write', 'execute'}. Actionable only by sealing the member set.
    LEXICOGRAPHIC_COINCIDENCE = "lexicographic_coincidence"
    #: Differs only at an exact boundary value (``>`` vs ``>=``); killable with
    #: an exact-boundary assertion, but no realistic input sits on the boundary.
    BOUNDARY_MEASURE_ZERO = "boundary_measure_zero"
    #: The mutant changes real authorization/scoping semantics and the mirror
    #: suite does not observe it. THE actionable class: each row is an untested
    #: architectural invariant.
    UNTESTED_INVARIANT = "untested_invariant"
    #: Mutates something no architectural invariant constrains (e.g. grant-ID
    #: entropy width). Out of scope for a near-zero-survivor policy.
    NON_INVARIANT_METADATA = "non_invariant_metadata"


#: The classes a near-zero-survivor policy counts. Equivalents are excluded at
#: generation time; boundaries and metadata are triaged, not chased.
ACTIONABLE_CATEGORIES = frozenset({SurvivorCategory.UNTESTED_INVARIANT})


@dataclass(frozen=True)
class SurvivorRecord:
    """One survivor of the recorded run, with its semantic role and category.

    ``line`` is the line in the zone module at run time; ``role`` names the
    semantic role the mutated expression plays — the stable input the taxonomy
    needs (line numbers alone would rot on any edit).
    """

    operator: str
    line: int
    definition: str
    role: str
    category: SurvivorCategory


def _s(
    operator: str, line: int, definition: str, role: str, category: SurvivorCategory
) -> SurvivorRecord:
    return SurvivorRecord(
        operator=operator, line=line, definition=definition, role=role, category=category
    )


#: All 50 survivors of the recorded run (operator, line, enclosing definition,
#: mutated expression's semantic role, taxonomy category).
SURVIVORS: tuple[SurvivorRecord, ...] = (
    # --- PermissionGrant defaults ---------------------------------------
    # grant-id entropy width: no invariant constrains the ID's character count.
    _s(
        "NumberReplacer",
        28,
        "PermissionGrant",
        "grant_id_entropy_width",
        SurvivorCategory.NON_INVARIANT_METADATA,
    ),
    _s(
        "NumberReplacer",
        28,
        "PermissionGrant",
        "grant_id_entropy_width",
        SurvivorCategory.NON_INVARIANT_METADATA,
    ),
    # can_execute: bool = False  ->  True: the fail-safe default itself.
    _s(
        "ReplaceFalseWithTrue",
        32,
        "PermissionGrant",
        "capability_default",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # expires_at default_factory: time.time() + TTL — every Add replacement.
    # Sub = grants instantly expired (deny everything); Mul/Div/Pow = grants
    # effectively never expire (over-extension). Grant liveness is unpinned.
    *(
        _s(
            f"ReplaceBinaryOperator_Add_{op}",
            34,
            "PermissionGrant",
            "ttl_default_arithmetic",
            SurvivorCategory.UNTESTED_INVARIANT,
        )
        for op in (
            "Sub",
            "Mul",
            "Div",
            "FloorDiv",
            "Mod",
            "Pow",
            "RShift",
            "LShift",
            "BitOr",
            "BitAnd",
            "BitXor",
        )
    ),
    # --- check_permission -------------------------------------------------
    # path/command parameters: str | None — PEP 563 annotations, never evaluated.
    *(
        _s(
            f"ReplaceBinaryOperator_BitOr_{op}",
            line,
            "check_permission",
            "parameter_type_annotation",
            SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION,
        )
        for line in (76, 77)
        for op in (
            "Add",
            "Sub",
            "Mul",
            "Div",
            "FloorDiv",
            "Mod",
            "Pow",
            "RShift",
            "LShift",
            "BitAnd",
            "BitXor",
        )
    ),
    # Expiry guard boundary: time.time() > expires_at -> >= (measure zero).
    _s(
        "ReplaceComparisonOperator_Gt_GtE",
        88,
        "check_permission",
        "expiry_boundary",
        SurvivorCategory.BOUNDARY_MEASURE_ZERO,
    ),
    # action == Action.READ -> <= : 'execute' <= 'read' is True under StrEnum
    # lexicographic order, so an EXECUTE call carrying a path would enter the
    # read branch. Equivalent only under the untested calling convention that
    # execute checks never pass a path.
    _s(
        "ReplaceComparisonOperator_Eq_LtE",
        91,
        "check_permission",
        "action_guard",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # == -> is on enum members: identical by member identity.
    _s(
        "ReplaceComparisonOperator_Eq_Is",
        91,
        "check_permission",
        "action_guard",
        SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION,
    ),
    # action == Action.WRITE -> <= : 'execute' <= 'write' is True — EXECUTE with
    # a path enters the write branch (same calling-convention gap).
    _s(
        "ReplaceComparisonOperator_Eq_LtE",
        94,
        "check_permission",
        "action_guard",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # action >= Action.WRITE: lexicographically True iff action == 'write' over
    # the closed member set — an equivalent by member-order coincidence.
    _s(
        "ReplaceComparisonOperator_Eq_GtE",
        94,
        "check_permission",
        "action_guard",
        SurvivorCategory.LEXICOGRAPHIC_COINCIDENCE,
    ),
    _s(
        "ReplaceComparisonOperator_Eq_Is",
        94,
        "check_permission",
        "action_guard",
        SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION,
    ),
    # action == Action.WRITE and path -> or : with symmetric factory grants
    # (read_paths == write_paths) the branches coincide; asymmetric scoping is
    # never pinned by any test.
    _s(
        "ReplaceAndWithOr",
        94,
        "check_permission",
        "path_scope_conjunction",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # action == Action.EXECUTE -> <= : 'read' <= 'execute' and 'write' <=
    # 'execute' are both False — equivalent by lexicographic coincidence.
    _s(
        "ReplaceComparisonOperator_Eq_LtE",
        97,
        "check_permission",
        "action_guard",
        SurvivorCategory.LEXICOGRAPHIC_COINCIDENCE,
    ),
    # action == Action.EXECUTE -> >= : 'read' >= 'execute' and 'write' >=
    # 'execute' are both True — READ and WRITE requests enter the execute
    # branch and can be granted by capability alone. The deny-by-default
    # fallback becomes unreachable for every action. Bypass-shaped, and the
    # mirror suite does not observe it.
    _s(
        "ReplaceComparisonOperator_Eq_GtE",
        97,
        "check_permission",
        "action_guard",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    _s(
        "ReplaceComparisonOperator_Eq_Is",
        97,
        "check_permission",
        "action_guard",
        SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION,
    ),
    # command and grant.allowed_commands -> or : both directions diverge — a
    # restricted grant asked to execute with command=None matches the gate and
    # fails inside it, and an unrestricted grant (allowed_commands = []) with a
    # command is denied instead of allowed. The allow-all semantics of an empty
    # allowlist is unpinned.
    _s(
        "ReplaceAndWithOr",
        100,
        "check_permission",
        "command_gate_conjunction",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # The final ``return False`` — deny-by-default — flipped to ``return True``.
    # Hand-verified: all 17 mirror tests pass under this mutant.
    _s(
        "ReplaceFalseWithTrue",
        106,
        "check_permission",
        "deny_all_fallback",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # --- create_grant_for_task / validate_spec ----------------------------
    # expires_at=time.time() + ttl_seconds -> * : factory-created grants never
    # expire. Grant liveness for the factory path is unpinned.
    _s(
        "ReplaceBinaryOperator_Add_Mul",
        122,
        "create_grant_for_task",
        "ttl_factory_arithmetic",
        SurvivorCategory.UNTESTED_INVARIANT,
    ),
    # len(description) > MAX -> >= : exact-boundary off-by-one, measure zero.
    _s(
        "ReplaceComparisonOperator_Gt_GtE",
        52,
        "validate_spec",
        "prompt_stuffing_boundary",
        SurvivorCategory.BOUNDARY_MEASURE_ZERO,
    ),
)

#: Hand-verified survivors: the mutated module was run against the mirror suite
#: directly and every test passed. Recorded so the strongest claim in the note
#: is the one that is provably not a harness artifact.
HAND_VERIFIED_SURVIVOR_LINES = frozenset({32, 106})


# ---------------------------------------------------------------------------
# Instrument 1 — critical-zone selection criteria
# ---------------------------------------------------------------------------


class AuthorityRole(StrEnum):
    """The invariant families the issue names as candidate critical zones."""

    EXECUTION_TRANSITION = "execution_transition"
    WORKSPACE_TENANT_SCOPING = "workspace_tenant_scoping"
    AUTHORIZATION_ENFORCEMENT = "authorization_enforcement"
    INVOCATION_RETRY_PROTECTION = "invocation_retry_protection"
    EVENT_ORDERING_REPLAY = "event_ordering_replay"
    GOAL_OWNERSHIP_DELEGATION = "goal_ownership_delegation"
    SCHEDULER_ADMISSION_IDEMPOTENCY = "scheduler_admission_idempotency"


#: A zone must guard at least this many of the issue's invariant families.
MIN_AUTHORITY_ROLES = 1

#: Measured mutant density of the prototype zone (103 mutants / 123 LOC) —
#: used to bound zone cost before any mutant is generated.
MEASURED_MUTANTS_PER_LOC = TOTAL_MUTANTS / 123.0


@dataclass(frozen=True)
class ZoneCandidate:
    """The facts a selection decision needs. No keyword guessing: the triager
    asserts authority adjacency explicitly, and the classifier enforces the
    measurable criteria around that assertion."""

    module: str
    lines_of_code: int
    authority_roles: frozenset[AuthorityRole]
    #: A mirror test file resolves (tests/test_<stem>.py beside the module) —
    #: the narrowest scope ``scripts/mutation_targets.py`` maps. A module whose
    #: tests resolve only to a whole-suite directory cannot run per-mutant
    #: affordably; that is how the historical 30-minute PR timeout happened.
    mirror_test_exists: bool
    #: The module's refusal path is fail-safe (default-deny / default-closed):
    #: mutation bias then surfaces as *granting* behavior, the dangerous
    #: direction, and survivors are security-relevant by construction.
    fail_safe_direction: bool
    #: Per-mutant seconds measured or estimated for the mirror suite.
    per_mutant_seconds: float


@dataclass(frozen=True)
class ZoneDecision:
    module: str
    accepted: bool
    unmet_criteria: tuple[str, ...]
    estimated_mutants: int


def classify_zone(
    candidate: ZoneCandidate,
    *,
    max_mutants: int,
    max_per_mutant_seconds: float,
) -> ZoneDecision:
    """Apply the selection criteria. A zone is in only if every criterion holds.

    Criteria (from the leaf, made checkable):
    C1 authority adjacency — the module enforces >= MIN_AUTHORITY_ROLES of the
       issue's invariant families, asserted via the explicit role registry;
    C2 narrow test scope — a mirror test file exists (no whole-suite widening);
    C3 bounded budget — estimated mutants (LOC x measured density) <= max_mutants;
    C4 affordable per-mutant cost — per_mutant_seconds <= max_per_mutant_seconds;
    C5 fail-safe shape — the refusal path defaults to deny, so survivors are
       dangerous-by-construction and worth their triage cost.
    """
    unmet: list[str] = []
    if len(candidate.authority_roles) < MIN_AUTHORITY_ROLES:
        unmet.append("C1:authority_adjacency")
    if not candidate.mirror_test_exists:
        unmet.append("C2:narrow_test_scope")
    estimated = round(candidate.lines_of_code * MEASURED_MUTANTS_PER_LOC)
    if estimated > max_mutants:
        unmet.append("C3:bounded_budget")
    if candidate.per_mutant_seconds > max_per_mutant_seconds:
        unmet.append("C4:per_mutant_cost")
    if not candidate.fail_safe_direction:
        unmet.append("C5:fail_safe_shape")
    return ZoneDecision(candidate.module, not unmet, tuple(unmet), estimated)


# ---------------------------------------------------------------------------
# Instrument 2 — operator semantic-risk taxonomy
# ---------------------------------------------------------------------------

OperatorRisk = Literal["decision_flip", "magnitude_or_flow", "structural"]


#: Family -> risk at a *runtime-value* context. Annotation and message contexts
#: override to equivalent-by-construction for every family (see
#: ``classify_operator``).
FAMILY_RISK_AT_RUNTIME: dict[str, OperatorRisk] = {
    "ReplaceComparisonOperator": "decision_flip",
    "ReplaceAndWithOr": "decision_flip",
    "ReplaceOrWithAnd": "decision_flip",
    "ReplaceTrueWithFalse": "decision_flip",
    "ReplaceFalseWithTrue": "decision_flip",
    "AddNot": "decision_flip",
    "ReplaceUnaryOperator": "decision_flip",
    "ReplaceBreakWithContinue": "decision_flip",
    "ReplaceContinueWithBreak": "decision_flip",
    "VariableReplacer": "decision_flip",
    "VariableInserter": "decision_flip",
    "ZeroIterationForLoop": "magnitude_or_flow",
    "NumberReplacer": "magnitude_or_flow",
    "ReplaceBinaryOperator": "magnitude_or_flow",
    "ExceptionReplacer": "magnitude_or_flow",
    "RemoveDecorator": "structural",
}


class SyntaxContext(StrEnum):
    """Where the mutated expression sits — the axis that decides real risk."""

    RUNTIME_VALUE = "runtime_value"
    TYPE_ANNOTATION = "type_annotation"
    DOCSTRING_OR_MESSAGE = "docstring_or_message"


@dataclass(frozen=True)
class OperatorMutation:
    family: str
    context: SyntaxContext


@dataclass(frozen=True)
class ClassifiedMutation:
    mutation: OperatorMutation
    risk: OperatorRisk | Literal["equivalent_by_construction"]
    rationale: str


def classify_operator(mutation: OperatorMutation) -> ClassifiedMutation:
    """Classify (operator family x syntactic context) by semantic risk.

    The prototype run's central taxonomy finding: risk is context-dependent.
    The same binary-operator family is a magnitude mutation with a security
    consequence on a runtime TTL (grants that never expire) and an
    equivalent-by-construction no-op on a PEP 563 annotation (``str | None`` ->
    ``str * None``: annotations are strings, never evaluated).
    """
    family, context = mutation.family, mutation.context
    if context is SyntaxContext.TYPE_ANNOTATION:
        return ClassifiedMutation(
            mutation,
            "equivalent_by_construction",
            "PEP 563: annotations are strings, never evaluated at runtime",
        )
    if context is SyntaxContext.DOCSTRING_OR_MESSAGE:
        return ClassifiedMutation(
            mutation,
            "equivalent_by_construction",
            "no behavioral surface; at most a message string changes",
        )
    return ClassifiedMutation(
        mutation, FAMILY_RISK_AT_RUNTIME[family], "runtime guard or value position"
    )


# ---------------------------------------------------------------------------
# Instrument 3 — survivor accounting + policy math
# ---------------------------------------------------------------------------


def survivor_accounting(
    survivors: tuple[SurvivorRecord, ...],
    *,
    total_mutants: int,
    killed: int,
) -> dict[str, float | int | bool]:
    """Kill-rate accounting that separates equivalents from actionable debt.

    Raw kill rate punishes a zone for the engine's equivalent-by-construction
    noise; the *meaningful* rate counts only mutants someone could actually be
    asked to kill. The near-zero-survivor policy is evaluated on actionable
    survivors alone (equivalents excluded at generation time, boundaries and
    metadata triaged).
    """
    counts = Counter(s.category for s in survivors)
    construction = counts[SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION]
    equivalent_survivors = construction + counts[SurvivorCategory.LEXICOGRAPHIC_COINCIDENCE]
    non_actionable = (
        equivalent_survivors
        + counts[SurvivorCategory.BOUNDARY_MEASURE_ZERO]
        + counts[SurvivorCategory.NON_INVARIANT_METADATA]
    )
    actionable = sum(counts[c] for c in ACTIONABLE_CATEGORIES)
    meaningful_mutants = total_mutants - construction
    meaningful_survivors = len(survivors) - construction
    meaningful_kill_rate = (
        (meaningful_mutants - meaningful_survivors) / meaningful_mutants
        if meaningful_mutants
        else 0.0
    )
    return {
        "total_mutants": total_mutants,
        "killed": killed,
        "survived": len(survivors),
        "raw_kill_rate": killed / total_mutants,
        "equivalent_survivors": equivalent_survivors,
        "non_actionable_survivors": non_actionable,
        "actionable_survivors": actionable,
        "meaningful_mutants": meaningful_mutants,
        "meaningful_kill_rate": meaningful_kill_rate,
        "near_zero_policy_met": actionable == 0,
    }


def ci_feasibility(
    zone_mutants: int, per_mutant_seconds: float, budget_seconds: float
) -> tuple[bool, float]:
    """Whether a zone fits a CI budget, and the projected wall-clock.

    Answers the leaf's "PR CI or nightly?" question with the measured unit
    cost instead of intuition.
    """
    projected = zone_mutants * per_mutant_seconds
    return projected <= budget_seconds, projected


# ---------------------------------------------------------------------------
# Instrument 4 — miniature mutation engine (deterministic CI stand-in)
# ---------------------------------------------------------------------------


class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


@dataclass(frozen=True)
class GuardGrant:
    """Hand-checked deny-by-default guard model with the recorded zone's
    control shape: an expiry guard, per-resource scopes, a capability gate with
    a fallback to capability-alone, and a final deny-all fallback. The
    allowlist regex is abstracted: a presented command is modeled as matching
    (the recorded L100 survivors concern the guard *conjunction*, not matching).

    ``can_execute=None`` models a grant constructed from the field default —
    exactly what the recorded L32 mutant rewrites — while explicit True/False
    is honored by both the original and the mutant.
    """

    read_scopes: frozenset[str] = frozenset()
    write_scopes: frozenset[str] = frozenset()
    can_execute: bool | None = None
    expired: bool = False


def _decide(
    grant: GuardGrant,
    action: Action,
    scope: str | None,
    command: str | None,
    *,
    default_capable: bool,
) -> bool:
    """The shared control shape; ``default_capable`` is the field default the
    L32 mutant flips. Explicit capability always wins over the default."""
    capable: bool = (
        (grant.can_execute is not False) if default_capable else (grant.can_execute is True)
    )
    if grant.expired:
        return False
    if action is Action.READ and scope is not None:
        return scope in grant.read_scopes
    if action is Action.WRITE and scope is not None:
        return scope in grant.write_scopes
    if action is Action.EXECUTE:
        if not capable:
            return False
        if command is not None:
            return True  # allowlist match, abstracted
        return capable  # capability alone decides
    return False


def model_guard(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    """Deny-by-default authorization decision over scopes and capabilities."""
    return _decide(grant, action, scope, command, default_capable=False)


MutatorName = Literal[
    "fallback_flip",
    "capability_default_flip",
    "action_guard_ge",
    "scope_conjunction_or",
    "delete_not",
]


def _guard_fallback_flip(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    """The L106 mutant flips ONLY the final deny-all ``return False`` — early
    denials (expired, capability gate) and scope decisions are untouched."""
    if grant.expired:
        return False
    if action is Action.READ and scope is not None:
        return scope in grant.read_scopes
    if action is Action.WRITE and scope is not None:
        return scope in grant.write_scopes
    if action is Action.EXECUTE:
        return grant.can_execute is True  # command match, or capability alone (L104)
    return True  # the L106 mutant: deny-all fallback flipped


def _guard_capability_default_flip(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    # The L32 mutant lives on the field *default*: a grant constructed from
    # the default (can_execute=None) silently carries can_execute=True.
    return _decide(grant, action, scope, command, default_capable=True)


def _guard_action_guard_ge(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    if grant.expired:
        return False
    if action is Action.READ and scope is not None:
        return scope in grant.read_scopes
    if action is Action.WRITE and scope is not None:
        return scope in grant.write_scopes
    if action >= Action.EXECUTE:  # StrEnum lexicographic: read AND write enter
        return model_guard(grant, Action.EXECUTE, scope, command)
    return False


def _guard_scope_conjunction_or(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    if grant.expired:
        return False
    if (action is Action.WRITE) or (scope is not None):  # the L94 mutant: and -> or
        return scope in grant.write_scopes
    return model_guard(grant, action, scope, command)


def _guard_delete_not(
    grant: GuardGrant,
    action: Action,
    scope: str | None = None,
    command: str | None = None,
) -> bool:
    if grant.expired:
        return False
    if action is Action.READ and scope is not None:
        return scope in grant.read_scopes
    if action is Action.WRITE and scope is not None:
        return scope in grant.write_scopes
    if action is Action.EXECUTE:
        # the L98 mutant: ``not`` deleted, so the gate inverts
        return command is not None and grant.can_execute is not True
    return False


_MUTATORS: dict[MutatorName, object] = {
    "fallback_flip": _guard_fallback_flip,
    "capability_default_flip": _guard_capability_default_flip,
    "action_guard_ge": _guard_action_guard_ge,
    "scope_conjunction_or": _guard_scope_conjunction_or,
    "delete_not": _guard_delete_not,
}

#: The invariants a near-zero-survivor policy requires oracles for. Each entry
#: names the mutator(s) it kills — the survivor mechanism made explicit: a
#: mutant survives exactly when no oracle distinguishes it.
KILLER_ORACLES: tuple[tuple[str, frozenset[MutatorName]], ...] = (
    (
        "deny_all_fallback",
        frozenset({"fallback_flip"}),
    ),
    (
        "fail_safe_default",
        frozenset({"capability_default_flip"}),
    ),
    (
        "action_guards_are_exact",
        frozenset({"action_guard_ge"}),
    ),
    (
        "scope_conjunction",
        frozenset({"scope_conjunction_or"}),
    ),
    (
        "capability_gate",
        frozenset({"delete_not"}),
    ),
)


def oracle_violations(decision_fn: object) -> list[str]:
    """Run every oracle against a decision function; return violated names.

    An oracle "kills" a mutant iff its violation is reported under the mutant
    and none is reported under the original — the miniature of what cosmic-ray
    measures with a real suite.
    """
    violations: list[str] = []
    # deny_all_fallback: a READ with no scope at all is denied.
    if decision_fn(GuardGrant(read_scopes={"a"}), Action.READ) or decision_fn(  # type: ignore[attr-defined]
        GuardGrant(read_scopes={"a"}), Action.READ, None
    ):
        violations.append("deny_all_fallback")
    # fail_safe_default: a default-constructed grant cannot execute.
    if decision_fn(GuardGrant(), Action.EXECUTE):  # type: ignore[attr-defined]
        violations.append("fail_safe_default")
    # action_guards_are_exact: a capability grant never authorizes an unscoped
    # READ — the action guards route READ/WRITE away from the execute branch.
    bypass_probe = GuardGrant(read_scopes=frozenset(), can_execute=True)
    if decision_fn(bypass_probe, Action.READ):  # type: ignore[attr-defined]
        violations.append("action_guards_are_exact")
    # scope_conjunction: a READ never consults write scopes.
    if decision_fn(GuardGrant(write_scopes={"w"}), Action.READ, "w"):  # type: ignore[attr-defined]
        violations.append("scope_conjunction")
    # capability_gate: a capability-less grant cannot execute even with a command.
    if decision_fn(GuardGrant(can_execute=False), Action.EXECUTE, None, "ls"):  # type: ignore[attr-defined]
        violations.append("capability_gate")
    return violations


# ---------------------------------------------------------------------------
# Tests — instruments before measurements, measurements before disposition
# ---------------------------------------------------------------------------


class TestEvidenceOnlyContract:
    def test_advisory_only_marker(self) -> None:
        assert ADVISORY_ONLY is True

    def test_survivor_records_are_frozen(self) -> None:
        record = SURVIVORS[0]
        with pytest.raises(AttributeError):
            record.category = SurvivorCategory.UNTESTED_INVARIANT  # type: ignore[misc]

    def test_hand_verified_claim_is_narrow(self) -> None:
        """Only survivors actually hand-verified may carry that claim."""
        assert {32, 106} == HAND_VERIFIED_SURVIVOR_LINES
        flagged = {s.line for s in SURVIVORS if s.line in HAND_VERIFIED_SURVIVOR_LINES}
        assert flagged == HAND_VERIFIED_SURVIVOR_LINES


class TestRecordedRunIntegrity:
    def test_totals_are_consistent(self) -> None:
        assert KILLED + SURVIVED == TOTAL_MUTANTS
        assert len(SURVIVORS) == SURVIVED

    def test_mutants_by_definition_partition_total(self) -> None:
        assert sum(MUTANTS_BY_DEFINITION.values()) == TOTAL_MUTANTS
        assert set(MUTANTS_BY_DEFINITION) == {
            "check_permission",
            "PermissionGrant",
            "validate_spec",
            "create_grant_for_task",
        }

    def test_operator_family_variants_complete_partition(self) -> None:
        """The taxonomy covers exactly the families cosmic-ray 8.7 ships."""
        assert len(OPERATOR_FAMILY_VARIANTS) == 16, "cosmic-ray 8.7 lists 16 operator families"
        assert sum(OPERATOR_FAMILY_VARIANTS.values()) == 213, (
            "cosmic-ray 8.7 lists 213 operator variants"
        )
        assert set(FAMILY_RISK_AT_RUNTIME) == set(OPERATOR_FAMILY_VARIANTS), (
            "every family must carry a runtime risk class"
        )

    def test_measured_unit_costs_are_plausible(self) -> None:
        assert pytest.approx(103 / 123) == MEASURED_MUTANTS_PER_LOC
        per_mutant = EXEC_WALL_SECONDS / TOTAL_MUTANTS
        assert 2.0 < per_mutant < 3.0, (
            f"measured serial cost was ~2.3 s/mutant, got {per_mutant:.2f}"
        )
        assert BASELINE_TESTS == 17
        assert BASELINE_WALL_SECONDS < EXEC_WALL_SECONDS / TOTAL_MUTANTS * 2


class TestZoneSelectionCriteria:
    def _candidate(self, **overrides: object) -> ZoneCandidate:
        facts: dict[str, object] = {
            "module": "packages/maistro-core/src/maistro/security/trust_boundary.py",
            "lines_of_code": 123,
            "authority_roles": frozenset({AuthorityRole.AUTHORIZATION_ENFORCEMENT}),
            "mirror_test_exists": True,
            "fail_safe_direction": True,
            "per_mutant_seconds": 2.3,
        }
        facts.update(overrides)
        return ZoneCandidate(**facts)  # type: ignore[arg-type]

    def test_prototype_zone_is_accepted(self) -> None:
        decision = classify_zone(self._candidate(), max_mutants=250, max_per_mutant_seconds=10.0)
        assert decision.accepted, decision.unmet_criteria
        assert decision.estimated_mutants == round(123 * MEASURED_MUTANTS_PER_LOC)

    def test_each_criterion_rejects_when_violated(self) -> None:
        cases = [
            ({"authority_roles": frozenset[AuthorityRole]()}, "C1:authority_adjacency"),
            ({"mirror_test_exists": False}, "C2:narrow_test_scope"),
            ({"lines_of_code": 10_000}, "C3:bounded_budget"),
            ({"per_mutant_seconds": 60.0}, "C4:per_mutant_cost"),
            ({"fail_safe_direction": False}, "C5:fail_safe_shape"),
        ]
        for overrides, expected_unmet in cases:
            decision = classify_zone(
                self._candidate(**overrides), max_mutants=250, max_per_mutant_seconds=10.0
            )
            assert not decision.accepted
            assert expected_unmet in decision.unmet_criteria

    def test_a_large_authority_module_needs_splitting_not_role_denial(self) -> None:
        """Scheduler admission guards real invariants but busts the budget: the
        criteria must attribute the failure to the budget, not the authority —
        widening the budget admits it, denying the role loses the zone."""
        big = self._candidate(module=".../scheduling/admission.py", lines_of_code=1465)
        tight = classify_zone(big, max_mutants=250, max_per_mutant_seconds=10.0)
        assert not tight.accepted
        assert tight.unmet_criteria == ("C3:bounded_budget",)
        generous = classify_zone(big, max_mutants=5000, max_per_mutant_seconds=10.0)
        assert generous.accepted

    def test_estimated_mutants_scale_from_measured_density(self) -> None:
        decision = classify_zone(
            self._candidate(lines_of_code=246), max_mutants=1000, max_per_mutant_seconds=10.0
        )
        assert decision.estimated_mutants == 2 * TOTAL_MUTANTS


class TestOperatorSemanticRiskTaxonomy:
    def test_decision_flip_families_at_runtime(self) -> None:
        for family in (
            "ReplaceComparisonOperator",
            "ReplaceFalseWithTrue",
            "AddNot",
            "ReplaceAndWithOr",
        ):
            classified = classify_operator(OperatorMutation(family, SyntaxContext.RUNTIME_VALUE))
            assert classified.risk == "decision_flip", family

    def test_binary_operator_is_magnitude_at_runtime(self) -> None:
        classified = classify_operator(
            OperatorMutation("ReplaceBinaryOperator", SyntaxContext.RUNTIME_VALUE)
        )
        assert classified.risk == "magnitude_or_flow"

    def test_annotation_context_is_equivalent_regardless_of_family(self) -> None:
        for family in (
            "ReplaceBinaryOperator",
            "ReplaceComparisonOperator",
            "ReplaceFalseWithTrue",
        ):
            classified = classify_operator(OperatorMutation(family, SyntaxContext.TYPE_ANNOTATION))
            assert classified.risk == "equivalent_by_construction", family

    def test_message_context_never_counts_as_killed_coverage(self) -> None:
        classified = classify_operator(
            OperatorMutation("NumberReplacer", SyntaxContext.DOCSTRING_OR_MESSAGE)
        )
        assert classified.risk == "equivalent_by_construction"

    def test_ttl_arithmetic_is_the_concrete_high_consequence_magnitude_case(self) -> None:
        """The recorded L34/L122 survivors: Add -> Mul on a TTL means grants
        never expire — a magnitude mutation with a security consequence, which
        is exactly why 'magnitude' must not collapse to 'low'."""
        classified = classify_operator(
            OperatorMutation("ReplaceBinaryOperator", SyntaxContext.RUNTIME_VALUE)
        )
        assert classified.risk == "magnitude_or_flow"
        l34 = [s for s in SURVIVORS if s.role == "ttl_default_arithmetic"]
        assert len(l34) == 11
        assert all(s.category is SurvivorCategory.UNTESTED_INVARIANT for s in l34)


class TestSurvivorTaxonomyOnRecordedRun:
    def test_taxonomy_covers_all_fifty_survivors(self) -> None:
        counts = Counter(s.category for s in SURVIVORS)
        assert sum(counts.values()) == 50
        assert counts == Counter(
            {
                SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION: 25,
                SurvivorCategory.LEXICOGRAPHIC_COINCIDENCE: 2,
                SurvivorCategory.BOUNDARY_MEASURE_ZERO: 2,
                SurvivorCategory.UNTESTED_INVARIANT: 19,
                SurvivorCategory.NON_INVARIANT_METADATA: 2,
            }
        )

    def test_accounting_arithmetic(self) -> None:
        accounting = survivor_accounting(SURVIVORS, total_mutants=TOTAL_MUTANTS, killed=KILLED)
        assert accounting["raw_kill_rate"] == pytest.approx(53 / 103)
        assert accounting["equivalent_survivors"] == 27  # 25 construction + 2 lexicographic
        assert accounting["non_actionable_survivors"] == 31  # + 2 boundary + 2 metadata
        assert accounting["actionable_survivors"] == 19
        assert accounting["meaningful_mutants"] == 78  # 103 - 25 annotation equivalents
        assert accounting["meaningful_kill_rate"] == pytest.approx(53 / 78)
        assert accounting["near_zero_policy_met"] is False

    def test_meaningful_rate_implicit_in_raw_and_taxonomy(self) -> None:
        """Cross-check the accounting against first principles: all 53 kills
        are meaningful (equivalents survive by definition), and the meaningful
        survivors are exactly the four non-construction classes."""
        accounting = survivor_accounting(SURVIVORS, total_mutants=TOTAL_MUTANTS, killed=KILLED)
        meaningful_survivors = (
            accounting["meaningful_mutants"]
            - accounting["meaningful_kill_rate"] * accounting["meaningful_mutants"]
        )
        assert meaningful_survivors == pytest.approx(25)
        raw = float(accounting["raw_kill_rate"])  # 0.515
        meaningful = float(accounting["meaningful_kill_rate"])  # 0.679
        assert raw < meaningful < 1.0

    def test_both_flagship_survivors_are_classified_actionable(self) -> None:
        """The deny-all fallback and the fail-safe default are the two survivors
        hand-verified against the mirror suite; both must sit in the actionable
        class — that is the leaf's core finding."""
        for line in (32, 106):
            records = [s for s in SURVIVORS if s.line == line]
            assert records, line
            assert all(s.category is SurvivorCategory.UNTESTED_INVARIANT for s in records)

    def test_annotation_survivors_are_the_largest_equivalent_block(self) -> None:
        annotations = [s for s in SURVIVORS if s.role == "parameter_type_annotation"]
        assert len(annotations) == 22  # 11 per str | None parameter, two parameters
        assert all(s.category is SurvivorCategory.EQUIVALENT_BY_CONSTRUCTION for s in annotations)

    def test_every_survivor_role_is_semantic_not_a_line_number(self) -> None:
        """Roles are stable names; line numbers alone would rot on any edit."""
        roles = {s.role for s in SURVIVORS}
        assert {
            "grant_id_entropy_width",
            "capability_default",
            "ttl_default_arithmetic",
            "parameter_type_annotation",
            "expiry_boundary",
            "action_guard",
            "path_scope_conjunction",
            "command_gate_conjunction",
            "deny_all_fallback",
            "ttl_factory_arithmetic",
            "prompt_stuffing_boundary",
        } <= roles


class TestMiniatureMutationEngine:
    """The survivor mechanism, reproduced deterministically: a mutant survives
    exactly when no oracle distinguishes it. Representative recorded survivors
    are demonstrated twice — killed by their oracle, surviving without it."""

    def test_original_model_passes_every_oracle(self) -> None:
        assert oracle_violations(model_guard) == []

    def test_mutator_registry_covers_every_killer_oracle(self) -> None:
        named = set()
        for _, kills in KILLER_ORACLES:
            named |= set(kills)
        assert named == set(_MUTATORS)

    def test_every_mutator_is_distinguishable_from_original(self) -> None:
        """With the full oracle battery, all five representative mutators
        violate at least one invariant the original satisfies."""
        for mutator in _MUTATORS:
            violations = oracle_violations(_MUTATORS[mutator])
            assert violations, f"{mutator} is indistinguishable from the original — taxonomy gap"

    def test_each_oracle_kills_exactly_its_named_mutator(self) -> None:
        """The mapping is not bulk: each oracle names the mutator it kills, and
        the killed mutator violates that oracle's invariant specifically — the
        recorded survivors are oracle gaps, not test-count accidents."""
        for oracle_name, kills in KILLER_ORACLES:
            for mutator in kills:
                violations = oracle_violations(_MUTATORS[mutator])
                assert oracle_name in violations, (oracle_name, mutator)

    def test_fallback_flip_is_invisible_without_deny_all_oracle(self) -> None:
        """L106 mechanism: without a test asserting non-matching requests are
        denied, ``return True`` passes every remaining behavior the suite
        actually probes."""
        mutant = _guard_fallback_flip
        assert not mutant(GuardGrant(), Action.EXECUTE)  # fail-safe default holds
        assert not mutant(GuardGrant(can_execute=False), Action.EXECUTE, None, "ls")  # gate holds
        assert mutant(GuardGrant(read_scopes={"a"}), Action.READ, "a")  # happy path holds
        assert not mutant(GuardGrant(read_scopes={"a"}), Action.READ, "b")  # scope denial holds
        # ...and the one behavior that flips is exactly the fallback:
        assert mutant(GuardGrant(read_scopes={"a"}), Action.READ)  # no scope: ALLOWED by mutant
        assert not model_guard(GuardGrant(read_scopes={"a"}), Action.READ)

    def test_capability_default_flip_is_invisible_without_default_grant_oracle(self) -> None:
        """L32 mechanism: no test constructs a default grant and tries to
        execute, so flipping the fail-safe default to True is unobserved."""
        assert _guard_capability_default_flip(GuardGrant(), Action.EXECUTE) is True
        assert model_guard(GuardGrant(), Action.EXECUTE) is False
        # Grants that set capability explicitly are unaffected — the mutant is
        # a *default* flip, which is what makes it easy to leave untested.
        explicit = GuardGrant(can_execute=False)
        assert _guard_capability_default_flip(explicit, Action.EXECUTE, None, "ls") is False
        defaulted = GuardGrant(read_scopes={"r"})  # capability omitted: mutated
        assert _guard_capability_default_flip(defaulted, Action.EXECUTE) is True
        assert model_guard(defaulted, Action.EXECUTE) is False

    def test_action_guard_ge_reproduces_the_bypass_shape(self) -> None:
        """L97 mechanism: under ``action >= EXECUTE`` (StrEnum lexicographic),
        READ requests fall into the execute branch and are granted by
        capability alone — the deny-by-default fallback goes unreachable."""
        grant = GuardGrant(read_scopes=frozenset(), can_execute=True)
        assert _guard_action_guard_ge(grant, Action.READ) is True, (
            "bypass shape: capability alone authorizes an unscoped read"
        )
        assert model_guard(grant, Action.READ) is False

    def test_scope_conjunction_or_reads_write_scopes(self) -> None:
        """L94 mechanism: with the conjunction ORed, a scoped READ consults
        write scopes; symmetric factory grants hide exactly this divergence."""
        grant = GuardGrant(write_scopes={"w"})
        assert _guard_scope_conjunction_or(grant, Action.READ, "w") is True
        assert model_guard(grant, Action.READ, "w") is False


class TestPolicyAndCiFeasibility:
    def test_single_zone_fits_a_pr_budget(self) -> None:
        per_mutant = EXEC_WALL_SECONDS / TOTAL_MUTANTS
        fits, projected = ci_feasibility(TOTAL_MUTANTS, per_mutant, budget_seconds=600.0)
        assert fits
        assert projected == pytest.approx(EXEC_WALL_SECONDS)

    def test_seven_zone_curated_set_fits_nightly_not_a_pr_slot(self) -> None:
        per_mutant = EXEC_WALL_SECONDS / TOTAL_MUTANTS
        curated = 7 * TOTAL_MUTANTS  # the issue's seven candidate zones, zone-sized
        fits_pr, projected_pr = ci_feasibility(curated, per_mutant, budget_seconds=600.0)
        fits_nightly, _ = ci_feasibility(curated, per_mutant, budget_seconds=3600.0)
        assert not fits_pr
        assert projected_pr > 600.0
        assert fits_nightly

    def test_near_zero_policy_requires_annotation_aware_generation(self) -> None:
        """A near-zero-survivor policy is impractical against raw cosmic-ray
        output: 25 of 50 survivors in one small module are equivalent by
        construction. The policy must exclude that class at generation time
        (annotation-aware operators) and count only actionable survivors."""
        accounting = survivor_accounting(SURVIVORS, total_mutants=TOTAL_MUTANTS, killed=KILLED)
        assert accounting["equivalent_survivors"] > accounting["actionable_survivors"]
        assert accounting["near_zero_policy_met"] is False
        # With equivalents excluded at generation time, the policy gap is 19
        # actionable survivors in 123 LOC — large but finite and triage-able.
        assert accounting["actionable_survivors"] == 19

    def test_stricter_local_policy_dominates_broad_score_chasing(self) -> None:
        """Per the hypothesis: concentrating on zones yields actionable
        findings (19 untested invariants in one module) while broad maximization
        would spend most of its triage budget on equivalents and metadata (31
        of 50 survivors here are non-actionable classes)."""
        accounting = survivor_accounting(SURVIVORS, total_mutants=TOTAL_MUTANTS, killed=KILLED)
        assert accounting["non_actionable_survivors"] == 31
        assert accounting["non_actionable_survivors"] > accounting["actionable_survivors"]
