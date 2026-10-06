"""The `maistro-ext-harness` console entry point (#974).

The invocation shape a third-party CI uses:

    maistro-ext-harness run --path . --report conformance-report.json
    maistro-ext-harness run --path . --with-reference --report report.json

Exit codes, so CI can act on them:

- `0` — every case passed (skipped cases are named in the report);
- `1` — at least one case failed, including a required-backend case whose
  backend was unavailable (fail closed beats silently skipping);
- `2` — the harness could not run at all: bad arguments, no extension at
  the path, or a rejected manifest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from maistro_ext_harness import runner
from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.contract import FAMILIES, ContractError
from maistro_ext_harness.lifecycle import HostError
from maistro_ext_harness.manifest import ManifestRejected
from maistro_ext_harness.report import CaseStatus
from maistro_ext_harness.runner import RunRequest, run_conformance

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface. One command, explicit flags."""
    parser = argparse.ArgumentParser(
        prog="maistro-ext-harness",
        description=(
            "Local public-SDK host harness and extension-family conformance "
            "runner. A local result is not platform certification; the "
            "report states this."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"maistro-ext-harness {runner.HARNESS_VERSION}"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the conformance suite over one extension directory")
    run.add_argument(
        "--path",
        type=Path,
        required=True,
        help="the extension directory to run against (holds extension.json)",
    )
    run.add_argument(
        "--family",
        choices=list(FAMILIES),
        default=None,
        help="override the family suite (must match the manifest's family)",
    )
    run.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the machine-readable report JSON here",
    )
    run.add_argument(
        "--with-reference",
        action="store_true",
        help="also run the same cases against the built-in reference extension",
    )
    run.add_argument(
        "--allow-missing-backend",
        action="append",
        default=[],
        metavar="NAME",
        help="record a waiver for an unavailable registered backend NAME "
        "(the report lists every waiver; without it a required-backend case "
        "FAILS when the backend is absent)",
    )
    return parser


def _run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    backends = BackendRegistry(waivers=frozenset(args.allow_missing_backend))
    request = RunRequest(
        subject=args.path,
        family=args.family,
        with_reference=args.with_reference,
        backends=backends,
    )
    report = run_conformance(request)
    if args.report is not None:
        report.write_json(args.report)
        print(f"report: {args.report}")
    print(
        f"conformance: {report.passed_count} passed, {len(report.failed)} failed, "
        f"{len(report.skipped)} skipped "
        f"(contract {report.contract_version}, harness {report.harness_version})"
    )
    for case in report.failed:
        print(f"FAIL {case.subject}:{case.case_id} - {case.detail}", file=sys.stderr)
    for case in report.cases:
        if case.status is CaseStatus.SKIPPED:
            print(f"SKIP {case.subject}:{case.case_id} - {case.detail}")
    return 1 if report.failed else 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point; returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    # Usage/subject errors exit 2; case outcomes exit 0/1. A manifest that
    # cannot even be validated is "could not run", not "failed a case".
    try:
        return _run(argv)
    except (ManifestRejected, HostError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
