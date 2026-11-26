#!/usr/bin/env python3
"""Byte-equivalent final promotion (E3 §6 / #89) — the RC-artifact reuse path.

Why this exists
---------------
ADR-073126-c4e1 §6: "the final release ships the artifacts the last rc already
validated." Before #89 the shipping workflow *rebuilt* wheels and container
images for a final tag: equal git trees make a rebuild plausible, not identical
— wheel zip members carry build-time mtimes, and image builds re-resolve base
layers and dependency locks. A final built again was a different byte sequence
from the candidate the soak exercised, which voids the soak's evidential value.

The contract this script enforces (all fail-closed):

1. **record-evidence** (RC runs) freezes one machine-readable identity record:
   the tag, commit, git tree, run, and the sha256 of every wheel/sdist built
   from the candidate commit. The images job later adds the image digests. A
   wheel built on Tuesday and a wheel "re-built from the same tree" on Friday
   are not interchangeable; this record is what makes that falsifiable.

2. **adopt-wheels** (final runs) locates the successful release run of the
   selected RC tag (`release_guard.py --verify-rc-tree` names it), downloads
   that run's evidence and `dist` artifacts, verifies every downloaded file
   against the recorded sha256 — byte for byte, not "should be the same" — and
   refuses any mismatch, missing file, or extra file. The final's `dist/` is
   then the candidate's bytes; PyPI publishes what the soak installed.

3. **adopt-digests** (final runs) validates the soak evidence bound to the
   same record: the soak must name the exact wheel sha256 map and image
   digests, the exact configuration digest, and must report pass on clean
   install, real-model execution, the security hot path, backup/restore and
   the #860 multi-replica workload. Any load/concurrency finding that
   invalidates an earlier milestone invariant must carry the issue it was
   filed/reclassified under before promotion is allowed. It then emits the
   digests the images job promotes — `buildx imagetools create` re-tags those
   digests byte-for-byte; the final run never builds an image.

4. **finalize-evidence** (images job, both run kinds) completes the record
   with the promoted digests and — for finals — the promotion linkage (which
   RC run the bytes were adopted from). The GitHub release attaches the
   record and the soak evidence as release assets, so the machine-readable
   evidence ships with the exact promoted artifact/configuration.

The soak itself is produced outside this script (the soak harness uploads a
`soak-evidence` artifact to the RC run before final promotion is attempted).
Promotion without it fails here, loudly — the same deliberate fail-loud
posture as the PyPI publisher before its trusted publisher exists.

Cross-lane contract (#860 / PR #1672): the soak harness's native record
(`m3a-soak-evidence.json` — `thresholds.checks.<name>.ok` booleans) does NOT
satisfy this gate. The soak lane must publish an Actions artifact named
exactly `soak-evidence` on the RC release run, in the `soak-evidence.json`
schema below (schema 1: `artifact_binding` over the record's wheel sha256 map
and image digests plus a config digest; the five REQUIRED_SOAK_CHECKS each
`status == "pass"` with cited evidence; invariant-invalidating findings
carrying `routed_issue`). Until that artifact exists, `adopt-digests` fails
closed — by design; adapting this gate to the harness's boolean schema would
weaken it.

Record shapes
-------------
release-evidence.json (schema 1)::

    {
      "schema": 1,
      "tag": "v1.0.0-rc1",
      "version": "1.0.0",
      "commit": "<40 hex>",
      "tree": "<40 hex>",
      "run_id": 123,
      "run_url": "https://github.com/.../actions/runs/123",
      "wheels": {"maistro_core-1.0.0-py3-none-any.whl": "<64 hex>", ...},
      "images": {"maistro-engine": "sha256:<64 hex>",      # added by finalize
                 "hive-conductor": "sha256:<64 hex>"}
    }

soak-evidence.json (schema 1)::

    {
      "schema": 1,
      "artifact_binding": {
        "wheels_sha256": {...same map as the record...},
        "image_digests": {...same map as the record's images...},
        "config_digest": "<64 hex>",
        "config": "deploy/soak/compose.yaml@<digest-ish reference>"
      },
      "checks": {
        "clean_install":       {"status": "pass", "evidence": ["..."]},
        "real_model":          {"status": "pass", "evidence": ["..."]},
        "security_hot_path":   {"status": "pass", "evidence": ["..."]},
        "backup_restore":      {"status": "pass", "evidence": ["..."]},
        "multi_replica_soak":  {"status": "pass", "evidence": ["..."]}
      },
      "findings": [
        {"id": "F-1", "severity": "high", "invalidates_invariant": false},
        {"id": "F-2", "severity": "high", "invalidates_invariant": true,
         "routed_issue": "#412"}
      ]
    }

Usage
-----
    scripts/promote_release.py record-evidence  --tag v1.0.0-rc1 --version 1.0.0 \
        --dist dist/ --output release-evidence.json
    scripts/promote_release.py adopt-wheels     --tag v1.0.0 --version 1.0.0 \
        --rc-tag v1.0.0-rc1 --dist-dir dist/ --evidence-out release-evidence.json
    scripts/promote_release.py adopt-digests    --evidence release-evidence.json \
        --soak-out soak-evidence/soak-evidence.json --github-output "$GITHUB_OUTPUT"
    scripts/promote_release.py finalize-evidence --evidence release-evidence.json \
        --engine-digest sha256:... --conductor-digest sha256:... \
        [--adopted-from-rc-tag v1.0.0-rc1 --adopted-from-run-id 123] \
        --output release-evidence.json

Every failure exits non-zero after printing ``::error::`` annotations; the
workflow stops before anything is published. GitHub access is isolated in
``_gh``/``_download_artifact`` so tests exercise the whole logic against
fakes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCHEMA = 1
SOAK_SCHEMA = 1

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_NAMES = ("maistro-engine", "hive-conductor")
ARTIFACT_SUFFIXES = (".whl", ".tar.gz")
ISSUE_REF = re.compile(r"^#\d+$")

EVIDENCE_ARTIFACT = "release-evidence"
SOAK_ARTIFACT = "soak-evidence"

# The soak coverage #89 requires before anything is promoted: the documented
# install/product/security/recovery checks, plus the #860 representative
# sustained multi-replica workload. A record missing any of these, or reporting
# any of them as something other than pass with cited evidence, fails promotion.
REQUIRED_SOAK_CHECKS = (
    "clean_install",
    "real_model",
    "security_hot_path",
    "backup_restore",
    "multi_replica_soak",
)


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256sums(dist: Path) -> dict[str, str]:
    """The artifact identity map: filename -> sha256, for everything in `dist`."""
    return {entry.name: _sha256(entry) for entry in sorted(dist.iterdir()) if entry.is_file()}


def _check_wheel_map(wheels: object, errors: list[str]) -> None:
    if not isinstance(wheels, dict) or not wheels:
        _fail(errors, "wheels: must be a non-empty {filename: sha256} map")
        return
    for name, digest in wheels.items():
        if not isinstance(name, str) or name.startswith(".") or "/" in name or "\\" in name:
            _fail(errors, f"wheels: {name!r} is not a plain artifact filename")
            continue
        if not name.endswith(ARTIFACT_SUFFIXES):
            _fail(errors, f"wheels: {name!r} is neither a wheel nor an sdist")
        if not isinstance(digest, str) or not SHA64.fullmatch(digest):
            _fail(errors, f"wheels: {name} has no lowercase sha256 digest")


def _validate_identity(
    evidence: dict, *, version: str, rc_tag: str, tree: str | None, errors: list[str]
) -> None:
    if evidence.get("schema") != SCHEMA:
        _fail(errors, f"schema: expected {SCHEMA}, got {evidence.get('schema')!r}")
    if evidence.get("version") != version:
        _fail(errors, f"version: expected {version!r}, got {evidence.get('version')!r}")
    if evidence.get("tag") != rc_tag:
        _fail(
            errors,
            f"tag: expected the selected candidate {rc_tag!r}, got {evidence.get('tag')!r}",
        )
    for field in ("commit", "tree"):
        value = evidence.get(field)
        if not isinstance(value, str) or not SHA40.fullmatch(value):
            _fail(errors, f"{field}: expected a 40-hex git object id, got {value!r}")
    # The guard proves tag-to-tag tree equality; this proves the RECORD
    # describes the promoted tree, so the adopted bytes were built from it.
    if (
        isinstance(evidence.get("commit"), str)
        and isinstance(tree, str)
        and evidence["tree"] != tree
    ):
        _fail(
            errors,
            f"tree: record describes {evidence['tree']}, but the promoted tree is {tree}",
        )
    run_id = evidence.get("run_id")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        _fail(errors, f"run_id: expected a positive run id, got {run_id!r}")
    run_url = evidence.get("run_url")
    if not isinstance(run_url, str) or not run_url.startswith("https://"):
        _fail(errors, f"run_url: expected an https run URL, got {run_url!r}")
    _check_wheel_map(evidence.get("wheels"), errors)
    images = evidence.get("images")
    if images is not None:
        _check_image_map(images, errors)


def validate_evidence(
    evidence: object,
    *,
    version: str,
    rc_tag: str,
    tree: str | None = None,
) -> list[str]:
    """Everything the final promotion relies on, checked before anything moves.

    `tree` (the final tag's tree, when supplied) must equal the recorded RC
    tree. `images` is optional — the wheels job records before the images job
    runs — but when present it must already name both published images.
    """
    errors: list[str] = []
    if not isinstance(evidence, dict):
        return ["release evidence must be a JSON object"]
    _validate_identity(evidence, version=version, rc_tag=rc_tag, tree=tree, errors=errors)
    return errors


def _check_image_map(images: object, errors: list[str]) -> None:
    if not isinstance(images, dict):
        _fail(errors, "images: must be a {image: sha256:...} map")
        return
    for name in IMAGE_NAMES:
        digest = images.get(name)
        if not isinstance(digest, str) or not IMAGE_DIGEST.fullmatch(digest):
            _fail(errors, f"images: {name} must carry a sha256:<64 hex> registry digest")


def _validate_binding(binding: object, evidence: dict, errors: list[str]) -> None:
    if not isinstance(binding, dict):
        _fail(
            errors,
            "artifact_binding: required ({wheels_sha256, image_digests, config_digest, config})",
        )
        return
    if binding.get("wheels_sha256") != evidence.get("wheels"):
        _fail(
            errors,
            "artifact_binding.wheels_sha256 does not match the release record exactly; "
            "the soak did not run against these artifacts",
        )
    if binding.get("image_digests") != evidence.get("images"):
        _fail(
            errors,
            "artifact_binding.image_digests does not match the release record exactly; "
            "the soak did not run against these image digests",
        )
    config_digest = binding.get("config_digest")
    if not isinstance(config_digest, str) or not SHA64.fullmatch(config_digest):
        _fail(errors, f"artifact_binding.config_digest: expected 64-hex, got {config_digest!r}")
    config = binding.get("config")
    if not isinstance(config, str) or not config.strip():
        _fail(errors, "artifact_binding.config: expected the soaked configuration reference")


def _validate_checks(checks: object, errors: list[str]) -> None:
    if not isinstance(checks, dict):
        _fail(errors, "checks: required")
        return
    for name in REQUIRED_SOAK_CHECKS:
        check = checks.get(name)
        if not isinstance(check, dict):
            _fail(errors, f"checks.{name}: missing — required before promotion (#89)")
            continue
        if check.get("status") != "pass":
            _fail(errors, f"checks.{name}: status must be 'pass', got {check.get('status')!r}")
        cited = check.get("evidence")
        if (
            not isinstance(cited, list)
            or not cited
            or not all(isinstance(item, str) and item.strip() for item in cited)
        ):
            _fail(errors, f"checks.{name}.evidence: must cite at least one non-empty reference")


def _validate_findings(findings: object, errors: list[str]) -> None:
    if not isinstance(findings, list):
        _fail(errors, "findings: must be a list")
        return
    for finding in findings:
        if not isinstance(finding, dict):
            _fail(errors, "findings: each entry must be an object")
            continue
        if not isinstance(finding.get("id"), str) or not finding["id"].strip():
            _fail(errors, "findings: every finding needs a non-empty id")
        if not isinstance(finding.get("invalidates_invariant"), bool):
            _fail(
                errors,
                f"findings[{finding.get('id')}]: invalidates_invariant must be a boolean",
            )
            continue
        if finding["invalidates_invariant"] and not (
            isinstance(finding.get("routed_issue"), str)
            and ISSUE_REF.fullmatch(finding["routed_issue"])
        ):
            _fail(
                errors,
                f"findings[{finding.get('id')}]: invalidates an earlier milestone invariant "
                "but names no routed_issue — file/reclassify it there before promotion (#89)",
            )


def validate_soak(soak: object, *, evidence: dict) -> list[str]:
    """Soak evidence must bind to the exact promoted artifacts and configuration.

    Anything less — a soak of a rebuild, a stale digest, a failing check, or an
    invariant-invalidating finding without the issue it was routed to — fails
    the promotion here rather than on PyPI's doorstep.
    """
    errors: list[str] = []
    if not isinstance(soak, dict):
        return ["soak evidence must be a JSON object"]
    if soak.get("schema") != SOAK_SCHEMA:
        _fail(errors, f"schema: expected {SOAK_SCHEMA}, got {soak.get('schema')!r}")
    _validate_binding(soak.get("artifact_binding"), evidence, errors)
    _validate_checks(soak.get("checks"), errors)
    _validate_findings(soak.get("findings", []), errors)
    return errors


def verify_dist(dist_dir: Path, wheels: dict[str, str]) -> list[str]:
    """The downloaded artifacts must be EXACTLY the recorded candidate bytes.

    A missing file, a hash mismatch, or an extra file means the final would
    publish something the soak never ran against.
    """
    errors: list[str] = []
    present = {entry.name for entry in dist_dir.iterdir() if entry.is_file()}
    for name, digest in wheels.items():
        path = dist_dir / name
        if not path.is_file():
            _fail(errors, f"{name}: recorded artifact is missing from the RC run's dist")
            continue
        actual = _sha256(path)
        if actual != digest:
            _fail(errors, f"{name}: sha256 {actual} != recorded {digest} — not the soaked bytes")
    for extra in sorted(present - set(wheels)):
        _fail(errors, f"{extra}: present in the RC run's dist but not in the record")
    return errors


# --- GitHub access (isolated for tests) -------------------------------------


def _gh(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _download_artifact(repo: str, artifact_id: int, dest: Path) -> None:
    """Download one workflow-run artifact zip and unpack it into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="promote-artifact-") as tmp:
        zip_path = Path(tmp) / "artifact.zip"
        with zip_path.open("wb") as handle:
            # gh follows the artifact zip redirect to the blob store; --header
            # accepts the binary zip payload gh api pipes to stdout.
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/actions/artifacts/{artifact_id}/zip"],
                stdout=handle,
                stderr=subprocess.PIPE,
                text=False,
                check=False,
            )
            stderr = (result.stderr or b"").decode(errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"artifact {artifact_id} download failed: {stderr.strip()}")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(dest)


def select_rc_run(runs: list[dict], rc_tag: str) -> tuple[dict | None, list[str]]:
    """The release run of the selected candidate tag, if that attempt succeeded.

    Strictly the LATEST run: a re-run that failed after an earlier success is
    the candidate's current truth, and an older candidate's successful run is
    never promotion evidence for a newer one. The newest attempt defines what
    ships, so a failed rc run blocks promotion until rc (or a successor)
    succeeds.
    """
    errors: list[str] = []
    eligible = [
        run
        for run in runs
        if run.get("head_branch") == rc_tag
        and run.get("event") == "push"
        and (run.get("path") == ".github/workflows/release.yml" or run.get("name") == "release")
    ]
    if not eligible:
        _fail(
            errors,
            f"no release run found for {rc_tag}; its artifacts and soak evidence cannot be located",
        )
        return None, errors
    latest = max(eligible, key=lambda run: run.get("id", 0))
    if latest.get("conclusion") != "success":
        _fail(
            errors,
            f"the latest release run for {rc_tag} concluded "
            f"{latest.get('conclusion')!r}, not 'success'; fix and re-tag or cut a "
            "new candidate — an older successful run is not promotion evidence",
        )
        return None, errors
    return latest, errors


def _fetch_run_id(repo: str, rc_tag: str) -> int:
    raw = _gh(
        [
            "api",
            f"repos/{repo}/actions/workflows/release.yml/runs?per_page=100",
            "--jq",
            ".workflow_runs[]",
        ]
    )
    runs = [json.loads(line) for line in raw.splitlines() if line.strip()]
    run, errors = select_rc_run(runs, rc_tag)
    if run is None:
        raise SystemExit(
            "\n".join(f"::error::{message}" for message in errors) or "::error::no RC run"
        )
    return int(run["id"])


def _artifact_id(repo: str, run_id: int, name: str) -> int:
    raw = _gh(
        [
            "api",
            f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
            "--jq",
            ".artifacts[]",
        ]
    )
    for line in raw.splitlines():
        artifact = json.loads(line)
        if artifact.get("name") == name and not artifact.get("expired", False):
            return int(artifact["id"])
    raise SystemExit(f"::error::run {run_id} has no '{name}' artifact")


def _load_json(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"::error::{what} is unreadable: {exc}") from exc


# --- subcommands -------------------------------------------------------------


def cmd_record_evidence(args: argparse.Namespace) -> int:
    """RC runs: freeze the candidate artifact identity before anything scans it."""
    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"::error::{dist} is not a directory", file=sys.stderr)
        return 1
    entries = sha256sums(dist)
    if not entries:
        print(f"::error::{dist} contains no artifacts to record", file=sys.stderr)
        return 1
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    run_id = int(os.environ.get("GITHUB_RUN_ID", "0") or 0)
    run_url = (
        f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'unknown/unknown')}"
        f"/actions/runs/{run_id}"
        if run_id
        else "https://invalid/run-missing-GITHUB_RUN_ID"
    )
    record = {
        "schema": SCHEMA,
        "tag": args.tag,
        "version": args.version,
        "commit": commit,
        "tree": tree,
        "run_id": run_id,
        "run_url": run_url,
        "wheels": entries,
    }
    Path(args.output).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"recorded {len(entries)} artifact(s) for {args.tag} at tree {tree}")
    return 0


def cmd_adopt_wheels(args: argparse.Namespace) -> int:
    """Final runs: replace the rebuild with the soaked candidate's bytes."""
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("::error::--repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1
    run_id = _fetch_run_id(repo, args.rc_tag)
    artifact_dir = Path(tempfile.mkdtemp(prefix="adopt-wheels-"))
    _download_artifact(repo, _artifact_id(repo, run_id, EVIDENCE_ARTIFACT), artifact_dir)
    evidence_path = artifact_dir / f"{EVIDENCE_ARTIFACT}.json"
    evidence = _load_json(evidence_path, "downloaded release evidence")
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
    errors = validate_evidence(evidence, version=args.version, rc_tag=args.rc_tag, tree=tree)
    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        return 1
    assert isinstance(evidence, dict)  # validate_evidence returned no errors
    wheels: dict[str, str] = evidence["wheels"]

    dist_dir = Path(args.dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    _download_artifact(repo, _artifact_id(repo, run_id, "dist"), dist_dir)
    errors = verify_dist(dist_dir, wheels)
    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        return 1

    out = Path(args.evidence_out)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"rc_run_id={run_id}\n")
    print(
        f"adopted {len(wheels)} artifact(s) of {args.rc_tag} (run {run_id}) byte-identical "
        f"at tree {tree}"
    )
    return 0


def cmd_adopt_digests(args: argparse.Namespace) -> int:
    """Final runs: gate on soak evidence, then hand the promoted digests over."""
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("::error::--repo or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 1
    evidence = _load_json(Path(args.evidence), "release evidence")
    errors = validate_evidence(evidence, version=args.version, rc_tag=args.rc_tag)
    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        return 1
    assert isinstance(evidence, dict)

    run_id = int(evidence["run_id"])
    soak_dir = Path(args.soak_out).parent
    _download_artifact(repo, _artifact_id(repo, run_id, SOAK_ARTIFACT), soak_dir)
    soak = _load_json(Path(args.soak_out), "downloaded soak evidence")
    errors = validate_soak(soak, evidence=evidence)
    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        return 1
    assert isinstance(soak, dict)

    images: dict[str, str] = evidence["images"]
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"engine_digest={images['maistro-engine']}\n")
            handle.write(f"conductor_digest={images['hive-conductor']}\n")
            handle.write(f"rc_run_id={run_id}\n")
    print(
        f"soak evidence for {args.rc_tag} binds these exact artifacts and configuration; "
        f"promoting digests {images['maistro-engine']}, {images['hive-conductor']}"
    )
    return 0


def cmd_finalize_evidence(args: argparse.Namespace) -> int:
    """Images job: complete the record with the promoted digests (+ linkage)."""
    evidence = _load_json(Path(args.evidence), "release evidence")
    assert isinstance(evidence, dict), "finalize reads a record written by this script"
    errors: list[str] = []
    _check_image_map(
        {"maistro-engine": args.engine_digest, "hive-conductor": args.conductor_digest},
        errors,
    )
    if errors:
        for message in errors:
            print(f"::error::{message}", file=sys.stderr)
        return 1
    evidence["images"] = {
        "maistro-engine": args.engine_digest,
        "hive-conductor": args.conductor_digest,
    }
    if args.adopted_from_rc_tag or args.adopted_from_run_id:
        if not (args.adopted_from_rc_tag and args.adopted_from_run_id):
            print(
                "::error::promotion linkage needs both --adopted-from-rc-tag and "
                "--adopted-from-run-id",
                file=sys.stderr,
            )
            return 1
        evidence["promotion"] = {
            "adopted_from_rc_tag": args.adopted_from_rc_tag,
            "adopted_from_run_id": int(args.adopted_from_run_id),
            "wheels_rebuilt": False,
            "images_rebuilt": False,
        }
    Path(args.output).write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("evidence finalized: images bound, promotion linkage recorded")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record-evidence", help="RC runs: freeze the candidate identity")
    record.add_argument("--tag", required=True)
    record.add_argument("--version", required=True)
    record.add_argument("--dist", required=True, help="directory holding the built artifacts")
    record.add_argument("--output", required=True)

    adopt_wheels = sub.add_parser(
        "adopt-wheels", help="final runs: download + verify the RC run's dist"
    )
    adopt_wheels.add_argument("--tag", required=True, help="the final tag")
    adopt_wheels.add_argument("--version", required=True)
    adopt_wheels.add_argument("--rc-tag", required=True, help="candidate to adopt (guard output)")
    adopt_wheels.add_argument("--dist-dir", required=True)
    adopt_wheels.add_argument("--evidence-out", required=True)
    adopt_wheels.add_argument("--repo", default=None)
    adopt_wheels.add_argument("--github-output", default=None)

    adopt_digests = sub.add_parser(
        "adopt-digests", help="final runs: validate soak, emit the RC digests"
    )
    adopt_digests.add_argument("--evidence", required=True)
    adopt_digests.add_argument("--version", required=True)
    adopt_digests.add_argument("--rc-tag", required=True)
    adopt_digests.add_argument("--soak-out", required=True)
    adopt_digests.add_argument("--repo", default=None)
    adopt_digests.add_argument("--github-output", default=None)

    finalize = sub.add_parser("finalize-evidence", help="images job: bind digests + linkage")
    finalize.add_argument("--evidence", required=True)
    finalize.add_argument("--engine-digest", required=True)
    finalize.add_argument("--conductor-digest", required=True)
    finalize.add_argument("--adopted-from-rc-tag", default=None)
    finalize.add_argument("--adopted-from-run-id", default=None)
    finalize.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    commands = {
        "record-evidence": cmd_record_evidence,
        "adopt-wheels": cmd_adopt_wheels,
        "adopt-digests": cmd_adopt_digests,
        "finalize-evidence": cmd_finalize_evidence,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
