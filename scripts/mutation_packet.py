#!/usr/bin/env python3
"""Execute one mutation packet and checkpoint each completed source immediately."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import mutation_resume


def run(command: list[str], *, env: dict[str, str] | None = None, stdout=None) -> None:
    subprocess.run(command, check=True, env=env, stdout=stdout)


@contextmanager
def _restored(source: Path) -> Iterator[None]:
    """Guarantee `source` is byte-identical after the run (#419).

    Cosmic-ray mutates the file in place and restores it between mutants. Kill
    the process mid-mutant -- a timeout, a cancelled job, Ctrl-C -- and the
    mutation stays on disk. On a CI runner that is harmless because the
    checkout is thrown away; locally it is not. Observed twice while measuring
    this: `(pkg // "__init__.py")` and `for alias in []` were left behind, and
    only a test run afterwards noticed.

    A leftover mutant is worse than an ordinary dirty file, because it reads as
    deliberate: a small, plausible, syntactically valid change that a reviewer
    would have to know the original to question.

    Restores from the bytes read before the run rather than from git, so it
    works on an already-dirty tree and cannot discard unrelated edits.
    """
    original = source.read_bytes()
    try:
        yield
    finally:
        if source.read_bytes() != original:
            source.write_bytes(original)
            print(
                f"restored {source}: a mutation was left on disk by an interrupted run",
                file=sys.stderr,
            )


def package_pythonpath() -> str:
    return ":".join(str(path) for path in sorted(Path("packages").glob("*/src")))


def safe_id(source: str) -> str:
    stem = Path(source).stem.replace("_", "-")[:32]
    digest = hashlib.sha256(source.encode()).hexdigest()[:12]
    return f"{stem}-{digest}"


def cosmic_config(source: str, tests: str, pythonpath: str) -> str:
    return f'''[cosmic-ray]\nmodule-path = "{source}"\ntimeout = 60.0\nexcluded-modules = []\ntest-command = "env PYTHONPATH={pythonpath} python -m pytest {tests} --timeout=20 -q -x"\n\n[cosmic-ray.distributor]\nname = "local"\n\n[cosmic-ray.distributor.local]\nworker-count = 4\n'''


def survivor_identity(item: dict[str, object]) -> str:
    """Return a stable-enough identity for a meaningful surviving mutant.

    Cosmic Ray job IDs are session-specific. Location, operator, and before/after
    source text are much more useful for detecting a previously killed behavior
    becoming surviving across otherwise equivalent sessions.
    """
    return (
        f"L{int(item['line'])}:{int(item['col'])} {item['operator']} | "
        f"{item.get('source', '')} => {item.get('mutated', '')}"
    )


def build_checkpoint(
    source: str,
    tests: str,
    report: dict[str, object],
    environment: dict[str, str],
    *,
    baseline_seconds: float,
    mutation_seconds: float,
    commit: str,
) -> dict[str, object]:
    adjusted = report["adjusted"]
    assert isinstance(adjusted, dict)
    raw = report["raw"]
    assert isinstance(raw, dict)
    viable = report["viable"]
    assert isinstance(viable, list)
    survivor_ids = sorted(survivor_identity(item) for item in viable if isinstance(item, dict))
    return {
        "source": source,
        "source_hash": mutation_resume.tree_hash(source),
        "test_scope_hash": mutation_resume.tree_hash(tests),
        "baseline_test_seconds": baseline_seconds,
        "mutation_seconds": mutation_seconds,
        "mutant_count": int(raw["total"]),
        "viable_mutants": int(adjusted["total"]),
        "killed_mutants": int(adjusted["killed"]),
        "surviving_mutants": len(viable),
        "survivor_ids": survivor_ids,
        "non_viable_mutants": len(report["non_viable"]),
        "invalid_mutants": len(report["invalid"]),
        "undetermined_mutants": len(report["undetermined"]),
        "kill_rate": float(adjusted["rate"]),
        "runner": environment["runner"],
        "python_version": environment["python_version"],
        "cosmic_ray_version": environment["cosmic_ray_version"],
        "pytest_version": environment["pytest_version"],
        "tool_fingerprint": environment["tool_fingerprint"],
        "verified_commit": commit,
        "verified_at": dt.datetime.now(dt.UTC).isoformat(),
        "complete": int(report["pending"]) == 0,
    }


def execute_source(
    source: str,
    tests: str,
    environment: dict[str, str],
    *,
    commit: str,
    run_id: str,
    run_attempt: str,
    uploader: Path,
) -> dict[str, object]:
    identifier = safe_id(source)
    session = Path(f"session-{identifier}.sqlite")
    report_path = Path(f"report-{identifier}.json")
    rows_path = Path(f"{identifier}.rows.jsonl")
    checkpoint_dir = Path("mutation-checkpoints-new") / identifier
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    session.unlink(missing_ok=True)

    pythonpath = package_pythonpath()
    test_env = dict(os.environ)
    test_env["PYTHONPATH"] = pythonpath
    baseline_start = time.monotonic()
    run([sys.executable, "-m", "pytest", tests, "--timeout=20", "-q", "-x"], env=test_env)
    baseline_seconds = time.monotonic() - baseline_start

    config = Path(f"cosmic-ray-{identifier}.toml")
    config.write_text(cosmic_config(source, tests, pythonpath), encoding="utf-8")
    mutation_start = time.monotonic()
    run(["cosmic-ray", "init", str(config), str(session)])
    # Between init and exec, drop the mutants no test could ever kill (#419).
    # Under `from __future__ import annotations` an annotation is a string, so
    # `-> Path | None` yields six unkillable mutants that each cost a full test
    # run and then need triaging as "equivalent". Measured repository-wide:
    # ~11,166 of them, ~18 hours of runner time, zero signal.
    run([sys.executable, "scripts/mutation_filter_annotations.py", str(session), "--report"])
    with _restored(Path(source)):
        run(["cosmic-ray", "exec", str(config), str(session)])
    mutation_seconds = time.monotonic() - mutation_start
    with rows_path.open("w", encoding="utf-8") as handle:
        run(["cosmic-ray", "dump", str(session)], stdout=handle)
    run(
        [
            sys.executable,
            "scripts/mutation_viability.py",
            str(session),
            source,
            "--json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checkpoint = build_checkpoint(
        source,
        tests,
        report,
        environment,
        baseline_seconds=baseline_seconds,
        mutation_seconds=mutation_seconds,
        commit=commit,
    )
    checkpoint_path = checkpoint_dir / f"{identifier}.checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(report_path, checkpoint_dir / f"{identifier}.report.json")
    shutil.copy2(rows_path, checkpoint_dir / rows_path.name)

    artifact_name = f"mutation-checkpoint-{run_id}-{identifier}-attempt-{run_attempt}"
    upload_env = dict(os.environ)
    run(["node", str(uploader), artifact_name, str(checkpoint_dir)], env=upload_env)
    return checkpoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--uploader", type=Path, required=True)
    args = parser.parse_args(argv)

    environment = json.loads(args.environment.read_text(encoding="utf-8"))
    targets = mutation_resume.read_targets(args.targets)
    pending, reused = mutation_resume.filter_targets(
        targets,
        mutation_resume.read_checkpoints(args.checkpoints),
        commit=args.commit,
        tool_fingerprint=environment["tool_fingerprint"],
    )
    Path("mutation-targets-pending.tsv").write_text(
        "".join(f"{source}\t{tests}\n" for source, tests in pending), encoding="utf-8"
    )
    Path("mutation-reused.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in reused), encoding="utf-8"
    )
    telemetry = Path("mutation-telemetry.jsonl")
    sessions = Path("mutation-sessions.tsv")
    rows = Path("mutation-rows.jsonl")
    telemetry.write_text("", encoding="utf-8")
    sessions.write_text("", encoding="utf-8")
    rows.write_text("", encoding="utf-8")

    print(f"packet continuation: reused={len(reused)} pending={len(pending)}")
    for source, tests in pending:
        print(f"::group::mutate {source} (tests: {tests})")
        checkpoint = execute_source(
            source,
            tests,
            environment,
            commit=args.commit,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            uploader=args.uploader,
        )
        identifier = safe_id(source)
        with telemetry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint, sort_keys=True) + "\n")
        with sessions.open("a", encoding="utf-8") as handle:
            handle.write(f"session-{identifier}.sqlite\t{source}\n")
        with rows.open("a", encoding="utf-8") as handle:
            handle.write(Path(f"{identifier}.rows.jsonl").read_text(encoding="utf-8"))
        print("::endgroup::")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
