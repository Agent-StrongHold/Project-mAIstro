#!/usr/bin/env python3
"""Ratchet Cosmic Ray mutation quality per production source file.

PR-era callers can still score raw Cosmic Ray dump JSONL. Repository-health
candidate generation uses the complete viability-adjusted telemetry emitted by
the scheduler, enforcing both the global floor and any stricter reviewed
per-source baseline. Automated candidates may tighten but never weaken reviewed
baselines.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "quality" / "mutation-baseline.json"
FLOOR = 0.90


def scores(rows_path: Path) -> dict[str, tuple[int, int]]:
    """Return ``source -> (killed, total)`` from Cosmic Ray dump JSONL."""
    result: dict[str, list[int]] = {}
    for raw in rows_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        parsed = json.loads(raw)
        if not (isinstance(parsed, list) and len(parsed) == 2):
            continue
        work_item, outcome = parsed
        if not isinstance(work_item, dict) or not isinstance(outcome, dict):
            continue
        mutations = work_item.get("mutations") or []
        source = mutations[0].get("module_path") if mutations else None
        if not isinstance(source, str):
            continue
        killed, total = result.setdefault(source, [0, 0])
        result[source] = [killed + (outcome.get("test_outcome") == "killed"), total + 1]
    return {source: (values[0], values[1]) for source, values in result.items()}


def payload(
    current: dict[str, tuple[int, int]], baseline: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Legacy raw-row candidate builder retained for non-scheduler callers."""
    entries = dict((baseline or {}).get("entries", {}))
    entries.update(
        {
            source: {"killed": killed, "total": total, "kill_rate": round(killed / total, 4)}
            for source, (killed, total) in current.items()
            if total
        }
    )
    return {
        "version": 1,
        "owner": "@BlakeMatthews-dev",
        "policy": (
            "Legacy raw per-source mutation candidate. Repository-health sweeps use "
            "viability-adjusted version-2 candidates."
        ),
        "entries": dict(sorted(entries.items())),
    }


def enforce(current: dict[str, tuple[int, int]], baseline: dict[str, Any]) -> list[str]:
    """Enforce the global floor plus source-specific reviewed non-regression."""
    entries = baseline.get("entries", {})
    failures: list[str] = []
    for source, (killed, total) in sorted(current.items()):
        if total == 0:
            failures.append(f"{source}: no mutants produced")
            continue
        rate = killed / total
        entry = entries.get(source, {}) if isinstance(entries, dict) else {}
        prior = entry.get("kill_rate", FLOOR) if isinstance(entry, dict) else FLOOR
        required = max(FLOOR, float(prior))
        if rate < required:
            failures.append(f"{source}: {rate:.1%} below required {required:.1%}")
    return failures


def _scheduler_telemetry_for(rows_path: Path) -> Path | None:
    candidate = rows_path.with_name("mutation-telemetry-all.jsonl")
    return candidate if candidate.is_file() else None


def _publish_ratchet_into_health_report(rows_path: Path, report: dict[str, Any]) -> None:
    # Imported here, not at module scope: this file sits in scripts/ and imports
    # a sibling, which only resolves when Python puts scripts/ on sys.path — true
    # for `python scripts/check_mutation_baseline.py`, false for a test that
    # loads this file by path. A lazy import keeps both working.
    import mutation_ratchet

    json_path = rows_path.with_name("mutation-health-report.json")
    markdown_path = rows_path.with_name("mutation-health-report.md")
    if json_path.is_file():
        payload_json = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(payload_json, dict):
            payload_json["ratchet"] = report
            json_path.write_text(
                json.dumps(payload_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    if markdown_path.is_file():
        existing = markdown_path.read_text(encoding="utf-8")
        markdown_path.write_text(
            existing.rstrip() + "\n\n" + mutation_ratchet.render_markdown(report),
            encoding="utf-8",
        )


def _write_scheduler_candidate(rows_path: Path, baseline_path: Path) -> int:
    import mutation_ratchet

    telemetry_path = _scheduler_telemetry_for(rows_path)
    if telemetry_path is None:
        raise ValueError("scheduler telemetry not found beside aggregate mutation rows")
    telemetry = mutation_ratchet.read_telemetry(telemetry_path)
    baseline = mutation_ratchet.load_json(baseline_path)
    history_path = ROOT / "quality" / "mutation-history.json"
    history = mutation_ratchet.load_json(history_path)
    report = mutation_ratchet.evaluate(telemetry, baseline, history, floor=FLOOR)
    candidate = mutation_ratchet.baseline_candidate(telemetry, baseline, floor=FLOOR)
    baseline_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _publish_ratchet_into_health_report(rows_path, report)
    print(
        f"wrote viability-adjusted mutation baseline candidate for {len(telemetry)} source file(s): "
        f"{baseline_path}"
    )
    print(
        f"mutation ratchet: quality_failures={len(report['quality_failures'])} "
        f"runtime_regressions={len(report['runtime_regressions'])} "
        f"newly_surviving_sources={len(report['newly_surviving'])}"
    )
    for failure in report["quality_failures"]:
        print(f"::error::{failure}", file=sys.stderr)
    return 1 if report["quality_failures"] else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", type=Path, help="Cosmic Ray dump JSONL")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    if args.write_baseline and _scheduler_telemetry_for(args.rows) is not None:
        try:
            return _write_scheduler_candidate(args.rows, args.baseline)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

    current = scores(args.rows)
    if not current:
        print(
            "::error::No mutation outcomes found; this is a configuration failure.", file=sys.stderr
        )
        return 1
    if args.write_baseline:
        existing = (
            json.loads(args.baseline.read_text(encoding="utf-8"))
            if args.baseline.is_file()
            else None
        )
        args.baseline.write_text(
            json.dumps(payload(current, existing), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"wrote legacy candidate mutation baseline for {len(current)} source file(s): {args.baseline}"
        )
        return 0
    if not args.baseline.is_file():
        print(f"::error::Missing mutation baseline: {args.baseline}", file=sys.stderr)
        return 1
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    failures = enforce(current, baseline)
    print(
        f"mutation baseline summary: {len(current)} source file(s), {len(failures)} regression(s)"
    )
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
