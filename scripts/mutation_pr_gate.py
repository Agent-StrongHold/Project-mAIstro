#!/usr/bin/env python3
"""Diff-scoped mutation PR gate runner (#330).

Executes one changed critical source through the #330 pipeline:

    selection groups -> per-group cosmic-ray session -> annotation filter ->
    diff scope -> exec -> viability report -> baseline decision

Properties this runner owns (each one explicit, none passable-by-accident):

  fail fast            the first survivor whose stable identity is not in the
                       trusted baseline stops the whole run and fails it.
                       Sources without a reviewed baseline entry are
                       report-only (the recorded policy of
                       quality/mutation-baseline.json): they can neither pass
                       nor fail a PR, but their survivors are published so the
                       measured baseline can grow monotonically.
  per-mutant timeout   each group's cosmic-ray timeout is derived from that
                       group's own selected-test baseline duration (measured
                       immediately before `init`), not a global constant.
  explicit failures    a red selected-test baseline, zero in-scope mutants,
                       an unfinished session, or a viability failure each
                       abort with a non-zero exit and a named reason.
  restore guarantee    the source is restored to its pre-run bytes even when
                       exec is interrupted (reuses mutation_packet's guard).

Outputs under --artifacts: per-source checkpoint + viability report + session
rows, and one telemetry JSONL row per source for history/aggregation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mutation_packet
import mutation_resume
from mutation_select_tests import Selection, select

DEFAULT_TIMEOUT_FACTOR = 4.0
MIN_TIMEOUT_SECONDS = 30.0
FLOOR = 0.90


def tool_fingerprint() -> str:
    """Hash the mutation toolchain so cached results cannot survive an upgrade."""
    import importlib.metadata as metadata

    parts = []
    for package in ("cosmic-ray", "pytest", "coverage", "pytest-timeout"):
        parts.append(f"{package}={metadata.version(package)}")
    digest = hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()
    return f"sha256:{digest}"


def environment() -> dict[str, str]:
    return {
        "runner": os.environ.get("RUNNER_NAME") or socket.gethostname(),
        "python_version": platform.python_version(),
        "cosmic_ray_version": _version("cosmic-ray"),
        "pytest_version": _version("pytest"),
        "tool_fingerprint": tool_fingerprint(),
    }


def _version(package: str) -> str:
    import importlib.metadata as metadata

    return metadata.version(package)


def cosmic_config(source: str, tests: str, pythonpath: str, timeout: float) -> str:
    """A cosmic-ray config whose per-mutant budget is the selected-test baseline."""
    rendered_timeout = f"{max(MIN_TIMEOUT_SECONDS, timeout):.1f}"
    return (
        f'[cosmic-ray]\nmodule-path = "{source}"\ntimeout = {rendered_timeout}\n'
        f"excluded-modules = []\n"
        f'test-command = "env PYTHONPATH={pythonpath} python -m pytest {tests} '
        f'--timeout={max(10.0, timeout / 4):.1f} -q -x"\n'
        '\n[cosmic-ray.distributor]\nname = "local"\n'
        "\n[cosmic-ray.distributor.local]\nworker-count = 4\n"
    )


def measure_baseline(tests, pythonpath: str, pytest_args: list[str]) -> float:
    """Wall seconds for one run of the selected tests. Red baseline = abort."""
    test_items = tests.split() if isinstance(tests, str) else [str(item) for item in tests]
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath
    start = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *test_items, *pytest_args, "-q"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed = time.monotonic() - start
    if completed.returncode != 0:
        print(completed.stdout[-3000:], file=sys.stderr)
        print(
            f"::error::selected-test baseline is red for {tests}; a mutant run on a "
            "red baseline proves nothing.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return elapsed


def read_baseline(path: Path) -> dict:
    if not path.is_file():
        print(
            f"::error::mutation baseline is unreadable/missing: {path}. "
            "The gate refuses to run without its trusted base.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::mutation baseline is unreadable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("entries", {}), dict):
        print(
            "::error::mutation baseline must be an object with an 'entries' object", file=sys.stderr
        )
        raise SystemExit(1)
    return payload


def survivor_identities(report: dict) -> list[str]:
    viable = report.get("viable", [])
    return sorted(
        {mutation_packet.survivor_identity(item) for item in viable if isinstance(item, dict)}
    )


def combine_reports(reports: list[dict]) -> dict:
    """Merge per-group viability reports into one per-source report."""
    combined: dict = {
        "module": reports[0]["module"] if reports else "",
        "future_annotations": all(r.get("future_annotations") for r in reports),
        "pending": sum(int(r.get("pending", 0)) for r in reports),
        "raw": {
            "killed": sum(int(r["raw"]["killed"]) for r in reports),
            "total": sum(int(r["raw"]["total"]) for r in reports),
        },
        "adjusted": {
            "killed": sum(int(r["adjusted"]["killed"]) for r in reports),
            "total": sum(int(r["adjusted"]["total"]) for r in reports),
        },
        "viable": [item for r in reports for item in r.get("viable", [])],
        "baseline_test_seconds": sum(float(r.get("_baseline_seconds", 0.0)) for r in reports),
        "non_viable": [item for r in reports for item in r.get("non_viable", [])],
        "invalid": [item for r in reports for item in r.get("invalid", [])],
        "undetermined": [item for r in reports for item in r.get("undetermined", [])],
    }
    adjusted = combined["adjusted"]
    combined["adjusted"]["rate"] = (
        adjusted["killed"] / adjusted["total"] if adjusted["total"] else 0.0
    )
    return combined


def run_group(
    source: str,
    group: dict,
    group_index: int,
    *,
    artifacts: Path,
    diff_path: Path | None,
    pythonpath: str,
    timeout_factor: float,
) -> tuple[dict, float]:
    """One cosmic-ray session for one selection group. Returns (report, seconds)."""
    tests = " ".join(group["tests"])
    identifier = f"{mutation_packet.safe_id(source)}-g{group_index}"
    session = artifacts / f"session-{identifier}.sqlite"
    config_path = artifacts / f"cosmic-ray-{identifier}.toml"
    session.unlink(missing_ok=True)

    baseline_seconds = measure_baseline(tests, pythonpath, ["--timeout=120"])
    timeout = max(MIN_TIMEOUT_SECONDS, baseline_seconds * timeout_factor)
    config_path.write_text(cosmic_config(source, tests, pythonpath, timeout), encoding="utf-8")

    mutation_start = time.monotonic()
    subprocess.run(["cosmic-ray", "init", str(config_path), str(session)], check=True)
    subprocess.run(
        [sys.executable, "scripts/mutation_filter_annotations.py", str(session)],
        check=True,
        capture_output=True,
    )
    if diff_path is not None:
        subprocess.run(
            [
                sys.executable,
                "scripts/mutation_diff_scope.py",
                str(session),
                "--source",
                source,
                "--diff",
                str(diff_path),
                "--require-intersection",
            ],
            check=True,
        )
    with mutation_packet._restored(Path(source)):
        subprocess.run(["cosmic-ray", "exec", str(config_path), str(session)], check=True)
    seconds = time.monotonic() - mutation_start

    rows_path = artifacts / f"{identifier}.rows.jsonl"
    with rows_path.open("w", encoding="utf-8") as handle:
        subprocess.run(["cosmic-ray", "dump", str(session)], stdout=handle, check=True)

    report_path = artifacts / f"{identifier}.report.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/mutation_viability.py",
            str(session),
            source,
            "--json",
            str(report_path),
        ],
        check=True,
    )
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["_baseline_seconds"] = baseline_seconds
    return report_payload, seconds


def gate_source(
    source: str,
    tests_path: str,
    *,
    artifacts: Path,
    baseline: dict,
    diff_path: Path | None,
    changed_lines: list[int] | None,
    timeout_factor: float,
    commit: str,
    env: dict[str, str],
) -> tuple[dict, str]:
    """Mutate one source and decide pass / report-only / fail.

    Returns (checkpoint, decision) where decision is "pass", "report-only",
    or "fail" (fail raises SystemExit instead).
    """
    selection: Selection
    if changed_lines is None:
        # Measurement mode: the whole file is in scope, one group, all tests
        # the mirror scope provides.
        selection = Selection(groups=[{"lines": [], "tests": [tests_path]}])
    else:
        selection = select(source, tests_path, changed_lines)
        if selection.no_coverage and changed_lines is not None:
            print(
                f"::error::{source}: changed line(s) {selection.no_coverage} have no "
                "selected test; zero selected tests cannot pass.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if not selection.groups:
            print(
                f"::error::{source}: zero selected tests; refusing to run an empty gate.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    reports: list[dict] = []
    mutation_seconds = 0.0
    for index, group in enumerate(selection.groups):
        report, seconds = run_group(
            source,
            group,
            index,
            artifacts=artifacts,
            diff_path=diff_path if changed_lines is not None else None,
            pythonpath=mutation_packet.package_pythonpath(),
            timeout_factor=timeout_factor,
        )
        reports.append(report)
        mutation_seconds += seconds

    combined = combine_reports(reports)
    identities = survivor_identities(combined)

    entry = baseline.get("entries", {}).get(source)
    entry = entry if isinstance(entry, dict) else None
    adjusted = combined["adjusted"]
    viable, killed = int(adjusted["total"]), int(adjusted["killed"])
    if viable <= 0:
        print(
            f"::error::{source}: no mutants produced in scope — a configuration "
            "error, never a pass.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if entry is None:
        # Report-only until a reviewed candidate entry exists (recorded policy).
        print(
            f"::warning::{source}: no reviewed baseline entry; run is report-only. "
            f"killed {killed}/{viable} viable mutants; survivors:",
            file=sys.stderr,
        )
        for identity in identities:
            print(f"  survivor: {identity}", file=sys.stderr)
        decision = "report-only"
    else:
        prior_ids = {str(v) for v in entry.get("survivor_ids", []) if isinstance(v, str)}
        un_baselined = [identity for identity in identities if identity not in prior_ids]
        if un_baselined:
            print(
                f"::error::{source}: {len(un_baselined)} survivor(s) not in the trusted "
                "baseline — failing fast on the first:",
                file=sys.stderr,
            )
            print(f"  {un_baselined[0]}", file=sys.stderr)
            raise SystemExit(1)
        required = max(FLOOR, float(entry.get("kill_rate", FLOOR)))
        rate = killed / viable
        if rate + 1e-12 < required:
            print(
                f"::error::{source}: kill rate {rate:.1%} below required {required:.1%}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        decision = "pass"

    checkpoint = mutation_packet.build_checkpoint(
        source,
        tests_path,
        combined,
        env,
        baseline_seconds=float(combined.get("baseline_test_seconds", 0.0)),
        mutation_seconds=mutation_seconds,
        commit=commit,
    )
    return checkpoint, decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path, help="TSV source<TAB>test-scope")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--diff-dir", type=Path, default=None)
    parser.add_argument("--selection-dir", type=Path, default=None)
    parser.add_argument(
        "--scope",
        choices=("changed", "all"),
        default="changed",
        help="changed: mutate changed lines only (PR gate); all: whole files (measurement)",
    )
    parser.add_argument("--timeout-factor", type=float, default=DEFAULT_TIMEOUT_FACTOR)
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "local"))
    parser.add_argument(
        "--uploader",
        type=Path,
        default=None,
        help="optional node artifact uploader (CI); absent = local run, no upload",
    )
    args = parser.parse_args(argv)

    artifacts = args.artifacts
    artifacts.mkdir(parents=True, exist_ok=True)
    baseline = read_baseline(args.baseline)
    env = environment()
    targets = mutation_resume.read_targets(args.targets)
    if not targets:
        print("::error::no mutation targets; a run against nothing is not a pass.", file=sys.stderr)
        return 1

    telemetry_path = artifacts / "mutation-telemetry.jsonl"
    decisions: dict[str, str] = {}
    for source, tests_path in targets:
        identifier = mutation_packet.safe_id(source)
        print(f"::group::mutate {source} (scope: {args.scope})")
        diff_path = None
        changed_lines = None
        if args.scope == "changed":
            diff_path = (args.diff_dir / f"{identifier}.diff") if args.diff_dir else None
            selection_path = (
                (args.selection_dir / f"{identifier}.selection.json")
                if args.selection_dir
                else None
            )
            if selection_path is not None and selection_path.is_file():
                payload = json.loads(selection_path.read_text(encoding="utf-8"))
                changed_lines = [int(line) for line in payload.get("changed_lines", [])]
            elif diff_path is not None and diff_path.is_file():
                from mutation_diff_scope import DiffScope

                changed_lines = sorted(DiffScope.from_unified_diff(diff_path.read_text()).lines)
            else:
                print(
                    f"::error::{source}: neither a selection nor a diff was provided for "
                    "changed-line scope.",
                    file=sys.stderr,
                )
                return 1
        try:
            checkpoint, decision = gate_source(
                source,
                tests_path,
                artifacts=artifacts,
                baseline=baseline,
                diff_path=diff_path,
                changed_lines=changed_lines,
                timeout_factor=args.timeout_factor,
                commit=args.commit,
                env=env,
            )
        finally:
            print("::endgroup::")
        decisions[source] = decision
        checkpoint["decision"] = decision
        with telemetry_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint, sort_keys=True) + "\n")
        checkpoint_path = artifacts / f"{identifier}.checkpoint.json"
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    print(
        f"mutation gate: {len(decisions)} source(s); "
        + " ".join(f"{src}={decision}" for src, decision in sorted(decisions.items()))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
