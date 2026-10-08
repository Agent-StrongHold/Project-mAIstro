"""The certification pipeline: structure, security, conformance, digest,
signature, and the truthful report (M9-H3, #975).

What these tests pin, as executed behavior:

- **the report cannot claim a property whose test did not execute** —
  `claims` is built only from executed-passed checks and cases; skipped
  and waived properties land in `not_proven`, never in `claims`;
- **required skips decline certification under the profile that demands
  them** — a waived backend case certifies under `standard` (recorded,
  listed as not proven) and declines under `strict`; a required check that
  could not run always declines;
- **the signed digest corresponds exactly to the certified bytes** — sign,
  flip one byte, and `verify_certification` refuses; swap the shipped
  manifest, and the manifest binding refuses;
- **certification records provenance** — extension id/version/publisher,
  the harness and contract versions, the observed SDK distribution, and
  the executing environment;
- **the security checks are the namespace policy** — the embedded
  product-private/public roots stay equal to
  `extensions/namespace-policy.json`, so the tool a third party runs
  enforces the same boundary the repository's gate does;
- **the same tooling certifies built-in and external-style subjects** — a
  scaffolded-by-the-SDK extension certifies through this exact pipeline,
  and the reference extension's tree passes the source-inspection half.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maistro_ext_harness.backends import Backend, BackendRegistry
from maistro_ext_harness.certification import (
    CertificationProfile,
    CertificationRequest,
    certify,
    verify_certification,
)
from maistro_ext_harness.checks import CheckStatus
from maistro_ext_harness.families import (
    CaseOutcome,
    ConformanceCase,
    FamilyPlugin,
    family_plugin,
    register_family,
)
from maistro_ext_harness.packaging import inspect_artifact, inspect_source_tree
from maistro_ext_harness.security import (
    PRODUCT_PRIVATE_ROOTS,
    PUBLIC_SDK_ROOTS,
    REPO_RELATIVE_ROOTS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NAMESPACE_POLICY = REPO_ROOT / "extensions" / "namespace-policy.json"

DIST_NAME = "acme-widget"
VERSION = "1.0.0"
TOP = "acme_widget"


def _pkg(root: Path) -> Path:
    """The fabricated extension's package dir (the conftest src/ layout)."""
    return root / "src" / TOP


def _write_pyproject(root: Path, *, name: str = DIST_NAME, version: str = VERSION) -> None:
    """Give a fabricated extension the packaging metadata certify checks."""
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
                "[project]",
                f'name = "{name}"',
                f'version = "{version}"',
                'description = "fabricated for the certification suite"',
                "dependencies = []",
                "",
                "[tool.hatch.build.targets.wheel.force-include]",
                f'"extension.json" = "{TOP}/extension.json"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _make_wheel(
    tmp_path: Path,
    manifest: dict,
    *,
    name: str = "ext",
    dist_name: str = DIST_NAME,
    version: str = VERSION,
    include_manifest: bool = True,
    manifest_override: dict | None = None,
    metadata_name: str | None = None,
    metadata_version: str | None = None,
    extra_members: dict[str, str] | None = None,
    omit_members: tuple[str, ...] = (),
) -> Path:
    """Synthesize the artifact certify binds: a wheel-shaped zip."""
    package = tmp_path / f"{name}-src" / TOP
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(f'"""fabricated {TOP}."""\n', encoding="utf-8")
    (package / "plugin.py").write_text(
        "PLUGIN: dict[str, object] = {\n"
        '    "kind": "tool",\n'
        f'    "name": "{manifest["id"]}",\n'
        f'    "version": "{manifest["version"]}",\n'
        '    "capabilities": [],\n'
        '    "handler": "spin",\n'
        "}\n"
        "\n"
        "\n"
        "def spin() -> str:\n"
        '    return "spin-ok"\n'
        "\n"
        "\n"
        'HANDLERS: dict[str, object] = {"spin": spin}\n',
        encoding="utf-8",
    )
    wheel = tmp_path / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for member in (f"{TOP}/__init__.py", f"{TOP}/plugin.py"):
            if member not in omit_members:
                archive.writestr(member, (package / Path(member).name).read_text(encoding="utf-8"))
        if include_manifest:
            payload = manifest_override if manifest_override is not None else manifest
            archive.writestr(f"{TOP}/extension.json", json.dumps(payload, indent=2))
        archive.writestr(
            f"{dist_name}-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {metadata_name or dist_name}\n"
            f"Version: {metadata_version or version}\n",
        )
        for member, content in (extra_members or {}).items():
            archive.writestr(member, content)
    return wheel


def _certifiable(
    make_extension: Callable[..., Path],
    tmp_path: Path,
) -> tuple[Path, Path]:
    """A conforming subject plus matching pyproject and wheel."""
    root = make_extension()
    _write_pyproject(root)
    manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
    wheel = _make_wheel(tmp_path, manifest)
    return root, wheel


def _request(root: Path, wheel: Path, **kwargs: object) -> CertificationRequest:
    return CertificationRequest(subject=root, artifact=wheel, **kwargs)  # type: ignore[arg-type]


class TestHappyPath:
    def test_a_conforming_project_certifies(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert report.certified, report.human_summary()
        assert report.decline_reasons == []
        # Provenance: who, what, against which contract, in which environment.
        assert report.subject["id"] == "acme.widget"
        assert report.subject["publisher"] == "acme"
        assert report.subject["version"] == VERSION
        assert report.subject["contract_range"] == ">=1.0.0,<2.0.0"
        assert report.subject["capabilities"] == []
        assert report.contract_version == "1.0.0"
        assert report.harness_version
        assert "python" in report.environment
        # The artifact digest is recorded, not implied.
        assert report.artifact is not None
        import hashlib

        assert report.artifact["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()

    def test_claims_come_only_from_executed_passes(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert report.certified
        assert report.claims, "a certified report with no claims proves nothing"
        for claim in report.claims:
            assert "did NOT execute" not in claim
        assert not any("conformance" in claim and "failed" in claim for claim in report.claims)

    def test_the_platform_boundary_is_always_not_proven(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert any("platform certification" in item for item in report.not_proven)
        assert not any("platform certification" in claim for claim in report.claims)
        document = report.to_dict()
        assert document["decision"]["platform_note"]
        assert document["conformance"]["report"]["certification"]["platform_certified"] is False

    def test_strict_profile_certifies_a_complete_whl_run(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, profile=CertificationProfile.STRICT))
        assert report.certified, report.human_summary()

    def test_report_json_round_trips(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "cert.json"
        assert report.write_json(out) == out
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["certification_schema"].startswith("maistro-ext-harness/certification@")
        assert document["decision"]["certified"] is True
        assert document["artifact"]["sha256"]

    def test_the_reference_extension_tree_passes_source_inspection(self) -> None:
        """The repository's own reference extension (src/ layout) passes the
        same source-tree and security checks — built-in and external
        subjects, one tooling."""
        from maistro_ext_harness.security import security_checks

        reference = REPO_ROOT / "extensions" / "reference-greeter"
        inspection = inspect_source_tree(reference)
        assert inspection.manifest is not None
        assert inspection.manifest.id == "reference.greeter"
        assert inspection.project_name == "reference-greeter"
        for check in inspection.checks:
            assert check.status is CheckStatus.PASSED, f"{check.check_id}: {check.detail}"
        security = security_checks(
            reference,
            entrypoint_module=inspection.manifest.entrypoint.module,
            declared=inspection.declared,
        )
        for check in security:
            assert check.status is CheckStatus.PASSED, f"{check.check_id}: {check.detail}"


class TestDeclines:
    def test_a_product_private_import_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "sneaky.py").write_text("import maistro_server.routes\n", encoding="utf-8")
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("security/imports-public-only" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )
        assert any("sneaky.py" in reason for reason in report.decline_reasons)

    def test_an_undeclared_dependency_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "needs_more.py").write_text("import yaml\n", encoding="utf-8")
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any(
            "security/no-undeclared-dependencies" in reason for reason in report.decline_reasons
        ), report.decline_reasons

    def test_a_declared_dependency_passes(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                "dependencies = []", 'dependencies = ["pydantic>=2"]'
            ),
            encoding="utf-8",
        )
        (_pkg(root) / "uses_pydantic.py").write_text(
            "from pydantic import BaseModel\n", encoding="utf-8"
        )
        report = certify(_request(root, wheel))
        assert report.certified, report.human_summary()

    def test_underscore_private_sdk_seam_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "private_seam.py").write_text(
            "from maistro_ext_sdk import _internal\n", encoding="utf-8"
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("private" in reason for reason in report.decline_reasons)

    def test_checkout_repair_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "repair.py").write_text(
            'import sys\nsys.path.insert(0, "packages/maistro-core/src")\n',
            encoding="utf-8",
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("sys-path-repair" in reason for reason in report.decline_reasons)

    def test_dynamic_import_of_a_private_root_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "dynamic.py").write_text(
            'from importlib import import_module as load\nload("maistro.extensions")\n',
            encoding="utf-8",
        )
        report = certify(_request(root, wheel))
        assert not report.certified

    def test_entrypoint_outside_the_own_package_declines(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        valid_manifest: dict,
    ) -> None:
        root = make_extension(
            manifest={
                **valid_manifest,
                "entrypoint": {"module": "maistro.plugin", "object": "PLUGIN"},
            }
        )
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any(
            "entrypoint-inside-own-package" in reason for reason in report.decline_reasons
        ), report.decline_reasons

    def test_missing_pyproject_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("pyproject-parses" in reason for reason in report.decline_reasons)

    def test_version_mismatch_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root, version="9.9.9")
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("version-parity" in reason for reason in report.decline_reasons)

    def test_a_failing_conformance_case_declines(
        self, raising_extension: Path, tmp_path: Path
    ) -> None:
        _write_pyproject(raising_extension)
        manifest = json.loads((raising_extension / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        report = certify(_request(raising_extension, wheel))
        assert not report.certified
        assert any("conformance case" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )
        # And the failed case never became a claim.
        assert not any(":failed" in claim for claim in report.claims)

    def test_a_rejected_manifest_declines_without_running_conformance(
        self, import_bomb: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = import_bomb()
        wheel = tmp_path / "bomb.whl"
        wheel.write_bytes(b"not a zip at all")
        report = certify(_request(root, wheel))
        assert not report.certified
        assert report.conformance_executed is False
        assert report.conformance_reason is not None
        assert any("did not execute" in reason for reason in report.decline_reasons)


class TestArtifactChecks:
    def test_a_wheel_without_the_manifest_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, include_manifest=False)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("artifact/manifest-ships" in reason for reason in report.decline_reasons)

    def test_a_shipped_manifest_that_differs_from_the_tested_one_declines(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        valid_manifest: dict,
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        tampered = {**valid_manifest, "version": "9.9.9", "id": "acme.widget"}
        tampered["publisher"] = "acme"
        wheel = _make_wheel(tmp_path, manifest, manifest_override=tampered)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any(
            "artifact/manifest-matches-tested" in reason for reason in report.decline_reasons
        ), report.decline_reasons

    def test_wheel_metadata_identity_mismatch_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, metadata_version="0.0.1")
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("artifact/metadata-identity" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_missing_entrypoint_member_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, omit_members=(f"{TOP}/plugin.py",))
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("artifact/entrypoint-ships" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_a_traversal_member_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(
            tmp_path, manifest, extra_members={"../escapes.py": "print('outside')\n"}
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("artifact/members-contained" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_a_corrupt_artifact_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        junk = tmp_path / "junk.whl"
        junk.write_bytes(b"this is not a zip")
        report = certify(_request(root, junk))
        assert not report.certified
        assert any("artifact/readable" in reason for reason in report.decline_reasons)
        assert report.artifact is None

    def test_inspect_artifact_directly_reports_digest(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        checks, info = inspect_artifact(wheel, None, project_name=None)
        assert info is not None
        assert info.filename == wheel.name
        assert info.size_bytes == wheel.stat().st_size
        assert any(check.check_id == "artifact/digest-recorded" for check in checks)


class TestBackendWaiverProfiles:
    @pytest.fixture
    def gated_tool_family(self):
        gated = ConformanceCase(
            case_id="acme/needs-real-service",
            description="a property that cannot be mocked honestly",
            run=lambda env: CaseOutcome(True, "ran against the real service"),
            requires_backend="acme-real-service",
        )
        original = family_plugin("tool")
        register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
        yield
        register_family(original)

    def _waived_backends(self) -> BackendRegistry:
        return BackendRegistry(
            backends={"acme-real-service": Backend("acme-real-service", probe=lambda: False)},
            waivers=frozenset({"acme-real-service"}),
        )

    def test_without_a_waiver_the_missing_backend_declines(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        gated_tool_family: None,
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("acme/needs-real-service" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_standard_profile_certifies_with_the_waiver_recorded_as_not_proven(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        gated_tool_family: None,
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, backends=self._waived_backends()))
        assert report.certified, report.human_summary()
        assert any(
            "acme/needs-real-service" in item and "did NOT execute" in item
            for item in report.not_proven
        ), report.not_proven
        assert not any("needs-real-service" in claim for claim in report.claims)

    def test_strict_profile_declines_on_the_same_waiver(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        gated_tool_family: None,
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(
            _request(
                root,
                wheel,
                profile=CertificationProfile.STRICT,
                backends=self._waived_backends(),
            )
        )
        assert not report.certified
        assert any("needs-real-service" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )


class TestSigning:
    @pytest.fixture
    def keypair(self) -> tuple[str, str]:
        key = Ed25519PrivateKey.generate()
        return (
            key.private_bytes_raw().hex(),
            key.public_key().public_bytes_raw().hex(),
        )

    def test_a_signed_report_verifies_against_the_publisher_key(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        assert report.certified
        assert report.signature["signed"] is True
        assert report.signature["algorithm"] == "ed25519"
        assert report.signature["public_key"] == public_hex
        out = tmp_path / "signed.json"
        report.write_json(out)
        result = verify_certification(out, wheel, publisher_key_hex=public_hex)
        assert result.ok, result.failures

    def test_verifying_without_a_pinned_key_reports_self_consistency(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        private_hex, _ = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        out = tmp_path / "signed.json"
        report.write_json(out)
        result = verify_certification(out, wheel)
        assert result.ok, result.failures
        assert any("self-consistency" in item for item in result.checked)

    def test_unsigned_report_with_a_pinned_key_fails(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        _, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "unsigned.json"
        report.write_json(out)
        result = verify_certification(out, wheel, publisher_key_hex=public_hex)
        assert not result.ok
        assert any("unsigned" in failure for failure in result.failures)

    def test_malformed_signing_key_fails_closed_but_truthfully(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex="not-hex"))
        assert report.signature["signed"] is False
        assert "signing failed" in report.signature["reason"]
        # The report is still a complete, honest document about a declined
        # signature — and the certification itself still succeeded on its checks.
        assert report.certified

    def test_tampered_artifact_fails_verification(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        out = tmp_path / "signed.json"
        report.write_json(out)
        mutated = tmp_path / "mutated.whl"
        data = bytearray(wheel.read_bytes())
        data[-1] ^= 0xFF
        mutated.write_bytes(bytes(data))
        result = verify_certification(out, mutated, publisher_key_hex=public_hex)
        assert not result.ok
        assert any("bytes changed" in failure for failure in result.failures)

    def test_swapped_manifest_inside_the_artifact_fails_verification(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        valid_manifest: dict,
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest)
        report = certify(_request(root, wheel))
        out = tmp_path / "cert.json"
        report.write_json(out)
        # An attacker swaps the shipped manifest for a different one and
        # re-records the artifact digest so the byte-digest check passes; the
        # manifest binding must still refuse the swap.
        swapped = _make_wheel(
            tmp_path,
            manifest,
            manifest_override={**valid_manifest, "title": "A different title"},
            name="swapped",
        )
        document = json.loads(out.read_text(encoding="utf-8"))
        import hashlib

        document["artifact"]["sha256"] = hashlib.sha256(swapped.read_bytes()).hexdigest()
        out.write_text(json.dumps(document), encoding="utf-8")
        result = verify_certification(out, swapped)
        assert not result.ok
        assert any(
            "manifest changed" in failure or "manifest_sha256" in failure
            for failure in result.failures
        ), result.failures

    def test_a_corrupt_report_is_unreadable_not_verified(
        self, tmp_path: Path, keypair: tuple[str, str]
    ) -> None:
        _, public_hex = keypair
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        result = verify_certification(bad, tmp_path / "whatever.whl", publisher_key_hex=public_hex)
        assert not result.ok
        assert any("unreadable" in failure for failure in result.failures)

    def test_certified_true_with_decline_reasons_is_corrupt(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        _, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "cert.json"
        report.write_json(out)
        document = json.loads(out.read_text(encoding="utf-8"))
        document["decision"]["decline_reasons"] = ["injected inconsistency"]
        out.write_text(json.dumps(document), encoding="utf-8")
        result = verify_certification(out, wheel, publisher_key_hex=public_hex)
        assert not result.ok
        assert any("corrupt" in failure for failure in result.failures)

    def test_a_foreign_signature_does_not_verify(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        signer = Ed25519PrivateKey.generate()
        other = Ed25519PrivateKey.generate()
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(
            _request(
                root,
                wheel,
                signing_key_hex=signer.private_bytes_raw().hex(),
            )
        )
        out = tmp_path / "signed.json"
        report.write_json(out)
        result = verify_certification(
            out, wheel, publisher_key_hex=other.public_key().public_bytes_raw().hex()
        )
        assert not result.ok
        assert any("does not verify" in failure for failure in result.failures)


class TestPolicySync:
    def test_embedded_roots_equal_the_repository_namespace_policy(self) -> None:
        """The certification tool a third party runs embeds the boundary; the
        embedded statement and the repository's policy file must stay the
        same statement."""
        policy = json.loads(NAMESPACE_POLICY.read_text(encoding="utf-8"))
        assert frozenset(policy["public_sdk_namespaces"]) == PUBLIC_SDK_ROOTS
        assert frozenset(policy["product_private_namespaces"]) == PRODUCT_PRIVATE_ROOTS
        assert {"packages", "extensions"} == REPO_RELATIVE_ROOTS


class TestCli:
    def _cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "maistro_ext_harness", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(Path(__file__).parent),
        )

    def test_certify_happy_path_exit_0_and_report_written(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        out = tmp_path / "cert.json"
        proc = self._cli(
            "certify",
            "--path",
            str(root),
            "--artifact",
            str(wheel),
            "--report",
            str(out),
        )
        assert proc.returncode == 0, proc.stderr
        assert "CERTIFIED" in proc.stdout
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["decision"]["certified"] is True

    def test_certify_declined_exit_1_and_names_the_reason(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "sneaky.py").write_text("import maistro_server.routes\n", encoding="utf-8")
        proc = self._cli("certify", "--path", str(root), "--artifact", str(wheel))
        assert proc.returncode == 1
        assert "DECLINED" in proc.stdout
        assert "security/imports-public-only" in proc.stdout

    def test_certify_missing_artifact_still_declines_truthfully(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root)
        proc = self._cli("certify", "--path", str(root), "--artifact", str(tmp_path / "absent.whl"))
        assert proc.returncode == 1
        assert "DECLINED" in proc.stdout

    def test_certify_signing_key_file_round_trip_and_verify(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        key = Ed25519PrivateKey.generate()
        key_file = tmp_path / "signing-key.hex"
        key_file.write_text(key.private_bytes_raw().hex(), encoding="utf-8")
        publisher_key = key.public_key().public_bytes_raw().hex()
        root, wheel = _certifiable(make_extension, tmp_path)
        out = tmp_path / "cert.json"
        proc = self._cli(
            "certify",
            "--path",
            str(root),
            "--artifact",
            str(wheel),
            "--signing-key-file",
            str(key_file),
            "--report",
            str(out),
        )
        assert proc.returncode == 0, proc.stderr
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["signature"]["signed"] is True

        verify = self._cli(
            "verify-certification",
            "--report",
            str(out),
            "--artifact",
            str(wheel),
            "--publisher-key",
            publisher_key,
        )
        assert verify.returncode == 0, verify.stderr
        assert "verified" in verify.stdout

    def test_verify_fails_on_a_mutated_artifact(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        out = tmp_path / "cert.json"
        self._cli("certify", "--path", str(root), "--artifact", str(wheel), "--report", str(out))
        mutated = tmp_path / "mutated.whl"
        mutated.write_bytes(wheel.read_bytes() + b"trailing")
        proc = self._cli("verify-certification", "--report", str(out), "--artifact", str(mutated))
        assert proc.returncode == 1
        assert "bytes changed" in proc.stderr

    def test_verify_unknown_schema_exit_1(self, tmp_path: Path) -> None:
        report = tmp_path / "cert.json"
        report.write_text(json.dumps({"certification_schema": "someone-else/v9"}), encoding="utf-8")
        wheel = tmp_path / "w.whl"
        wheel.write_bytes(b"nope")
        proc = self._cli("verify-certification", "--report", str(report), "--artifact", str(wheel))
        assert proc.returncode == 1
        assert "unknown certification schema" in proc.stderr
