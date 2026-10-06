"""Pre-publication certification: validate, sign, report truthfully (#975, M9-H3).

Each test pins one acceptance criterion of the issue against reachable
production behavior:

- a report cannot claim a property whose test did not execute (claims are
  earned only by a check that ran and passed);
- the signed digest corresponds exactly to the certified package bytes
  (real Ed25519 signatures over the report digest, whose subject digests
  cover the framed bundle);
- certification records extension/version/publisher/SDK and the test
  environment;
- required skipped checks cause certification failure under the relevant
  profile (publication without executed suites refuses);
- later package mutation invalidates the signature/certification
  association (any flipped byte in manifest, artifact or sources);
- the install lifecycle consumes certification as trust *evidence* — the
  inspect step accepts it and still parks the record in
  AWAITING_AUTHORIZATION, never skipping the operator decision.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from maistro.extensions import (
    CONFORMANCE_CHECK_ID,
    SECURITY_SCAN_CHECK_ID,
    STRUCTURE_CHECK_ID,
    MANIFEST_PROFILE,
    PUBLICATION_PROFILE,
    CertificationEnvironment,
    CertificationInvalid,
    CertificationPackageMismatch,
    CertificationProfile,
    CertificationReport,
    CertificationSeal,
    CertificationSubject,
    CheckOutcome,
    CheckResult,
    ConformanceCheck,
    ConformanceOutcome,
    ConformanceSuite,
    DuplicateCheckError,
    EntryPointPresenceCheck,
    ExtensionBundle,
    ImportPolicy,
    PackageStructureCheck,
    PublicImportCheck,
    SecurityScanCheck,
    UnboundCheckError,
    TrustPolicy,
    certification_as_trust_claim,
    certify,
    detect_environment,
    evaluate_trust,
    inspect_manifest,
    report_digest,
    report_from_json,
    report_to_json,
    seal_from_json,
    seal_to_json,
    sha256_hex,
    verify_certification,
    verify_certified_package,
)
from maistro.extensions.certification import render_summary
from maistro.extensions.service import ExtensionInstallService, UnwiredExtensionLoader
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.types import ExtensionPackage, ExtensionScope, ExtensionState, TrustClaim

PUBLISHER = "acme"
EXTENSION_ID = "acme.chart_tools"
VERSION = "1.4.0"
API_VERSION = "1.0.0"

#: A pinned environment: certification must record what it was given, so the
#: tests construct the record directly instead of sampling the host machine.
ENVIRONMENT = CertificationEnvironment(
    sdk_name="maistro-core",
    sdk_version="9.9.9-test",
    certifier_version="1.0.0",
    host="cert-host",
    backend="test-backend",
    python_version="3.12.0",
    platform="test-platform",
    executed_at=datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC),
)

SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-1")

PLUGIN_SOURCE = b"PLUGIN = object()\n"


def manifest_bytes(
    payload: bytes,
    *,
    extension_id: str = EXTENSION_ID,
    version: str = VERSION,
    publisher: str = PUBLISHER,
    api_version: str = API_VERSION,
    entry_module: str = "acme_chart.main",
) -> bytes:
    """A valid manifest whose artifact claim describes ``payload`` exactly."""
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": entry_module, "attribute": "activate"}],
        "artifact": {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
    }
    return json.dumps(document).encode("utf-8")


def make_bundle(
    *,
    payload: bytes = b"extension-payload-v1",
    manifest: bytes | None = None,
    sources: tuple[tuple[str, bytes], ...] = (("acme_chart/main.py", PLUGIN_SOURCE),),
) -> ExtensionBundle:
    """A certifiable bundle whose manifest binds its payload."""
    return ExtensionBundle(
        manifest_bytes=manifest_bytes(payload) if manifest is None else manifest,
        payload=payload,
        sources=sources,
    )


def environment() -> CertificationEnvironment:
    return ENVIRONMENT


class StubCheck:
    """A pre-recorded answer, for summary rendering tests that do not need
    real check semantics (bundle-bound checks must match the certified
    bundle, so foreign-bundle fixtures cannot fake outcomes anymore)."""

    def __init__(self, check_id: str, result: CheckResult) -> None:
        self.check_id = check_id
        self.title = result.title
        self._result = result

    def run(self) -> CheckResult:
        return self._result


class StaticSuite(ConformanceSuite):
    """A conformance suite with a pre-recorded answer."""

    def __init__(self, outcome: ConformanceOutcome) -> None:
        self.outcome = outcome
        self.runs = 0

    @property
    def suite_id(self) -> str:
        return self.outcome.suite_id

    def run(self) -> ConformanceOutcome:
        self.runs += 1
        return self.outcome


def passing_suite(suite_id: str = "chart-render") -> StaticSuite:
    return StaticSuite(
        ConformanceOutcome(
            suite_id=suite_id, passed=True, detail="all cases green", capabilities=("render.svg",)
        )
    )


def publication_checks(bundle: ExtensionBundle, suites: ConformanceSuite) -> tuple:
    """The built-in publication-profile checks over ``bundle``."""
    return (
        PackageStructureCheck(bundle),
        EntryPointPresenceCheck(bundle),
        PublicImportCheck(bundle, ImportPolicy(public_namespaces=frozenset({"maistro"}))),
        SecurityScanCheck(bundle),
        ConformanceCheck(suites=[suites]),
    )


def _policy(key_fingerprint: str) -> TrustPolicy:
    """A trust policy that admits exactly one publisher and one signing key."""
    return TrustPolicy(
        trusted_publishers=frozenset({PUBLISHER}),
        require_signature=True,
        allowed_signer_keys=frozenset({key_fingerprint}),
    )


# ---------------------------------------------------------------------------
# AC: a report cannot claim a property whose test did not execute
# ---------------------------------------------------------------------------


def test_claims_are_earned_only_by_a_pass() -> None:
    declared = ("some.property",)
    executed = {
        outcome: CheckResult(
            check_id="x", title="X", outcome=outcome, detail="", claims=declared
        ).earned_claims
        for outcome in CheckOutcome
    }
    assert executed[CheckOutcome.PASSED] == declared
    for outcome in (CheckOutcome.FAILED, CheckOutcome.SKIPPED, CheckOutcome.NOT_APPLICABLE):
        assert executed[outcome] == (), f"{outcome} must earn nothing"


def test_skipped_check_claims_never_reach_the_report() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=CertificationProfile(name="partial", required_checks=()),
        environment=environment(),
        checks=(
            PackageStructureCheck(bundle),
            EntryPointPresenceCheck(bundle),
            PublicImportCheck(bundle, ImportPolicy(public_namespaces=frozenset({"maistro"}))),
            SecurityScanCheck(bundle),
            ConformanceCheck(suites=[]),
        ),
    )
    conformance = next(r for r in report.results if r.check_id == CONFORMANCE_CHECK_ID)
    assert conformance.outcome is CheckOutcome.SKIPPED
    assert conformance.earned_claims == ()
    earned = set(report.certified_claims)
    assert earned, "the executed checks did earn claims"
    assert not any(claim.startswith("conformance.") for claim in earned)


def test_not_applicable_check_claims_do_not_reach_the_report() -> None:
    # No packaged sources: the entrypoints check has no subject and truthfully
    # answers not-applicable — its claim must not appear as earned.
    bundle = make_bundle(sources=())
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle), EntryPointPresenceCheck(bundle)),
    )
    entrypoints = next(r for r in report.results if r.check_id == "entrypoints")
    assert entrypoints.outcome is CheckOutcome.NOT_APPLICABLE
    assert "package.entrypoints-shipped" not in report.certified_claims


def test_duplicate_check_ids_refuse_the_run() -> None:
    bundle = make_bundle()
    with pytest.raises(DuplicateCheckError):
        certify(
            bundle,
            profile=MANIFEST_PROFILE,
            environment=environment(),
            checks=(PackageStructureCheck(bundle), PackageStructureCheck(bundle)),
        )


# ---------------------------------------------------------------------------
# AC: the signed digest corresponds exactly to the certified package bytes
# ---------------------------------------------------------------------------


def test_seal_verifies_over_the_report_it_signed() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    assert seal.signed
    assert report_digest(report) == seal.report_sha256
    assert verify_certification(report, seal) == seal.signer_key_fingerprint


def test_package_digest_binds_every_byte_of_the_bundle() -> None:
    bundle = make_bundle()
    baseline = bundle.digest()
    # Reordering the source list must not change the digest (framing is
    # canonical: sorted paths, length-prefixed).
    reordered = ExtensionBundle(
        manifest_bytes=bundle.manifest_bytes,
        payload=bundle.payload,
        sources=tuple(reversed(bundle.sources)),
    )
    assert reordered.digest() == baseline
    # One flipped byte in any part is a different package.
    assert make_bundle(payload=b"extension-payload-v2").digest() != baseline, (
        "payload mutation must change the digest"
    )
    assert make_bundle(manifest=manifest_bytes(bundle.payload, version="1.4.1")).digest() != (
        baseline
    ), "manifest mutation must change the digest"
    assert make_bundle(sources=(("acme_chart/main.py", b"PLUGIN = 1\n"),)).digest() != baseline, (
        "source mutation must change the digest"
    )


def test_report_edited_after_sealing_is_refused() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    # A doctored report with the version bumped: same key, different bytes.
    forged = CertificationReport(
        format_version=report.format_version,
        profile=report.profile,
        required_checks=report.required_checks,
        subject=CertificationSubject(
            extension_id=report.subject.extension_id,
            version="9.9.9",
            publisher=report.subject.publisher,
            api_version=report.subject.api_version,
            manifest_sha256=report.subject.manifest_sha256,
            artifact_sha256=report.subject.artifact_sha256,
            artifact_size=report.subject.artifact_size,
            package_sha256=report.subject.package_sha256,
        ),
        environment=report.environment,
        results=report.results,
        certified=report.certified,
        refusals=report.refusals,
    )
    with pytest.raises(CertificationInvalid, match="modified after sealing"):
        verify_certification(forged, seal)


def test_seal_by_another_key_is_refused_when_a_key_is_trusted() -> None:
    signer = Ed25519PrivateKey.generate()
    impostor = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    impostor_key = impostor.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    with pytest.raises(CertificationInvalid, match="other than the trusted public key"):
        verify_certification(report, seal, trusted_public_key=impostor_key)


def test_unsigned_seal_proves_nothing() -> None:
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=None,
    )
    assert not seal.signed
    with pytest.raises(CertificationInvalid, match="no signature"):
        verify_certification(report, seal)


def test_verify_refuses_wrong_format_and_status_disagreements() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    bad_seal_format = CertificationSeal(
        format_version="seal:v0",
        report_sha256=seal.report_sha256,
        signer_public_key=seal.signer_public_key,
        signer_key_fingerprint=seal.signer_key_fingerprint,
        signature=seal.signature,
        sealed_at=seal.sealed_at,
    )
    with pytest.raises(CertificationInvalid, match="unsupported seal format"):
        verify_certification(report, bad_seal_format)
    bad_report_format = replace(report, format_version="report:v0")
    with pytest.raises(CertificationInvalid, match="unsupported report format"):
        verify_certification(bad_report_format, seal)
    # A report whose stored status contradicts its own recorded results is
    # refuseable before the signature is even consulted.
    lying = replace(report, certified=False, refusals=("invented",))
    with pytest.raises(CertificationInvalid, match="edited after certification"):
        verify_certification(lying, seal)


def test_verify_refuses_malformed_key_or_signature_material() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    corrupt_key = replace(seal, signer_public_key="not-hex!")
    with pytest.raises(CertificationInvalid, match="not valid hex"):
        verify_certification(report, corrupt_key)
    corrupt_signature = replace(seal, signature="zz-signature")
    with pytest.raises(CertificationInvalid, match="not valid hex"):
        verify_certification(report, corrupt_signature)
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    restored = seal_from_json(seal_to_json(seal))
    assert restored == seal
    assert verify_certification(report, restored) == seal.signer_key_fingerprint


# ---------------------------------------------------------------------------
# AC: certification records extension/version/publisher/SDK + test environment
# ---------------------------------------------------------------------------


def test_report_records_subject_and_environment() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    assert report.subject.extension_id == EXTENSION_ID
    assert report.subject.version == VERSION
    assert report.subject.publisher == PUBLISHER
    assert report.subject.api_version == API_VERSION
    assert report.subject.manifest_sha256 == sha256_hex(bundle.manifest_bytes)
    assert report.subject.artifact_sha256 == sha256_hex(bundle.payload)
    assert report.subject.artifact_size == len(bundle.payload)
    assert report.subject.package_sha256 == bundle.digest()
    assert report.environment == ENVIRONMENT

    payload = json.loads(report_to_json(report))
    assert payload["environment"]["sdk_name"] == "maistro-core"
    assert payload["environment"]["sdk_version"] == "9.9.9-test"
    assert payload["environment"]["backend"] == "test-backend"
    assert payload["subject"]["extension_id"] == EXTENSION_ID
    assert payload["subject"]["publisher"] == PUBLISHER


def test_detect_environment_records_the_running_process() -> None:
    env = detect_environment(backend="ci")
    assert env.sdk_name == "maistro-core"
    assert env.backend == "ci"
    assert env.executed_at.tzinfo is UTC
    assert env.python_version


def test_report_roundtrips_through_json_and_still_verifies() -> None:
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
        signer=signer,
    )
    restored = report_from_json(report_to_json(report))
    assert restored == report
    assert verify_certification(restored, seal)


def test_report_json_refuses_a_hand_edited_status() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    assert report.certified
    payload = json.loads(report_to_json(report))
    payload["certified"] = False
    payload["refusals"] = ["invented refusal"]
    with pytest.raises(CertificationInvalid, match="edited after certification"):
        report_from_json(json.dumps(payload))


# ---------------------------------------------------------------------------
# AC: required skipped checks cause certification failure under the profile
# ---------------------------------------------------------------------------


def test_publication_profile_refuses_without_executed_conformance() -> None:
    suite = passing_suite()
    bundle = make_bundle()
    # The CLI path: no suite object can be supplied, so the conformance check
    # is constructed with none — a skipped required check must refuse, and the
    # declared suite must not have been invoked behind the scenes.
    report, _ = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=(
            PackageStructureCheck(bundle),
            EntryPointPresenceCheck(bundle),
            PublicImportCheck(bundle, ImportPolicy(public_namespaces=frozenset({"maistro"}))),
            SecurityScanCheck(bundle),
            ConformanceCheck(suites=[]),
        ),
    )
    assert not report.certified
    conformance = next(r for r in report.results if r.check_id == CONFORMANCE_CHECK_ID)
    assert conformance.outcome is CheckOutcome.SKIPPED
    assert any(
        "conformance" in refusal and "did not pass" in refusal for refusal in report.refusals
    )
    assert suite.runs == 0, "a suite nobody supplied cannot have executed"


def test_certify_refuses_a_check_bound_to_a_different_bundle() -> None:
    """A bundle-bound check may only run against the certified bundle.

    Otherwise the report's subject digests describe one set of bytes while
    the evidence was produced from another — the report could sign "this
    package passed" using verdicts earned by different bytes entirely.
    """
    bundle = make_bundle()
    other = make_bundle(payload=b"extension-payload-v2")
    assert other.digest() != bundle.digest()
    with pytest.raises(UnboundCheckError, match="security-scan"):
        certify(
            bundle,
            profile=MANIFEST_PROFILE,
            environment=environment(),
            checks=(PackageStructureCheck(bundle), SecurityScanCheck(other)),
        )
    # The same checks over the bundle they were built for certify fine.
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle), SecurityScanCheck(bundle)),
    )
    assert report.certified


def test_publication_profile_refuses_a_required_check_that_never_ran() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),  # everything else absent
    )
    assert not report.certified
    for required in PUBLICATION_PROFILE.required_checks:
        if required == "structure":
            continue
        assert any(f"{required!r} never ran" in refusal for refusal in report.refusals)


def test_publication_profile_certifies_with_executed_passing_suites() -> None:
    suite = passing_suite()
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=publication_checks(bundle, suite),
    )
    assert report.certified, report.refusals
    assert suite.runs == 1, "the orchestrator must have actually executed the suite"
    assert "conformance.chart-render" in report.certified_claims
    assert "capability.render.svg" in report.certified_claims
    assert report.certified_claims == tuple(sorted(report.certified_claims))


def test_failing_suite_refuses_publication_and_earns_no_claim() -> None:
    suite = StaticSuite(
        ConformanceOutcome(suite_id="chart-render", passed=False, detail="2 cases red")
    )
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=publication_checks(bundle, suite),
    )
    assert not report.certified
    assert not any(claim.startswith("conformance.") for claim in report.certified_claims)
    assert any("chart-render: 2 cases red" in refusal for refusal in report.refusals)


def test_raising_suite_is_recorded_as_a_failure_not_a_crash() -> None:
    class ExplodingSuite:
        suite_id = "boom"

        def run(self) -> ConformanceOutcome:
            raise RuntimeError("harness exploded")

    result = ConformanceCheck(suites=[ExplodingSuite()]).run()
    assert result.outcome is CheckOutcome.FAILED
    assert "harness exploded" in result.detail


def test_manifest_profile_certifies_without_optional_checks() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    assert report.certified, report.refusals
    # Only what the executed check proved may be claimed.
    assert report.certified_claims == ("package.artifact-bound", "package.manifest-valid")


def test_unparseable_manifest_fails_structure_but_stays_truthful() -> None:
    bundle = make_bundle(manifest=b"{not json")
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    assert not report.certified
    assert report.subject.extension_id == "", (
        "an unidentifiable candidate must not gain an identity"
    )
    assert report.subject.manifest_sha256, "the digest still records what was presented"


# ---------------------------------------------------------------------------
# Built-in static checks
# ---------------------------------------------------------------------------


def test_structure_check_refuses_an_unbound_artifact() -> None:
    bundle = make_bundle(payload=b"declared", manifest=manifest_bytes(b"different-bytes"))
    result = PackageStructureCheck(bundle).run()
    assert result.outcome is CheckOutcome.FAILED
    assert "digest mismatch" in result.detail


def test_entrypoint_containment() -> None:
    present = make_bundle(sources=(("acme_chart/main.py", PLUGIN_SOURCE),))
    assert EntryPointPresenceCheck(present).run().outcome is CheckOutcome.PASSED

    package_init = make_bundle(sources=(("acme_chart/main/__init__.py", PLUGIN_SOURCE),))
    assert EntryPointPresenceCheck(package_init).run().outcome is CheckOutcome.PASSED

    absent = make_bundle(sources=(("other/module.py", PLUGIN_SOURCE),))
    missing = EntryPointPresenceCheck(absent).run()
    assert missing.outcome is CheckOutcome.FAILED
    assert "acme_chart.main" in missing.detail


def _import_scan(source: str) -> CheckResult:
    bundle = make_bundle(sources=(("pkg/mod.py", source.encode()),))
    policy = ImportPolicy(
        public_namespaces=frozenset({"maistro"}),
        private_namespaces=frozenset({"maistro_internals"}),
    )
    return PublicImportCheck(bundle, policy).run()


def test_public_import_policy_admits_public_relative_and_stdlib_imports() -> None:
    assert _import_scan("from maistro import tools\n").outcome is CheckOutcome.PASSED
    assert _import_scan("from . import sibling\n").outcome is CheckOutcome.PASSED
    assert _import_scan("import json, os\n").outcome is CheckOutcome.PASSED


def test_public_import_policy_flags_violations() -> None:
    private = _import_scan("import maistro._hidden\n")
    assert private.outcome is CheckOutcome.FAILED
    assert "underscore-private" in private.detail

    member = _import_scan("from maistro import _secret\n")
    assert member.outcome is CheckOutcome.FAILED

    internals = _import_scan("from maistro_internals import core\n")
    assert internals.outcome is CheckOutcome.FAILED
    assert "product-private" in internals.detail

    repo = _import_scan("import packages.maistro.src.thing\n")
    assert repo.outcome is CheckOutcome.FAILED
    assert "repo-relative" in repo.detail

    dynamic = _import_scan('__import__("maistro._hidden")\n')
    assert dynamic.outcome is CheckOutcome.FAILED

    path_repair = _import_scan("sys.path.insert(0, '../src')\n")
    assert path_repair.outcome is CheckOutcome.FAILED
    assert "sys.path" in path_repair.detail


def test_public_import_scan_names_unparseable_sources() -> None:
    bundle = make_bundle(sources=(("pkg/broken.py", b"def f(:\n"),))
    result = PublicImportCheck(bundle, ImportPolicy(public_namespaces=frozenset())).run()
    assert result.outcome is CheckOutcome.FAILED
    assert "not parseable" in result.detail


def test_checks_without_sources_answer_not_applicable() -> None:
    # No packaged sources: the scans have no subject. The truthful answer is
    # not-applicable — recorded, proving nothing, and (under publication) a
    # required check that answers this way refuses certification.
    empty = make_bundle(sources=())
    imports = PublicImportCheck(empty, ImportPolicy(public_namespaces=frozenset({"maistro"}))).run()
    security = SecurityScanCheck(empty).run()
    assert imports.outcome is CheckOutcome.NOT_APPLICABLE
    assert security.outcome is CheckOutcome.NOT_APPLICABLE
    assert not imports.earned_claims and not security.earned_claims


def test_entrypoint_check_refuses_an_unparseable_manifest() -> None:
    bundle = make_bundle(manifest=b"{not json")
    result = EntryPointPresenceCheck(bundle).run()
    assert result.outcome is CheckOutcome.FAILED
    assert "unparseable" in result.detail


def test_import_scan_dispatch_handles_degenerate_call_shapes() -> None:
    def scan(source: str) -> CheckResult:
        bundle = make_bundle(sources=(("pkg/mod.py", source.encode()),))
        return PublicImportCheck(
            bundle, ImportPolicy(public_namespaces=frozenset({"maistro"}))
        ).run()

    # A file with calls but no imports still dispatches the call rules.
    assert scan("print('hello')\n").outcome is CheckOutcome.PASSED
    # A call through a subscript has no simple name for the rules to read.
    assert scan("handlers[0]('x')\n").outcome is CheckOutcome.PASSED
    # Non-insert mutations of other objects are not checkout repairs.
    assert scan("os.path.join(base, 'x')\n").outcome is CheckOutcome.PASSED
    # A future import has no module root to judge; a public from-import with
    # only public members is fine.
    assert scan("from __future__ import annotations\n").outcome is CheckOutcome.PASSED
    assert scan("from maistro.tools import render\n").outcome is CheckOutcome.PASSED
    # A non-string literal target of a dynamic import is invisible to the
    # literal-target rule — the security scan owns that shape.
    assert scan('__import__(b"json")\n').outcome is CheckOutcome.PASSED


def test_security_scan_names_unparseable_sources() -> None:
    bundle = make_bundle(sources=(("pkg/broken.py", b"def f(:\n"),))
    result = SecurityScanCheck(bundle).run()
    assert result.outcome is CheckOutcome.FAILED
    assert "not parseable" in result.detail


def test_security_scan_ignores_calls_without_a_scannable_name() -> None:
    # Subscript calls have no bare name: nothing to flag, nothing hidden.
    bundle = make_bundle(sources=(("pkg/mod.py", b"handlers[0](x)\n"),))
    assert SecurityScanCheck(bundle).run().outcome is CheckOutcome.PASSED


def _security_scan(source: str) -> CheckResult:
    bundle = make_bundle(sources=(("pkg/mod.py", source.encode()),))
    return SecurityScanCheck(bundle).run()


def test_security_scan_flags_dynamic_execution_only() -> None:
    assert _security_scan("value = eval(user_input)\n").outcome is CheckOutcome.FAILED
    assert _security_scan("exec(compile(src, '<x>', 'exec'))\n").outcome is CheckOutcome.FAILED
    dynamic = _security_scan("import importlib\nimportlib.import_module(name)\n")
    assert dynamic.outcome is CheckOutcome.FAILED
    assert "non-literal" in dynamic.detail
    # A bare reference is not a call, and a literal dynamic import is the
    # policy scan's subject, not a dynamic-execution finding.
    assert _security_scan("handler = eval\n").outcome is CheckOutcome.PASSED
    assert _security_scan('__import__("json")\n').outcome is CheckOutcome.PASSED


# ---------------------------------------------------------------------------
# AC: later package mutation invalidates signature/certification association
# ---------------------------------------------------------------------------


def _certified_bundle() -> tuple[ExtensionBundle, CertificationReport]:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    return bundle, report


def test_mutated_manifest_is_refused_by_name() -> None:
    bundle, report = _certified_bundle()
    mutated = ExtensionBundle(
        manifest_bytes=manifest_bytes(bundle.payload, version="1.4.1"),
        payload=bundle.payload,
        sources=bundle.sources,
    )
    with pytest.raises(CertificationPackageMismatch, match="manifest bytes no longer match"):
        verify_certified_package(report, mutated)


def test_mutated_artifact_is_refused_by_name() -> None:
    bundle, report = _certified_bundle()
    mutated = ExtensionBundle(
        manifest_bytes=bundle.manifest_bytes,
        payload=bundle.payload + b"x",
        sources=bundle.sources,
    )
    with pytest.raises(CertificationPackageMismatch, match="artifact bytes no longer match"):
        verify_certified_package(report, mutated)


def test_mutated_source_is_refused() -> None:
    bundle, report = _certified_bundle()
    mutated = ExtensionBundle(
        manifest_bytes=bundle.manifest_bytes,
        payload=bundle.payload,
        sources=(("acme_chart/main.py", b"PLUGIN = 'replaced'\n"),),
    )
    with pytest.raises(CertificationPackageMismatch):
        verify_certified_package(report, mutated)


def test_original_bundle_still_verifies() -> None:
    bundle, report = _certified_bundle()
    verify_certified_package(report, bundle)  # must not raise


# ---------------------------------------------------------------------------
# AC: install lifecycle consumes certification as evidence, not authorization
# ---------------------------------------------------------------------------


def _sealed_publication(
    suites: ConformanceSuite | None = None,
) -> tuple[ExtensionBundle, CertificationReport, CertificationSeal, Ed25519PrivateKey]:
    """A sealed publication-profile certification over a conforming package."""
    signer = Ed25519PrivateKey.generate()
    bundle = make_bundle()
    suite = suites if suites is not None else passing_suite()
    report, seal = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=publication_checks(bundle, suite),
        signer=signer,
    )
    return bundle, report, seal, signer


def test_certification_backs_the_trust_claim_the_inspector_consumes() -> None:
    bundle, report, seal, signer = _sealed_publication()
    assert report.certified
    claim = certification_as_trust_claim(
        report,
        seal,
        presented_manifest=bundle.manifest_bytes,
        presented_payload=bundle.payload,
    )
    assert claim.publisher_id == PUBLISHER
    assert claim.signature_present
    assert claim.signer_key_id == seal.signer_key_fingerprint
    assert claim.package_sha256 == report.subject.artifact_sha256

    public_hex = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    assert bytes.fromhex(public_hex)  # the key that sealed it is recoverable
    manifest = inspect_manifest(bundle.manifest_bytes)
    trust = evaluate_trust(manifest, claim, _policy(seal.signer_key_fingerprint))
    assert trust.trusted, trust.failures


def test_inspect_parks_certified_extensions_awaiting_authorization() -> None:
    bundle, report, seal, _signer = _sealed_publication()
    claim = certification_as_trust_claim(
        report,
        seal,
        presented_manifest=bundle.manifest_bytes,
        presented_payload=bundle.payload,
    )
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=UnwiredExtensionLoader(),
        trust_policy=_policy(seal.signer_key_fingerprint),
        platform_api_version=API_VERSION,
    )
    record = asyncio.run(
        service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(manifest_bytes=bundle.manifest_bytes, payload=bundle.payload),
            trust_evidence=claim,
        )
    )
    # Certification got it *seen*, not *authorized*: the record waits for the
    # explicit operator decision. Nothing activated; no loader was reached.
    assert record.state is ExtensionState.AWAITING_AUTHORIZATION


def test_unbacked_trust_evidence_fails_inspection_closed() -> None:
    bundle = make_bundle()
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=UnwiredExtensionLoader(),
        trust_policy=_policy("key-1"),
        platform_api_version=API_VERSION,
    )
    record = asyncio.run(
        service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(manifest_bytes=bundle.manifest_bytes, payload=bundle.payload),
            trust_evidence=TrustClaim(publisher_id=PUBLISHER),  # no signature presented
        )
    )
    assert record.state is ExtensionState.REJECTED


def test_failed_certification_cannot_back_trust_evidence() -> None:
    suite = StaticSuite(
        ConformanceOutcome(suite_id="chart-render", passed=False, detail="2 cases red")
    )
    bundle = make_bundle()
    report, seal = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=publication_checks(bundle, suite),
        signer=Ed25519PrivateKey.generate(),
    )
    assert not report.certified
    with pytest.raises(CertificationInvalid, match="did not pass"):
        certification_as_trust_claim(
            report,
            seal,
            presented_manifest=bundle.manifest_bytes,
            presented_payload=bundle.payload,
        )


def test_mutated_package_cannot_ride_on_its_certification() -> None:
    bundle, report, seal, _signer = _sealed_publication()
    with pytest.raises(CertificationPackageMismatch):
        certification_as_trust_claim(
            report,
            seal,
            presented_manifest=bundle.manifest_bytes,
            presented_payload=bundle.payload + b"tampered",
        )


def test_mutated_manifest_cannot_back_trust_evidence_by_name() -> None:
    bundle, report, seal, _signer = _sealed_publication()
    with pytest.raises(CertificationPackageMismatch, match="manifest"):
        certification_as_trust_claim(
            report,
            seal,
            presented_manifest=manifest_bytes(bundle.payload, version="1.4.1"),
            presented_payload=bundle.payload,
        )


def test_json_loaders_refuse_unknown_formats_and_naive_timestamps() -> None:
    with pytest.raises(CertificationInvalid, match="unsupported report format"):
        report_from_json(json.dumps({"format": "report:v0"}))
    with pytest.raises(CertificationInvalid, match="unsupported seal format"):
        seal_from_json(json.dumps({"format": "seal:v0"}))
    # Timestamps written by a third party without a zone are read as UTC, so
    # a report never becomes incomparable to its own seal.
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(PackageStructureCheck(bundle),),
    )
    payload = json.loads(report_to_json(report))
    payload["environment"]["executed_at"] = "2026-10-06T12:00:00"
    naive = report_from_json(json.dumps(payload))
    assert naive.environment.executed_at.tzinfo is UTC


def test_summary_states_the_no_claim_and_no_seal_cases() -> None:
    bundle = make_bundle()
    report, _ = certify(
        bundle,
        profile=MANIFEST_PROFILE,
        environment=environment(),
        checks=(
            StubCheck(
                STRUCTURE_CHECK_ID,
                CheckResult(
                    check_id=STRUCTURE_CHECK_ID,
                    title="structure",
                    outcome=CheckOutcome.FAILED,
                    detail="manifest unparseable",
                ),
            ),
        ),
    )
    text = render_summary(report, seal=None)
    assert "claims: none earned" in text
    assert "seal: none" in text


# ---------------------------------------------------------------------------
# CI-friendly output and human-readable summary
# ---------------------------------------------------------------------------


def test_summary_shows_outcomes_claims_and_refusals() -> None:
    bundle = make_bundle()
    failing = StubCheck(
        SECURITY_SCAN_CHECK_ID,
        CheckResult(
            check_id=SECURITY_SCAN_CHECK_ID,
            title="security scan",
            outcome=CheckOutcome.FAILED,
            detail="eval(x) at pkg/mod.py:1",
        ),
    )
    report, seal = certify(
        bundle,
        profile=PUBLICATION_PROFILE,
        environment=environment(),
        checks=(
            PackageStructureCheck(bundle),
            EntryPointPresenceCheck(bundle),
            PublicImportCheck(bundle, ImportPolicy(public_namespaces=frozenset({"maistro"}))),
            failing,  # a check that fails
            ConformanceCheck(suites=[]),  # a check that skips
        ),
    )
    text = render_summary(report, seal)
    assert "NOT CERTIFIED" in text
    assert "publication" in text
    assert f"sha256:{report.subject.package_sha256}" in text
    assert "security-scan: failed" in text
    assert "conformance: skipped" in text
    assert "claims:" in text
    claims_block = text.split("  claims:")[1].split("  refusals:")[0]
    earned = {
        line.strip()[2:] for line in claims_block.splitlines() if line.strip().startswith("- ")
    }
    # Only passing checks' claims are listed: nothing from the failed
    # security scan or the skipped conformance run.
    assert earned == {
        "package.manifest-valid",
        "package.artifact-bound",
        "package.entrypoints-shipped",
        "imports.public-sdk-only",
    }
    assert "static.no-dynamic-execution" not in earned
    assert not any(claim.startswith("conformance.") for claim in earned)
    assert "refusals:" in text
    assert "unsigned" in text
    # The certified variant names the verdict and its earned claims.
    _, ok_report, ok_seal, _ = _sealed_publication()
    ok_text = render_summary(ok_report, ok_seal)
    assert "CERTIFIED" in ok_text
    assert "- package.manifest-valid" in ok_text
    assert "- conformance.chart-render" in ok_text
