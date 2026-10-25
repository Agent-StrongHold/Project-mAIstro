"""The CLI: the shape a third-party CI invokes (#974)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from maistro_ext_harness.cli import main


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI exactly as a foreign CI would: a subprocess, no repo path
    repair, exit code as the verdict."""
    return subprocess.run(
        [sys.executable, "-m", "maistro_ext_harness", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).parent),
    )


def test_cli_passes_a_conforming_extension_and_writes_the_report(
    conforming_extension: Path, tmp_path: Path
) -> None:
    report_path = tmp_path / "report.json"
    proc = _cli("run", "--path", str(conforming_extension), "--report", str(report_path))
    assert proc.returncode == 0, proc.stderr
    assert "0 failed" in proc.stdout
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert document["summary"]["failed"] == 0
    assert document["certification"]["platform_certified"] is False


def test_cli_fails_a_broken_subject_with_exit_1(make_extension: Callable[..., Path]) -> None:
    """A nonconforming subject is a red exit with the failed cases named —
    here a handler the entrypoint names but the module does not provide."""
    plugin = """
PLUGIN: dict[str, object] = {"kind": "tool", "handler": "absent"}

HANDLERS: dict[str, object] = {}
"""
    root = make_extension(plugin_source=plugin)
    proc = _cli("run", "--path", str(root))
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr


def test_cli_invalid_manifest_exits_2(
    make_extension: Callable[..., Path], valid_manifest: dict
) -> None:
    root = make_extension(manifest={**valid_manifest, "family": "nope"})
    proc = _cli("run", "--path", str(root))
    assert proc.returncode == 2
    assert "error:" in proc.stderr


def test_cli_missing_extension_exits_2(tmp_path: Path) -> None:
    proc = _cli("run", "--path", str(tmp_path / "absent"))
    assert proc.returncode == 2


def test_cli_with_reference_runs_both_subjects(conforming_extension: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    proc = _cli(
        "run",
        "--path",
        str(conforming_extension),
        "--with-reference",
        "--report",
        str(report_path),
    )
    assert proc.returncode == 0, proc.stderr
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert {subject["role"] for subject in document["subjects"]} == {
        "external",
        "reference",
    }


def test_cli_in_process_main_matches_subprocess_verdict(
    conforming_extension: Path,
) -> None:
    assert main(["run", "--path", str(conforming_extension)]) == 0


def test_cli_reports_skip_lines_for_waived_backends(
    conforming_extension: Path, capsys: object
) -> None:
    """Waivers surface as SKIP lines; nothing is silently absent. In-process
    (main) so the gated family case and its backend probe are registered the
    way a third-party suite would register them."""
    from maistro_ext_harness.families import (
        CaseOutcome,
        ConformanceCase,
        FamilyPlugin,
        family_plugin,
        register_family,
    )

    gated = ConformanceCase(
        case_id="acme/needs-real-service",
        description="a property that cannot be mocked honestly",
        run=lambda env: CaseOutcome(True, "ran"),
        requires_backend="acme-real-service",
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
    try:
        code = main(
            [
                "run",
                "--path",
                str(conforming_extension),
                "--allow-missing-backend",
                "acme-real-service",
            ]
        )
    finally:
        register_family(original)
    assert code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "SKIP" in captured.out


# ----------------------------------------------------------- certify / verify
#
# The subprocess tests above pin what a foreign CI sees (exit codes, output).
# These drive `main` in process so the certify and verify-certification
# subcommands — argument handling, signing-key resolution, the report file,
# and the OK/INVALID lines — are themselves measured evidence, not just
# exercised in a child interpreter.


def _write_pyproject(root: Path) -> None:
    """The packaging metadata the certify pipeline checks."""
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
                "[project]",
                'name = "acme-widget"',
                'version = "1.0.0"',
                'description = "fabricated for the CLI suite"',
                "dependencies = []",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _make_wheel(tmp_path: Path, root: Path) -> Path:
    """A wheel whose bytes match the fabricated source tree and manifest."""
    import zipfile

    manifest = json.loads((root / "extension.json").read_text(encoding="utf-8"))
    package = tmp_path / "stage" / "acme_widget"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""fabricated acme_widget."""\n', encoding="utf-8")
    (package / "plugin.py").write_text(
        (root / "src" / "acme_widget" / "plugin.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    wheel = tmp_path / "acme-widget-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for module in sorted(package.glob("*.py")):
            archive.writestr(f"acme_widget/{module.name}", module.read_text(encoding="utf-8"))
        archive.writestr("acme_widget/extension.json", json.dumps(manifest, indent=2))
        archive.writestr(
            "acme-widget-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: acme-widget\nVersion: 1.0.0\n",
        )
    return wheel


@pytest.fixture
def certifiable(make_extension, tmp_path):
    """A conforming subject plus its pyproject and matching wheel."""
    root = make_extension()
    _write_pyproject(root)
    return root, _make_wheel(tmp_path, root)


class TestCertifyCommand:
    def test_certify_writes_the_report_and_prints_the_summary(
        self, certifiable, tmp_path, capsys
    ) -> None:
        root, wheel = certifiable
        report_path = tmp_path / "certification.json"
        code = main(
            ["certify", "--path", str(root), "--artifact", str(wheel), "--report", str(report_path)]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "CERTIFIED" in out
        assert f"certification report: {report_path}" in out
        document = json.loads(report_path.read_text(encoding="utf-8"))
        assert document["decision"]["certified"] is True

    def test_certify_without_a_report_flag_still_prints_the_verdict(
        self, certifiable, capsys
    ) -> None:
        root, wheel = certifiable
        assert main(["certify", "--path", str(root), "--artifact", str(wheel)]) == 0
        assert "CERTIFIED" in capsys.readouterr().out

    def test_certify_signs_with_a_key_and_the_summary_names_it(self, certifiable, capsys) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        root, wheel = certifiable
        code = main(
            [
                "certify",
                "--path",
                str(root),
                "--artifact",
                str(wheel),
                "--signing-key",
                key.private_bytes_raw().hex(),
            ]
        )
        assert code == 0
        assert "ed25519, public key" in capsys.readouterr().out

    def test_certify_reads_the_key_from_stdin_with_a_dash_file(
        self, certifiable, monkeypatch, capsys
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        monkeypatch.setattr(sys, "stdin", io.StringIO(key.private_bytes_raw().hex() + "\n"))
        root, wheel = certifiable
        code = main(
            [
                "certify",
                "--path",
                str(root),
                "--artifact",
                str(wheel),
                "--signing-key-file",
                "-",
            ]
        )
        assert code == 0
        assert "ed25519, public key" in capsys.readouterr().out

    def test_certify_reads_the_key_from_a_file(self, certifiable, tmp_path, capsys) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        key_file = tmp_path / "seed.hex"
        key_file.write_text(key.private_bytes_raw().hex() + "\n", encoding="utf-8")
        root, wheel = certifiable
        code = main(
            [
                "certify",
                "--path",
                str(root),
                "--artifact",
                str(wheel),
                "--signing-key-file",
                str(key_file),
            ]
        )
        assert code == 0
        assert "ed25519, public key" in capsys.readouterr().out

    def test_an_unreadable_key_file_is_exit_2_without_a_traceback(
        self, certifiable, capsys
    ) -> None:
        root, wheel = certifiable
        code = main(
            [
                "certify",
                "--path",
                str(root),
                "--artifact",
                str(wheel),
                "--signing-key-file",
                str(wheel.parent / "absent.hex"),
            ]
        )
        assert code == 2
        err = capsys.readouterr().err
        assert "cannot read --signing-key-file" in err
        assert "Traceback" not in err

    def test_a_declined_certification_is_exit_1_but_the_report_is_truthful(
        self, make_extension, tmp_path, capsys
    ) -> None:
        """A recorded decline is exit 1 — and the decision document still exists."""
        root = make_extension(
            plugin_source="PLUGIN: dict[str, object] = {'kind': 'tool', 'handler': 'absent'}\n"
        )
        _write_pyproject(root)
        wheel = _make_wheel(tmp_path, root)
        report_path = tmp_path / "declined.json"
        code = main(
            ["certify", "--path", str(root), "--artifact", str(wheel), "--report", str(report_path)]
        )
        assert code == 1
        assert "DECLINED" in capsys.readouterr().out
        document = json.loads(report_path.read_text(encoding="utf-8"))
        assert document["decision"]["certified"] is False
        assert document["decision"]["decline_reasons"]


class TestVerifyCertificationCommand:
    def test_a_signed_certification_verifies_with_the_publisher_key(
        self, certifiable, tmp_path, capsys
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        private_hex, public_hex = (
            key.private_bytes_raw().hex(),
            key.public_key().public_bytes_raw().hex(),
        )
        root, wheel = certifiable
        report_path = tmp_path / "signed.json"
        assert (
            main(
                [
                    "certify",
                    "--path",
                    str(root),
                    "--artifact",
                    str(wheel),
                    "--signing-key",
                    private_hex,
                    "--report",
                    str(report_path),
                ]
            )
            == 0
        )
        capsys.readouterr()
        code = main(
            [
                "verify-certification",
                "--report",
                str(report_path),
                "--artifact",
                str(wheel),
                "--publisher-key",
                public_hex,
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "OK " in out and "verified:" in out

    def test_a_mutated_artifact_prints_INVALID_lines_and_exits_1(
        self, certifiable, tmp_path, capsys
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        root, wheel = certifiable
        report_path = tmp_path / "signed.json"
        main(
            [
                "certify",
                "--path",
                str(root),
                "--artifact",
                str(wheel),
                "--signing-key",
                key.private_bytes_raw().hex(),
                "--report",
                str(report_path),
            ]
        )
        mutated = tmp_path / "mutated.whl"
        data = bytearray(wheel.read_bytes())
        data[-1] ^= 0xFF
        mutated.write_bytes(bytes(data))
        capsys.readouterr()
        code = main(
            [
                "verify-certification",
                "--report",
                str(report_path),
                "--artifact",
                str(mutated),
                "--publisher-key",
                key.public_key().public_bytes_raw().hex(),
            ]
        )
        assert code == 1
        captured = capsys.readouterr()
        assert "INVALID" in captured.err
        assert "verification failed" in captured.err
