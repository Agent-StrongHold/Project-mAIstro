"""CLI certification commands: `maistro extensions certify` / `verify-certification`.

The CLI is the pre-publication operator surface (#975). These tests pin the
contract the help text promises: a manifest-profile run certifies a
well-formed package and writes CI-friendly report/seal JSON; a
publication-profile run truthfully refuses — conformance suites are
host-supplied Python objects a command line cannot carry — and the refusal
names the skipped required check; verification re-checks a report+seal
against the presented bytes, mints the install flow's trust claim, and exits
non-zero for a mutated package or an untrusted key.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from typer.testing import CliRunner

from maistro.cli._extensions import app

runner = CliRunner()

PLUGIN_SOURCE = b"PLUGIN = object()\n"


def _wheel_bytes(*entries: tuple[str, bytes]) -> bytes:
    """A wheel-style zip archive carrying the given ``(path, bytes)`` files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def _write_package(dir: Path) -> dict[str, Path]:
    """A valid package on disk: manifest and a payload wheel with its sources.

    The payload is the only carrier of source code: the certification scans
    read it from the artifact, so there is no side-channel source directory
    a malicious wheel could be paired with.
    """
    dir.mkdir(parents=True, exist_ok=True)
    payload = _wheel_bytes(("acme_chart/main.py", PLUGIN_SOURCE))
    document = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
    }
    manifest = dir / "manifest.json"
    manifest.write_text(json.dumps(document))
    payload_path = dir / "payload.bin"
    payload_path.write_bytes(payload)
    return {
        "manifest": manifest,
        "payload": payload_path,
    }


def _write_key(dir: Path) -> tuple[Path, str]:
    """A hex Ed25519 private key file and its public-key hex."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    key_file = dir / "signing-key.hex"
    key_file.write_text(raw.hex())
    public_hex = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return key_file, public_hex


def _certify(package: dict[str, Path], out: Path, *args: str) -> Any:
    return runner.invoke(
        app,
        [
            "certify",
            "--manifest",
            str(package["manifest"]),
            "--payload",
            str(package["payload"]),
            "--report-json",
            str(out / "report.json"),
            "--seal-json",
            str(out / "seal.json"),
            *args,
        ],
    )


def test_certify_manifest_profile_writes_report_and_seal(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()

    result = _certify(package, out, "--profile", "manifest")

    assert result.exit_code == 0, result.output
    assert "CERTIFIED" in result.output
    report = json.loads((out / "report.json").read_text())
    assert report["certified"] is True
    assert report["profile"] == "manifest"
    assert report["subject"]["extension_id"] == "acme.chart_tools"
    assert report["subject"]["publisher"] == "acme"
    assert report["subject"]["package_sha256"]
    assert json.loads((out / "seal.json").read_text())["signature"] == ""


def test_certify_with_signing_key_seals_the_report(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file, public_hex = _write_key(tmp_path)

    result = _certify(package, out, "--sign-key-file", str(key_file))

    assert result.exit_code == 0, result.output
    seal = json.loads((out / "seal.json").read_text())
    assert seal["signature"]
    assert seal["signer_public_key"] == public_hex


def test_certify_publication_profile_truthfully_refuses(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()

    result = _certify(package, out, "--profile", "publication")

    assert result.exit_code != 0
    assert "NOT CERTIFIED" in result.output
    assert "conformance" in result.output
    assert "skipped" in result.output
    # The report still exists and still tells the truth about the gap.
    report = json.loads((out / "report.json").read_text())
    assert report["certified"] is False
    assert any("conformance" in refusal for refusal in report["refusals"])


def test_certify_unknown_profile_refuses(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()

    result = _certify(package, out, "--profile", "no-such-profile")

    assert result.exit_code != 0
    assert "Unknown profile" in result.output


def test_certify_missing_manifest_exits_nonzero(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    package["manifest"].unlink()

    result = _certify(package, out)

    assert result.exit_code != 0
    assert "Cannot read manifest" in result.output


def _verify(
    package: dict[str, Path],
    out: Path,
    *args: str,
) -> Any:
    return runner.invoke(
        app,
        [
            "verify-certification",
            str(out / "report.json"),
            str(out / "seal.json"),
            "--manifest",
            str(package["manifest"]),
            "--payload",
            str(package["payload"]),
            *args,
        ],
    )


def test_verify_certification_roundtrip_prints_the_trust_claim(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file, public_hex = _write_key(tmp_path)
    assert _certify(package, out, "--sign-key-file", str(key_file)).exit_code == 0

    result = _verify(package, out, "--trusted-public-key", public_hex)

    assert result.exit_code == 0, result.output
    assert "CERTIFIED" in result.output
    assert "trust claim (evidence only)" in result.output
    assert "publisher=acme" in result.output


def test_verify_certification_refuses_mutated_package(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file, public_hex = _write_key(tmp_path)
    assert _certify(package, out, "--sign-key-file", str(key_file)).exit_code == 0

    # One flipped source byte inside the payload wheel after certification.
    package["payload"].write_bytes(
        _wheel_bytes(("acme_chart/main.py", b"PLUGIN = object()\n# x\n"))
    )

    result = _verify(package, out, "--trusted-public-key", public_hex)

    assert result.exit_code != 0
    assert "Certification refused" in result.output
    assert "no longer match" in result.output


def test_verify_certification_refuses_an_unsigned_seal(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    assert _certify(package, out).exit_code == 0  # no --sign-key-file: unsigned

    result = _verify(package, out)

    assert result.exit_code != 0
    assert "Certification refused" in result.output
    assert "no signature" in result.output


def test_verify_certification_refuses_an_untrusted_key(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file, _public_hex = _write_key(tmp_path)
    assert _certify(package, out, "--sign-key-file", str(key_file)).exit_code == 0

    impostor = Ed25519PrivateKey.generate()
    other_public = impostor.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    result = _verify(package, out, "--trusted-public-key", other_public)

    assert result.exit_code != 0
    assert "Certification refused" in result.output


def test_verify_certification_refuses_an_edited_report(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file, public_hex = _write_key(tmp_path)
    assert _certify(package, out, "--sign-key-file", str(key_file)).exit_code == 0

    report = json.loads((out / "report.json").read_text())
    report["subject"]["version"] = "9.9.9"
    (out / "report.json").write_text(json.dumps(report, sort_keys=True))

    result = _verify(package, out, "--trusted-public-key", public_hex)

    assert result.exit_code != 0
    assert "Certification refused" in result.output


def test_certify_refuses_a_malformed_signing_key(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    key_file = tmp_path / "bad-key.hex"
    key_file.write_text("definitely-not-hex!")

    result = _certify(package, out, "--sign-key-file", str(key_file))

    assert result.exit_code != 0
    assert "not a hex Ed25519 private key" in result.output


def test_certify_honors_an_import_policy_file_and_skips_pycache(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    # A stale bytecode cache inside the artifact must not become a packaged
    # source file.
    package["payload"].write_bytes(
        _wheel_bytes(
            ("acme_chart/main.py", PLUGIN_SOURCE),
            ("acme_chart/__pycache__/main.cpython-312.pyc", b""),
            ("acme_chart/__pycache__/rogue.py", b"import maistro._hidden\n"),
        )
    )
    _refresh_artifact_claim(package)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"public_namespaces": ["maistro"]}))

    result = _certify(package, out, "--import-policy", str(policy))

    assert result.exit_code == 0, result.output
    assert "imports.public-sdk-only" in result.output


def test_certify_scans_the_payload_not_a_side_directory(tmp_path: Any) -> None:
    """The static scans read the artifact's own sources — nothing else.

    Regression for the review finding that a benign ``--source-dir`` could
    be paired with a malicious wheel: with sources extracted from the
    payload, a wheel whose code violates the import policy cannot ride on
    an unrelated clean tree.
    """
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    package["payload"].write_bytes(
        _wheel_bytes(("acme_chart/main.py", b"import maistro._hidden\n"))
    )
    _refresh_artifact_claim(package)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"public_namespaces": ["maistro"]}))

    result = _certify(package, out, "--profile", "publication", "--import-policy", str(policy))

    assert result.exit_code != 0
    assert "NOT CERTIFIED" in result.output
    assert "maistro._hidden" in result.output


def test_certify_non_zip_payload_scans_no_sources(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    package["payload"].write_bytes(b"extension-payload-v1")
    _refresh_artifact_claim(package)

    result = _certify(package, out, "--profile", "publication")

    assert result.exit_code != 0
    report = json.loads((out / "report.json").read_text())
    not_applicable = {
        check["id"] for check in report["checks"] if check["outcome"] == "not_applicable"
    }
    assert not_applicable, report


def _refresh_artifact_claim(package: dict[str, Path]) -> None:
    """Re-align a package manifest's artifact claim with its mutated payload."""
    payload = package["payload"].read_bytes()
    manifest = json.loads(package["manifest"].read_text())
    manifest["artifact"] = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }
    package["manifest"].write_text(json.dumps(manifest))


def test_certify_writes_no_files_when_none_are_requested(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")

    result = runner.invoke(
        app,
        [
            "certify",
            "--manifest",
            str(package["manifest"]),
            "--payload",
            str(package["payload"]),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "CERTIFIED" in result.output


def test_verify_certification_refuses_an_unreadable_report(tmp_path: Any) -> None:
    package = _write_package(tmp_path / "pkg")
    out = tmp_path / "out"
    out.mkdir()
    assert _certify(package, out).exit_code == 0
    (out / "report.json").write_text("{broken json")

    result = _verify(package, out)

    assert result.exit_code != 0
    assert "Cannot load certification" in result.output
