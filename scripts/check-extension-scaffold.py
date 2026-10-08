#!/usr/bin/env python3
"""Fixture: the scaffold builds, tests, conforms, and certifies out of tree (M9-H1 #973, M9-H3 #975).

What this proves
----------------
`check-extension-imports.py` reads generated imports statically, and the
SDK's own suite validates the scaffold's manifest in process. This fixture
makes the epic's first acceptance physical, for **every family template**:

1. scaffolds a project with ``maistro-ext-sdk new``;
2. **builds** it as a wheel with ``uv build``;
3. **creates a fresh venv** and installs into it exactly: the scaffolded
   wheel, the public SDK wheel, the harness wheel, pytest, and the signing
   extra's ``cryptography`` — nothing from the repository;
4. **asserts the venv is clean**: every product-private root from the
   namespace policy, plus the repo-relative sentinels ``packages`` and
   ``extensions``, must be UNIMPORTABLE from that venv;
5. **validates** the scaffolded manifest with the installed SDK's CLI (the
   acceptance "generated manifest passes public schema validation", run
   from the installed distribution, not the checkout);
6. **runs the staged copy of the generated sample tests** with the venv
   interpreter from a neutral working directory — the acceptance
   "scaffolded project builds/tests in a clean directory outside the
   MAIstro repo";
7. **runs the harness conformance suite** over the scaffolded project and
   **certifies** it: package checks, security checks, conformance, digest,
   an Ed25519 signature, and a certification report — then
   **verify-certification** against the publisher key, and finally a
   negative control: one mutated byte in the artifact must flip
   verification to exit 1 (a verifier that accepts anything proves
   nothing);
8. certifies the **repository's built-in reference extension** through the
   same installed harness — built-in and external-style subjects, one
   tooling (epic acceptance).

Usage
-----
    python3 scripts/check-extension-scaffold.py
    python3 scripts/check-extension-scaffold.py --family tool
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / "extensions" / "namespace-policy.json"
SDK_PACKAGE_DIR = REPO_ROOT / "packages" / "maistro-ext-sdk"
HARNESS_PACKAGE_DIR = REPO_ROOT / "packages" / "maistro-ext-harness"
REFERENCE_EXTENSION = REPO_ROOT / "extensions" / "reference-greeter"

#: Repo-relative sentinels probed alongside the policy's private roots.
_REPO_RELATIVE_SENTINELS = ("packages", "extensions")

#: The families the scaffold ships templates for — the manifest's closed
#: vocabulary. One scaffold-and-certify round trip each.
FAMILIES = ("tool", "skill", "mcp-gateway", "capability-provider", "renderer-plugin")

_SUBPROCESS_TIMEOUT_S = 900


class FixtureError(RuntimeError):
    """A configuration or execution failure of the fixture itself."""


@dataclass(frozen=True)
class Step:
    """One executed command and what it was for (printed on failure)."""

    description: str
    argv: tuple[str, ...]
    cwd: Path | None = None
    expect_failure: bool = False
    """Negative controls: the command succeeding is the violation."""


def clean_env() -> dict[str, str]:
    """No inherited interpreter state: the levers that could smuggle the
    repository into the fresh venv are removed, so the negative control is
    meaningful on a developer machine as well as in CI."""
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def _run(step: Step) -> str:
    print(f"  · {step.description}")
    result = subprocess.run(
        step.argv,
        cwd=step.cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    expected = step.expect_failure
    if (result.returncode != 0) == expected:
        return result.stdout
    verdict = "failed" if not expected else "succeeded where it must not"
    raise FixtureError(
        f"{step.description} {verdict} (exit {result.returncode}):\n"
        f"  command: {' '.join(step.argv)}\n"
        f"  stdout:\n{result.stdout}\n  stderr:\n{result.stderr}"
    )


def build_first_party_wheels(dist: Path) -> tuple[Path, Path]:
    """Build the SDK and harness wheels the fresh venvs install."""
    print("· building first-party wheels (maistro-ext-sdk, maistro-ext-harness)")
    _run(
        Step(
            "build maistro-ext-sdk wheel",
            ("uv", "build", "--wheel", "--out-dir", str(dist)),
            cwd=SDK_PACKAGE_DIR,
        )
    )
    _run(
        Step(
            "build maistro-ext-harness wheel",
            ("uv", "build", "--wheel", "--out-dir", str(dist)),
            cwd=HARNESS_PACKAGE_DIR,
        )
    )
    sdk_wheel = dist / "maistro_ext_sdk-0.9.0-py3-none-any.whl"
    harness_wheel = dist / "maistro_ext_harness-0.9.0-py3-none-any.whl"
    for wheel in (sdk_wheel, harness_wheel):
        if not wheel.is_file():
            built = sorted(p.name for p in dist.glob("*.whl"))
            raise FixtureError(f"expected {wheel.name} after building; dist holds {built}")
    return sdk_wheel, harness_wheel


def generate_signing_key(venv_python: Path, key_file: Path) -> str:
    """A fresh Ed25519 seed via the venv (the signing extra is installed).

    Prints the private seed (saved to ``key_file``) and the publisher key
    (returned for ``--publisher-key``) — one process, no key on any argv.
    """
    out = _run(
        Step(
            "generate a fresh Ed25519 signing key",
            (
                str(venv_python),
                "-c",
                "from cryptography.hazmat.primitives.asymmetric.ed25519 import "
                "Ed25519PrivateKey; k = Ed25519PrivateKey.generate(); "
                "print(k.private_bytes_raw().hex()); "
                "print(k.public_key().public_bytes_raw().hex())",
            ),
        )
    )
    lines = out.strip().splitlines()
    if len(lines) != 2:
        raise FixtureError(f"unexpected key-generator output: {out!r}")
    private_hex, publisher_key = (line.strip() for line in lines)
    key_file.write_text(private_hex, encoding="utf-8")
    return publisher_key


def scaffold_round_trip(
    family: str,
    workdir: Path,
    sdk_wheel: Path,
    harness_wheel: Path,
    private_roots: tuple[str, ...],
) -> None:
    """The full lifecycle for one family template, in fresh venvs."""
    home = workdir / family
    project = home / "proj"
    dist = home / "dist"
    venv = home / "venv"
    venv_python = venv / "bin" / "python"
    venv_sdk = venv / "bin" / "maistro-ext-sdk"
    venv_harness = venv / "bin" / "maistro-ext-harness"
    sandbox = home / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    print(f"· family {family}: scaffold → build → install → test → conform → certify")

    _run(
        Step(
            f"scaffold the {family} project (with the built SDK wheel, not the checkout)",
            (
                "uv",
                "run",
                "--no-project",
                "--with",
                str(sdk_wheel),
                "python",
                "-m",
                "maistro_ext_sdk.cli",
                "new",
                "widget",
                "--publisher",
                "gate",
                "--family",
                family,
                "--out",
                str(project),
            ),
            cwd=REPO_ROOT,
        )
    )
    _run(
        Step(
            f"build the {family} scaffold's wheel",
            ("uv", "build", "--wheel", "--out-dir", str(dist)),
            cwd=project,
        )
    )
    wheels = list(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise FixtureError(f"{family}: expected exactly one scaffold wheel, got {wheels}")
    scaffold_wheel = wheels[0]

    _run(Step("create the fresh venv", ("uv", "venv", str(venv), "--python", sys.executable)))
    _run(
        Step(
            "install scaffold + SDK + harness + pytest + signing into the fresh venv",
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(venv_python),
                str(scaffold_wheel),
                str(sdk_wheel),
                str(harness_wheel),
                "pytest",
                "cryptography",
            ),
        )
    )

    # The tooling venv deliberately installs the SDK and the harness — they
    # ARE the developer tools under test. What must be absent is every OTHER
    # product root and the repo-relative sentinels: the extension could not
    # reach product internals from this venv even if its code tried (and the
    # certify run below scans its imports for exactly that).
    forbidden = tuple(
        root
        for root in (*private_roots, *_REPO_RELATIVE_SENTINELS)
        if root not in ("maistro_ext_sdk", "maistro_ext_harness")
    )
    for root in forbidden:
        _run(
            Step(
                f"product root {root!r} is unimportable from the fresh venv",
                (str(venv_python), "-c", f"import {root}"),
                # Neutral cwd: from the repository root, `import packages`
                # resolves as a cwd namespace package — the checkout leaking
                # in through sys.path[0], not through the venv.
                cwd=sandbox,
                expect_failure=True,
            )
        )

    _run(
        Step(
            "the generated manifest validates from the installed SDK",
            (str(venv_sdk), "validate", str(project)),
        )
    )

    staged_tests = sandbox / "tests"
    shutil.rmtree(staged_tests, ignore_errors=True)
    shutil.copytree(
        project / "tests",
        staged_tests,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    _run(
        Step(
            "the generated sample tests pass with the fresh venv's interpreter",
            (
                str(venv_python),
                "-m",
                "pytest",
                str(staged_tests),
                "-q",
                "--import-mode=importlib",
                "--strict-markers",
                "--rootdir",
                str(staged_tests.parent),
                "--confcutdir",
                str(staged_tests.parent),
                "-p",
                "no:cacheprovider",
            ),
        )
    )

    _run(
        Step(
            "the harness conformance suite passes over the scaffolded project",
            (
                str(venv_harness),
                "run",
                "--path",
                str(project),
                "--report",
                str(home / "conformance.json"),
            ),
        )
    )

    key_file = home / "signing-key.hex"
    publisher_key = generate_signing_key(venv_python, key_file)
    _run(
        Step(
            "certify the scaffolded artifact (sign with the fresh key)",
            (
                str(venv_harness),
                "certify",
                "--path",
                str(project),
                "--artifact",
                str(scaffold_wheel),
                "--signing-key-file",
                str(key_file),
                "--report",
                str(home / "certification.json"),
            ),
        )
    )
    _run(
        Step(
            "verify-certification accepts the signed artifact",
            (
                str(venv_harness),
                "verify-certification",
                "--report",
                str(home / "certification.json"),
                "--artifact",
                str(scaffold_wheel),
                "--publisher-key",
                publisher_key,
            ),
        )
    )

    # Negative control: flip the artifact's last byte; the verifier must
    # refuse (exit 1), or verification proves nothing.
    mutated = home / "mutated.whl"
    data = bytearray(scaffold_wheel.read_bytes())
    data[-1] ^= 0xFF
    mutated.write_bytes(bytes(data))
    _run(
        Step(
            "verify-certification refuses a mutated artifact (negative control)",
            (
                str(venv_harness),
                "verify-certification",
                "--report",
                str(home / "certification.json"),
                "--artifact",
                str(mutated),
                "--publisher-key",
                publisher_key,
            ),
            expect_failure=True,
        )
    )


def _public_key_from_report(report_path: Path) -> str:
    document = json.loads(report_path.read_text(encoding="utf-8"))
    signature = document.get("signature", {})
    if not signature.get("signed"):
        raise FixtureError(f"{report_path} carries no signature to verify")
    return str(signature["public_key"])


def certify_reference_extension(
    workdir: Path,
    harness_wheel: Path,
    sdk_wheel: Path,
    private_roots: tuple[str, ...],
) -> None:
    """The built-in reference extension certifies through the same tooling."""
    home = workdir / "reference-greeter"
    dist = home / "dist"
    venv = home / "venv"
    venv_python = venv / "bin" / "python"
    venv_harness = venv / "bin" / "maistro-ext-harness"
    print("· reference extension: build → certify → verify (same installed harness)")

    _run(
        Step(
            "build the reference extension's wheel",
            ("uv", "build", "--wheel", "--out-dir", str(dist)),
            cwd=REFERENCE_EXTENSION,
        )
    )
    wheels = list(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise FixtureError(f"reference extension: expected one wheel, got {wheels}")
    reference_wheel = wheels[0]

    _run(Step("create the fresh venv", ("uv", "venv", str(venv), "--python", sys.executable)))
    _run(
        Step(
            "install reference wheel + SDK + harness into the fresh venv",
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(venv_python),
                str(reference_wheel),
                str(sdk_wheel),
                str(harness_wheel),
                "cryptography",
            ),
        )
    )
    # Same rule as the scaffold venvs: sdk + harness are the installed
    # tools; every other product root must be absent.
    for root in (
        r
        for r in (*private_roots, *_REPO_RELATIVE_SENTINELS)
        if r not in ("maistro_ext_sdk", "maistro_ext_harness")
    ):
        _run(
            Step(
                f"product root {root!r} is unimportable from the fresh venv",
                (str(venv_python), "-c", f"import {root}"),
                cwd=home,
                expect_failure=True,
            )
        )

    key_file = home / "signing-key.hex"
    generate_signing_key(venv_python, key_file)
    _run(
        Step(
            "certify the reference extension's wheel",
            (
                str(venv_harness),
                "certify",
                "--path",
                str(REFERENCE_EXTENSION),
                "--artifact",
                str(reference_wheel),
                "--signing-key-file",
                str(key_file),
                "--report",
                str(home / "certification.json"),
            ),
        )
    )
    _run(
        Step(
            "verify-certification accepts the reference certification",
            (
                str(venv_harness),
                "verify-certification",
                "--report",
                str(home / "certification.json"),
                "--artifact",
                str(reference_wheel),
                "--publisher-key",
                _public_key_from_report(home / "certification.json"),
            ),
        )
    )


def load_policy(path: Path) -> tuple[str, ...]:
    """The product-private roots, straight from the namespace policy."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureError(f"policy file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"policy file is not valid JSON: {path}: {exc}") from exc
    roots = raw.get("product_private_namespaces")
    if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
        raise FixtureError("policy product_private_namespaces must be a list of strings")
    return tuple(roots)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--family",
        choices=FAMILIES,
        action="append",
        help="limit to one family (repeatable); default: every family",
    )
    args = parser.parse_args()
    families = tuple(args.family) if args.family else FAMILIES

    private_roots = load_policy(args.policy)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ext-scaffold-gate-") as tmp:
        workdir = Path(tmp)
        dist = workdir / "first-party"
        sdk_wheel, harness_wheel = build_first_party_wheels(dist)
        for family in families:
            try:
                scaffold_round_trip(family, workdir, sdk_wheel, harness_wheel, private_roots)
            except FixtureError as exc:
                failures.append(f"[{family}] {exc}")
        if not failures:
            try:
                certify_reference_extension(workdir, harness_wheel, sdk_wheel, private_roots)
            except FixtureError as exc:
                failures.append(f"[reference-greeter] {exc}")

    if failures:
        print("\nThe scaffold gate FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"\nScaffold gate passed: {len(families)} family template(s) scaffolded, "
        "built, tested, conformed, certified, signed, verified (and the negative "
        "control refused) — plus the built-in reference extension through the "
        "same tooling."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FixtureError as exc:
        print(f"scaffold gate error: {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
