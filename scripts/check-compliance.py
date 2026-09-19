#!/usr/bin/env python3
"""Validate the compliance control registry and its rendered Markdown view.

The registry is deliberately evidence-first.  A control may describe an
implementation without claiming that a release has proved it.  Only an
``implemented`` control with passing, non-expired evidence bound to the exact
release digest can be green.  Legal sufficiency is outside this checker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "compliance-registry.json"
DOCUMENT = ROOT / "COMPLIANCE.md"
SCHEMA_VERSION = 1
MAX_EVIDENCE_AGE = dt.timedelta(days=90)
GITHUB_REPOSITORY = "Agent-StrongHold/Project-mAIstro"
STATUSES = frozenset(
    {
        "implemented",
        "partially_implemented",
        "documented",
        "planned",
        "not_applicable",
        "unverified",
    }
)
ID_RE = re.compile(r"^[A-Z][A-Z0-9-]+$")
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{40,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_CONTROL_FIELDS = frozenset(
    {
        "id",
        "framework",
        "requirement",
        "status",
        "owner",
        "scope",
        "control_refs",
        "test_refs",
        "evidence",
        "last_verified",
        "expires",
        "release_required",
    }
)
REQUIRED_REGISTRY_FIELDS = frozenset({"schema_version", "release_digest", "controls"})
REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "url",
        "sha256",
        "release_digest",
        "control_id",
        "control_refs",
        "test_refs",
        "observed_at",
        "result",
        "workflow_ref",
        "workflow_enabled",
        "manual_only",
        "ran",
    }
)
OPTIONAL_EVIDENCE_FIELDS = frozenset({"attestation"})
TABLE_HEADER = (
    "ID",
    "Framework",
    "Claim",
    "Status",
    "Owner",
    "Scope",
    "Last verification",
    "Expires",
    "Evidence",
)
BEGIN_MARKER = "<!-- compliance-registry:begin -->"
END_MARKER = "<!-- compliance-registry:end -->"


def _date(value: Any, field: str, where: str, errors: list[str]) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        errors.append(f"{where}.{field} must be an ISO date or null")
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where}.{field} is not a real calendar date")
        return None


def _is_link(value: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _workflow_locator(value: str) -> tuple[str, str] | None:
    """Return the commit digest and workflow path from an immutable source link."""
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    prefix = f"/{GITHUB_REPOSITORY}/blob/"
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        return None
    if not parsed.path.startswith(prefix):
        return None
    suffix = parsed.path[len(prefix) :].strip("/").split("/", 1)
    if len(suffix) != 2 or not HEX_DIGEST_RE.fullmatch(suffix[0]):
        return None
    workflow_ref = suffix[1]
    if not workflow_ref.startswith(".github/workflows/"):
        return None
    return suffix[0], workflow_ref


def _is_immutable_evidence_link(value: str) -> bool:
    """Accept immutable artifact URLs or commit-bound workflow evidence locators."""
    if _workflow_locator(value) is not None:
        return True
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        return False
    expected_prefix = f"/{GITHUB_REPOSITORY}/actions/runs/"
    if not parsed.path.startswith(expected_prefix):
        return False
    suffix = parsed.path[len(expected_prefix) :].strip("/").split("/")
    return (
        bool(suffix)
        and suffix[0].isdigit()
        and (
            len(suffix) == 1
            or (len(suffix) == 3 and suffix[1] == "artifacts" and suffix[2].isdigit())
        )
    )


def _evidence_artifact_ids(value: str) -> tuple[int, int] | None:
    """Return the immutable Actions run and artifact IDs from an evidence URL."""
    parsed = urlparse(value)
    prefix = f"/{GITHUB_REPOSITORY}/actions/runs/"
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query:
        return None
    suffix = (
        parsed.path[len(prefix) :].strip("/").split("/") if parsed.path.startswith(prefix) else []
    )
    if len(suffix) != 3 or suffix[1] != "artifacts":
        return None
    if not suffix[0].isdigit() or not suffix[2].isdigit():
        return None
    run_id, artifact_id = int(suffix[0]), int(suffix[2])
    return (run_id, artifact_id) if run_id > 0 and artifact_id > 0 else None


def _github_json(url: str) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch immutable Actions metadata; failures are evidence failures."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "GitHub returned a non-object response"
    return payload, None


def _github_bytes(url: str) -> tuple[bytes | None, str | None]:
    """Download immutable artifact contents; failures are evidence failures."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read(), None
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        return None, str(exc)


def _verify_attestation(  # noqa: C901 - provenance and execution binding stay together
    item: dict[str, Any],
    *,
    evidence_where: str,
    artifact_id: int,
) -> list[str]:
    """Prove the artifact contains the claimed control's executed test manifest."""
    attestation = item.get("attestation")
    if not isinstance(attestation, dict):
        return [f"{evidence_where} is missing its executed-test attestation"]
    file_name = attestation.get("file")
    manifest_sha = attestation.get("sha256")
    if (
        not isinstance(file_name, str)
        or not file_name
        or Path(file_name).name != file_name
        or (
            manifest_sha is not None
            and (not isinstance(manifest_sha, str) or not SHA256_RE.fullmatch(manifest_sha))
        )
    ):
        return [
            f"{evidence_where}.attestation must name a file and optional SHA-256 manifest digest"
        ]

    archive, failure = _github_bytes(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/artifacts/{artifact_id}/zip"
    )
    if archive is None:
        return [f"{evidence_where} could not download artifact {artifact_id}: {failure}"]
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            manifest = bundle.read(file_name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return [f"{evidence_where} artifact has no readable {file_name}: {exc}"]
    errors: list[str] = []
    if (
        isinstance(manifest_sha, str)
        and hashlib.sha256(manifest).hexdigest() != manifest_sha.lower()
    ):
        errors.append(f"{evidence_where}.attestation.sha256 does not match its artifact file")
        return errors
    try:
        payload = json.loads(manifest)
    except json.JSONDecodeError as exc:
        return [f"{evidence_where} attestation is not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return [f"{evidence_where} attestation must be a JSON object"]
    if payload.get("control_id") != item["control_id"]:
        errors.append(f"{evidence_where} attestation names the wrong control")
    if payload.get("release_digest") != item["release_digest"]:
        errors.append(f"{evidence_where} attestation is not bound to the evidence release digest")
    if payload.get("control_refs") != item["control_refs"]:
        errors.append(f"{evidence_where} attestation control_refs do not match the claim")
    if payload.get("test_refs") != item["test_refs"]:
        errors.append(f"{evidence_where} attestation test_refs do not match the claim")
    tests = payload.get("tests")
    if (
        not isinstance(tests, list)
        or [test.get("ref") for test in tests if isinstance(test, dict)] != item["test_refs"]
    ):
        errors.append(f"{evidence_where} attestation does not enumerate every claimed test")
    if payload.get("result") != "passed" or any(
        not isinstance(test, dict) or test.get("result") != "passed" or test.get("exit_code") != 0
        for test in tests or []
    ):
        errors.append(f"{evidence_where} attestation does not prove passing test execution")
    return errors


def _resolve_workflow_artifact(  # noqa: C901 - fail-closed lookup stays together
    item: dict[str, Any], *, evidence_where: str, workflow_ref: str
) -> tuple[dict[str, Any] | None, int | None, int | None, list[str]]:
    """Resolve the artifact produced for a commit-bound workflow locator.

    The locator is committed before the Actions run exists. Resolving by the
    exact head SHA and deterministic artifact name preserves that provenance
    without requiring a post-run registry edit that would change the digest.
    """
    locator = _workflow_locator(item["url"])
    if locator is None:
        return None, None, None, []
    locator_digest, locator_ref = locator
    errors: list[str] = []
    if locator_digest != item["release_digest"]:
        errors.append(f"{evidence_where}.url is not bound to the evidence release digest")
    if locator_ref != workflow_ref:
        errors.append(f"{evidence_where}.url does not identify workflow_ref")
    workflow_name = Path(workflow_ref).name
    runs_url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/"
        f"{quote(workflow_name)}/runs?head_sha={quote(item['release_digest'])}&per_page=100"
    )
    runs_payload, failure = _github_json(runs_url)
    if runs_payload is None:
        errors.append(f"{evidence_where} could not list workflow runs: {failure}")
        return None, None, None, errors
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        errors.append(f"{evidence_where} workflow run listing is malformed")
        return None, None, None, errors
    matching_runs = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == item["release_digest"]
        and run.get("path") == workflow_ref
    ]
    if not matching_runs:
        errors.append(f"{evidence_where} has no workflow run for the evidence release digest")
        return None, None, None, errors
    successful_runs = [
        run
        for run in matching_runs
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]
    if not successful_runs:
        errors.append(f"{evidence_where} workflow run did not complete successfully")
        return None, None, None, errors

    artifact_name = f"compliance-evidence-{item['release_digest']}"
    for run in successful_runs:
        run_id = run.get("id")
        if not isinstance(run_id, int) or run_id <= 0:
            continue
        artifacts_url = (
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/runs/{run_id}/artifacts"
            f"?name={quote(artifact_name)}&per_page=100"
        )
        payload, failure = _github_json(artifacts_url)
        if payload is None:
            errors.append(
                f"{evidence_where} could not list artifacts for workflow run {run_id}: {failure}"
            )
            continue
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append(f"{evidence_where} artifact listing is malformed")
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("name") != artifact_name:
                continue
            artifact_id = artifact.get("id")
            if isinstance(artifact_id, int) and artifact_id > 0:
                return artifact, run_id, artifact_id, errors
    errors.append(f"{evidence_where} has no artifact named {artifact_name}")
    return None, None, None, errors


def _verify_artifact_evidence(  # noqa: C901 - fail-closed provenance checks stay together
    item: dict[str, Any], *, evidence_where: str, workflow_ref: str
) -> list[str]:
    """Prove a green claim names a real, unexpired artifact from its release run."""
    errors: list[str] = []
    artifact_ids = _evidence_artifact_ids(item["url"])
    if artifact_ids is not None:
        run_id, artifact_id = artifact_ids
        api_url = (
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/artifacts/{artifact_id}"
        )
        artifact, failure = _github_json(api_url)
        if artifact is None:
            return [f"{evidence_where} could not verify GitHub artifact {artifact_id}: {failure}"]
        workflow_run = artifact.get("workflow_run")
        if not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id:
            errors.append(f"{evidence_where} artifact does not belong to the URL's workflow run")
        run_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/runs/{run_id}"
        run, failure = _github_json(run_url)
        if run is None:
            errors.append(f"{evidence_where} could not verify workflow run {run_id}: {failure}")
        else:
            if run.get("head_sha") != item["release_digest"]:
                errors.append(
                    f"{evidence_where} workflow run is not for the evidence release digest"
                )
            if run.get("path") != workflow_ref:
                errors.append(f"{evidence_where} workflow run does not match workflow_ref")
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                errors.append(f"{evidence_where} workflow run did not complete successfully")
    elif _workflow_locator(item["url"]) is None:
        return [
            f"{evidence_where}.url must identify an immutable GitHub Actions artifact "
            "or commit-bound workflow locator for implemented status"
        ]
    else:
        artifact, run_id, artifact_id, resolution_errors = _resolve_workflow_artifact(
            item, evidence_where=evidence_where, workflow_ref=workflow_ref
        )
        errors.extend(resolution_errors)
        if artifact is None or run_id is None or artifact_id is None:
            return errors

    workflow_name = Path(workflow_ref).name
    workflow_url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/{quote(workflow_name)}"
    )
    workflow, failure = _github_json(workflow_url)
    if workflow is None:
        errors.append(
            f"{evidence_where} could not verify live workflow state for {workflow_ref}: {failure}"
        )
    elif workflow.get("state") != "active":
        errors.append(
            f"{evidence_where} workflow {workflow_ref} is not active in GitHub Actions "
            f"(state={workflow.get('state')!r})"
        )

    if artifact.get("expired") is not False:
        errors.append(f"{evidence_where} artifact is expired or has no expiry state")
    digest = artifact.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        errors.append(f"{evidence_where} artifact has no GitHub SHA-256 digest")
    elif (
        item["sha256"] is not None
        and digest.removeprefix("sha256:").lower() != item["sha256"].lower()
    ):
        errors.append(f"{evidence_where}.sha256 does not match the GitHub artifact digest")
    errors.extend(
        _verify_attestation(
            item,
            evidence_where=evidence_where,
            artifact_id=artifact_id,
        )
    )
    return errors


def _workflow_state(workflow_ref: str, root: Path) -> tuple[bool, bool] | None:
    """Derive whether a workflow can run automatically from its checked-in YAML."""
    path = root / workflow_ref
    try:
        source = path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(source)
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(workflow, dict):
        return None
    # PyYAML's YAML 1.1 loader parses the GitHub Actions ``on`` key as True.
    trigger_config = workflow.get("on", workflow.get(True))
    if isinstance(trigger_config, str):
        triggers = {trigger_config}
    elif isinstance(trigger_config, (list, dict)):
        triggers = {value for value in trigger_config if isinstance(value, str)}
    else:
        return None
    manual_only = triggers == {"workflow_dispatch"}
    header = "\n".join(source.splitlines()[:20]).lower()
    explicitly_disabled = any(
        phrase in header
        for phrase in (
            "temporarily disabled",
            "explicitly disabled",
            "disabled until",
            "do not run automatically",
        )
    )
    return not manual_only and not explicitly_disabled, manual_only


def _git_commit_exists(digest: str, root: Path) -> bool:
    """Check release provenance when the checkout contains a Git object database."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{digest}^{{commit}}"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _local_ref_exists(value: str, root: Path) -> bool:
    if _is_link(value):
        return True
    return (root / value).is_file()


def _is_executable_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(
        ("packages/", "scripts/", "formal/", "tests/", ".github/workflows/")
    )


def _is_test_ref(value: Any) -> bool:
    """Accept only repository paths that identify a runnable test module."""
    if not _is_executable_ref(value) or not isinstance(value, str):
        return False
    path = Path(value)
    return (
        path.suffix == ".py"
        and path.name.startswith("test_")
        and (value.startswith("tests/") or "/tests/" in value or value.startswith("formal/"))
    )


def validate_registry(  # noqa: C901 - this is the single fail-closed schema/evidence gate
    registry: Any,
    *,
    root: Path = ROOT,
    today: dt.date | None = None,
    release_digest: str | None = None,
    require_release_evidence: bool = False,
) -> list[str]:
    """Return schema and evidence errors, verifying green artifacts with GitHub."""
    errors: list[str] = []
    today = today or dt.date.today()
    if not isinstance(registry, dict):
        return ["registry must be a JSON object"]
    unknown_registry_fields = set(registry) - REQUIRED_REGISTRY_FIELDS
    missing_registry_fields = REQUIRED_REGISTRY_FIELDS - set(registry)
    if unknown_registry_fields:
        errors.append("registry has unknown fields: " + ", ".join(sorted(unknown_registry_fields)))
    if missing_registry_fields:
        errors.append("registry is missing fields: " + ", ".join(sorted(missing_registry_fields)))
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"registry schema_version must be {SCHEMA_VERSION}")
    registry_digest = registry.get("release_digest")
    if registry_digest is not None and (
        not isinstance(registry_digest, str) or not HEX_DIGEST_RE.fullmatch(registry_digest)
    ):
        errors.append("registry.release_digest must be null or a 40-64 character git digest")
    controls = registry.get("controls")
    if not isinstance(controls, list) or not controls:
        errors.append("registry.controls must be a non-empty list")
        return errors

    seen: set[str] = set()
    for index, control in enumerate(controls):
        where = f"controls[{index}]"
        if not isinstance(control, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = set(control) - REQUIRED_CONTROL_FIELDS
        missing = REQUIRED_CONTROL_FIELDS - set(control)
        if unknown:
            errors.append(f"{where} has unknown fields: {', '.join(sorted(unknown))}")
        if missing:
            errors.append(f"{where} is missing fields: {', '.join(sorted(missing))}")
            continue
        ident = control["id"]
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
            errors.append(f"{where}.id must be an uppercase control ID")
        elif ident in seen:
            errors.append(f"duplicate control ID {ident}")
        else:
            seen.add(ident)
        for field in ("framework", "requirement", "owner", "scope"):
            if not isinstance(control[field], str) or not control[field].strip():
                errors.append(f"{where}.{field} must be a non-empty string")
        status = control["status"]
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(f"{where}.status {status!r} is not a supported status")
        if not isinstance(control["release_required"], bool):
            errors.append(f"{where}.release_required must be boolean")
        for field in ("control_refs", "test_refs", "evidence"):
            if not isinstance(control[field], list):
                errors.append(f"{where}.{field} must be a list")
        refs = control["control_refs"]
        if isinstance(refs, list):
            if not refs:
                errors.append(f"{where}.control_refs must not be empty")
            for ref in refs:
                if not isinstance(ref, str) or not _local_ref_exists(ref, root):
                    errors.append(f"{where}.control_refs contains a missing reference: {ref!r}")
        test_refs = control["test_refs"]
        if isinstance(test_refs, list):
            for ref in test_refs:
                if not isinstance(ref, str) or not _local_ref_exists(ref, root):
                    errors.append(f"{where}.test_refs contains a missing reference: {ref!r}")
                elif not _is_test_ref(ref):
                    errors.append(
                        f"{where}.test_refs contains a non-test executable reference: {ref!r}"
                    )
        last_verified = _date(control["last_verified"], "last_verified", where, errors)
        expires = _date(control["expires"], "expires", where, errors)
        if last_verified is not None and last_verified > today:
            errors.append(f"{ident} has a future last_verified date ({control['last_verified']})")
        if expires is not None and last_verified is not None and expires < last_verified:
            errors.append(f"{ident} expires before it was last verified")
        if expires is not None and expires < today and status == "implemented":
            errors.append(f"{ident} has expired evidence ({control['expires']})")
        if (
            isinstance(status, str)
            and status in {"implemented", "partially_implemented", "documented"}
            and last_verified is None
        ):
            errors.append(f"{ident} requires last_verified for status {status}")
        evidence = control["evidence"]
        observed_dates: list[dt.date] = []
        if isinstance(evidence, list):
            for evidence_index, item in enumerate(evidence):
                evidence_where = f"{where}.evidence[{evidence_index}]"
                if not isinstance(item, dict):
                    errors.append(f"{evidence_where} must be an object")
                    continue
                evidence_missing = REQUIRED_EVIDENCE_FIELDS - set(item)
                evidence_unknown = set(item) - REQUIRED_EVIDENCE_FIELDS - OPTIONAL_EVIDENCE_FIELDS
                if evidence_unknown:
                    errors.append(
                        f"{evidence_where} has unknown fields: {', '.join(sorted(evidence_unknown))}"
                    )
                if evidence_missing:
                    errors.append(
                        f"{evidence_where} is missing fields: {', '.join(sorted(evidence_missing))}"
                    )
                    continue
                if item["control_id"] != ident:
                    errors.append(f"{evidence_where}.control_id does not match control ID {ident}")
                for field in ("control_refs", "test_refs"):
                    refs = item[field]
                    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                        errors.append(f"{evidence_where}.{field} must be a list of strings")
                    elif refs != control[field]:
                        errors.append(f"{evidence_where}.{field} is not bound to control {ident}")
                if not isinstance(item["url"], str) or not _is_immutable_evidence_link(item["url"]):
                    errors.append(
                        f"{evidence_where}.url must be an immutable GitHub Actions run or artifact link"
                    )
                workflow_ref = item["workflow_ref"]
                if (
                    not isinstance(workflow_ref, str)
                    or not workflow_ref.startswith(".github/workflows/")
                    or not _local_ref_exists(workflow_ref, root)
                ):
                    errors.append(f"{evidence_where}.workflow_ref must name an existing workflow")
                for field in ("workflow_enabled", "manual_only", "ran"):
                    if not isinstance(item[field], bool):
                        errors.append(f"{evidence_where}.{field} must be boolean")
                if isinstance(workflow_ref, str) and _local_ref_exists(workflow_ref, root):
                    workflow_state = _workflow_state(workflow_ref, root)
                    if workflow_state is None:
                        errors.append(f"{evidence_where} cannot derive workflow execution state")
                    else:
                        actual_enabled, actual_manual_only = workflow_state
                        if item["workflow_enabled"] != actual_enabled:
                            errors.append(
                                f"{evidence_where}.workflow_enabled does not match the workflow"
                            )
                        if item["manual_only"] != actual_manual_only:
                            errors.append(
                                f"{evidence_where}.manual_only does not match the workflow"
                            )
                if not (
                    isinstance(item["sha256"], str) and SHA256_RE.fullmatch(item["sha256"])
                ) and not (item["sha256"] is None and _workflow_locator(item["url"]) is not None):
                    errors.append(
                        f"{evidence_where}.sha256 must be a 64 character SHA-256 digest, "
                        "or null for a commit-bound workflow locator"
                    )
                evidence_digest = item["release_digest"]
                if not isinstance(evidence_digest, str) or not HEX_DIGEST_RE.fullmatch(
                    evidence_digest
                ):
                    errors.append(f"{evidence_where}.release_digest must be a git digest")
                observed_at = _date(item["observed_at"], "observed_at", evidence_where, errors)
                if observed_at is not None:
                    observed_dates.append(observed_at)
                if observed_at is not None and observed_at > today:
                    errors.append(f"{evidence_where}.observed_at cannot be in the future")
                if (
                    status == "implemented"
                    and observed_at is not None
                    and today - observed_at > MAX_EVIDENCE_AGE
                ):
                    errors.append(
                        f"{ident} has stale evidence ({item['observed_at']}); "
                        f"evidence is limited to {MAX_EVIDENCE_AGE.days} days"
                    )
                if not isinstance(item["result"], str) or item["result"] not in {
                    "passed",
                    "failed",
                }:
                    errors.append(f"{evidence_where}.result must be 'passed' or 'failed'")
                if status == "implemented":
                    if item.get("result") != "passed":
                        errors.append(
                            f"{ident} has non-passing evidence supporting implemented status"
                        )
                    if not item.get("workflow_enabled"):
                        errors.append(
                            f"{ident} has disabled workflow evidence supporting implemented status"
                        )
                    if item.get("manual_only"):
                        errors.append(
                            f"{ident} has manual-only evidence supporting implemented status"
                        )
                    if not item.get("ran"):
                        errors.append(
                            f"{ident} has never-run evidence supporting implemented status"
                        )
                    if (
                        isinstance(item.get("url"), str)
                        and _is_immutable_evidence_link(item["url"])
                        and isinstance(workflow_ref, str)
                        and isinstance(item.get("release_digest"), str)
                        and (
                            (
                                isinstance(item.get("sha256"), str)
                                and SHA256_RE.fullmatch(item["sha256"])
                            )
                            or (
                                item.get("sha256") is None
                                and _workflow_locator(item["url"]) is not None
                            )
                        )
                    ):
                        errors.extend(
                            _verify_artifact_evidence(
                                item,
                                evidence_where=evidence_where,
                                workflow_ref=workflow_ref,
                            )
                        )
                if registry_digest and evidence_digest != registry_digest:
                    errors.append(f"{ident} evidence is not bound to registry.release_digest")
        if (
            status == "implemented"
            and isinstance(registry_digest, str)
            and HEX_DIGEST_RE.fullmatch(registry_digest)
            and not _git_commit_exists(registry_digest, root)
        ):
            errors.append(f"{ident} release_digest does not name a commit in this checkout")
        if (
            status == "implemented"
            and last_verified is not None
            and observed_dates
            and last_verified != max(observed_dates)
        ):
            errors.append(f"{ident}.last_verified must match the newest evidence observation")
        if status == "implemented":
            if not registry_digest:
                errors.append(f"{ident} is implemented but has no release digest")
            if not control["evidence"]:
                errors.append(f"{ident} is implemented but has no immutable evidence")
            if not control["test_refs"]:
                errors.append(f"{ident} is implemented but has no executable test reference")
            if not any(_is_executable_ref(ref) for ref in control["control_refs"]):
                errors.append(f"{ident} is implemented but has no executable control reference")
            if not any(_is_test_ref(ref) for ref in control["test_refs"]):
                errors.append(f"{ident} is implemented but has no executable test reference")
            if expires is not None and expires < today:
                errors.append(f"{ident} is implemented but its evidence expiry has passed")
        if require_release_evidence and control["release_required"]:
            if status != "implemented":
                errors.append(
                    f"release evidence is incomplete: {ident} is {status}, not implemented"
                )
            if not registry_digest:
                errors.append(
                    f"release evidence is missing: registry has no release_digest for {ident}"
                )
            if not control["evidence"]:
                errors.append(f"release evidence is missing: {ident} has no evidence")

    if require_release_evidence:
        if not release_digest:
            errors.append("--release-digest is required when release evidence is required")
        elif not HEX_DIGEST_RE.fullmatch(release_digest):
            errors.append("--release-digest must be a 40-64 character git digest")
        elif registry_digest != release_digest:
            errors.append("registry.release_digest does not match --release-digest")
    return errors


def _table_rows(document: str) -> tuple[list[tuple[str, ...]], list[str]]:
    errors: list[str] = []
    if BEGIN_MARKER not in document or END_MARKER not in document:
        return [], ["COMPLIANCE.md is missing the compliance registry markers"]
    body = document.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) < 3:
        return [], ["compliance registry table is incomplete"]
    if not (lines[0].startswith("|") and lines[0].endswith("|")):
        errors.append("compliance registry table has no header row")
        return [], errors
    header = tuple(cell.strip() for cell in lines[0][1:-1].split("|"))
    if header != TABLE_HEADER:
        errors.append(f"compliance registry header must be {TABLE_HEADER!r}")
    separator = (
        tuple(cell.strip() for cell in lines[1][1:-1].split("|"))
        if lines[1].startswith("|")
        else ()
    )
    if len(separator) != len(TABLE_HEADER) or any(
        not set(cell) <= {"-", ":"} for cell in separator
    ):
        errors.append("compliance registry has a malformed separator row")
    rows: list[tuple[str, ...]] = []
    for line_number, line in enumerate(lines[2:], start=3):
        if not (line.startswith("|") and line.endswith("|")):
            errors.append(f"compliance registry line {line_number} is not a table row")
            continue
        cells = tuple(cell.strip() for cell in line[1:-1].split("|"))
        if len(cells) != len(TABLE_HEADER):
            errors.append(
                f"compliance registry line {line_number} has {len(cells)} cells; expected {len(TABLE_HEADER)}"
            )
            continue
        rows.append(cells)
    return rows, errors


def validate_document(document: str, registry: Any) -> list[str]:
    rows, errors = _table_rows(document)
    controls = registry.get("controls", []) if isinstance(registry, dict) else []
    by_id = {control.get("id"): control for control in controls if isinstance(control, dict)}
    row_ids: set[str] = set()
    for row in rows:
        ident, framework, claim, status, owner, scope, last_verified, expires, evidence = row
        if ident in row_ids:
            errors.append(f"COMPLIANCE.md repeats control ID {ident}")
        row_ids.add(ident)
        control = by_id.get(ident)
        if control is None:
            errors.append(f"COMPLIANCE.md names unknown control ID {ident}")
            continue
        if not REQUIRED_CONTROL_FIELDS.issubset(control):
            errors.append(f"registry control {ident} is incomplete; document comparison skipped")
            continue
        expected = (
            control["framework"],
            control["requirement"],
            control["status"],
            control["owner"],
            control["scope"],
            control["last_verified"] or "not recorded",
            control["expires"],
            _evidence_cell(control["evidence"]),
        )
        if (framework, claim, status, owner, scope, last_verified, expires, evidence) != expected:
            errors.append(f"COMPLIANCE.md row for {ident} does not match the registry")
        if status == "implemented" and evidence == "none":
            errors.append(f"COMPLIANCE.md marks {ident} implemented without evidence")
    missing = set(by_id) - row_ids
    if missing:
        errors.append(f"COMPLIANCE.md is missing control IDs: {', '.join(sorted(missing))}")
    return errors


def _evidence_cell(evidence: Any) -> str:
    if not evidence:
        return "none"
    cells: list[str] = []
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("url"), str)
            or not (
                isinstance(item.get("sha256"), str)
                or (item.get("sha256") is None and _workflow_locator(item["url"]) is not None)
            )
        ):
            cells.append("invalid")
        elif item["sha256"] is None:
            cells.append(f"[artifact via workflow]({item['url']})")
        else:
            cells.append(f"[{item['sha256'][:12]}]({item['url']})")
    return "; ".join(cells)


def load_registry(path: Path = REGISTRY) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check(
    *,
    registry_path: Path = REGISTRY,
    document_path: Path = DOCUMENT,
    release_digest: str | None = None,
    require_release_evidence: bool = False,
    today: dt.date | None = None,
) -> list[str]:
    try:
        registry = load_registry(registry_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load {registry_path}: {exc}"]
    errors = validate_registry(
        registry,
        root=registry_path.parents[1],
        today=today,
        release_digest=release_digest,
        require_release_evidence=require_release_evidence,
    )
    try:
        document = document_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [*errors, f"cannot load {document_path}: {exc}"]
    return [*errors, *validate_document(document, registry)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--document", type=Path, default=DOCUMENT)
    parser.add_argument("--release-digest", help="exact commit digest being released")
    parser.add_argument(
        "--require-release-evidence",
        action="store_true",
        help="require every release-required control to have current passing evidence",
    )
    args = parser.parse_args(argv)
    errors = check(
        registry_path=args.registry,
        document_path=args.document,
        release_digest=args.release_digest,
        require_release_evidence=args.require_release_evidence,
    )
    if errors:
        print(f"compliance check FAILED ({len(errors)} problem(s))", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("compliance registry and COMPLIANCE.md are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
