#!/usr/bin/env python3
"""Verify the declared dependency floors install and import the OIDC path (#1100).

Why this exists
---------------
PR #1073 made OIDC verification mandatory and, in doing so, made the auth
modules unconditionally import specific PyJWT APIs (``MissingCryptographyError``,
``PyJWKClient``). The published ``pyjwt`` floor advertised versions the code did
not work with, and only the workspace lockfile -- which a consumer installing
the published wheel never reads -- held a working resolution. Issue #1100: the
declared range itself must produce an importable, supported product, and the
fix must not be satisfiable by moving the lock alone.

``verify-wheel-imports.py`` installs wheels with dependencies at the CURRENT
released versions, so it cannot catch a stale floor: code that needs a newer
API imports fine at latest. This script resolves the DECLARED floors instead
(``uv pip install --resolution lowest-direct`` against the package source) and
proves, in the result:

  1. the floor set installs cleanly -- every declared lower bound is an
     installable release, not just the newest one (#1100 also caught
     ``pyyaml>=6.0`` here: 6.0 has no CPython 3.12 wheels and its sdist does
     not build under Cython >=3.1);
  2. the OIDC/auth modules import there, including the version-sensitive
     imports the issue is about;
  3. PyJWT itself resolved to the declared floor -- proving the environment is
     the minimum, not the current set in disguise;
  4. removing PyJWT still fails closed at import with the #856 actionable
     error, so a minimum install never means a downgraded verifier.

Usage
-----
    python scripts/verify-minimum-dependencies.py --python 3.12
    python scripts/verify-minimum-dependencies.py \\
        --package packages/maistro-core --python 3.12
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

#: The dependency whose floor the gate pins to the minimum. The issue is about
#: PyJWT, but the install covers every declared dependency of the package --
#: this is only the one whose resolved version is asserted to be the floor.
FLOOR_DEPENDENCY = "pyjwt"

#: The modules whose import at the floor versions the issue requires. The OIDC
#: verifier path (#856/#1073): the mandatory-verification module, the JWKS
#: bearer verifier and the demo-cookie verifier -- the three files that
#: unconditionally import PyJWT.
DEFAULT_MODULES = [
    "maistro.auth.oauth",
    "maistro.security.auth_jwt",
    "maistro.security.auth_demo_cookie",
]

#: The two imports PR #1073 added that motivated #1100: an exception and a
#: client class a stale floor was believed not to expose. Asserted explicitly
#: so a module-level import being made lazy cannot silently shrink the gate.
VERSION_SENSITIVE_IMPORTS = [
    ("jwt.exceptions", "MissingCryptographyError"),
    ("jwt", "PyJWKClient"),
]

#: Runs inside the floor venv. Prints one JSON object so the parent reports
#: every failure at once instead of stopping at the first.
PROBE_MINIMUM = r"""
import importlib, importlib.metadata, json, sys

targets = sys.argv[1].split(",")
floor_dependency = sys.argv[2]

checked, failures, versions = [], [], {}


def record(name, fn):
    checked.append(name)
    try:
        fn()
    except BaseException as exc:            # noqa: BLE001 - report, never mask
        failures.append({"check": name, "error": f"{type(exc).__name__}: {exc}"})


def dist_version(name):
    versions[name] = importlib.metadata.version(name)


def module_version():
    import jwt

    versions["jwt.__version__"] = jwt.__version__


record(f"dist version of {floor_dependency}", lambda: dist_version(floor_dependency))
record("import jwt", module_version)
for symbol_module, symbol in json.loads(sys.argv[3]):
    record(
        f"from {symbol_module} import {symbol}",
        lambda sm=symbol_module, s=symbol: getattr(importlib.import_module(sm), s),
    )
for name in targets:
    record(f"import {name}", lambda n=name: importlib.import_module(n))

print(json.dumps({"checked": len(checked), "failures": failures, "versions": versions}))
"""

#: Runs in a second interpreter of the same floor venv, with PyJWT made
#: unimportable before any import runs (the tests/auth/test_mandatory_verification.py
#: meta_path pattern): a minimum install must refuse to load the OIDC module
#: with the #856 actionable error, never degrade verification.
PROBE_FAIL_CLOSED = r"""
import json, sys

blocked = sys.argv[1].split(",")


class _Blocked:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"blocked: {name}", name=name)
        return None


sys.meta_path.insert(0, _Blocked())

try:
    import maistro.auth.oauth  # noqa: F401
except ImportError as exc:
    message = str(exc)
    refused = "pyjwt" in message.lower() and "fails closed" in message.lower()
    print(json.dumps({"refused": refused, "error": message}))
    sys.exit(0 if refused else 1)

print(json.dumps({"refused": False, "error": "maistro.auth.oauth imported without pyjwt"}))
sys.exit(1)
"""


def _run(
    cmd: list[str], **kw: object
) -> subprocess.CompletedProcess[
    str
]:  # pragma: no cover - only reachable through check()'s subprocess driving
    return subprocess.run(cmd, text=True, capture_output=True, check=False, **kw)  # type: ignore[call-overload,no-any-return]


def declared_requirement(package_dir: Path, dependency: str) -> str:
    """The package's declared requirement string for ``dependency``."""
    with (package_dir / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("project", {}).get("dependencies", [])
    for dep in deps:
        name = re.split(r"[\[>=<;! \n]", dep.strip(), maxsplit=1)[0].strip()
        if name.lower() == dependency.lower():
            return dep.strip()
    raise SystemExit(
        f"error: {package_dir}/pyproject.toml declares no {dependency!r} dependency (found: {deps})"
    )


def derive_floor(requirement: str) -> tuple[int, ...]:
    """Lowest version the requirement permits, from its ``>=`` clause.

    Only the ``>=VERSION`` form is supported -- every floor in this repository
    uses it (``>=2.14,<3``, ``>=50.0.0,<51``). Anything else (wildcards,
    ``~=``, ``==``) fails loudly rather than silently gating nothing.
    """
    if re.search(r">=\s*[^,;]*\*", requirement):
        raise SystemExit(
            f"error: cannot derive a floor from {requirement!r}: wildcard in the "
            ">= clause. supported form: 'name[extras]>=X.Y[.Z],<upper'"
        )
    match = re.search(r">=\s*(\d+(?:\.\d+)*)", requirement)
    if match is None:
        raise SystemExit(
            f"error: cannot derive a floor from {requirement!r}: no >=VERSION clause. "
            "supported form: 'name[extras]>=X.Y[.Z],<upper'"
        )
    return tuple(int(part) for part in match.group(1).split("."))


def floor_resolved(resolved: str, floor: tuple[int, ...]) -> bool:
    """True when the resolved version IS the floor (prefix-equal releases).

    ``--resolution lowest-direct`` must pick exactly the declared floor for the
    gated dependency. If it resolved anything newer, the environment would be
    the current dependency set wearing a minimum-deps label, and checks 1-4
    would prove nothing about what a floor-pinned consumer gets.
    """
    parts = re.match(r"(\d+(?:\.\d+)*)", resolved)
    if parts is None:
        return False
    release = tuple(int(part) for part in parts.group(1).split("."))
    return release[: len(floor)] == floor and len(release) >= len(floor)


def _probe_env() -> dict[str, str]:
    # Same scrub as verify-wheel-imports.py: an inherited PYTHONPATH or
    # VIRTUAL_ENV could let the repo tree satisfy an import the floor install
    # cannot, which is precisely the failure this gate exists to expose.
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    env["UV_NO_CONFIG"] = "1"
    return env


def _floor_assertion(versions: dict[str, str], floor: tuple[int, ...]) -> str | None:
    dist = versions.get(FLOOR_DEPENDENCY)
    if dist is None:
        return f"{FLOOR_DEPENDENCY} dist metadata unreadable in the floor venv"
    if not floor_resolved(dist, floor):
        return (
            f"floor venv resolved {FLOOR_DEPENDENCY} {dist}, not the declared floor "
            f"{'.'.join(map(str, floor))} -- --resolution lowest-direct did not apply "
            "to the package's direct dependencies, so this run did not test the minimum"
        )
    return None


def render(result: dict, floor: tuple[int, ...]) -> tuple[bool, str]:
    """Turn the probe payload into an (ok, detail) pair, floor check included."""
    failures = list(result["failures"])
    floor_problem = _floor_assertion(result.get("versions", {}), floor)
    if floor_problem:
        failures.append({"check": "pyjwt resolved at the declared floor", "error": floor_problem})
    versions = result.get("versions", {})
    resolved = versions.get(FLOOR_DEPENDENCY, "?")
    if failures:
        lines = [
            f"{len(failures)} of {result['checked']} floor check(s) failed "
            f"({FLOOR_DEPENDENCY} resolved {resolved}):"
        ]
        for f in failures:
            lines.append(f"  {f['check']}: {f['error']}")
        return False, "\n".join(lines)
    return True, f"{result['checked']} check(s) passed ({FLOOR_DEPENDENCY} resolved {resolved})"


def check(
    package_dir: Path, modules: list[str], uv: str, py: str
) -> tuple[bool, str]:  # pragma: no cover - end-to-end producer is ci.yml/release.yml, not pytest
    """Install the package's floors into a fresh venv and probe it.

    Every pure decision this function makes on the probe payload is unit-tested
    (`render`, `_floor_assertion`); the body below drives real `uv`/subprocess
    work against PyPI, so its producer is the gate's own end-to-end run -- the
    `ci.yml` and `release.yml` steps that execute this script, not the pytest
    suite. Marking it out of the per-line scorer is the same idiom as the
    broken-install guard in `maistro/auth/oauth.py`: the lines run, just not
    under the unit interpreter.
    """
    requirement = declared_requirement(package_dir, FLOOR_DEPENDENCY)
    floor = derive_floor(requirement)
    print(f"declared {FLOOR_DEPENDENCY} requirement: {requirement}")
    print(f"floor under test: {'.'.join(map(str, floor))}")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        venv = tmpdir / ".venv"

        made = _run([uv, "venv", "--python", py, str(venv)], cwd=tmpdir, env=_probe_env())
        if made.returncode != 0:
            return False, f"uv venv failed:\n{made.stderr.strip()}"

        # lowest-direct: the package's DIRECT dependencies resolve to their
        # declared floors, transitives to current. Installing the source
        # directory (not a wheel) is what makes uv treat [project.dependencies]
        # as direct; a wheel's Requires-Dist resolve as transitive and the
        # floors would be ignored silently.
        install = _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv),
                "--resolution",
                "lowest-direct",
                str(package_dir),
            ],
            cwd=tmpdir,
            env=_probe_env(),
        )
        if install.returncode != 0:
            return False, (
                "the declared floors do not resolve to an installable environment:\n"
                f"{install.stderr.strip()[-2000:]}\n"
                "Fix by raising the failing dependency's floor to the earliest release "
                "that installs (#1100) -- not by widening the range or editing the "
                "lockfile only."
            )

        python = venv / "bin" / "python"
        if not python.exists():  # Windows layout
            python = venv / "Scripts" / "python.exe"

        # cwd must not be an ancestor of the venv (see verify-wheel-imports.py:
        # an import hook in a transitive dependency refuses imports that
        # resolve inside the cwd), and must not be the repo tree.
        probe_cwd = tmpdir / "probe-cwd"
        probe_cwd.mkdir(exist_ok=True)

        probe = _run(
            [
                str(python),
                "-c",
                PROBE_MINIMUM,
                ",".join(modules),
                FLOOR_DEPENDENCY,
                json.dumps([list(pair) for pair in VERSION_SENSITIVE_IMPORTS]),
            ],
            cwd=probe_cwd,
            env=_probe_env(),
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            return False, f"probe crashed:\n{probe.stdout.strip()}\n{probe.stderr.strip()[-2000:]}"
        ok, detail = render(json.loads(probe.stdout.strip().splitlines()[-1]), floor)
        if not ok:
            return False, detail

        closed = _run(
            [str(python), "-c", PROBE_FAIL_CLOSED, "jwt"],
            cwd=probe_cwd,
            env=_probe_env(),
        )
        if closed.returncode != 0 or not closed.stdout.strip():
            return False, (
                "fail-closed probe crashed:\n"
                f"{closed.stdout.strip()}\n{closed.stderr.strip()[-2000:]}"
            )
        verdict = json.loads(closed.stdout.strip().splitlines()[-1])
        if not verdict["refused"]:
            return False, (
                "fail-closed probe did not refuse: "
                f"{verdict['error']} -- a minimum install must refuse the OIDC module "
                "with the #856 actionable error, never degrade verification"
            )
        return True, detail + "; PyJWT-removal refusal intact"


def main() -> int:  # pragma: no cover - CLI plumbing; its logic is unit-covered
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        type=Path,
        default=Path("packages/maistro-core"),
        help="package source directory whose declared floors are installed",
    )
    parser.add_argument(
        "--python",
        default=f"{sys.version_info.major}.{sys.version_info.minor}",
        help="interpreter version for the throwaway venv (default: the running one)",
    )
    args = parser.parse_args()

    uv = shutil.which("uv")
    if uv is None:
        print("error: uv not on PATH", file=sys.stderr)
        return 2
    package_dir = args.package.resolve()
    if not (package_dir / "pyproject.toml").is_file():
        print(f"error: {package_dir}/pyproject.toml not found", file=sys.stderr)
        return 2

    print(f"=== minimum supported dependencies ({package_dir.name}, Python {args.python}) ===")
    ok, detail = check(package_dir, DEFAULT_MODULES, uv, args.python)
    print(f"  {'ok  ' if ok else 'FAIL'} {package_dir.name}: {detail}")
    if not ok:
        print(
            "\nA failure here means the published dependency range does not produce an\n"
            "importable product at its own floors. Raise the stale floor on the package\n"
            "that declares it -- never satisfy this gate by moving the lockfile alone\n"
            "(#1100: consumers of the published wheel never read uv.lock)."
        )
        return 1
    print(f"\nMinimum supported dependencies install and import (Python {args.python}).")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry; main()'s logic is unit-covered
    sys.exit(main())
