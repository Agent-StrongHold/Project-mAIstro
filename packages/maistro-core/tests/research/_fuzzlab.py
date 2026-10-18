"""Coverage-guided fuzzing lab for parser attack surfaces (#896, M8-A15).

Research artifact for the M8-A15 leaf: a bounded, deterministic,
coverage-guided mutational fuzzer built on PEP 669 (``sys.monitoring``) — the
"justified equivalent" the issue names, since Atheris needs a libFuzzer-
instrumented CPython that this repository's deterministic CI cannot install or
run (see ``docs/research/896-coverage-guided-fuzzing-parser-surfaces.md``).
Branch/line feedback is captured per code object of ONE target module via
``set_local_events``; a corpus seeded with representative valid inputs is
mutated with byte-level operators, and inputs that reveal coverage so far
unseen are retained (the standard libFuzzer loop, minus the native
instrumentation).

Trust boundary (the epic contract, enforced by construction):

- Every result produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control, and nothing outside the test tree imports
  it (asserted by ``test_research_machinery_is_inert_to_production_source``).
  It cannot become an authority by accident (M8 guardrails 1-2).
- Findings are frozen records with reproducible input bytes; a defect is only
  ever "the target raised an exception outside its documented rejection
  contract" — never a pass/fail verdict about a subsystem. Routed defects stay
  owned by their M0-M7 surfaces; this lab does not fix them (epic contract 7).
- Campaigns are bounded by an exec budget and a fixed RNG seed: same seed,
  same corpus growth, same findings, same edge set. A truncated budget is
  reported as what it is — a smaller sample — never as a clean pass.
- ``formal/`` and the existing Hypothesis suites stay the canonical property
  authority; the Hypothesis comparison arm is a measurement of that baseline
  on the same targets, not a replacement of it.

Experiment record and terminal disposition (INCUBATE) live in
``docs/research/896-coverage-guided-fuzzing-parser-surfaces.md``.
"""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

#: Explicit evidence-only contract marker, asserted by a test so it cannot
#: silently rot. No adoption here routes anything: production ownership of the
#: probed parsers stays with the extensions manifest surface (#953, M9-B2) and
#: the agent GitAgent import/export surface.
ADVISORY_ONLY = True

#: Terminal disposition recorded in the research note. INCUBATE: the prototype
#: found real, host-triggerable contract escapes on a live import boundary and
#: discovered more parser paths per exec than the Hypothesis arms, but the
#: defects are unfixed, byte-level mutation provably misses depth-structural
#: failures, and CI placement/ownership is undecided — the next required
#: evidence is recorded in the research note.
RESEARCH_DISPOSITION = "INCUBATE"

#: The PEP 669 tool id this lab uses. Freed on close(); never left set across
#: campaigns so tests cannot leak monitoring into the product suite.
_TOOL_ID = 5

#: Branch events were split into BRANCH_LEFT/BRANCH_RIGHT in Python 3.13;
#: 3.12 carries the combined BRANCH event only. Either way the callback fires
#: per taken/not-taken conditional jump, which is the feedback signal.
_BRANCH_EVENTS: tuple[int, ...] = (
    (sys.monitoring.events.BRANCH_LEFT, sys.monitoring.events.BRANCH_RIGHT)
    if hasattr(sys.monitoring.events, "BRANCH_LEFT")
    else (sys.monitoring.events.BRANCH,)
)

#: A target parses one candidate: it returns on acceptance and raises its
#: documented rejection type(s) on malformed input. Anything else raised is a
#: contract escape — the only "crash" this lab records.
Target = Callable[[bytes], None]

#: The rejection types a target's contract documents (e.g. ManifestRejected,
#: or ValueError for the GitAgent importer).
AllowedRejections = tuple[type[BaseException], ...]


def _walk_code(code: Any, acc: list[Any]) -> None:
    """Collect ``code`` and every nested code object reachable via co_consts."""
    acc.append(code)
    for const in code.co_consts:
        if hasattr(const, "co_consts"):
            _walk_code(const, acc)


def _module_code_objects(module: ModuleType) -> list[Any]:
    """Every code object defined by ``module``: functions and class methods.

    Objects are filtered on ``__module__`` so imports (e.g. the dataclass
    types a parser module imports for its result models) and the
    ``dataclasses.py``-generated methods attached to them are never
    instrumented — measured edges must stay attributable to the target
    module itself, or the campaign-vs-Hypothesis comparison is inflated by
    code nobody claims to be probing.
    """
    codes: list[Any] = []
    for obj in vars(module).values():
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if hasattr(obj, "__code__"):
            _walk_code(obj.__code__, codes)
        elif isinstance(obj, type):
            for member in vars(obj).values():
                if hasattr(member, "__code__"):
                    _walk_code(member.__code__, codes)
    return codes


@dataclass(frozen=True)
class FuzzFinding:
    """One contract escape: the offending input, the escaping exception, and
    the exec index that produced it. ``input_bytes`` is the full reproducible
    candidate (campaign mutators only shrink/grow seed-sized inputs, so
    findings stay small; probes are handed bounded inputs by the experiment)."""

    input_bytes: bytes
    exception_type: str
    exception_message: str
    exec_index: int

    def reproduces(self, target: Target) -> bool:
        """Re-run the target on the recorded input; the same exception type
        must escape again. Reproducibility is the finding's only currency."""
        try:
            target(self.input_bytes)
        except BaseException as exc:  # the oracle IS the point
            return type(exc).__name__ == self.exception_type
        return False


@dataclass(frozen=True)
class CampaignResult:
    """Frozen outcome of one bounded campaign. ``seed_edges`` counts the
    coverage the seed corpus alone reaches (replayed under the same monitor
    before mutation starts), so ``edges - seed_edges`` is what the fuzz loop
    itself discovered."""

    execs: int
    seconds: float
    seed_edges: int
    edges: int
    corpus_size: int
    accepted: int
    rejected: int
    findings: tuple[FuzzFinding, ...] = field(default_factory=tuple)

    @property
    def finding_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.exception_type] = counts.get(finding.exception_type, 0) + 1
        return counts

    @property
    def discovered_edges(self) -> int:
        return self.edges - self.seed_edges


@dataclass(frozen=True)
class HypothesisArmResult:
    """Frozen outcome of one Hypothesis comparison arm on the same target and
    monitor. This is the measured baseline, not a competing authority."""

    execs: int
    edges: int
    accepted: int
    rejected: int
    escapes: tuple[FuzzFinding, ...] = field(default_factory=tuple)

    @property
    def finding_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.escapes:
            counts[finding.exception_type] = counts.get(finding.exception_type, 0) + 1
        return counts


@dataclass(frozen=True)
class UnguidedArmResult:
    """Frozen outcome of the seed-matched unguided baseline: the campaign's
    seeds, mutator, RNG stream, and exec budget with the coverage feedback
    loop removed. ``edges - seed_edges`` is what blind mutation adds over the
    same corpus — the number coverage guidance must beat to earn its keep."""

    execs: int
    seconds: float
    seed_edges: int
    edges: int
    accepted: int
    rejected: int
    findings: tuple[FuzzFinding, ...] = field(default_factory=tuple)

    @property
    def finding_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.exception_type] = counts.get(finding.exception_type, 0) + 1
        return counts

    @property
    def discovered_edges(self) -> int:
        return self.edges - self.seed_edges


class ModuleMonitor:
    """PEP 669 line+branch coverage restricted to one module's code objects.

    Local events keep the interpreter's remaining code un-instrumented (the
    global path fired on ~8800 code objects in a smoke run; the local path
    instruments exactly the target module), which is what makes ~10^5 execs/s
    possible in-process. ``edges()`` is the union of line and branch events
    keyed by code object identity — stable within one campaign.
    """

    def __init__(self, module: ModuleType) -> None:
        self._codes = _module_code_objects(module)
        self._hits: set[tuple[Any, ...]] = set()
        self._events = (sys.monitoring.events.LINE, *_BRANCH_EVENTS)
        sys.monitoring.use_tool_id(_TOOL_ID, "maistro-fuzzlab")
        for event in self._events:
            sys.monitoring.register_callback(_TOOL_ID, event, self._make_callback(event))

    def _make_callback(self, event: int) -> Callable[..., Any]:
        prefix: tuple[Any, ...] = (event,)

        def callback(*args: Any) -> int:
            self._hits.add(prefix + args)
            return sys.monitoring.MISSING

        return callback

    def __enter__(self) -> ModuleMonitor:
        for code in self._codes:
            sys.monitoring.set_local_events(_TOOL_ID, code, sum(self._events))
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Defensive teardown: a partially-initialized monitor (e.g. the tool id
        # was taken elsewhere) must not mask the original error.
        try:
            for code in self._codes:
                sys.monitoring.set_local_events(_TOOL_ID, code, 0)
            for event in self._events:
                sys.monitoring.register_callback(_TOOL_ID, event, None)
            sys.monitoring.free_tool_id(_TOOL_ID)
        except ValueError:
            pass

    def edges(self) -> frozenset[tuple[Any, ...]]:
        return frozenset(self._hits)


def classify(
    target: Target, data: bytes, allowed_rejections: AllowedRejections
) -> tuple[str, BaseException | None]:
    """Run one candidate through the oracle: 'accepted', 'rejected', or
    'escaped' (with the exception). The classification IS the experiment's
    defect definition — nothing else is asserted about the target."""
    try:
        target(data)
    except allowed_rejections as exc:
        return "rejected", exc
    except BaseException as exc:  # escapes are the findings
        return "escaped", exc
    return "accepted", None


def mutate(data: bytes, rng: random.Random) -> bytes:
    """One byte-level mutation: the libFuzzer basics — bit flip, splice,
    region duplication (growth), truncation, interesting-byte extension,
    and byte replacement. Deliberately structure-blind: structure-awareness
    is what the directed probes exist to measure the lack of."""
    buf = bytearray(data)
    if not buf:
        return bytes(rng.randrange(256) for _ in range(rng.randint(1, 16)))
    op = rng.randrange(6)
    if op == 0:
        buf[rng.randrange(len(buf))] ^= 1 << rng.randrange(8)
    elif op == 1 and len(buf) > 8:
        i, j = rng.randrange(len(buf)), rng.randrange(len(buf))
        buf[i : i + 4] = buf[j : j + 4]
    elif op == 2:
        i = rng.randrange(len(buf))
        buf[i:i] = buf[i : i + rng.randint(4, 32)]
    elif op == 3:
        buf = buf[: rng.randrange(1, len(buf) + 1)]
    elif op == 4:
        buf += bytes([rng.choice((0, 255, 91, 123, 34, 32))]) * rng.randint(1, 16)
    else:
        buf[rng.randrange(len(buf))] = rng.randrange(256)
    return bytes(buf)


def _replay_seeds(
    monitor: ModuleMonitor,
    target: Target,
    seeds: Sequence[bytes],
    allowed_rejections: AllowedRejections,
) -> tuple[int, int, int]:
    """Seed-only baseline under the campaign's monitor: distinct edges, plus
    accept/reject counts. A seed that escapes its own target is a broken
    corpus, so escapes here raise. Runs while the caller holds the monitor
    open — one monitor per campaign, entered exactly once."""
    edges: set[tuple[Any, ...]] = set()
    accepted = rejected = 0
    for seed in seeds:
        outcome, exc = classify(target, seed, allowed_rejections)
        if outcome == "escaped":
            msg = f"seed corpus candidate escapes its own target: {exc!r}"
            raise AssertionError(msg)
        if outcome == "accepted":
            accepted += 1
        else:
            rejected += 1
        edges |= monitor.edges()
    return len(edges), accepted, rejected


def run_campaign(
    target: Target,
    *,
    module: ModuleType,
    seeds: Sequence[bytes],
    allowed_rejections: AllowedRejections,
    execs: int,
    rng_seed: int,
) -> CampaignResult:
    """One deterministic, coverage-guided campaign.

    Same loop as libFuzzer, in miniature: pick a corpus entry, mutate it,
    execute under the module monitor, retain the input when it revealed
    coverage unseen so far. Fixed seed => identical corpus growth, edge set,
    and findings on every run (asserted by the experiment's determinism test).
    """
    rng = random.Random(rng_seed)
    findings: list[FuzzFinding] = []
    corpus = [(seed, "seed") for seed in seeds]
    accepted = rejected = 0
    start = time.perf_counter()
    with ModuleMonitor(module) as monitor:
        seed_edges, seed_accepted, seed_rejected = _replay_seeds(
            monitor, target, seeds, allowed_rejections
        )
        accepted += seed_accepted
        rejected += seed_rejected
        seen: frozenset[tuple[Any, ...]] = frozenset()
        for index in range(execs):
            base = corpus[rng.randrange(len(corpus))][0]
            candidate = mutate(base, rng) if rng.random() < 0.95 else base
            outcome, exc = classify(target, candidate, allowed_rejections)
            if outcome == "accepted":
                accepted += 1
            elif outcome == "rejected":
                rejected += 1
            else:
                findings.append(
                    FuzzFinding(
                        input_bytes=candidate,
                        exception_type=type(exc).__name__ if exc else "Unknown",
                        exception_message=str(exc)[:300] if exc else "",
                        exec_index=index,
                    )
                )
            new_edges = monitor.edges() - seen
            if new_edges:
                corpus.append((candidate, "mutant"))
                seen |= new_edges
        edges = monitor.edges()
    return CampaignResult(
        execs=execs,
        seconds=time.perf_counter() - start,
        seed_edges=seed_edges,
        edges=len(edges),
        corpus_size=len(corpus),
        accepted=accepted,
        rejected=rejected,
        findings=tuple(findings),
    )


def run_unguided_arm(
    target: Target,
    *,
    module: ModuleType,
    seeds: Sequence[bytes],
    allowed_rejections: AllowedRejections,
    execs: int,
    rng_seed: int,
) -> UnguidedArmResult:
    """The campaign minus its guidance, everything else held fixed: same
    seeds, same mutator, same RNG stream and exec budget, but mutation draws
    only from the seed corpus and no input is ever retained. Comparing
    ``discovered_edges`` against this arm (not the seedless Hypothesis arms)
    is what licenses the claim that coverage-guided retention — not the
    seeds, and not blind mutation volume — drives the campaign's discovery."""
    rng = random.Random(rng_seed)
    findings: list[FuzzFinding] = []
    accepted = rejected = 0
    start = time.perf_counter()
    with ModuleMonitor(module) as monitor:
        seed_edges, seed_accepted, seed_rejected = _replay_seeds(
            monitor, target, seeds, allowed_rejections
        )
        accepted += seed_accepted
        rejected += seed_rejected
        for index in range(execs):
            base = seeds[rng.randrange(len(seeds))]
            candidate = mutate(base, rng) if rng.random() < 0.95 else base
            outcome, exc = classify(target, candidate, allowed_rejections)
            if outcome == "accepted":
                accepted += 1
            elif outcome == "rejected":
                rejected += 1
            else:
                findings.append(
                    FuzzFinding(
                        input_bytes=candidate,
                        exception_type=type(exc).__name__ if exc else "Unknown",
                        exception_message=str(exc)[:300] if exc else "",
                        exec_index=index,
                    )
                )
        edges = len(monitor.edges())
    return UnguidedArmResult(
        execs=execs,
        seconds=time.perf_counter() - start,
        seed_edges=seed_edges,
        edges=edges,
        accepted=accepted,
        rejected=rejected,
        findings=tuple(findings),
    )


def run_probes(
    target: Target,
    probes: Iterable[tuple[str, bytes]],
    allowed_rejections: AllowedRejections,
) -> tuple[FuzzFinding, ...]:
    """Directed, structure-aware inputs run outside the mutation loop. These
    measure exactly what byte-level mutation misses (depth/structural
    failures) and double as minimized repros for routed defects."""
    findings: list[FuzzFinding] = []
    for index, (_, data) in enumerate(probes):
        outcome, exc = classify(target, data, allowed_rejections)
        if outcome == "escaped" and exc is not None:
            findings.append(
                FuzzFinding(
                    input_bytes=data,
                    exception_type=type(exc).__name__,
                    exception_message=str(exc)[:300],
                    exec_index=index,
                )
            )
    return tuple(findings)


def run_hypothesis_arm(
    target: Target,
    *,
    module: ModuleType,
    strategy: Any,
    allowed_rejections: AllowedRejections,
    max_examples: int,
) -> HypothesisArmResult:
    """One Hypothesis comparison arm: the same target and monitor, generic
    property-based generation instead of seeded coverage-guided mutation.
    ``derandomize`` pins the arm so the recorded baseline is CI-stable; the
    oracle swallows nothing — escapes are recorded, not raised, because the
    arm's job is to measure, and a measured escape is routed, not re-raised."""
    from hypothesis import HealthCheck, given, settings

    accepted = rejected = 0
    escapes: list[FuzzFinding] = []
    seen: set[tuple[Any, ...]] = set()
    with ModuleMonitor(module) as monitor:

        @settings(
            max_examples=max_examples,
            deadline=None,
            database=None,
            derandomize=True,
            suppress_health_check=list(HealthCheck),
        )
        @given(strategy)
        def arm(data: bytes) -> None:
            outcome, exc = classify(target, data, allowed_rejections)
            if outcome == "accepted":
                nonlocal accepted
                accepted += 1
            elif outcome == "rejected":
                nonlocal rejected
                rejected += 1
            elif exc is not None:
                escapes.append(
                    FuzzFinding(
                        input_bytes=data,
                        exception_type=type(exc).__name__,
                        exception_message=str(exc)[:300],
                        exec_index=-1,
                    )
                )
            seen.update(monitor.edges())

        arm()
    return HypothesisArmResult(
        execs=accepted + rejected + len(escapes),
        edges=len(seen),
        accepted=accepted,
        rejected=rejected,
        escapes=tuple(escapes),
    )
