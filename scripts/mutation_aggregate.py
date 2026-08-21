#!/usr/bin/env python3
"""Aggregate per-source mutation checkpoints into one repository health report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_inventory(path: Path) -> list[str]:
    sources: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        source, _tests = raw.split("\t", 1)
        sources.append(source)
    return sources


def read_history(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"entries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"entries": {}}


def select_checkpoints(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    by_source: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(root.rglob("*.checkpoint.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("complete") is not True:
            continue
        source = payload.get("source")
        if not isinstance(source, str) or not source:
            continue
        current = by_source.get(source)
        if current is None or str(payload.get("verified_at", "")) >= str(
            current[1].get("verified_at", "")
        ):
            by_source[source] = (path, payload)
    return [by_source[source] for source in sorted(by_source)]


def read_checkpoints(root: Path) -> list[dict[str, Any]]:
    return [payload for _path, payload in select_checkpoints(root)]


def validate_tool_fingerprint(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    fingerprints = {row.get("tool_fingerprint") for row in rows}
    if None in fingerprints or "" in fingerprints:
        raise ValueError("complete mutation checkpoint is missing tool_fingerprint")
    if len(fingerprints) != 1:
        rendered = ", ".join(sorted(str(value) for value in fingerprints))
        raise ValueError(f"mixed mutation tool fingerprints in sweep: {rendered}")
    return str(next(iter(fingerprints)))


def read_selected_mutation_rows(selected: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    mutation_rows: list[str] = []
    for checkpoint_path, _payload in selected:
        stem = checkpoint_path.name.removesuffix(".checkpoint.json")
        rows_path = checkpoint_path.with_name(f"{stem}.rows.jsonl")
        if not rows_path.is_file():
            raise ValueError(f"complete checkpoint has no mutation rows: {checkpoint_path}")
        mutation_rows.extend(
            line for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    return mutation_rows


def classify(rows: list[dict[str, Any]], history: dict[str, Any]) -> tuple[list[str], list[str]]:
    previous = history.get("entries", {})
    improved: list[str] = []
    regressed: list[str] = []
    for row in rows:
        prior = previous.get(row["source"], {}) if isinstance(previous, dict) else {}
        prior_rate = prior.get("kill_rate") if isinstance(prior, dict) else None
        if not isinstance(prior_rate, (int, float)):
            continue
        delta = float(row["kill_rate"]) - float(prior_rate)
        if delta > 1e-9:
            improved.append(row["source"])
        elif delta < -1e-9:
            regressed.append(row["source"])
    return improved, regressed


def build_report(
    rows: list[dict[str, Any]], inventory: list[str], history: dict[str, Any]
) -> dict[str, Any]:
    measured = {row["source"] for row in rows}
    unmeasured = sorted(set(inventory) - measured)
    viable = sum(int(row["viable_mutants"]) for row in rows)
    killed = sum(int(row["killed_mutants"]) for row in rows)
    surviving = sum(int(row["surviving_mutants"]) for row in rows)
    improved, regressed = classify(rows, history)
    slowest = sorted(
        (
            {
                "source": row["source"],
                "mutation_seconds": float(row["mutation_seconds"]),
                "baseline_test_seconds": float(row["baseline_test_seconds"]),
            }
            for row in rows
        ),
        key=lambda item: (-item["mutation_seconds"], item["source"]),
    )[:10]
    return {
        "complete": len(unmeasured) == 0 and len(measured) == len(inventory),
        "inventory_sources": len(inventory),
        "measured_sources": len(measured),
        "unmeasured_sources": unmeasured,
        "viable_mutants": viable,
        "killed_mutants": killed,
        "surviving_mutants": surviving,
        "kill_rate": killed / viable if viable else 1.0,
        "improved_sources": improved,
        "regressed_sources": regressed,
        "slowest_sources": slowest,
        "aggregate_mutation_seconds": sum(float(row["mutation_seconds"]) for row in rows),
        "aggregate_baseline_test_seconds": sum(float(row["baseline_test_seconds"]) for row in rows),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Repository mutation health",
        "",
        f"- Complete sweep: **{'yes' if report['complete'] else 'no'}**",
        f"- Sources measured: **{report['measured_sources']} / {report['inventory_sources']}**",
        f"- Viable mutants: **{report['viable_mutants']}**",
        f"- Killed mutants: **{report['killed_mutants']}**",
        f"- Surviving mutants: **{report['surviving_mutants']}**",
        f"- Kill rate: **{report['kill_rate']:.1%}**",
        f"- Aggregate mutation CPU/job time: **{report['aggregate_mutation_seconds'] / 60:.1f} min**",
        "",
        "## Source movement",
        "",
        f"- Improved: {len(report['improved_sources'])}",
        f"- Regressed: {len(report['regressed_sources'])}",
        f"- Unmeasured: {len(report['unmeasured_sources'])}",
        "",
        "## Slowest mutation targets",
        "",
        "| Source | Mutation | Baseline tests |",
        "|---|---:|---:|",
    ]
    for item in report["slowest_sources"]:
        lines.append(
            f"| `{item['source']}` | {item['mutation_seconds'] / 60:.1f}m | "
            f"{item['baseline_test_seconds']:.1f}s |"
        )
    if report["regressed_sources"]:
        lines.extend(["", "## Regressed sources", ""])
        lines.extend(f"- `{source}`" for source in report["regressed_sources"])
    if report["unmeasured_sources"]:
        lines.extend(["", "## Unmeasured sources", ""])
        lines.extend(f"- `{source}`" for source in report["unmeasured_sources"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--telemetry-output", type=Path, required=True)
    parser.add_argument("--rows-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args(argv)

    selected = select_checkpoints(args.checkpoints)
    rows = [payload for _path, payload in selected]
    validate_tool_fingerprint(rows)
    inventory = read_inventory(args.inventory)
    history = read_history(args.history)
    report = build_report(rows, inventory, history)

    args.telemetry_output.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    mutation_rows = read_selected_mutation_rows(selected)
    args.rows_output.write_text("".join(line + "\n" for line in mutation_rows), encoding="utf-8")
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"mutation aggregate: measured={report['measured_sources']}/{report['inventory_sources']} "
        f"kill_rate={report['kill_rate']:.1%} complete={report['complete']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
