"""The extension certification pipeline and its report (M9-H3, #975).

`certify` turns (source tree, artifact bytes) into one truthful document:
it validates the package structure, runs the static security checks,
executes the conformance suite over the source tree, digests the exact
artifact bytes, optionally signs, and decides. The decision rule is the
honesty rule:

- a **failed** check or a **failed** conformance case declines
  certification, and names itself in ``decline_reasons``;
- a **skipped** required check declines certification (a skip is an
  unexecuted property, and certification cannot claim what did not
  execute);
- under the ``strict`` profile every skip *and* every not-applicable check
  declines; under ``standard`` an explicit, recorded backend waiver is
  allowed, and the waived property is listed under ``not_proven``;
- ``claims`` — the properties this certification asserts — are built
  **only** from checks and conformance cases that actually executed and
  passed. A property whose test did not execute is structurally unable to
  become a claim.

One claim is never available at all, under any profile: platform
certification. No sandbox ran, no tenant policy was evaluated, and no
canonical ``Goal -> Graph -> Run -> NodeRun -> Attempt`` execution was
created by a local certification run — the report says so as data, and the
install lifecycle consumes the report as *evidence*, never as
authorization by itself.

The signature covers a canonical payload of (extension id, version,
package sha256, manifest sha256) — so later package mutation breaks the
digest, the digest breaks the signature, and `verify_certification`
detects both.
"""

from __future__ import annotations

import hashlib
import json
import platform
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.metadata import version as _metadata_version
from pathlib import Path
from typing import Any

from maistro_ext_harness.backends import BackendRegistry
from maistro_ext_harness.checks import CheckRecord, CheckStatus
from maistro_ext_harness.contract import (
    CERTIFICATION_SCHEMA,
    CONTRACT_VERSION,
    PLATFORM_NOTE,
    SUPPORTED_CONTRACT_MAJORS,
)
from maistro_ext_harness.grants import GrantPolicy
from maistro_ext_harness.manifest import ExtensionManifest
from maistro_ext_harness.packaging import ArtifactInfo, inspect_artifact, inspect_source_tree
from maistro_ext_harness.runner import HARNESS_VERSION, RunRequest, run_conformance
from maistro_ext_harness.security import security_checks
from maistro_ext_harness.signing import canonical_certification_payload, sign_payload

__all__ = [
    "CertificationProfile",
    "CertificationReport",
    "CertificationRequest",
    "VerificationResult",
    "certify",
    "verify_certification",
]


class CertificationProfile(StrEnum):
    """How much a run must execute before it may say 'certified'."""

    #: Recorded backend waivers are allowed; every waived property is named
    #: under ``not_proven`` and appears in no claim.
    STANDARD = "standard"
    #: No skips, no waivers, no not-applicable checks: a strict run proves
    #: everything it reports, or it declines.
    STRICT = "strict"

    @property
    def declines_skips(self) -> bool:
        return self is CertificationProfile.STRICT


@dataclass(frozen=True)
class CertificationRequest:
    """What to certify: a source tree, its built artifact, how strictly."""

    subject: Path
    artifact: Path
    profile: CertificationProfile = CertificationProfile.STANDARD
    #: Ed25519 private seed, hex. ``None`` produces an unsigned report —
    #: recorded as ``signed: false`` with that reason, never as a silent
    #: absence.
    signing_key_hex: str | None = None
    with_reference: bool = False
    policy: GrantPolicy | None = None
    backends: BackendRegistry | None = None


@dataclass
class CertificationReport:
    """The certification result document. Serialize with `to_dict`."""

    schema: str
    profile: str
    harness_version: str
    contract_version: str
    supported_contract_majors: tuple[int, ...]
    sdk_package_version: str | None
    environment: dict[str, str]
    subject: dict[str, Any]
    artifact: dict[str, Any] | None
    checks: list[CheckRecord] = field(default_factory=list)
    conformance_executed: bool = True
    conformance_reason: str | None = None
    conformance_report: dict[str, Any] | None = None
    signature: dict[str, Any] = field(default_factory=dict)
    certified: bool = False
    decline_reasons: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    not_proven: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """The report's JSON shape — versioned by `CERTIFICATION_SCHEMA`."""
        return {
            "certification_schema": self.schema,
            "profile": self.profile,
            "tooling": {
                "harness_version": self.harness_version,
                "contract_version": self.contract_version,
                "supported_contract_majors": list(self.supported_contract_majors),
                "sdk_package_version": self.sdk_package_version,
            },
            "environment": dict(self.environment),
            "subject": dict(self.subject),
            "artifact": self.artifact,
            "checks": [check.to_dict() for check in self.checks],
            "conformance": {
                "executed": self.conformance_executed,
                "reason": self.conformance_reason,
                "report": self.conformance_report,
            },
            "signature": dict(self.signature),
            "decision": {
                "certified": self.certified,
                "decline_reasons": list(self.decline_reasons),
                "claims": list(self.claims),
                "not_proven": list(self.not_proven),
                "platform_note": PLATFORM_NOTE,
            },
        }

    def write_json(self, path: Path) -> Path:
        """Write the machine-readable report; parents are created."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def human_summary(self) -> str:
        """The CI-log-friendly, human-readable summary."""
        signature = self.signature
        signed = (
            f"ed25519, public key {str(signature.get('public_key', ''))[:16]}…"
            if signature.get("signed")
            else f"unsigned ({signature.get('reason', 'no key supplied')})"
        )
        lines = [
            f"certification: {'CERTIFIED' if self.certified else 'DECLINED'} "
            f"(profile {self.profile})",
            f"  subject:   {self.subject.get('id')} {self.subject.get('version')} "
            f"({self.subject.get('family')}, contract {self.subject.get('contract_range')})",
            "  artifact:  "
            + (
                f"{self.artifact['filename']} sha256:{self.artifact['sha256'][:16]}…"
                if self.artifact
                else "n/a"
            ),
            f"  tooling:   harness {self.harness_version}, contract "
            f"{self.contract_version}, sdk {self.sdk_package_version or 'not installed'}",
            f"  signature: {signed}",
            f"  decision:  {len(self.claims)} proven, {len(self.not_proven)} not proven, "
            f"{len(self.decline_reasons)} decline reason(s)",
        ]
        for reason in self.decline_reasons:
            lines.append(f"  DECLINE: {reason}")
        for check in self.checks:
            if check.status is CheckStatus.FAILED:
                lines.append(f"  FAIL {check.check_id}: {check.detail}")
            elif check.status in (CheckStatus.SKIPPED, CheckStatus.NOT_APPLICABLE):
                lines.append(f"  {check.status.value.upper()} {check.check_id}: {check.detail}")
        if not self.conformance_executed:
            lines.append(f"  conformance did NOT execute: {self.conformance_reason}")
        return "\n".join(lines)


def _sdk_package_version() -> str | None:
    """The installed SDK distribution's version, if any.

    Reading *metadata* is not importing the module: the harness stays
    stdlib-only, and the SDK version is recorded as observed provenance —
    what was actually installed in the certifying environment.
    """
    try:
        return _metadata_version("maistro-ext-sdk")
    except Exception:
        return None


def _environment(profile: CertificationProfile) -> dict[str, str]:
    """The environment that executed the certification, recorded truthfully.

    Unlike the conformance report (deliberately byte-stable across hosts), a
    certification is evidence about *a run*: which interpreter, which
    platform, which profile. Same environment in, same bytes out.
    """
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": f"{platform.system()}/{platform.machine()}",
        "profile": profile.value,
    }


def _subject_record(manifest: ExtensionManifest) -> dict[str, Any]:
    return {
        "id": manifest.id,
        "publisher": manifest.publisher,
        "version": manifest.version,
        "title": manifest.title,
        "family": manifest.family,
        "contract_range": manifest.contract,
        "capabilities": list(manifest.capabilities),
        "effects": list(manifest.effects),
    }


@dataclass
class _Pipeline:
    """The certification run's accumulators, threaded through the stages."""

    request: CertificationRequest
    checks: list[CheckRecord] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    not_proven: list[str] = field(default_factory=list)
    decline_reasons: list[str] = field(default_factory=list)
    manifest: ExtensionManifest | None = None
    artifact_info: ArtifactInfo | None = None
    conformance_executed: bool = False
    conformance_reason: str | None = None
    conformance_report: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.not_proven.append(f"platform certification: {PLATFORM_NOTE}")


def _structural_stage(pipeline: _Pipeline) -> None:
    """Source-tree, security, and artifact checks — the static halves."""
    source = inspect_source_tree(pipeline.request.subject)
    pipeline.checks.extend(source.checks)
    pipeline.manifest = source.manifest
    if source.manifest is not None:
        pipeline.checks.extend(
            security_checks(
                pipeline.request.subject,
                entrypoint_module=source.manifest.entrypoint.module,
                declared=source.declared,
            )
        )
    artifact_checks, artifact_info = inspect_artifact(
        pipeline.request.artifact,
        source.manifest,
        project_name=source.project_name,
    )
    pipeline.checks.extend(artifact_checks)
    pipeline.artifact_info = artifact_info


def _verdicts_from_checks(pipeline: _Pipeline) -> None:
    """Turn each check's status into a claim, a decline, or a not-proven."""
    strict = pipeline.request.profile.declines_skips
    for check in pipeline.checks:
        if check.status is CheckStatus.PASSED:
            pipeline.claims.append(f"{check.check_id}: {check.description}")
        elif check.status is CheckStatus.FAILED:
            pipeline.decline_reasons.append(f"check {check.check_id} failed: {check.detail}")
        elif check.status is CheckStatus.SKIPPED:
            if strict or check.required:
                pipeline.decline_reasons.append(
                    f"check {check.check_id} did not execute: {check.detail}"
                )
            else:
                pipeline.not_proven.append(f"{check.check_id}: {check.detail}")
        elif strict:
            pipeline.decline_reasons.append(
                f"check {check.check_id} is not applicable under the strict profile: {check.detail}"
            )
        else:
            pipeline.not_proven.append(f"{check.check_id}: {check.detail}")


def _conformance_stage(pipeline: _Pipeline) -> None:
    """Run the conformance suite (or record, truthfully, that it could not)."""
    manifest = pipeline.manifest
    if manifest is None:
        pipeline.conformance_reason = (
            "the manifest did not parse; conformance cannot run against an "
            "extension the contract already rejects"
        )
        return
    try:
        report = run_conformance(
            RunRequest(
                subject=pipeline.request.subject,
                with_reference=pipeline.request.with_reference,
                policy=pipeline.request.policy,
                backends=pipeline.request.backends,
            )
        )
    except Exception as exc:
        pipeline.conformance_reason = f"{type(exc).__name__}: {exc}"
        return
    pipeline.conformance_executed = True
    pipeline.conformance_report = report.to_dict()
    strict = pipeline.request.profile.declines_skips
    for case in report.cases:
        label = f"conformance {case.subject}:{case.case_id}"
        if case.status.value == "passed":
            pipeline.claims.append(f"{label}: {case.detail}")
        elif case.status.value == "skipped":
            if strict:
                pipeline.decline_reasons.append(
                    f"conformance case {case.subject}:{case.case_id} did not "
                    f"execute under the strict profile: {case.detail}"
                )
            else:
                pipeline.not_proven.append(f"{label}: did NOT execute ({case.detail})")
    for case in report.failed:
        pipeline.decline_reasons.append(
            f"conformance case {case.subject}:{case.case_id} failed: {case.detail}"
        )


def _conformance_verdict(pipeline: _Pipeline) -> None:
    if not pipeline.conformance_executed:
        pipeline.decline_reasons.append(
            "conformance did not execute"
            + (f": {pipeline.conformance_reason}" if pipeline.conformance_reason else "")
        )


def _signing_stage(pipeline: _Pipeline, key_hex: str | None) -> dict[str, Any]:
    """Sign the canonical payload, or record truthfully why nothing was."""
    package_sha = pipeline.artifact_info.sha256 if pipeline.artifact_info else ""
    manifest_sha = pipeline.artifact_info.manifest_sha256 if pipeline.artifact_info else ""
    manifest = pipeline.manifest
    if key_hex is None:
        return {"signed": False, "reason": "no signing key supplied; the report is unsigned"}
    if not package_sha or not manifest_sha:
        return {
            "signed": False,
            "reason": (
                "signing requested but the artifact digests are unavailable "
                "(the artifact did not validate); nothing was signed"
            ),
        }
    payload = canonical_certification_payload(
        extension_id=manifest.id if manifest else "",
        version=manifest.version if manifest else "",
        package_sha256=package_sha,
        manifest_sha256=manifest_sha,
    )
    try:
        public_key, signature_hex = sign_payload(payload, key_hex)
    except Exception as exc:
        return {"signed": False, "reason": f"signing failed: {exc}"}
    return {
        "signed": True,
        "algorithm": "ed25519",
        "key_format": "hex-encoded 32-byte Ed25519 private seed",
        "public_key": public_key,
        "signature": signature_hex,
        "payload": {
            "extension_id": manifest.id if manifest else "",
            "version": manifest.version if manifest else "",
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
        },
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


def certify(request: CertificationRequest) -> CertificationReport:
    """Run the full pipeline: structure, security, conformance, digest, sign."""
    pipeline = _Pipeline(request=request)
    _structural_stage(pipeline)
    _verdicts_from_checks(pipeline)
    _conformance_stage(pipeline)
    _conformance_verdict(pipeline)
    signature = _signing_stage(pipeline, request.signing_key_hex)

    return CertificationReport(
        schema=CERTIFICATION_SCHEMA,
        profile=request.profile.value,
        harness_version=HARNESS_VERSION,
        contract_version=CONTRACT_VERSION,
        supported_contract_majors=SUPPORTED_CONTRACT_MAJORS,
        sdk_package_version=_sdk_package_version(),
        environment=_environment(request.profile),
        subject=(_subject_record(pipeline.manifest) if pipeline.manifest is not None else {}),
        artifact=_artifact_record(pipeline.artifact_info),
        checks=pipeline.checks,
        conformance_executed=pipeline.conformance_executed,
        conformance_reason=pipeline.conformance_reason,
        conformance_report=pipeline.conformance_report,
        signature=signature,
        certified=not pipeline.decline_reasons,
        decline_reasons=pipeline.decline_reasons,
        claims=pipeline.claims,
        not_proven=pipeline.not_proven,
    )


def _artifact_record(info: ArtifactInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "filename": info.filename,
        "sha256": info.sha256,
        "size_bytes": info.size_bytes,
        "manifest_sha256": info.manifest_sha256,
        "top_package": info.top_package,
    }


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of re-deriving a certification from its own bytes."""

    ok: bool
    checked: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


def verify_certification(
    report_path: Path,
    artifact_path: Path,
    publisher_key_hex: str | None = None,
) -> VerificationResult:
    """Re-derive a certification from its own bytes.

    Checks, in order:

    1. the report parses and carries a known certification schema;
    2. the artifact's exact bytes digest to the report's recorded
       ``artifact.sha256`` — later package mutation invalidates the
       certification association here;
    3. the manifest shipped inside the artifact digests to the report's
       ``artifact.manifest_sha256``;
    4. the decision is internally consistent (``certified`` true while
       decline reasons are listed is a corrupt report, and so is a decline
       with no named reason);
    5. a carried signature is bound to the report's own ``subject`` and
       ``artifact`` records (the signed payload must equal them) and
       verifies — against ``publisher_key_hex`` when the consumer pins the
       publisher's key, otherwise against the public key
       recorded in the report (self-consistency only; pinning the key is
       the consumer's policy, evidence is not authorization).
    """
    checked: list[str] = []
    failures: list[str] = []

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerificationResult(ok=False, failures=(f"report unreadable: {exc}",))
    if not isinstance(report, dict):
        return VerificationResult(ok=False, failures=("report is not a JSON object",))

    schema = report.get("certification_schema", "")
    if not str(schema).startswith("maistro-ext-harness/certification@"):
        return VerificationResult(
            ok=False,
            checked=tuple(checked),
            failures=(f"unknown certification schema {schema!r}",),
        )
    checked.append(f"schema {schema}")

    artifact = report.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("sha256"):
        failures.append("report records no artifact digest; nothing binds the bytes")
        return VerificationResult(ok=False, checked=tuple(checked), failures=tuple(failures))

    _check_artifact_digest(artifact, artifact_path, checked, failures)
    _check_manifest_binding(artifact, artifact_path, checked, failures)
    _check_decision_consistency(report, checked, failures)
    _check_signature(report, publisher_key_hex, checked, failures)

    return VerificationResult(
        ok=not failures,
        checked=tuple(checked),
        failures=tuple(failures),
    )


def _check_artifact_digest(
    artifact: dict[str, Any],
    artifact_path: Path,
    checked: list[str],
    failures: list[str],
) -> None:
    """The bytes in hand must digest to the recorded artifact digest."""
    try:
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    except OSError as exc:
        failures.append(f"artifact unreadable: {exc}")
        return
    if digest != artifact.get("sha256"):
        failures.append(
            "artifact bytes changed since certification: report records "
            f"sha256:{artifact.get('sha256')}, the bytes in hand digest to sha256:{digest}"
        )
    else:
        checked.append(f"artifact digest matches ({digest[:16]}…)")


def _shipped_manifest_bytes(artifact: dict[str, Any], artifact_path: Path) -> bytes | None:
    """The discovery manifest as shipped in the artifact, if still readable."""
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            names = archive.namelist()
            top = str(artifact.get("top_package", ""))
            for name in (f"{top}/extension.json", "extension.json"):
                if name in names:
                    return archive.read(name)
    except (zipfile.BadZipFile, OSError):
        return None
    return None


def _check_manifest_binding(
    artifact: dict[str, Any],
    artifact_path: Path,
    checked: list[str],
    failures: list[str],
) -> None:
    """The manifest shipped inside the artifact must still be the certified one."""
    manifest_sha = str(artifact.get("manifest_sha256", ""))
    if not manifest_sha:
        failures.append("report records no manifest digest; the association is incomplete")
        return
    shipped = _shipped_manifest_bytes(artifact, artifact_path)
    if shipped is None and not artifact_path.is_file():
        failures.append("artifact unreadable or no longer a zip archive")
        return
    if shipped is None:
        failures.append("artifact no longer ships the discovery manifest")
        return
    if hashlib.sha256(shipped).hexdigest() != manifest_sha:
        failures.append(
            "the shipped manifest changed since certification (manifest_sha256 mismatch)"
        )
    else:
        checked.append("shipped manifest digest matches")


def _check_decision_consistency(
    report: dict[str, Any], checked: list[str], failures: list[str]
) -> None:
    """`certified` and the decline reasons must tell the same story."""
    decision = report.get("decision", {})
    certified = decision.get("certified")
    decline_reasons = decision.get("decline_reasons", [])
    if certified is True and decline_reasons:
        failures.append("report claims certified while listing decline reasons — corrupt report")
    elif certified is False and not decline_reasons:
        failures.append("report declines certification without naming a reason")
    else:
        checked.append(f"decision consistent (certified={certified})")


def _check_signature(
    report: dict[str, Any],
    publisher_key_hex: str | None,
    checked: list[str],
    failures: list[str],
) -> None:
    """A carried signature must cover the report's subject/artifact records;
    an unsigned report fails when the consumer pinned a publisher key.

    The payload is re-derived from the top-level ``subject`` and ``artifact``
    records — the same records the digest and manifest checks validate
    against the bytes in hand — and the signed ``signature.payload`` copy
    must equal them. A signature therefore certifies exactly the supplied
    artifact, not whatever an intermediary typed into the payload block.
    """
    signature = report.get("signature", {})
    if not signature.get("signed"):
        if publisher_key_hex is not None:
            failures.append(
                "report is unsigned; a publisher key was supplied but there is no "
                "signature to verify"
            )
        return
    subject = report.get("subject") or {}
    artifact = report.get("artifact") or {}
    payload_fields = {
        "extension_id": str(subject.get("id", "")),
        "version": str(subject.get("version", "")),
        "package_sha256": str(artifact.get("sha256", "")),
        "manifest_sha256": str(artifact.get("manifest_sha256", "")),
    }
    signed_fields = signature.get("payload", {})
    if not isinstance(signed_fields, dict) or any(
        str(signed_fields.get(name, "")) != value for name, value in payload_fields.items()
    ):
        failures.append(
            "signature payload does not match the report's subject/artifact "
            "records; the signature does not cover the supplied artifact"
        )
        return
    payload = canonical_certification_payload(**payload_fields)
    if hashlib.sha256(payload).hexdigest() != signature.get("payload_sha256"):
        failures.append("signature payload does not re-derive from the report's own fields")
        return
    from maistro_ext_harness.signing import verify_payload

    key = publisher_key_hex or signature.get("public_key", "")
    if verify_payload(payload, str(signature.get("signature", "")), str(key)):
        checked.append(
            "signature verifies against the supplied publisher key"
            if publisher_key_hex
            else (
                "signature verifies against the report's own public key "
                "(self-consistency; pin the publisher key to authenticate)"
            )
        )
    else:
        failures.append(
            "signature does not verify"
            + (" against the supplied publisher key" if publisher_key_hex else "")
        )
