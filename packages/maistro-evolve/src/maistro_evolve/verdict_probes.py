"""Adversarial/mutation evidence that benchmark verdicts are host-owned (#104 M4-G).

Epic #104 (M4-G) does not ask for another benchmark. It asks for the evidence
that a benchmark's pass/fail verdict belongs to the **host**, and that the
evidence can be falsified independently, before any number is published or fed
into M4 fitness/promotion.

The 2026-08-31 Defect Ladder named the ways this evidence had been fakeable:

1. a candidate sets the verdict through stdout/text formatting;
2. judge parsing accepts negated substrings, or cannot parse the format the
   prompt actually requests;
3. missing fields are rewarded;
4. tool-use benchmarks score prose mentions rather than observed structured
   calls.

This module is the falsifier for those classes.

Two halves, and the second is what makes the first mean anything
---------------------------------------------------------------
**Probes.** Each *verdict path* — a host-owned grader — is fed a corpus of
hostile candidate responses. Every one of them must be **rejected** (scored
0). A path that accepts any hostile response fails.

**Mutants.** Each verdict path also has a *permissive mutant* — a deliberately
gameable version of that same grader, reproducing the defect class the ladder
named. The same probe corpus must **kill** it: the mutant must accept at least
one hostile response. If a mutant survives, the probe corpus demonstrates
nothing — a battery that cannot tell a gameable grader from a hostile one
cannot certify that a real grader is host-owned. The battery therefore
measures its own power on every run, and the two columns ship together: a
report that says "no hostile response was accepted" is worthless without the
mutant column, and a report that says "the mutant was killed" is worthless
without the hostile column.

Scope boundary
--------------
This module *probes* graders; it does not become a second grading authority.
The graders it exercises are the production ones (``benchmarks.arc_agi``,
``benchmarks.scoring``); the mutants are test fixtures that are never
registered anywhere as a grader. Publication of a run's evidence is gated on a
passing report in :mod:`maistro_evolve.evidence_manifest` — the report is
evidence about the graders, not a replacement for them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .benchmarks.arc_agi import grade_attempt
from .benchmarks.scoring import function_call_match, json_field_match, judge_score

#: A host-owned verdict function: candidate response in, score in [0, 1] out.
#: 1.0 means "this candidate solved the task"; 0.0 means it did not.
VerdictFunction = Callable[[str], float]


class VerdictConformanceError(RuntimeError):
    """The verdict battery did not hold.

    Raised at the producer — the harness — so that a run whose verdicts
    cannot be falsified produces no results at all. Nothing downstream
    (fitness, promotion, publication) can then act on a number whose
    pass/fail rule was not shown to be host-owned.
    """


@dataclass(frozen=True)
class HostileResponse:
    """One candidate-authored response that must never be graded as a pass."""

    id: str
    defect_class: str
    response: str
    rationale: str


@dataclass(frozen=True)
class MutantGrader:
    """A deliberately gameable version of a verdict path.

    Mutants exist to prove the probe corpus has power. They are never
    registered anywhere as a grader — they only ever run *against* the probes,
    where accepting a hostile response is the expected outcome. A mutant that
    survives the corpus means the corpus is too weak to certify anything.
    """

    name: str
    rationale: str
    grade: VerdictFunction


@dataclass(frozen=True)
class VerdictPath:
    """A host-owned grader plus the hostile corpus that must not defeat it."""

    name: str
    rationale: str
    grade: VerdictFunction
    hostile: tuple[HostileResponse, ...]
    mutant: MutantGrader


@dataclass(frozen=True)
class VerdictProbe:
    """One probe's outcome against one verdict path."""

    path: str
    probe_id: str
    defect_class: str
    rationale: str
    response: str
    score: float
    rejected: bool


@dataclass(frozen=True)
class PathReport:
    """Per-path conformance: every hostile response rejected, mutant killed."""

    name: str
    rationale: str
    probes: tuple[VerdictProbe, ...]
    mutant_name: str
    mutant_rationale: str
    mutant_killed: bool
    mutant_survivor_ids: tuple[str, ...]

    @property
    def accepted_hostile(self) -> tuple[VerdictProbe, ...]:
        """Hostile responses this path failed to reject — the defect itself."""
        return tuple(p for p in self.probes if not p.rejected)

    @property
    def passed(self) -> bool:
        return not self.accepted_hostile and self.mutant_killed

    def failures(self) -> list[str]:
        problems = [
            f"{self.name}: accepted hostile response {p.probe_id!r} "
            f"({p.defect_class}) — score {p.score}"
            for p in self.accepted_hostile
        ]
        if not self.mutant_killed:
            problems.append(
                f"{self.name}: permissive mutant {self.mutant_name!r} survived "
                "the probe corpus — the corpus cannot certify this grader"
            )
        return problems


@dataclass(frozen=True)
class ConformanceReport:
    """The whole battery's verdict, publishable as the evidence section."""

    paths: tuple[PathReport, ...]

    @property
    def passed(self) -> bool:
        return bool(self.paths) and all(p.passed for p in self.paths)

    def failures(self) -> list[str]:
        problems: list[str] = []
        for path in self.paths:
            problems.extend(path.failures())
        if not self.paths:
            problems.append("no verdict path was probed — an empty battery certifies nothing")
        return problems

    def to_section(self) -> list[dict[str, object]]:
        """The manifest shape: one row per verdict path, mutants included."""
        return [
            {
                "grader": path.name,
                "rationale": path.rationale,
                "hostile_total": len(path.probes),
                "hostile_rejected": sum(1 for p in path.probes if p.rejected),
                "surviving_hostile": [p.probe_id for p in path.accepted_hostile],
                "mutant": path.mutant_name,
                "mutant_rationale": path.mutant_rationale,
                "mutant_killed": path.mutant_killed,
                "mutant_survivor_ids": list(path.mutant_survivor_ids),
                "passed": path.passed,
            }
            for path in self.paths
        ]


# --- the hostile corpora ----------------------------------------------------
#
# One corpus per verdict path. A corpus is only meaningful against the grader
# it was written for: "the answer is 42" is hostile to a JSON-field grader and
# irrelevant to a grid grader, and pretending otherwise would make the report
# look broader than it is.


def _arc_agi_grade(response: str) -> float:
    """The production ARC-AGI verdict: exact structural grid match."""
    correct, _spoofed = grade_attempt(response, [[1, 0], [0, 1]])
    return 1.0 if correct else 0.0


def _json_field_grade(response: str) -> float:
    """The production JSON-field verdict: the field must be present and equal."""
    return json_field_match(response, "answer", 42)


def _tool_call_grade(response: str) -> float:
    """The production tool-call verdict: an observed structured call."""
    return function_call_match(response, "get_weather", {"city": "Paris"})


_ARC_HOSTILE: tuple[HostileResponse, ...] = (
    HostileResponse(
        id="spoofed-verdict-marker",
        defect_class="verdict-through-text-formatting",
        response="PASS",
        rationale="a candidate that prints a verdict marker instead of a grid "
        "must not be graded as solving the task",
    ),
    HostileResponse(
        id="prose-embedded-grid",
        defect_class="verdict-through-text-formatting",
        response="The answer is [[1, 0], [0, 1]].",
        rationale="the correct grid buried in prose is not a grid; only the "
        "requested structured output counts",
    ),
    HostileResponse(
        id="boolean-cells",
        defect_class="type-strict-canonicalization",
        response="[[true, false], [false, true]]",
        rationale="JSON booleans are not integers; True != 1",
    ),
    HostileResponse(
        id="transposed-grid",
        defect_class="wrong-answer",
        response="[[0, 1], [1, 0]]",
        rationale="a parseable but incorrect grid scores zero",
    ),
    HostileResponse(
        id="empty-response",
        defect_class="malformed-output",
        response="",
        rationale="an empty response is not an answer",
    ),
)

_JSON_FIELD_HOSTILE: tuple[HostileResponse, ...] = (
    HostileResponse(
        id="missing-field",
        defect_class="absence-rewarded",
        response='{"other": 1}',
        rationale="a missing required field must fail, not be rewarded "
        "(the historical None-equals-None defect)",
    ),
    HostileResponse(
        id="null-field",
        defect_class="absence-rewarded",
        response='{"answer": null}',
        rationale="an explicitly null value is not the expected value",
    ),
    HostileResponse(
        id="stringified-number",
        defect_class="type-strict-canonicalization",
        response='{"answer": "42"}',
        rationale="'42' is not 42",
    ),
    HostileResponse(
        id="not-json",
        defect_class="malformed-output",
        response="answer: 42",
        rationale="unparseable output is a failure, never a partial pass",
    ),
    HostileResponse(
        id="array-response",
        defect_class="type-strict-canonicalization",
        response="[42]",
        rationale="a JSON array is not an object with the required field",
    ),
    HostileResponse(
        id="absent-keyword",
        defect_class="malformed-output",
        response="the answer is 42",
        rationale="prose mentioning the value is not a structured answer",
    ),
)

_TOOL_CALL_HOSTILE: tuple[HostileResponse, ...] = (
    HostileResponse(
        id="prose-tool-mention",
        defect_class="prose-mention-scored-as-call",
        response="I called the tool get_weather(city='Paris')",
        rationale="a prose mention of a tool is not an observed structured call",
    ),
    HostileResponse(
        id="wrong-tool-name",
        defect_class="wrong-call",
        response='{"name": "get_time", "parameters": {"city": "Paris"}}',
        rationale="the wrong tool was called",
    ),
    HostileResponse(
        id="missing-parameters",
        defect_class="wrong-call",
        response='{"name": "get_weather"}',
        rationale="a call without the required parameter did not make the call",
    ),
    HostileResponse(
        id="wrong-parameter-value",
        defect_class="wrong-call",
        response='{"name": "get_weather", "parameters": {"city": "London"}}',
        rationale="the right tool with the wrong argument is not the call",
    ),
)

_JUDGE_HOSTILE: tuple[HostileResponse, ...] = (
    HostileResponse(
        id="negated-verdict",
        defect_class="negated-substring-accepted",
        response="incorrect",
        rationale="'incorrect' contains 'correct'; a substring scan would score it as a pass",
    ),
    HostileResponse(
        id="negated-phrase",
        defect_class="negated-substring-accepted",
        response="not correct",
        rationale="'not correct' contains 'correct'; word boundaries and "
        "negation-first ordering are what keep it a failure",
    ),
    HostileResponse(
        id="malformed-json-verdict",
        defect_class="malformed-output",
        response='{"score": "high"}',
        rationale="a verdict object with a non-numeric score is malformed, not a score",
    ),
    HostileResponse(
        id="truncated-json-verdict",
        defect_class="malformed-output",
        response='{"score": ',
        rationale="unparseable verdict output fails closed",
    ),
    HostileResponse(
        id="unparseable-prose",
        defect_class="malformed-output",
        response="The candidate seems to have done well.",
        rationale="prose with no verdict is not a verdict",
    ),
    HostileResponse(
        id="empty-verdict",
        defect_class="malformed-output",
        response="",
        rationale="an empty verdict is not a pass",
    ),
)


# --- the permissive mutants -------------------------------------------------


def _arc_agi_mutant(response: str) -> float:
    """The historical defect: a printed verdict marker sets the verdict."""
    return 1.0 if "pass" in response.lower() else 0.0


def _json_field_mutant(response: str) -> float:
    """The historical defect: a missing field is rewarded as if it matched."""
    try:
        data = json.loads(response.strip())
    except (json.JSONDecodeError, ValueError):
        return 0.0
    if isinstance(data, dict):
        return 1.0 if data.get("answer") is None else 0.0
    return 0.0


def _tool_call_mutant(response: str) -> float:
    """The historical defect: a prose mention of the tool counts as the call."""
    return 1.0 if "get_weather" in response.lower() else 0.0


def _judge_mutant(response: str) -> float:
    """The historical defect: a substring scan for 'correct' accepts 'incorrect'."""
    return 1.0 if "correct" in response.lower() else 0.0


#: The verdict paths this package ships probes for. Each names the production
#: grader it exercises — these are the graders a candidate could otherwise
#: influence through its own output.
VERDICT_PATHS: tuple[VerdictPath, ...] = (
    VerdictPath(
        name="arc_agi_exact_grid",
        rationale="the second-domain grader compares the candidate's parsed "
        "grid with the withheld expected grid; the candidate cannot reach "
        "the expected value",
        grade=_arc_agi_grade,
        hostile=_ARC_HOSTILE,
        mutant=MutantGrader(
            name="pass-marker-substring",
            rationale="the pre-#852 shape: a printed 'PASS' sets the verdict",
            grade=_arc_agi_mutant,
        ),
    ),
    VerdictPath(
        name="json_field_required",
        rationale="the structured-answer grader requires the field to be "
        "present and equal to the expected value",
        grade=_json_field_grade,
        hostile=_JSON_FIELD_HOSTILE,
        mutant=MutantGrader(
            name="absence-rewarded",
            rationale="the pre-#852 shape: an absent field compared equal to "
            "None and therefore scored 1.0",
            grade=_json_field_mutant,
        ),
    ),
    VerdictPath(
        name="tool_call_structured",
        rationale="the tool-use grader requires an observed structured call, not a mention of one",
        grade=_tool_call_grade,
        hostile=_TOOL_CALL_HOSTILE,
        mutant=MutantGrader(
            name="prose-mention-counts",
            rationale="the pre-#852 shape: the tool's name appearing in the "
            "response was enough to count as the call",
            grade=_tool_call_mutant,
        ),
    ),
    VerdictPath(
        name="judge_parse_fail_closed",
        rationale="the judge parser reads a verdict the host asked for; it "
        "must fail closed on anything it cannot parse, and must not read a "
        "negation as a pass",
        grade=judge_score,
        hostile=_JUDGE_HOSTILE,
        mutant=MutantGrader(
            name="negated-substring",
            rationale="the pre-#852 shape: 'incorrect' matched the 'correct' "
            "substring and scored as a pass",
            grade=_judge_mutant,
        ),
    ),
)


def probe_verdict_path(path: VerdictPath) -> tuple[VerdictProbe, ...]:
    """Run ``path``'s hostile corpus through its grader.

    A probe is *rejected* when the grader scores it 0. A grader that scores a
    hostile response above 0 has a hole, and the hole is the finding — the
    score, not the probe, is what is reported.
    """
    probes: list[VerdictProbe] = []
    for hostile in path.hostile:
        score = float(path.grade(hostile.response))
        probes.append(
            VerdictProbe(
                path=path.name,
                probe_id=hostile.id,
                defect_class=hostile.defect_class,
                rationale=hostile.rationale,
                response=hostile.response,
                score=score,
                rejected=score <= 0.0,
            )
        )
    return tuple(probes)


def _probe_mutant(path: VerdictPath) -> tuple[bool, tuple[str, ...]]:
    """Did the permissive mutant die? Returns (killed, surviving probe ids).

    The mutant is killed when it accepts at least one hostile response — that
    is, when the same corpus that must defeat the real grader defeats the
    gameable one. A mutant that accepts nothing is indistinguishable from the
    real grader, and the corpus has then proved nothing about either.
    """
    surviving = tuple(
        hostile.id for hostile in path.hostile if path.mutant.grade(hostile.response) > 0.0
    )
    return bool(surviving), surviving


def run_conformance(paths: Iterable[VerdictPath] | None = None) -> ConformanceReport:
    """Probe every verdict path and measure the battery's own power.

    The report is only a pass when *both* halves hold for every path: no
    hostile response was accepted, and the permissive mutant was killed.
    """
    selected = tuple(paths) if paths is not None else VERDICT_PATHS
    reports: list[PathReport] = []
    for path in selected:
        probes = probe_verdict_path(path)
        killed, survivors = _probe_mutant(path)
        reports.append(
            PathReport(
                name=path.name,
                rationale=path.rationale,
                probes=probes,
                mutant_name=path.mutant.name,
                mutant_rationale=path.mutant.rationale,
                mutant_killed=killed,
                mutant_survivor_ids=survivors,
            )
        )
    return ConformanceReport(paths=tuple(reports))


def conformance_gate_failures(report: ConformanceReport) -> list[str]:
    """Gate entries for a conformance report that does not hold.

    Wired into the same shape as the other evolve gates (``FitnessComponents
    .gate_failures``): a reason a caller can surface, not a boolean.
    """
    return report.failures()


def require_conformance(report: ConformanceReport) -> ConformanceReport:
    """Return the report, or raise if the battery does not hold.

    Fail closed, and fail at the producer: the harness runs this before it
    hands any result back, so a grader that accepts a hostile response stops
    the run instead of producing numbers that look quotable.
    """
    failures = conformance_gate_failures(report)
    if failures:
        raise VerdictConformanceError(
            "the verdict battery did not hold, so this run's pass/fail "
            "verdicts are not shown to be host-owned: " + "; ".join(failures)
        )
    return report


__all__ = [
    "VERDICT_PATHS",
    "ConformanceReport",
    "HostileResponse",
    "MutantGrader",
    "PathReport",
    "VerdictConformanceError",
    "VerdictFunction",
    "VerdictPath",
    "VerdictProbe",
    "conformance_gate_failures",
    "probe_verdict_path",
    "require_conformance",
    "run_conformance",
]
