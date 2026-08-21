#!/usr/bin/env python3
"""Enforce per-source mutation quality and performance ratchets from telemetry.

The ratchet consumes only complete, viability-adjusted source telemetry. Every
measured source must clear the global floor; reviewed sources must also clear
their recorded source-specific rate. Runtime regressions and newly surviving
meaningful mutants are reported independently from the quality decision.

Baseline candidates are monotonic: a complete result may add a new source or
raise an existing reviewed rate, but automation never writes a worse reviewed
baseline into the candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BASELINE_VERSION = 2
DEFAULT_FLOOR = 0.90
DEFAULT_RUNTIME_FACTOR = 2.0
DEFAULT_RUNTIME_MIN_SAMPLES = 3


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"entries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    payload.setdefault("entries", {})
    return payload


def read_telemetry(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError("telemetry JSONL rows must be objects")
        if row.get("complete") is not True:
            raise ValueError(f"refusing incomplete mutation telemetry for {row.get('source')!r}")
        rows.append(row)
    return rows


def _survivor_ids(row: dict[str, Any]) -> list[str]:
    values = row.get("survivor_ids", [])
    if not isinstance(values, list):
        return []
    return sorted({value for value in values if isinstance(value, str) and value})


def evaluate(
    rows: list[dict[str, Any]],
    baseline: dict[str, Any],
    history: dict[str, Any],
    *,
    floor: float = DEFAULT_FLOOR,
    runtime_factor: float = DEFAULT_RUNTIME_FACTOR,
    runtime_min_samples: int = DEFAULT_RUNTIME_MIN_SAMPLES,
) -> dict[str, Any]:
    baseline_entries = baseline.get("entries", {})
    history_entries = history.get("entries", {})
    if not isinstance(baseline_entries, dict) or not isinstance(history_entries, dict):
        raise ValueError("baseline/history entries must be objects")

    sources: list[dict[str, Any]] = []
    quality_failures: list[str] = []
    runtime_regressions: list[str] = []
    newly_surviving: dict[str, list[str]] = {}

    for row in sorted(rows, key=lambda item: str(item.get("source", ""))):
        source = row.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("telemetry row has no source")
        viable = int(row["viable_mutants"])
        killed = int(row["killed_mutants"])
        if viable <= 0:
            quality_failures.append(f"{source}: no viable mutants produced")
            rate = 0.0
        else:
            rate = killed / viable

        prior = baseline_entries.get(source, {})
        prior = prior if isinstance(prior, dict) else {}
        prior_rate_value = prior.get("kill_rate")
        prior_rate = float(prior_rate_value) if isinstance(prior_rate_value, (int, float)) else None
        required = max(floor, prior_rate if prior_rate is not None else floor)
        regression = rate + 1e-12 < required
        if regression and viable > 0:
            quality_failures.append(
                f"{source}: {killed}/{viable} = {rate:.1%} below required {required:.1%}"
            )

        current_survivors = _survivor_ids(row)
        prior_survivors = prior.get("survivor_ids", [])
        prior_survivor_set = (
            {value for value in prior_survivors if isinstance(value, str)}
            if isinstance(prior_survivors, list)
            else set()
        )
        new_survivors = (
            sorted(set(current_survivors) - prior_survivor_set) if prior_rate is not None else []
        )
        if new_survivors:
            newly_surviving[source] = new_survivors

        historic = history_entries.get(source, {})
        historic = historic if isinstance(historic, dict) else {}
        samples = int(historic.get("sample_count", 0) or 0)
        expected_value = historic.get("ewma_mutation_seconds")
        expected = float(expected_value) if isinstance(expected_value, (int, float)) else None
        actual = float(row["mutation_seconds"])
        runtime_ratio = actual / expected if expected and expected > 0 else None
        runtime_regression = (
            samples >= runtime_min_samples
            and runtime_ratio is not None
            and runtime_ratio >= runtime_factor
        )
        if runtime_regression:
            runtime_regressions.append(source)

        sources.append(
            {
                "source": source,
                "viable_mutants": viable,
                "killed_mutants": killed,
                "surviving_mutants": int(row["surviving_mutants"]),
                "kill_rate": rate,
                "baseline_kill_rate": prior_rate,
                "required_kill_rate": required,
                "quality_regression": regression,
                "new_survivor_ids": new_survivors,
                "expected_mutation_seconds": expected,
                "actual_mutation_seconds": actual,
                "runtime_ratio": runtime_ratio,
                "runtime_regression": runtime_regression,
                "history_sample_count": samples,
            }
        )

    return {
        "floor": floor,
        "runtime_factor": runtime_factor,
        "runtime_min_samples": runtime_min_samples,
        "quality_passed": not quality_failures,
        "quality_failures": quality_failures,
        "runtime_regressions": runtime_regressions,
        "newly_surviving": newly_surviving,
        "sources": sources,
    }


def baseline_candidate(
    rows: list[dict[str, Any]], baseline: dict[str, Any], *, floor: float = DEFAULT_FLOOR
) -> dict[str, Any]:
    entries_raw = baseline.get("entries", {})
    entries: dict[str, Any] = dict(entries_raw) if isinstance(entries_raw, dict) else {}
    for row in rows:
        source = str(row["source"])
        viable = int(row["viable_mutants"])
        killed = int(row["killed_mutants"])
        if viable <= 0:
            continue
        rate = killed / viable
        previous = entries.get(source, {})
        previous = previous if isinstance(previous, dict) else {}
        previous_rate_value = previous.get("kill_rate")
        previous_rate = (
            float(previous_rate_value) if isinstance(previous_rate_value, (int, float)) else None
        )
        if rate < floor:
            continue
        if previous_rate is not None and rate <= previous_rate + 1e-12:
            continue
        entries[source] = {
            "killed": killed,
            "viable": viable,
            "kill_rate": round(rate, 6),
            "survivor_ids": _survivor_ids(row),
            "reviewed_commit": row.get("verified_commit"),
            "reviewed_at": row.get("verified_at"),
        }
    return {
        "version": BASELINE_VERSION,
        "owner": baseline.get("owner", "@BlakeMatthews-dev"),
        "policy": (
            "Viability-adjusted per-source mutation ratchet. Every measured source must meet "
            f"the {floor:.0%} global floor; reviewed sources must also not regress below their "
            "recorded kill rate. Automated candidates may tighten but never weaken a reviewed baseline."
        ),
        "entries": dict(sorted(entries.items())),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Mutation ratchet",
        "",
        f"- Quality gate: **{'PASS' if report['quality_passed'] else 'FAIL'}**",
        f"- Global floor: **{report['floor']:.0%}**",
        f"- Runtime regressions: **{len(report['runtime_regressions'])}**",
        f"- Sources with newly surviving reviewed mutant identities: **{len(report['newly_surviving'])}**",
        "",
        "| Source | Viable | Killed | Rate | Reviewed | Required | Runtime |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["sources"]:
        reviewed = row["baseline_kill_rate"]
        reviewed_text = f"{reviewed:.1%}" if reviewed is not None else "new"
        runtime_ratio = row["runtime_ratio"]
        runtime_text = f"{runtime_ratio:.2f}x" if runtime_ratio is not None else "n/a"
        lines.append(
            f"| `{row['source']}` | {row['viable_mutants']} | {row['killed_mutants']} | "
            f"{row['kill_rate']:.1%} | {reviewed_text} | {row['required_kill_rate']:.1%} | "
            f"{runtime_text} |"
        )
    if report["quality_failures"]:
        lines.extend(["", "## Quality regressions", ""])
        lines.extend(f"- {item}" for item in report["quality_failures"])
    if report["runtime_regressions"]:
        lines.extend(["", "## Runtime regressions", ""])
        for source in report["runtime_regressions"]:
            row = next(item for item in report["sources"] if item["source"] == source)
            lines.append(
                f"- `{source}`: expected {row['expected_mutation_seconds'] / 60:.1f}m, "
                f"actual {row['actual_mutation_seconds'] / 60:.1f}m "
                f"({row['runtime_ratio']:.2f}x slower; {row['history_sample_count']} historical samples)"
            )
    if report["newly_surviving"]:
        lines.extend(["", "## Newly surviving reviewed mutant identities", ""])
        for source, identities in sorted(report["newly_surviving"].items()):
            lines.append(f"- `{source}`")
            lines.extend(f"  - `{identity}`" for identity in identities)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--runtime-factor", type=float, default=DEFAULT_RUNTIME_FACTOR)
    parser.add_argument("--runtime-min-samples", type=int, default=DEFAULT_RUNTIME_MIN_SAMPLES)
    args = parser.parse_args(argv)

    try:
        rows = read_telemetry(args.telemetry)
        baseline = load_json(args.baseline)
        history = load_json(args.history)
        report = evaluate(
            rows,
            baseline,
            history,
            floor=args.floor,
            runtime_factor=args.runtime_factor,
            runtime_min_samples=args.runtime_min_samples,
        )
        candidate = baseline_candidate(rows, baseline, floor=args.floor)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    args.candidate_output.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"mutation ratchet: sources={len(report['sources'])} "
        f"quality_failures={len(report['quality_failures'])} "
        f"runtime_regressions={len(report['runtime_regressions'])}"
    )
    for failure in report["quality_failures"]:
        print(f"::error::{failure}", file=sys.stderr)
    return 1 if report["quality_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
