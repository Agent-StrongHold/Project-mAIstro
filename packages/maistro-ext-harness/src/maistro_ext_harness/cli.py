"""The `maistro-ext-harness` console entry point (#974, #975).

The invocation shapes a third-party CI uses:

    maistro-ext-harness run --path . --report conformance-report.json
    maistro-ext-harness run --path . --with-reference --report report.json
    maistro-ext-harness certify --path . --artifact dist/*.whl \
        --report certification.json [--signing-key-file key.hex]
    maistro-ext-harness verify-certification --report certification.json \
        --artifact dist/*.whl [--publisher-key <hex>]

Exit codes, so CI can act on them (`run`):

- `0` — every case passed (skipped cases are named in the report);
- `1` — at least one case failed, including a required-backend case whose
  backend was unavailable (fail closed beats silently skipping);
- `2` — the harness could not run at all: bad arguments, no extension at
  the path, or a rejected manifest.

For `certify`: `0` certified, `1` declined (the report says exactly why),
`2` bad arguments. For `verify-certification`: `0` verified, `1` invalid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from maistro_ext_harness import runner
from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.certification import (
    CertificationProfile,
    CertificationRequest,
    certify,
    verify_certification,
)
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

    certify_cmd = sub.add_parser(
        "certify",
        help="certify one extension: structure, security, conformance, digest, "
        "signature, report (M9-H3)",
    )
    certify_cmd.add_argument(
        "--path",
        type=Path,
        required=True,
        help="the extension source directory conformance runs against (holds extension.json)",
    )
    certify_cmd.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="the built package whose exact bytes the certification binds (the wheel)",
    )
    certify_cmd.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the machine-readable certification report JSON here",
    )
    certify_cmd.add_argument(
        "--profile",
        choices=[profile.value for profile in CertificationProfile],
        default=CertificationProfile.STANDARD.value,
        help="standard allows recorded backend waivers (listed as not proven); "
        "strict declines on any skip, waiver, or not-applicable check",
    )
    certify_cmd.add_argument(
        "--signing-key",
        default=None,
        metavar="HEX",
        help="Ed25519 private seed (32 bytes, hex) to sign the certification "
        "payload; prefer --signing-key-file so the key stays out of the "
        "process list",
    )
    certify_cmd.add_argument(
        "--signing-key-file",
        type=Path,
        default=None,
        metavar="FILE",
        help="read the Ed25519 private seed hex from FILE ('-' for stdin)",
    )
    certify_cmd.add_argument(
        "--with-reference",
        action="store_true",
        help="also run the conformance cases against the built-in reference extension",
    )
    certify_cmd.add_argument(
        "--allow-missing-backend",
        action="append",
        default=[],
        metavar="NAME",
        help="record a waiver for an unavailable backend NAME (standard profile "
        "lists it as not proven; strict declines)",
    )

    verify = sub.add_parser(
        "verify-certification",
        help="re-derive a certification from its bytes: digest, manifest binding, signature",
    )
    verify.add_argument(
        "--report",
        type=Path,
        required=True,
        help="the certification report JSON to verify",
    )
    verify.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="the package bytes in hand (mutation since certification fails here)",
    )
    verify.add_argument(
        "--publisher-key",
        default=None,
        metavar="HEX",
        help="the publisher's Ed25519 public key hex; when omitted, the "
        "signature is checked against the report's own recorded key "
        "(self-consistency, not authentication)",
    )
    return parser


def _read_signing_key(args: argparse.Namespace) -> str | None:
    """Resolve the signing key from --signing-key or --signing-key-file."""
    key = getattr(args, "signing_key", None)
    if key is not None:
        return str(key).strip()
    key_file = getattr(args, "signing_key_file", None)
    if key_file is not None:
        if str(key_file) == "-":
            return sys.stdin.read().strip()
        return Path(key_file).read_text(encoding="utf-8").strip()
    return None


def _certify(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    profile = CertificationProfile(args.profile)
    try:
        key = _read_signing_key(args)
    except (OSError, UnicodeDecodeError) as exc:
        # An unreadable --signing-key-file is a bad argument (exit 2), not
        # a traceback and not a silent unsigned certification (PR #2089
        # review, P2).
        print(f"error: cannot read --signing-key-file: {exc}", file=sys.stderr)
        return 2
    backends = BackendRegistry(waivers=frozenset(args.allow_missing_backend))
    report = certify(
        CertificationRequest(
            subject=args.path,
            artifact=args.artifact,
            profile=profile,
            signing_key_hex=key,
            with_reference=args.with_reference,
            backends=backends,
        )
    )
    if args.report is not None:
        report.write_json(args.report)
        print(f"certification report: {args.report}")
    print(report.human_summary())
    return 0 if report.certified else 1


def _verify(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    result = verify_certification(
        args.report,
        args.artifact,
        publisher_key_hex=args.publisher_key,
    )
    for item in result.checked:
        print(f"OK {item}")
    for failure in result.failures:
        print(f"INVALID {failure}", file=sys.stderr)
    if result.ok:
        print(
            "verified: the bytes in hand are the bytes this certification "
            "covers, and the signature holds"
        )
        return 0
    print("verification failed", file=sys.stderr)
    return 1


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
    # cannot even be validated is "could not run" for `run`, and a recorded
    # decline (exit 1) for `certify` — the decision document is still
    # produced and truthful there.
    if argv and argv[0] == "certify":
        return _certify(argv)
    if argv and argv[0] == "verify-certification":
        return _verify(argv)
    try:
        return _run(argv)
    except (ManifestRejected, HostError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
