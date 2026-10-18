#!/usr/bin/env python3
"""Validate the installed-workspace release-proof envelope, fail-closed (#1878).

One offline validator distinguishes structurally valid evidence from a
complete observed release-proof envelope. It reads a bundle directory
(``manifest.json``, ``results.json`` and the payload files the manifest
lists) plus a separately supplied reviewed profile, and never infers that
profile from the evidence being validated.

Validation runs in the contract's stage order — parse JSON; schema-validate
the profile, manifest and results; required IDs and uniqueness; profile and
candidate joins with browser applicability; safe paths, listed-reference
membership, file presence and SHA-256; then closeout conditions — and stops
at the first failing stage. Diagnostics within a stage are sorted by
``(path, code)`` and never quote raw file contents or secrets.

Output is exactly one report object::

    {"schema_version": 1, "valid": <bool>, "mode": "<mode>",
     "errors": [{"code": "<CODE>", "path": "<JSON-pointer-or-file>"}]}

Exit codes: 0 valid, 1 invalid, 2 CLI misuse (missing arguments, an unknown
mode, or a control input that does not exist — usage diagnostics on stderr
rather than a pretend bundle report).

Passing this validator does not assert that a run occurred, that evidence is
authentic, or that live security or provider behavior passed: structural or
envelope validation is explicitly not independent verification.

Usage::

    python scripts/validate-installed-workspace-proof.py \\
        --bundle <dir> --profile <reviewed-profile.json> --mode structural|closeout
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import installed_workspace_proof_contract as contract  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

#: The shipped envelope schema, resolved relative to this script so the CLI
#: works from any working directory inside a checkout.
SCHEMA_PATH = _SCRIPT_DIR.parent / "docs" / "testing" / "installed-workspace-proof.schema.json"

#: Diagnostic document labels, keyed as the parsed-document container uses them.
_DOCS = (contract.PROFILE_LABEL, contract.MANIFEST_NAME, contract.RESULTS_NAME)

#: Which ``$defs`` entry each document validates against.
_DOC_DEFS = {
    contract.PROFILE_LABEL: "reviewedProfile",
    contract.MANIFEST_NAME: "manifest",
    contract.RESULTS_NAME: "results",
}

_HASH_CHUNK = 1 << 20


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """Load the shipped envelope schema (the contract's shape authority)."""
    with (path or SCHEMA_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: str) -> str:
    """Hash the file's bytes — never decoded or reformatted content."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _path_stays_in_bundle(bundle_real: str, rel: str) -> bool:
    """Whether *rel* is a safe relative POSIX path contained in the bundle.

    Lexical rejection first; then symlink/realpath resolution against the
    bundle's real root. Containment is resolved before any read or hash, so a
    listed path can never cause this validator to touch a file outside the
    bundle.
    """
    if not contract.is_safe_relative_posix_path(rel):
        return False
    target = os.path.realpath(os.path.join(bundle_real, rel))
    return target == bundle_real or target.startswith(bundle_real + os.sep)


def _stage_parse(
    report: contract.Report, bundle: Path, profile_path: Path
) -> dict[str, Any] | None:
    """Stage 1 — parse all three documents, duplicate keys included."""
    sources = {
        contract.PROFILE_LABEL: profile_path,
        contract.MANIFEST_NAME: bundle / contract.MANIFEST_NAME,
        contract.RESULTS_NAME: bundle / contract.RESULTS_NAME,
    }
    docs: dict[str, Any] = {}
    for label in _DOCS:
        try:
            docs[label] = contract.parse_json_object(sources[label].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report.add(contract.INVALID_JSON, label)
    return None if report.failed else docs


def _stage_schema(report: contract.Report, schema: dict[str, Any], docs: dict[str, Any]) -> None:
    """Stage 2 — schema-validate each document against its ``$defs`` entry."""
    for label in _DOCS:
        # Root the validator at a $ref wrapper so the defs' internal "#/$defs/..."
        # references resolve against the shipped schema, not the bare def.
        def_name = _DOC_DEFS[label]
        rooted = {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]}
        for error in Draft202012Validator(rooted).iter_errors(docs[label]):
            parts = tuple(error.absolute_path)
            if error.validator == "additionalProperties" and not parts:
                # jsonschema reports an extra property at the object root;
                # name the offending keys structurally (from the schema's
                # allowed set, never from raw content) so the diagnostic says
                # which property to remove.
                allowed = set(schema["$defs"][def_name].get("properties", {}))
                for key in sorted(set(docs[label]) - allowed):
                    report.add(contract.SCHEMA_INVALID, contract.doc_path(label, key))
                continue
            report.add(
                contract.SCHEMA_INVALID,
                contract.doc_path(label, *parts) if parts else label,
            )


def _stage_ids(report: contract.Report, results: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Stage 3 — required IDs and uniqueness; return first index per row ID."""
    first: dict[str, dict[str, int]] = {}
    for field, required_ids in (
        ("scenarios", contract.SCENARIO_IDS),
        ("subchecks", contract.SUBCHECK_IDS),
    ):
        indexes: dict[str, list[int]] = {rid: [] for rid in required_ids}
        for i, row in enumerate(results[field]):
            indexes.setdefault(row["id"], []).append(i)
        for rid in required_ids:
            found = indexes[rid]
            if not found:
                report.add(
                    contract.REQUIRED_SCENARIO_NOT_PASS,
                    contract.doc_path(contract.RESULTS_NAME, field),
                )
                continue
            first.setdefault(field, {})[rid] = found[0]
            for i in found[1:]:
                report.add(
                    contract.DUPLICATE_SCENARIO,
                    contract.doc_path(contract.RESULTS_NAME, field, i),
                )
    return first


def _stage_joins(
    report: contract.Report,
    docs: dict[str, Any],
    first: dict[str, dict[str, int]],
) -> None:
    """Stage 4 — profile/candidate joins and browser-login applicability."""
    profile, manifest, results = (
        docs[contract.PROFILE_LABEL],
        docs[contract.MANIFEST_NAME],
        docs[contract.RESULTS_NAME],
    )
    profile_id = profile["profile_id"]
    if manifest["profile_id"] != profile_id:
        report.add(
            contract.PROFILE_MISMATCH,
            contract.doc_path(contract.MANIFEST_NAME, "profile_id"),
        )
    if results["profile_id"] != profile_id:
        report.add(
            contract.PROFILE_MISMATCH,
            contract.doc_path(contract.RESULTS_NAME, "profile_id"),
        )
    if results["candidate_sha256"] != manifest["candidate"]["artifact_sha256"]:
        report.add(
            contract.CANDIDATE_MISMATCH,
            contract.doc_path(contract.RESULTS_NAME, "candidate_sha256"),
        )
    subcheck_index = first.get("subchecks", {}).get("BROWSER_LOGIN")
    if subcheck_index is None:  # stage 3 already failed for the missing row
        return
    applicable = profile["browser_login_applicable"]
    outcome = results["subchecks"][subcheck_index]["outcome"]
    # NOT_APPLICABLE exactly when the reviewed profile says browser login does
    # not apply — in both modes, so a structurally convenient "not applicable"
    # can never contradict the independently supplied profile.
    if (outcome == "NOT_APPLICABLE") == applicable:
        report.add(
            contract.INVALID_APPLICABILITY,
            contract.doc_path(contract.RESULTS_NAME, "subchecks", subcheck_index),
        )


def _profile_references(profile_path: Path) -> frozenset[str]:
    """Names the external reviewed profile is inadmissible under."""
    as_posix = profile_path.as_posix()
    return frozenset({as_posix, profile_path.name})


def _check_path_safety(
    report: contract.Report,
    bundle_real: str,
    manifest: dict[str, Any],
    results: dict[str, Any],
    listed: dict[str, list[int]],
    inadmissible: frozenset[str] | set[str],
) -> dict[str, bool]:
    """Stage 5a — safe paths, before anything is read; return per-path safety."""
    listed_safe: dict[str, bool] = {}
    for i, entry in enumerate(manifest["files"]):
        path = entry["path"]
        if path not in listed_safe:
            listed_safe[path] = _path_stays_in_bundle(bundle_real, path)
        if not listed_safe[path]:
            report.add(
                contract.EVIDENCE_PATH_UNSAFE,
                contract.doc_path(contract.MANIFEST_NAME, "files", i, "path"),
            )
    for field in ("scenarios", "subchecks"):
        for i, row in enumerate(results[field]):
            for j, evidence in enumerate(row["evidence_paths"]):
                at = contract.doc_path(contract.RESULTS_NAME, field, i, "evidence_paths", j)
                if not _path_stays_in_bundle(bundle_real, evidence):
                    report.add(contract.EVIDENCE_PATH_UNSAFE, at)
                    continue
                # Evidence must name listed payload files — never a control
                # input such as results.json itself or the reviewed profile.
                if evidence in inadmissible or evidence not in listed:
                    report.add(contract.EVIDENCE_UNLISTED, at)
    return listed_safe


def _check_listing_boundary(
    report: contract.Report,
    listed: dict[str, list[int]],
    profile_refs: frozenset[str],
) -> None:
    """Stage 5b — results.json and the required payloads listed; manifest.json
    and the reviewed profile never listed; listed paths unique."""
    if contract.RESULTS_NAME not in listed:
        report.add(contract.EVIDENCE_UNLISTED, contract.RESULTS_NAME)
    for payload in contract.REQUIRED_PAYLOADS:
        if payload not in listed:
            report.add(contract.EVIDENCE_UNLISTED, payload)
    for path, indexes in listed.items():
        forbidden_listing = path == contract.MANIFEST_NAME or path in profile_refs
        for i in indexes:
            if forbidden_listing:
                report.add(
                    contract.EVIDENCE_UNLISTED,
                    contract.doc_path(contract.MANIFEST_NAME, "files", i),
                )
            elif i > indexes[0]:
                report.add(
                    contract.DUPLICATE_FILE,
                    contract.doc_path(contract.MANIFEST_NAME, "files", i),
                )


def _check_presence_and_hash(
    report: contract.Report,
    bundle_real: str,
    files: list[dict[str, Any]],
    listed_safe: dict[str, bool],
) -> None:
    """Stage 5c — every listed, path-safe entry present and correctly hashed."""
    for i, entry in enumerate(files):
        path = entry["path"]
        if not listed_safe[path]:
            continue
        real = os.path.realpath(os.path.join(bundle_real, path))
        if not os.path.isfile(real):
            report.add(
                contract.EVIDENCE_MISSING,
                contract.doc_path(contract.MANIFEST_NAME, "files", i),
            )
            continue
        if _sha256_file(real) != entry["sha256"]:
            report.add(
                contract.EVIDENCE_HASH_MISMATCH,
                contract.doc_path(contract.MANIFEST_NAME, "files", i),
            )


def _stage_files(
    report: contract.Report,
    bundle: Path,
    profile_path: Path,
    docs: dict[str, Any],
) -> None:
    """Stage 5 — path safety, listing membership, presence and SHA-256."""
    bundle_real = os.path.realpath(bundle)
    manifest = docs[contract.MANIFEST_NAME]
    results = docs[contract.RESULTS_NAME]
    files = manifest["files"]
    listed: dict[str, list[int]] = {}
    for i, entry in enumerate(files):
        listed.setdefault(entry["path"], []).append(i)
    profile_refs = _profile_references(profile_path)
    inadmissible = set(contract.INADMISSIBLE_EVIDENCE) | profile_refs

    listed_safe = _check_path_safety(report, bundle_real, manifest, results, listed, inadmissible)
    _check_listing_boundary(report, listed, profile_refs)
    _check_presence_and_hash(report, bundle_real, files, listed_safe)


def _stage_closeout(
    report: contract.Report,
    docs: dict[str, Any],
    first: dict[str, dict[str, int]],
) -> None:
    """Stage 6 — closeout: every family PASS, applicable browser subcheck
    PASS, and observed (never synthetic) evidence."""
    profile, manifest, results = (
        docs[contract.PROFILE_LABEL],
        docs[contract.MANIFEST_NAME],
        docs[contract.RESULTS_NAME],
    )
    if manifest["evidence_kind"] == "synthetic":
        report.add(
            contract.SYNTHETIC_NOT_CLOSEOUT,
            contract.doc_path(contract.MANIFEST_NAME, "evidence_kind"),
        )
    for i, row in enumerate(results["scenarios"]):
        if row["outcome"] != "PASS":
            report.add(
                contract.REQUIRED_SCENARIO_NOT_PASS,
                contract.doc_path(contract.RESULTS_NAME, "scenarios", i),
            )
    subcheck_index = first.get("subchecks", {}).get("BROWSER_LOGIN")
    if (
        profile["browser_login_applicable"]
        and subcheck_index is not None
        and results["subchecks"][subcheck_index]["outcome"] != "PASS"
    ):
        report.add(
            contract.REQUIRED_SCENARIO_NOT_PASS,
            contract.doc_path(contract.RESULTS_NAME, "subchecks", subcheck_index),
        )


def validate_bundle(
    bundle: Path,
    profile_path: Path,
    mode: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate one bundle; return the report object the CLI prints."""
    report = contract.Report(mode)
    docs = _stage_parse(report, bundle, profile_path)
    if docs is None:
        return report.as_dict()
    _stage_schema(report, schema, docs)
    if report.failed:
        return report.as_dict()
    first = _stage_ids(report, docs[contract.RESULTS_NAME])
    if report.failed:
        return report.as_dict()
    _stage_joins(report, docs, first)
    if report.failed:
        return report.as_dict()
    _stage_files(report, bundle, profile_path, docs)
    if report.failed:
        return report.as_dict()
    if mode == "closeout":
        _stage_closeout(report, docs, first)
    return report.as_dict()


def run(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog=Path(__file__).name,
        description=(
            "Validate an installed-workspace release-proof envelope "
            "(structural or closeout). Never asserts that a run occurred or "
            "that evidence is authentic."
        ),
    )
    parser.add_argument("--bundle", required=True, type=Path, help="bundle directory to validate")
    parser.add_argument(
        "--profile",
        required=True,
        type=Path,
        help="independently supplied reviewed profile JSON (never inferred from the bundle)",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=list(contract.MODES),
        help="structural = well-formed envelope; closeout = complete "
        "observed release-proof envelope",
    )
    args = parser.parse_args(argv)
    if not args.bundle.is_dir():
        print(f"error: --bundle is not a directory: {args.bundle}", file=sys.stderr)
        return 2
    if not args.profile.is_file():
        print(f"error: --profile is not a file: {args.profile}", file=sys.stderr)
        return 2
    try:
        schema = load_schema()
    except (OSError, ValueError) as exc:
        print(f"error: cannot load envelope schema {SCHEMA_PATH}: {exc}", file=sys.stderr)
        return 2
    report = validate_bundle(args.bundle, args.profile, args.mode, schema)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(run())
