"""Published evidence manifests for benchmark runs (#104 M4-G).

Epic #104's goal is to *publish the evidence* — trace, manifest, and
refused-diff artifacts — rather than quote scores. A score in a table is a
claim; a manifest is a falsifiable artifact: every row carries the numbers
that make it checkable (samples evaluated, fidelity, baseline version) and
every section is checksummed so post-hoc edits are detectable.

What a manifest contains
------------------------
``build_evidence_manifest`` turns the outputs of one evaluation run into a
deterministic dict:

* ``results`` — one row per benchmark result: benchmark, score,
  ``samples_evaluated`` (SPEC-202/SPEC-281: a percentage without its sample
  count is unquotable), fidelity, and the adapter's own provenance metadata
  (official-comparability, sampling, parse failures).
* ``lift`` — SPEC-281 matrix rows (lift/gap/gap_closure/transfer/inversion),
  each stamped with its ``baseline_version``. AC-10: a numeric ``gap_closure``
  without ``baseline_version`` is refused at build time, and a ``None``
  ``gap_closure`` (gap <= 0 — the benchmark cannot measure harness lift)
  must survive to publication instead of being quietly zeroed.
* ``metering`` — the run's metered cost / security tax / RHAE block
  (:mod:`maistro_evolve.eval_metering`), or the explicitly-reasoned
  explanation of its absence. Absence is not silence. The block is read back
  off the results the harness stamped, so the published number is the number
  the run measured rather than a number typed in at publish time.
* ``verdict_conformance`` — the adversarial/mutation evidence that the
  graders are host-owned (:mod:`maistro_evolve.verdict_probes`). **Required**:
  a manifest that cannot show that its pass/fail verdicts survive hostile
  input is not publishable, and a report without its mutant column is not
  evidence either. The epic's acceptance is that the verdict is host-owned
  and independently falsifiable *before* results are published or fed into
  fitness/promotion — so this is a build-time requirement, not a note.
* ``refused_diffs`` — patches the run produced that policy refused, with the
  refusal reason recorded verbatim. Publishing refusals is the point: a
  manifest of only the successes is curation, not evidence.
* ``trace`` — the ordered public record of what the run did: one event per
  evaluation, comparison, verdict check, and refusal, in that order.
* ``checksums`` — SHA-256 over the canonical JSON of each section, plus a
  top-level checksum over the checksummed manifest.

Refusal rules (``verify_evidence_manifest`` → list of errors; empty = valid)
---------------------------------------------------------------------------
* a section's bytes no longer hash to its recorded checksum (tampering or
  corruption — either way the manifest is not evidence anymore);
* the top-level checksum no longer matches (the run id or the section set was
  edited after the fact);
* a result row without ``samples_evaluated`` or with a score but zero samples
  (an unquotable percentage);
* a numeric ``gap_closure`` without ``baseline_version`` (AC-10);
* a ``gap_closure`` of ``0.0`` where the gap was positive but the lift was
  zero is fine — ``0.0`` where gap <= 0 is not, the honest value is ``None``;
* a metering block that is absent without ``metering_absent_reason``;
* a verdict-conformance section that is missing, that accepted a hostile
  response, or whose permissive mutant survived (the battery proved nothing);
* a refused diff without a non-empty reason;
* a trace that is empty or whose steps are not sequential.

``publish_evidence_manifest`` refuses to write anything unless verification
passes, and writes atomically (tmp file + rename) so a crash mid-write cannot
leave a half-manifest that verifies.

Scope boundary: patch-content *policy* (what a diff may contain) stays in
``maistro_rsi.export_policy``/``quarantine`` — the RSI side of the boundary.
This module records refusals as data and checks structural integrity; it does
not become a second authority on patch content.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .eval_metering import RunMetering
from .lift_matrix import LiftReport
from .types import EvalResult
from .verdict_probes import ConformanceReport, conformance_gate_failures

MANIFEST_VERSION = 1

#: The sections a manifest carries, in the order they appear.
SECTION_NAMES = (
    "results",
    "lift",
    "metering",
    "metering_absent_reason",
    "verdict_conformance",
    "refused_diffs",
    "trace",
)


class ManifestVerificationError(ValueError):
    """A manifest failed structural or checksum verification."""


class RefusedDiff(BaseModel):
    """A candidate diff the run produced and policy refused."""

    candidate_id: str
    diff: str
    reason: str


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _metering_from_results(results: list[EvalResult]) -> RunMetering | None:
    """Read the metered block back off the results the harness stamped.

    The harness stamps the *same* whole-run block on every result, so one
    stamped result is enough to recover the run's metering. Results that
    disagree are a contradiction, not a rounding difference: a run whose rows
    report different costs did not measure one run, and the manifest refuses
    to pick a winner.
    """
    blocks = [r.run_metering for r in results if r.run_metering is not None]
    if not blocks:
        return None
    first = blocks[0]
    for other in blocks[1:]:
        if other != first:
            raise ValueError(
                "results carry different metered blocks — a run's metering is "
                "one block stamped on every result; these rows disagree"
            )
    return RunMetering.model_validate(first)


def _build_trace(
    results_rows: list[dict[str, Any]],
    lift_rows: list[dict[str, Any]],
    conformance_rows: list[dict[str, Any]],
    refused_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The ordered public record of the run.

    Derived from the manifest's own sections rather than accepted as a
    separate input, so the trace cannot disagree with the numbers it
    describes — there is exactly one set of numbers and the trace narrates
    those.
    """
    events: list[dict[str, Any]] = []

    def emit(phase: str, detail: str) -> None:
        events.append({"step": len(events) + 1, "phase": phase, "detail": detail})

    for row in results_rows:
        emit(
            "evaluate",
            f"benchmark {row['benchmark']} scored {row['score']} over "
            f"{row['samples_evaluated']} sample(s)",
        )
    for row in lift_rows:
        emit(
            "compare",
            f"{row['benchmark']} lift {row['lift']} gap {row['gap']} "
            f"gap_closure {row['gap_closure']} transfer {row['transfer']} "
            f"inversion {row['inversion']}",
        )
    for row in conformance_rows:
        emit(
            "verify-verdict",
            f"{row['grader']} rejected {row['hostile_rejected']}/"
            f"{row['hostile_total']} hostile responses; mutant "
            f"{row['mutant']} killed={row['mutant_killed']}",
        )
    for row in refused_rows:
        emit("refuse", f"{row['candidate_id']}: {row['reason']}")
    return events


def _results_rows(results: list[EvalResult]) -> list[dict[str, Any]]:
    """One row per result, with the denominator and the adapter's provenance."""
    rows: list[dict[str, Any]] = []
    for r in results:
        if r.samples_evaluated == 0 and r.score > 0:
            raise ValueError(
                f"{r.benchmark}: score {r.score} with zero samples evaluated is "
                "unquotable — refusing to build a manifest row that quotes a "
                "percentage with no denominator (SPEC-281 §4)"
            )
        rows.append(
            {
                "benchmark": r.benchmark,
                "score": r.score,
                "samples_evaluated": r.samples_evaluated,
                "cost_usd": r.cost_usd,
                "duration_seconds": r.duration_seconds,
                "fidelity": r.metadata.get("fidelity"),
                "provenance": {
                    k: v
                    for k, v in r.metadata.items()
                    if k
                    in (
                        "official_comparable",
                        "official_comparable_reason",
                        "sampled",
                        "attempts_per_task",
                        "parse_failures",
                    )
                },
            }
        )
    return rows


def build_evidence_manifest(
    run_id: str,
    results: list[EvalResult],
    *,
    lift_reports: list[LiftReport] | None = None,
    metering: RunMetering | None = None,
    metering_absent_reason: str | None = None,
    refused_diffs: list[RefusedDiff] | None = None,
    verdict_conformance: ConformanceReport | None = None,
) -> dict[str, Any]:
    """Assemble the manifest dict. Raises on inputs it refuses to represent.

    Building is where the unquotable is stopped: a numeric ``gap_closure``
    without ``baseline_version`` raises here, and a verdict-conformance
    report that does not hold raises here too, so the error surfaces at the
    producer rather than at every consumer.
    """
    if verdict_conformance is None:
        raise ValueError(
            "an evidence manifest requires a verdict-conformance report: the "
            "pass/fail verdict must be shown to be host-owned (hostile "
            "responses rejected, permissive mutant killed) before results are "
            "published or fed into fitness/promotion (#104 M4-G)"
        )
    conformance_problems = conformance_gate_failures(verdict_conformance)
    if not verdict_conformance.passed or conformance_problems:
        raise ValueError(
            "refusing to build an evidence manifest whose verdict conformance "
            "does not hold: " + "; ".join(conformance_problems)
        )

    results_rows = _results_rows(results)

    lift_rows = []
    for report in lift_reports or []:
        if report.gap_closure is not None and not report.baseline_version:
            raise ValueError(
                f"{report.benchmark}: numeric gap_closure {report.gap_closure} "
                "without baseline_version — uninterpretable, refusing to build "
                "(SPEC-281 AC-10)"
            )
        lift_rows.append(
            {
                "benchmark": report.benchmark,
                "baseline_version": report.baseline_version,
                "w_base": report.w_base,
                "w_evo": report.w_evo,
                "f_base": report.f_base,
                "f_evo": report.f_evo,
                "lift": report.lift,
                "gap": report.gap,
                "gap_closure": report.gap_closure,
                "transfer": report.transfer,
                "inversion": report.inversion,
                "transfer_stale": report.transfer_stale,
            }
        )

    if metering is None:
        metering = _metering_from_results(results)
    if metering is not None:
        if metering_absent_reason:
            raise ValueError(
                "metering present alongside metering_absent_reason — a run "
                "either measured its cost/security tax/RHAE or did not; it "
                "cannot claim both"
            )
        metering_block: dict[str, Any] | None = metering.to_block()
        absent_reason = None
    else:
        metering_block = None
        absent_reason = (metering_absent_reason or "").strip()
        if not absent_reason:
            raise ValueError(
                "no metering block and no metering_absent_reason — a manifest "
                "must carry the run's metered cost / security tax / RHAE, or "
                "say why it could not be measured. Absence is not silence"
            )

    refused_rows = [
        {
            "candidate_id": d.candidate_id,
            "diff": d.diff,
            "reason": d.reason,
        }
        for d in (refused_diffs or [])
    ]
    conformance_rows = verdict_conformance.to_section()
    trace_rows = _build_trace(results_rows, lift_rows, conformance_rows, refused_rows)

    sections: dict[str, Any] = {
        "results": results_rows,
        "lift": lift_rows,
        "metering": metering_block,
        "metering_absent_reason": absent_reason,
        "verdict_conformance": conformance_rows,
        "refused_diffs": refused_rows,
        "trace": trace_rows,
    }

    checksums = {
        name: _sha256(payload) for name, payload in sections.items() if payload is not None
    }
    checksums["manifest"] = _sha256(
        {
            "run_id": run_id,
            **checksums,
        }
    )

    return {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        **sections,
        "checksums": checksums,
    }


def _verify_checksums(manifest: dict[str, Any], checksums: dict[str, Any]) -> list[str]:
    """Every section's bytes must still hash to what was recorded.

    A section with no payload (``None``) was not checksummed when the
    manifest was built, so there is nothing to compare it against — its
    absence is judged by the section rules instead (metering, for instance,
    must carry an explicit reason when it is absent).
    """
    errors: list[str] = []
    for section in SECTION_NAMES:
        if section not in manifest:
            continue
        payload = manifest[section]
        if payload is None:
            continue
        expected = checksums.get(section)
        actual = _sha256(payload)
        if expected != actual:
            errors.append(
                f"section {section!r} does not match its checksum "
                f"(recorded {expected}, content hashes {actual})"
            )
    recorded_manifest_checksum = checksums.get("manifest")
    section_checksums = {k: v for k, v in checksums.items() if k != "manifest"}
    actual_manifest_checksum = _sha256(
        {
            "run_id": manifest.get("run_id"),
            **section_checksums,
        }
    )
    if recorded_manifest_checksum != actual_manifest_checksum:
        errors.append(
            "manifest checksum does not match its run id and section checksums "
            "(the manifest was edited after it was built)"
        )
    return errors


def _verify_results(results: Any) -> list[str]:
    """A percentage without its sample count is unquotable (SPEC-281 §4)."""
    errors: list[str] = []
    if not isinstance(results, list) or not results:
        return [
            "results section missing or empty — an evidence manifest with no results is not evidence"
        ]
    for row in results:
        if not isinstance(row, dict):
            errors.append("results row is not an object")
            continue
        name = row.get("benchmark", "<unnamed>")
        if "samples_evaluated" not in row:
            errors.append(
                f"result {name!r}: no samples_evaluated — a percentage without "
                "its sample count is unquotable (SPEC-281 §4)"
            )
        elif not isinstance(row.get("samples_evaluated"), int) or row["samples_evaluated"] < 0:
            errors.append(f"result {name!r}: samples_evaluated must be a non-negative int")
        if "score" in row and row.get("samples_evaluated") == 0:
            score = row.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool) and score > 0:
                errors.append(
                    f"result {name!r}: score {score} with zero samples evaluated is unquotable"
                )
    return errors


def _verify_lift(lift: Any) -> list[str]:
    """AC-10: a numeric gap_closure is meaningless without its baseline."""
    errors: list[str] = []
    if not isinstance(lift, list):
        return ["lift section is not a list"]
    for row in lift:
        if not isinstance(row, dict):
            errors.append("lift row is not an object")
            continue
        name = row.get("benchmark", "<unnamed>")
        gap_closure = row.get("gap_closure")
        if gap_closure is not None:
            if not row.get("baseline_version"):
                errors.append(
                    f"lift {name!r}: numeric gap_closure without baseline_version (AC-10)"
                )
            if not isinstance(gap_closure, (int, float)) or isinstance(gap_closure, bool):
                errors.append(f"lift {name!r}: gap_closure must be a number or null")
        if "transfer" not in row:
            errors.append(f"lift {name!r}: no transfer — inversion is undetectable without it")
    return errors


def _verify_conformance(conformance: Any) -> list[str]:
    """The manifest must show its verdicts are host-owned, with the mutants."""
    errors: list[str] = []
    if not isinstance(conformance, list) or not conformance:
        return [
            "verdict_conformance section missing or empty — a manifest that "
            "cannot show its verdicts are host-owned is not publishable "
            "(#104 M4-G)"
        ]
    for row in conformance:
        if not isinstance(row, dict):
            errors.append("verdict_conformance row is not an object")
            continue
        grader = row.get("grader", "<unnamed>")
        total = row.get("hostile_total")
        rejected = row.get("hostile_rejected")
        if not isinstance(total, int) or total <= 0:
            errors.append(f"verdict_conformance {grader!r}: no hostile responses were probed")
        if rejected != total:
            errors.append(
                f"verdict_conformance {grader!r}: {rejected} of {total} hostile "
                "responses rejected — a hostile response was graded as a pass"
            )
        if not row.get("mutant_killed"):
            errors.append(
                f"verdict_conformance {grader!r}: the permissive mutant survived "
                "the probe corpus, so the corpus cannot certify this grader"
            )
        if not row.get("passed"):
            errors.append(f"verdict_conformance {grader!r}: reported as not passed")
    return errors


def _verify_refused(refused: Any) -> list[str]:
    """A refusal without a reason is not evidence."""
    errors: list[str] = []
    if not isinstance(refused, list):
        return ["refused_diffs section is not a list"]
    for row in refused:
        if isinstance(row, dict) and not str(row.get("reason") or "").strip():
            errors.append(
                f"refused diff for {row.get('candidate_id', '<unnamed>')!r}: "
                "refusal without a reason is not evidence"
            )
    return errors


def _verify_trace(trace: Any) -> list[str]:
    """The public record must be present and in order."""
    errors: list[str] = []
    if not isinstance(trace, list) or not trace:
        return ["trace section missing or empty — a published run has a public record"]
    for index, event in enumerate(trace, 1):
        if not isinstance(event, dict):
            errors.append("trace event is not an object")
            continue
        if event.get("step") != index:
            errors.append(f"trace event {index}: step {event.get('step')!r} is out of order")
        if not str(event.get("phase") or "").strip():
            errors.append(f"trace event {index}: no phase")
        if not str(event.get("detail") or "").strip():
            errors.append(f"trace event {index}: no detail")
    return errors


def verify_evidence_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return every reason this manifest is not publishable; [] means valid."""
    errors: list[str] = []

    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        return ["manifest has no checksums section — not a verifiable artifact"]

    errors.extend(_verify_checksums(manifest, checksums))

    # Metering is either present (and checksummed) or explicitly absent.
    # Absence is not silence: a run with no metering block must say why.
    if manifest.get("metering") is None:
        if not str(manifest.get("metering_absent_reason") or "").strip():
            errors.append(
                "metering absent without metering_absent_reason — absence must be explicit"
            )
    elif manifest.get("metering_absent_reason"):
        errors.append("metering present alongside metering_absent_reason")

    errors.extend(_verify_results(manifest.get("results")))
    errors.extend(_verify_lift(manifest.get("lift", [])))
    errors.extend(_verify_conformance(manifest.get("verdict_conformance")))
    errors.extend(_verify_refused(manifest.get("refused_diffs", [])))
    errors.extend(_verify_trace(manifest.get("trace")))
    return errors


def publish_evidence_manifest(manifest: dict[str, Any], dest: Path) -> Path:
    """Verify, then atomically write the manifest as ``manifest.json``.

    Refuses (raises :class:`ManifestVerificationError`) when verification
    fails — a manifest that does not verify must never reach a publish target,
    because downstream consumers treat its presence as the claim that it did.
    """
    errors = verify_evidence_manifest(manifest)
    if errors:
        raise ManifestVerificationError(
            "refusing to publish a manifest that does not verify: " + "; ".join(errors)
        )
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "manifest.json"
    tmp = dest / ".manifest.json.tmp"
    tmp.write_text(_canonical(manifest) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_evidence_manifest(path: Path) -> dict[str, Any]:
    """Load and verify a published manifest; raises when it does not verify."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ManifestVerificationError(f"{path}: manifest is not a JSON object")
    errors = verify_evidence_manifest(manifest)
    if errors:
        raise ManifestVerificationError(f"{path}: " + "; ".join(errors))
    return manifest


__all__ = [
    "MANIFEST_VERSION",
    "SECTION_NAMES",
    "ManifestVerificationError",
    "RefusedDiff",
    "build_evidence_manifest",
    "load_evidence_manifest",
    "publish_evidence_manifest",
    "verify_evidence_manifest",
]
