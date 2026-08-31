#!/usr/bin/env python3
"""Ratchet mutation quality against trusted baseline/history provenance (#542, #319).

The comparison baseline and mutation-history evidence are read from the merge
base through ``ratchet_provenance``. A candidate may generate a tighter baseline
candidate, but it cannot weaken the quality floor or rewrite runtime history in
the same change that is being judged.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "quality" / "mutation-baseline.json"
DEFAULT_HISTORY = ROOT / "quality" / "mutation-history.json"
_PROVENANCE_SOURCE = ROOT / "scripts" / "ratchet_provenance.py"
FLOOR = 0.90
RATCHET = "mutation"
METRIC_DEFINITION_VERSION = "2"


def _provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_ratchet_provenance", _PROVENANCE_SOURCE)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {_PROVENANCE_SOURCE}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def scores(rows_path: Path) -> dict[str, tuple[int, int]]:
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


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def _local_baseline(path: Path, *, prov: ModuleType) -> object:
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    return prov.Baseline(text=text, origin="worktree", base_sha=None, path=path)


def _trusted_json(path: Path, *, prov: ModuleType) -> tuple[dict[str, Any], object]:
    # --baseline has long supported temp/external files for local experimentation
    # and tests. Such a file has no meaningful path in repository history, so it
    # is explicitly local rather than being forced through a git resolver that
    # can only address files beneath ROOT.
    baseline = (
        prov.resolve_baseline(path, root=ROOT)
        if _inside_repository(path)
        else _local_baseline(path, prov=prov)
    )
    loaded = baseline.loads(default={"entries": {}})
    if not isinstance(loaded, dict):
        raise prov.RatchetProvenanceError(f"{path.name}: trusted content is not a JSON object")
    return loaded, baseline


def _entries(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries", {})
    return dict(entries) if isinstance(entries, dict) else {}


def _entry_rate(entry: object) -> float | None:
    if not isinstance(entry, dict) or "kill_rate" not in entry:
        return None
    try:
        return float(entry["kill_rate"])
    except (TypeError, ValueError):
        return None


def _measured_rate(current: dict[str, tuple[int, int]], source: str) -> float | None:
    measured = current.get(source)
    if not measured or not measured[1]:
        return None
    return round(measured[0] / measured[1], 4)


def _trusted_entry_failures(
    source: str,
    trusted_entry: object,
    candidate_entry: object,
    measured_rate: float | None,
) -> list[str]:
    trusted_rate = _entry_rate(trusted_entry)
    candidate_rate = _entry_rate(candidate_entry)
    if trusted_rate is None or candidate_rate is None:
        return [f"{source}: mutation baseline entry has no numeric kill_rate"]

    failures: list[str] = []
    if candidate_rate < trusted_rate:
        failures.append(
            f"{source}: candidate kill_rate {candidate_rate:.1%} weakens trusted "
            f"{trusted_rate:.1%}"
        )
    if measured_rate is not None and candidate_rate > measured_rate:
        failures.append(
            f"{source}: candidate kill_rate {candidate_rate:.1%} exceeds measured "
            f"{measured_rate:.1%}"
        )
    return failures


def _new_candidate_entry_failures(
    source: str, candidate_entry: object, measured_rate: float | None
) -> list[str]:
    if measured_rate is None:
        return [f"{source}: unreviewed candidate baseline entry has no measurement"]
    candidate_rate = _entry_rate(candidate_entry)
    if candidate_rate is None:
        return [f"{source}: mutation baseline entry has no numeric kill_rate"]
    if candidate_rate != measured_rate:
        return [
            f"{source}: new candidate kill_rate {candidate_rate:.1%} must equal measured "
            f"{measured_rate:.1%}"
        ]
    return []


def candidate_baseline_failures(
    current: dict[str, tuple[int, int]],
    trusted: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    """Reject candidate bookkeeping that weakens or invents reviewed floors."""
    trusted_entries = _entries(trusted)
    candidate_entries = _entries(candidate)
    failures: list[str] = []

    for source, trusted_entry in sorted(trusted_entries.items()):
        if source not in candidate_entries:
            failures.append(f"{source}: candidate baseline removed a trusted source floor")
            continue
        failures.extend(
            _trusted_entry_failures(
                source,
                trusted_entry,
                candidate_entries[source],
                _measured_rate(current, source),
            )
        )

    for source, candidate_entry in sorted(candidate_entries.items()):
        if source not in trusted_entries:
            failures.extend(
                _new_candidate_entry_failures(
                    source, candidate_entry, _measured_rate(current, source)
                )
            )
    return failures


def _candidate_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"entries": {}}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name}: candidate content is not a JSON object")
    return loaded


def _write_scheduler_candidate(
    rows_path: Path,
    baseline_path: Path,
    *,
    trusted_baseline: dict[str, Any],
    trusted_history: dict[str, Any],
    provenance: object,
    prov: ModuleType,
) -> int:
    import mutation_ratchet

    telemetry_path = _scheduler_telemetry_for(rows_path)
    if telemetry_path is None:
        raise ValueError("scheduler telemetry not found beside aggregate mutation rows")
    telemetry = mutation_ratchet.read_telemetry(telemetry_path)
    prov.require_measurement(telemetry, ratchet=RATCHET, what="mutation telemetry rows")
    report = mutation_ratchet.evaluate(telemetry, trusted_baseline, trusted_history, floor=FLOOR)
    candidate = mutation_ratchet.baseline_candidate(telemetry, trusted_baseline, floor=FLOOR)
    baseline_path.write_text(
        json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _publish_ratchet_into_health_report(rows_path, report)
    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=provenance,
            tool="cosmic-ray scheduler telemetry",
            metric_definition_version=METRIC_DEFINITION_VERSION,
            old_value=f"{len(trusted_baseline.get('entries', {}))} reviewed source floor(s)",
            new_value=f"{len(telemetry)} measured source(s)",
            candidate_sha=prov.head_sha(ROOT),
        ).render()
    )
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

    prov = _provenance()
    try:
        trusted_baseline, baseline_ref = _trusted_json(args.baseline, prov=prov)
        trusted_history, _history_ref = _trusted_json(DEFAULT_HISTORY, prov=prov)
    except prov.RatchetProvenanceError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    if args.write_baseline and _scheduler_telemetry_for(args.rows) is not None:
        try:
            return _write_scheduler_candidate(
                args.rows,
                args.baseline,
                trusted_baseline=trusted_baseline,
                trusted_history=trusted_history,
                provenance=baseline_ref,
                prov=prov,
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

    current = scores(args.rows)
    if not current:
        print(
            "::error::No mutation outcomes found; this is a configuration failure.", file=sys.stderr
        )
        return 1
    try:
        prov.require_measurement(current, ratchet=RATCHET, what="mutation source outcomes")
    except prov.RatchetProvenanceError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    if args.write_baseline:
        # Candidate construction starts from the trusted baseline, not the
        # candidate's possibly weakened copy. A generated file can therefore
        # tighten or extend the reviewed state but cannot erase its floor.
        args.baseline.write_text(
            json.dumps(payload(current, trusted_baseline), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            prov.Provenance(
                ratchet=RATCHET,
                baseline=baseline_ref,
                tool="cosmic-ray raw outcomes",
                metric_definition_version="1",
                old_value=f"{len(trusted_baseline.get('entries', {}))} reviewed source floor(s)",
                new_value=f"{len(current)} measured source(s)",
                candidate_sha=prov.head_sha(ROOT),
            ).render()
        )
        print(
            f"wrote legacy candidate mutation baseline for {len(current)} source file(s): {args.baseline}"
        )
        return 0

    failures = enforce(current, trusted_baseline)
    if _inside_repository(args.baseline):
        try:
            failures.extend(
                candidate_baseline_failures(current, trusted_baseline, _candidate_json(args.baseline))
            )
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2

    print(
        prov.Provenance(
            ratchet=RATCHET,
            baseline=baseline_ref,
            tool="cosmic-ray raw outcomes",
            metric_definition_version="1",
            old_value=f"{len(trusted_baseline.get('entries', {}))} reviewed source floor(s)",
            new_value=f"{len(current)} measured source(s)",
            candidate_sha=prov.head_sha(ROOT),
        ).render()
    )
    print(
        f"mutation baseline summary: {len(current)} source file(s), {len(failures)} regression(s)"
    )
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
