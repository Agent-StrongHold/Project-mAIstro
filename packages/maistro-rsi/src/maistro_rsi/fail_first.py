"""Fail-first evidence: the promotion contract for behavior-changing RSI work (#392).

Before this module, a source-touching candidate could satisfy the loop with a
*characterization* test — one that snapshots current behavior, passes on the
base revision, and is committed alongside the change as "test-first" evidence.
Nothing proved the test ever failed, so nothing proved the change fixed or
improved anything: red→green was only a small positive *signal*
(``maistro_evolve.tdd_gate``), never a requirement, and the recorded evidence
was two bare exit codes.

The contract now has teeth, in four parts:

1. **Classification** (:func:`resolve_contract`) — every candidate resolves to
   an evidence contract from its declared ``ImprovementKind`` and diff shape:

   - ``BEHAVIOR``   — the diff touches non-test source. Fail-first evidence is
     REQUIRED: a new/changed test that fails on the exact base revision, for
     the reason the change cures, and passes on the candidate.
   - ``REFACTOR``   — declared refactor/doc polish that still touches source.
     Alternative evidence: the module's static code-quality composite must
     measurably improve against the baseline (behavior preservation stays with
     the universal gates: tests pass, coverage not dropped, mutation probe).
   - ``CHARACTERIZATION`` — test-only diff. Alternative evidence: net-new
     tests and/or a measurable assertion-strength delta (the new_test/coverage
     signals already reward this) — a characterization test is welcome, it is
     just never *improvement* evidence for a source change.
   - ``DOCUMENTATION`` — no code at all (spec drafts, markdown). The existing
     doc-regression veto and spec signals are the contract.

2. **Collection** (:func:`collect_fail_first_evidence`) — the probe reverts
   ONLY the candidate's source files in the worktree (keeping the candidate's
   tests and config), runs the changed tests twice on that base state, and
   restores. It records the base SHA, the failing test identities, a digest of
   the failure output, the candidate SHA, and the passing result — the exact
   record an auditor needs to replay the proof.

3. **Anti-manufacturing** — a candidate cannot conjure a failure:

   - the red must be *attributable*: it appears when (and only when) the
     source change is reverted, and it must *reproduce* — the second probe
     must fail with the identical test set, else the evidence is flaky noise;
   - the red must *vanish on the candidate* (green), so a permanently broken
     or sabotaged oracle doesn't count;
   - the failing test must *reference the changed source* (static import
     match) — picking an unrelated already-failing test doesn't count;
   - any edited pytest configuration file (``conftest.py``, ``pytest.ini``,
     ``pyproject.toml``, ...) voids the evidence outright — config edits are
     the cheapest way to manufacture a red (same taint rule the
     protected-inventory gate applies to shrinkage, #306).

4. **Enforcement** (:func:`fail_first_gate`) — a ``Scorecard`` gate, so a
   candidate with missing, non-reproducible, already-passing, unrelated, or
   config-tainted evidence is REJECTED before promotion, and the gate detail
   (the full evidence record) rides the promotion's git-notes trace
   (``trace_notes.TraceNote.fail_first``).

Valid fail-first evidence also satisfies the REFACTOR contract — it is
strictly stronger proof. A refactor without it must show the measured
quality delta instead; a behavior change has no such substitute.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence, run_test_selection

__all__ = [
    "EvidenceContract",
    "FailFirstEvidence",
    "ProbeExecutor",
    "collect_fail_first_evidence",
    "fail_first_gate",
    "resolve_contract",
]

# Improvement kinds whose contract is NOT behavior-first: declared
# refactor/doc polish may touch source without fail-first evidence, but then
# owes the refactor alternative evidence (measured quality delta). Every other
# declared kind — and any undeclared/generic objective — is held to BEHAVIOR.
_NON_BEHAVIORAL_KINDS = frozenset({"refactor", "doc"})


class EvidenceContract(StrEnum):
    """Which evidence a candidate owes for its diff (see module docstring)."""

    BEHAVIOR = "behavior"  # fail-first REQUIRED
    REFACTOR = "refactor"  # measured code-quality delta required
    CHARACTERIZATION = "characterization"  # test-only: net-new tests / assertion strength
    DOCUMENTATION = "documentation"  # no code: doc-regression + spec signals


def resolve_contract(
    declared_kind: str | None, changed_src: list[str], changed_tests: list[str]
) -> EvidenceContract:
    """Classify the evidence contract for a candidate diff.

    ``declared_kind`` is the slot's ``ImprovementKind`` value (lowercased str).
    Diff shape decides between code/no-code; the declaration only decides
    whether source-touching work is held to fail-first (default) or to the
    refactor alternative contract. Test-only diffs are characterization —
    deliberately NOT an escape hatch for source changes, so a candidate cannot
    downgrade its own contract by what it edits.
    """
    if changed_src:
        if (declared_kind or "").strip().lower() in _NON_BEHAVIORAL_KINDS:
            return EvidenceContract.REFACTOR
        return EvidenceContract.BEHAVIOR
    if changed_tests:
        return EvidenceContract.CHARACTERIZATION
    return EvidenceContract.DOCUMENTATION


@dataclass
class FailFirstEvidence:
    """The replayable record that a changed test failed on the exact base.

    ``base_sha`` / ``candidate_sha`` pin both revisions; ``failing_tests`` are
    the pytest node IDs that were red on the base; ``failure_digest`` is a
    sha256 over the canonical (sorted) failure identities; ``passing_on_candidate``
    is the same selection's result on the candidate tree; ``reproducible``
    records that a second base probe failed with the identical set;
    ``config_tainted`` and ``related`` are the two manufacturing guards.
    """

    base_sha: str
    candidate_sha: str
    failing_tests: list[str] = field(default_factory=list)
    failure_digest: str = ""
    passing_on_candidate: bool = False
    # Exit codes of the changed-test selection on each tree — the TddEvidence
    # view (red->green signal) is derived from these, so the probe runs once
    # for both consumers.
    candidate_changed_rc: int | None = None
    baseline_changed_rc: int | None = None
    reproducible: bool = False
    config_tainted: bool = False
    related: bool = False

    @property
    def status(self) -> str:
        """``valid`` or the specific reason the evidence is rejected. Order is
        the audit order: identity, greenness, reproducibility, then the two
        manufacturing guards."""
        if not self.failing_tests:
            return "already_passing"
        if not self.passing_on_candidate:
            return "not_green_on_candidate"
        if not self.reproducible:
            return "non_reproducible"
        if self.config_tainted:
            return "config_tainted"
        if not self.related:
            return "unrelated"
        return "valid"

    def tdd_view(self, tests: list[str]) -> TddEvidence:
        """The red→green signal view of the same probe (tdd_gate), for the
        given changed-test file paths."""
        return TddEvidence(
            changed_tests=list(tests),
            baseline_changed_rc=self.baseline_changed_rc,
            candidate_changed_rc=self.candidate_changed_rc,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "failing_tests": list(self.failing_tests),
            "failure_digest": self.failure_digest,
            "passing_on_candidate": self.passing_on_candidate,
            "reproducible": self.reproducible,
            "config_tainted": self.config_tainted,
            "related": self.related,
        }


_REJECTION_TEXT = {
    "already_passing": (
        "changed test(s) already pass on the base revision — a characterization "
        "snapshot is not improvement evidence"
    ),
    "not_green_on_candidate": "failing test(s) still fail on the candidate — the change does not fix them",
    "non_reproducible": "fail-first evidence is not reproducible (flaky or unattributable failure)",
    "config_tainted": (
        "fail-first evidence void: pytest configuration/oracle files were edited "
        "(a config edit can manufacture a failure)"
    ),
    "unrelated": (
        "fail-first evidence unrelated: failing test(s) do not reference any changed source module"
    ),
}


def failure_digest(failing_tests: list[str]) -> str:
    """Stable digest over the canonical failure identity set."""
    canonical = "\n".join(sorted(failing_tests))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rev_parse(cwd: Path, ref: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", ref], cwd=str(cwd), capture_output=True, text=True, timeout=30
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _failure_ids(output: str) -> list[str]:
    """Parse failing/erroring test identities from pytest's short summary.

    ``run_test_selection`` is invoked with ``-rfE`` so every failure and error
    prints a ``FAILED <nodeid> - ...`` / ``ERROR <file> - ...`` line. Errors
    count as failures with file-level identity (a candidate test that only
    imports on the candidate — e.g. ``from mod import new_func`` — is exactly
    red-on-base for the intended reason, but has no function-level node ID).
    """
    ids: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        for tag in ("FAILED ", "ERROR "):
            if stripped.startswith(tag):
                ident = stripped[len(tag) :].split()[0]
                if ident not in ids:
                    ids.append(ident)
    return ids


def _probe(ex: ProbeExecutor, tests: list[str], timeout: int) -> tuple[int, list[str]]:
    """Run the changed-test selection through ``ex``; return (exit code, ids)."""
    rc, out = ex.probe(tests, timeout)
    return rc, _failure_ids(out)


class ProbeExecutor(Protocol):
    """Where the fail-first probe's steps run (#614).

    The probe replays the candidate's changed tests against the baseline —
    which means importing candidate-authored test code. On the host that is
    the same escape the test gate closed; under container isolation the caller
    supplies an executor whose every step runs inside the evaluation sandbox.
    The default host executor below keeps the CLI paths unchanged.
    """

    def rev_parse(self, ref: str) -> str:
        """Full SHA for ``ref``, or "" when it does not resolve."""
        ...

    def base_has(self, ref: str, rel: str) -> bool:
        """Does ``ref`` carry ``rel``?"""
        ...

    def checkout(self, ref: str, rel: str) -> None:
        """Restore ``rel``'s contents from ``ref``."""
        ...

    def remove(self, rel: str) -> None:
        """Delete ``rel`` from the tree (its base state is absence)."""
        ...

    def probe(self, tests: list[str], timeout: int) -> tuple[int, str]:
        """Run the changed-test selection; return (exit code, output)."""
        ...

    def read_text(self, rel: str) -> str:
        """File content as data; raises OSError when absent."""
        ...


def _resolve_executor(executor: ProbeExecutor | None, cwd: Path) -> ProbeExecutor:
    """The caller's executor, or the host default (#614): the CLI paths run git
    and pytest as child processes here, and a contained evaluation passes the
    sandbox-backed one."""
    return executor if executor is not None else _HostExecutor(cwd)


class _HostExecutor:
    """The historical behavior: git and pytest run as child processes here."""

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def rev_parse(self, ref: str) -> str:
        return _rev_parse(self._cwd, ref)

    def base_has(self, ref: str, rel: str) -> bool:
        return _base_has(self._cwd, ref, rel)

    def checkout(self, ref: str, rel: str) -> None:
        subprocess.run(
            ["git", "checkout", ref, "--", rel],
            cwd=str(self._cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def remove(self, rel: str) -> None:
        (self._cwd / rel).unlink(missing_ok=True)

    def probe(self, tests: list[str], timeout: int) -> tuple[int, str]:
        return run_test_selection(self._cwd, tests, timeout=timeout, extra_args=("-rfE",))

    def read_text(self, rel: str) -> str:
        return (self._cwd / rel).read_text(encoding="utf-8")


def _base_has(cwd: Path, baseline_ref: str, rel: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{baseline_ref}:{rel}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


def _resolve_evidence_shas(ex: ProbeExecutor, baseline_ref: str) -> tuple[str, str] | None:
    """(base, candidate) SHAs anchoring the evidence record.

    ``None`` when either revision cannot be resolved: without both SHAs the
    record is not replayable by an auditor, so there is no evidence to
    collect. (#1792: extracted from ``collect_fail_first_evidence``.) The
    lookups ride the probe executor (#614).
    """
    base_sha = ex.rev_parse(baseline_ref)
    candidate_sha = ex.rev_parse("HEAD")
    if not base_sha or not candidate_sha:
        return None
    return base_sha, candidate_sha


def _tree_states(
    cwd: Path, src: list[str], baseline_ref: str, ex: ProbeExecutor
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Per-file presence maps, (candidate, base), captured BEFORE any revert.

    The candidate snapshot must precede the base reconstruction so the restore
    can rebuild even candidate DELETIONS (a plain ``git checkout HEAD --``
    would silently resurrect a deleted file). The base probe rides the
    executor (#614). (#1792 extraction.)
    """
    candidate_present = {rel: (cwd / rel).is_file() for rel in src}
    base_present = {rel: ex.base_has(baseline_ref, rel) for rel in src}
    return candidate_present, base_present


def _reconstruct_tree(
    src: list[str], present: dict[str, bool], from_ref: str | None, ex: ProbeExecutor
) -> None:
    """Force ``src`` to a recorded presence state.

    A file marked present is checked out of ``from_ref`` (``HEAD`` when no
    ref is given); a file marked absent is removed — its base state is
    absence, which is exactly how a test written FIRST for a new module
    proves fail-first. Both moves ride the executor (#614). (#1792: the
    probe's restore closure, hoisted to a module function so both tree flips
    share it.)
    """
    for rel in src:
        if present[rel]:
            ex.checkout(from_ref or "HEAD", rel)
        else:
            ex.remove(rel)


def _run_base_probes(
    src: list[str],
    tests: list[str],
    timeout: int,
    baseline_ref: str,
    base_present: dict[str, bool],
    ex: ProbeExecutor,
) -> tuple[int | None, int | None, list[str], list[str]] | None:
    """Run the changed-test selection on the reconstructed base state.

    A red first run is probed a second time for reproducibility; a green one
    stops early (the evidence is already-passing and a second run cannot
    change that). Returns ``(rc1, rc2, failing1, failing2)`` — ``rc2`` is
    ``None`` when no second run happened — or ``None`` when the base state
    cannot be constructed or run, which is no trustworthy evidence. The
    caller still restores the candidate tree. (#1792 extraction.)
    """
    base_rc2: int | None = None
    failing2: list[str] = []
    try:
        _reconstruct_tree(src, base_present, baseline_ref, ex)
        base_rc1, failing1 = _probe(ex, tests, timeout)
        if failing1:
            base_rc2, failing2 = _probe(ex, tests, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return base_rc1, base_rc2, failing1, failing2


def _reproducible(failing1: list[str], failing2: list[str], base_rc2: int | None) -> bool:
    """The red must reproduce: the second base probe fails with the identical
    test set, else the evidence is flaky noise. (#1792 extraction.)"""
    return bool(failing1) and base_rc2 is not None and failing1 == failing2


def collect_fail_first_evidence(
    cwd: str | Path,
    baseline_ref: str,
    src: list[str],
    tests: list[str],
    timeout: int,
    *,
    config_files_changed: list[str] | None = None,
    executor: ProbeExecutor | None = None,
) -> FailFirstEvidence | None:
    """Probe whether the candidate's changed tests fail on the exact base.

    Reconstructs the base state of ONLY the candidate's source files (tests
    and config stay candidate): a file that exists on ``baseline_ref`` is
    checked out from it; a NEW file (absent on base) is removed, because its
    base state is absence — that is exactly how a test written FIRST for a
    new module proves fail-first (ImportError on base, green once the module
    lands). Runs the changed-test selection twice on that base state, then
    restores the exact candidate state. Returns ``None`` when there is nothing
    to probe (no changed tests, or nothing source-touching — a test-only diff
    never claims fail-first) or when the base state cannot be constructed; the
    gate treats ``None`` as *missing* evidence and fails the behavior contract
    closed.

    The candidate MUST be committed (``HEAD`` is the candidate) — the restore
    step reconstructs each source file from ``HEAD`` (or removes it if the
    candidate deleted/newly-absent state says so). The loop guarantees the
    commit: ``_run_variant``/``code_fixer`` commit before scoring.

    Every step that runs candidate code — the probes replaying the changed
    tests — goes through ``executor`` (#614). The default host executor keeps
    the CLI paths; a contained evaluation passes one backed by the sandbox
    opened for this candidate, so the replay imports candidate test code only
    where the candidate's edits live. Git plumbing (rev-parse, cat-file,
    checkout) moves files per the ref's recorded contents and executes
    nothing the candidate wrote either way.

    Cost: one selection run on the candidate (green check — the same run the
    red→green signal always needed) plus two on the base when the first base
    run is red (reproducibility). A green first base run stops early: the
    evidence is already-passing and a second run cannot change that.
    """
    if not tests or not src:
        return None
    cwd = Path(cwd)
    ex = _resolve_executor(executor, cwd)
    resolved = _resolve_evidence_shas(ex, baseline_ref)
    if resolved is None:
        return None
    base_sha, candidate_sha = resolved

    cand_rc, _ = ex.probe(tests, timeout)

    candidate_present, base_present = _tree_states(cwd, src, baseline_ref, ex)
    probed: tuple[int | None, int | None, list[str], list[str]] | None = None
    try:
        probed = _run_base_probes(src, tests, timeout, baseline_ref, base_present, ex)
    finally:
        # Restore the exact candidate state on every path out of the probe.
        _reconstruct_tree(src, candidate_present, "HEAD", ex)
    if probed is None:
        # Cannot construct (or run against) the base state — no trustworthy
        # evidence; the gate fails the behavior contract closed.
        return None
    base_rc1, base_rc2, failing1, failing2 = probed

    return FailFirstEvidence(
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        failing_tests=failing1,
        failure_digest=failure_digest(failing1) if failing1 else "",
        passing_on_candidate=cand_rc == 0,
        candidate_changed_rc=cand_rc,
        baseline_changed_rc=base_rc1,
        reproducible=_reproducible(failing1, failing2, base_rc2),
        config_tainted=bool(config_files_changed),
        related=_has_related_failure(ex.read_text, failing1, src),
    )


def _module_suffixes(rel_src: str) -> set[str]:
    """Dotted suffixes of a source module path: ``a/b/c.py`` →
    ``{a.b.c, b.c, c}`` — so absolute imports, package-relative imports, and
    plain ``import c`` styles all match."""
    dotted = rel_src.replace("\\", "/").removesuffix(".py").replace("/", ".")
    parts = dotted.split(".")
    return {".".join(parts[i:]) for i in range(len(parts))}


def _imported_names(tree: ast.AST) -> set[str]:
    """Every dotted name a module imports, including ``module.member`` forms
    (``from pkg import mod`` yields both ``pkg`` and ``pkg.mod``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
            names.update(alias.name for alias in node.names)
    return names


def _test_module_imports(text: str) -> set[str]:
    """Every name one test file's source imports.

    The AST parse is primary; an unparsable file (``SyntaxError``), null
    bytes (``ValueError``) or pathologically nested source
    (``RecursionError``) falls back to a textual import-line match, so a
    syntactically broken test still gets the attribution check. Transport
    failures are the caller's concern — an unreadable file has no import
    surface at all, not a textual one. (#1792: extracted from
    ``_has_related_failure``; ``text`` arrives through the probe executor's
    ``read_text`` transport, #614.)
    """
    try:
        return _imported_names(ast.parse(text))
    except (SyntaxError, ValueError, RecursionError):
        return set(re.findall(r"(?:from|import)\s+([\w.]+)", text))


def _references_changed_module(text: str, suffixes: list[set[str]], stems: set[str]) -> bool:
    """Whether ONE test file's source statically references any changed
    module: either an import that intersects a module's dotted suffixes, or
    any mention of a module's file stem. (#1792: extracted from
    ``_has_related_failure``.)
    """
    if any(_test_module_imports(text) & s for s in suffixes):
        return True
    return any(re.search(rf"\b{re.escape(stem)}\b", text) for stem in stems)


def _has_related_failure(
    read_text: Callable[[str], str], failing_ids: list[str], src: list[str]
) -> bool:
    """Whether at least one failing test statically references a changed module.

    The dynamic flip (red with source reverted, green with it) is the primary
    attribution; this static check is the "unrelated test" guard: a failing
    test that never mentions any changed source module can't be evidence FOR
    that change, even if it flips for incidental reasons. Reads file CONTENT
    through ``read_text`` — on the host that is the worktree; contained, the
    sandbox the evaluation opened — and parses it here: parsing executes
    nothing the candidate wrote.
    """
    if not failing_ids:
        return False
    suffixes = [_module_suffixes(s) for s in src]
    stems = {s.rsplit("/", 1)[-1].removesuffix(".py") for s in src}
    test_files = sorted({ident.split("::")[0] for ident in failing_ids})
    for rel in test_files:
        try:
            text = read_text(rel)
        except FileNotFoundError:
            # Absent on this side (restored away, or never present): there is
            # no import surface here to match against.
            continue
        except (OSError, RuntimeError):
            # Unreadable through this side's transport: same answer.
            continue
        if _references_changed_module(text, suffixes, stems):
            return True
    return False


def fail_first_gate(
    contract: EvidenceContract,
    evidence: FailFirstEvidence | None,
    *,
    quality_delta: float | None = None,
    net_new_tests: int = 0,
    assertion_score: float | None = None,
) -> GateResult:
    """The ``fail_first_evidence`` Scorecard gate — promotion vetoes live here.

    Valid fail-first evidence passes under EVERY contract (it is the strongest
    proof available). Otherwise each contract falls to its own alternative:

    - BEHAVIOR: reject with the specific status reason (missing / already
      passing / not green on candidate / non-reproducible / config-tainted /
      unrelated).
    - REFACTOR: the measured code-quality delta must exist and be > 0 —
      "I improved clarity" must be visible in the static composite vs base.
    - CHARACTERIZATION: a net-new test or a measurable assertion-strength
      score — some verification delta beyond a bare snapshot.
    - DOCUMENTATION: passes (doc-regression + spec signals are the contract).

    An absent baseline quality composite under REFACTOR fails closed: the
    refactor's alternative evidence cannot be verified, so it doesn't count.
    """
    if evidence is not None and evidence.status == "valid":
        return _valid_evidence_result(evidence)
    if contract is EvidenceContract.BEHAVIOR:
        return _behavior_contract_result(evidence)
    if contract is EvidenceContract.REFACTOR:
        return _refactor_contract_result(quality_delta)
    if contract is EvidenceContract.CHARACTERIZATION:
        return _characterization_contract_result(net_new_tests, assertion_score)
    return GateResult(
        "fail_first_evidence",
        True,
        "documentation contract: non-code diff — doc-regression veto and spec "
        "signals are the evidence",
        detail={"contract": EvidenceContract.DOCUMENTATION.value},
    )


def _valid_evidence_result(evidence: FailFirstEvidence) -> GateResult:
    """The pass verdict for valid fail-first evidence — the strongest proof
    available, honored under EVERY contract. (#1792 extraction.)"""
    return GateResult(
        "fail_first_evidence",
        True,
        (
            f"{len(evidence.failing_tests)} changed test(s) red on base "
            f"{evidence.base_sha[:12]} → green on candidate "
            f"{evidence.candidate_sha[:12]} (reproducible)"
        ),
        detail=evidence.to_dict(),
    )


def _behavior_contract_result(evidence: FailFirstEvidence | None) -> GateResult:
    """Reject a BEHAVIOR candidate with the specific status reason (missing,
    already passing, not green, non-reproducible, config-tainted, unrelated).
    (#1792 extraction.)"""
    if evidence is None:
        return GateResult(
            "fail_first_evidence",
            False,
            "missing fail-first evidence: a behavior-changing candidate must add or "
            "extend a test that fails on the base revision for the intended reason",
            detail={"contract": EvidenceContract.BEHAVIOR.value},
        )
    return GateResult(
        "fail_first_evidence",
        False,
        f"fail-first evidence rejected: {_REJECTION_TEXT[evidence.status]}",
        detail=evidence.to_dict(),
    )


def _refactor_contract_result(quality_delta: float | None) -> GateResult:
    """The REFACTOR alternative: the measured code-quality delta must exist
    (fail closed when the baseline composite is absent) and be > 0 — "I
    improved clarity" must be visible in the static composite vs base.
    (#1792 extraction.)"""
    if quality_delta is None:
        return GateResult(
            "fail_first_evidence",
            False,
            "refactor contract unmet: no baseline code-quality composite to "
            "prove the improvement against (fail closed)",
            detail={"contract": EvidenceContract.REFACTOR.value},
        )
    if quality_delta <= 0:
        return GateResult(
            "fail_first_evidence",
            False,
            f"refactor contract unmet: code-quality composite did not improve "
            f"over baseline (delta {quality_delta:+.4f})",
            detail={"contract": EvidenceContract.REFACTOR.value, "quality_delta": quality_delta},
        )
    return GateResult(
        "fail_first_evidence",
        True,
        f"refactor contract met: code-quality composite improved (delta {quality_delta:+.4f})",
        detail={"contract": EvidenceContract.REFACTOR.value, "quality_delta": quality_delta},
    )


def _characterization_contract_result(
    net_new_tests: int, assertion_score: float | None
) -> GateResult:
    """The CHARACTERIZATION alternative: a net-new test or a measurable
    assertion-strength score — some verification delta beyond a bare
    snapshot. (#1792 extraction.)"""
    if net_new_tests <= 0 and assertion_score is None:
        return GateResult(
            "fail_first_evidence",
            False,
            "characterization contract unmet: no net-new test and no measurable "
            "assertion-strength score — the test change verifies nothing new",
            detail={"contract": EvidenceContract.CHARACTERIZATION.value},
        )
    return GateResult(
        "fail_first_evidence",
        True,
        "characterization contract met: test-only diff judged by net-new tests "
        "and assertion strength (never fail-first credit)",
        detail={
            "contract": EvidenceContract.CHARACTERIZATION.value,
            "net_new_tests": net_new_tests,
            "assertion_score": assertion_score,
        },
    )
