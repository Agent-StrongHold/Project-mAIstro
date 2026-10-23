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
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from maistro_evolve.scorecard import GateResult
from maistro_evolve.tdd_gate import TddEvidence, run_test_selection

__all__ = [
    "EvidenceContract",
    "FailFirstEvidence",
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


def _probe(cwd: Path, tests: list[str], timeout: int) -> tuple[int, list[str]]:
    """Run the changed-test selection; return (exit code, failing identities)."""
    rc, out = run_test_selection(cwd, tests, timeout=timeout, extra_args=("-rfE",))
    return rc, _failure_ids(out)


def _base_has(cwd: Path, baseline_ref: str, rel: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{baseline_ref}:{rel}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


def collect_fail_first_evidence(
    cwd: str | Path,
    baseline_ref: str,
    src: list[str],
    tests: list[str],
    timeout: int,
    *,
    config_files_changed: list[str] | None = None,
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

    Cost: one selection run on the candidate (green check — the same run the
    red→green signal always needed) plus two on the base when the first base
    run is red (reproducibility). A green first base run stops early: the
    evidence is already-passing and a second run cannot change that.
    """
    if not tests or not src:
        return None
    cwd = Path(cwd)
    base_sha = _rev_parse(cwd, baseline_ref)
    candidate_sha = _rev_parse(cwd, "HEAD")
    if not base_sha or not candidate_sha:
        return None

    cand_rc, _ = _probe(cwd, tests, timeout)

    # Exact candidate state per source file, captured BEFORE any revert, so
    # the restore can reconstruct it even for candidate DELETIONS (a plain
    # ``git checkout HEAD --`` would silently resurrect a deleted file).
    candidate_present = {rel: (cwd / rel).is_file() for rel in src}
    base_present = {rel: _base_has(cwd, baseline_ref, rel) for rel in src}

    def _reconstruct(state: dict[str, bool], from_ref: str | None) -> None:
        for rel in src:
            path = cwd / rel
            if state[rel]:
                subprocess.run(
                    ["git", "checkout", from_ref or "HEAD", "--", rel],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            else:
                path.unlink(missing_ok=True)

    base_rc1: int | None = None
    base_rc2: int | None = None
    failing1: list[str] = []
    failing2: list[str] = []
    try:
        _reconstruct(base_present, baseline_ref)
        base_rc1, failing1 = _probe(cwd, tests, timeout)
        if failing1:
            base_rc2, failing2 = _probe(cwd, tests, timeout)
    except (OSError, subprocess.SubprocessError):
        # Cannot construct (or run against) the base state — no trustworthy
        # evidence. The restore below still runs.
        return None
    finally:
        _reconstruct(candidate_present, "HEAD")

    return FailFirstEvidence(
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        failing_tests=failing1,
        failure_digest=failure_digest(failing1) if failing1 else "",
        passing_on_candidate=cand_rc == 0,
        candidate_changed_rc=cand_rc,
        baseline_changed_rc=base_rc1,
        reproducible=bool(failing1) and base_rc2 is not None and failing1 == failing2,
        config_tainted=bool(config_files_changed),
        related=_has_related_failure(cwd, failing1, src),
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


def _has_related_failure(cwd: Path, failing_ids: list[str], src: list[str]) -> bool:
    """Whether at least one failing test statically references a changed module.

    The dynamic flip (red with source reverted, green with it) is the primary
    attribution; this static check is the "unrelated test" guard: a failing
    test that never mentions any changed source module can't be evidence FOR
    that change, even if it flips for incidental reasons.
    """
    if not failing_ids:
        return False
    suffixes = [_module_suffixes(s) for s in src]
    stems = {s.rsplit("/", 1)[-1].removesuffix(".py") for s in src}
    test_files = sorted({ident.split("::")[0] for ident in failing_ids})
    for rel in test_files:
        path = cwd / rel
        if not path.is_file():
            continue
        try:
            imported = _imported_names(ast.parse(path.read_text(encoding="utf-8")))
        except (OSError, SyntaxError, ValueError):
            # Unparsable test file: fall back to a textual import-line match.
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            imported = set(re.findall(r"(?:from|import)\s+([\w.]+)", text))
        if any(imported & s for s in suffixes):
            return True
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(re.search(rf"\b{re.escape(stem)}\b", content) for stem in stems):
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

    if contract is EvidenceContract.BEHAVIOR:
        if evidence is None:
            return GateResult(
                "fail_first_evidence",
                False,
                "missing fail-first evidence: a behavior-changing candidate must add or "
                "extend a test that fails on the base revision for the intended reason",
                detail={"contract": contract.value},
            )
        return GateResult(
            "fail_first_evidence",
            False,
            f"fail-first evidence rejected: {_REJECTION_TEXT[evidence.status]}",
            detail=evidence.to_dict(),
        )

    if contract is EvidenceContract.REFACTOR:
        if quality_delta is None:
            return GateResult(
                "fail_first_evidence",
                False,
                "refactor contract unmet: no baseline code-quality composite to "
                "prove the improvement against (fail closed)",
                detail={"contract": contract.value},
            )
        if quality_delta <= 0:
            return GateResult(
                "fail_first_evidence",
                False,
                f"refactor contract unmet: code-quality composite did not improve "
                f"over baseline (delta {quality_delta:+.4f})",
                detail={"contract": contract.value, "quality_delta": quality_delta},
            )
        return GateResult(
            "fail_first_evidence",
            True,
            f"refactor contract met: code-quality composite improved (delta {quality_delta:+.4f})",
            detail={"contract": contract.value, "quality_delta": quality_delta},
        )

    if contract is EvidenceContract.CHARACTERIZATION:
        if net_new_tests <= 0 and assertion_score is None:
            return GateResult(
                "fail_first_evidence",
                False,
                "characterization contract unmet: no net-new test and no measurable "
                "assertion-strength score — the test change verifies nothing new",
                detail={"contract": contract.value},
            )
        return GateResult(
            "fail_first_evidence",
            True,
            "characterization contract met: test-only diff judged by net-new tests "
            "and assertion strength (never fail-first credit)",
            detail={
                "contract": contract.value,
                "net_new_tests": net_new_tests,
                "assertion_score": assertion_score,
            },
        )

    return GateResult(
        "fail_first_evidence",
        True,
        "documentation contract: non-code diff — doc-regression veto and spec "
        "signals are the evidence",
        detail={"contract": EvidenceContract.DOCUMENTATION.value},
    )
