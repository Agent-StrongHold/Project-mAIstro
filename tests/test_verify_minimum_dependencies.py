"""Tests for the minimum-supported-dependencies floor gate (#1100).

#1100's failure mode is invisible to every other gate: a published dependency
floor that advertises versions the mandatory OIDC verifier does not import on,
while the workspace lockfile -- which a consumer of the published wheel never
reads -- resolves something newer. `verify-wheel-imports.py` installs at
CURRENT versions, so it passes either way.

The gate itself (`scripts/verify-minimum-dependencies.py`) resolves the
DECLARED floors in a throwaway venv and imports the OIDC/auth modules there;
that end-to-end run belongs to CI (release.yml and ci.yml both execute it --
asserted below, because a gate no workflow references is not a gate). What is
unit-proven here is everything that does not need the five-minute install:

- the floor derivation and the "resolved == floor" prefix check, including
  their degenerate inputs;
- the declared floors themselves: maistro-core must keep a PyJWT floor at or
  above the verified minimum, and both in-tree consumers of the published
  range must agree on it (the "metadata and documentation agree" criterion);
- the JWT API inventory the three verifier modules import resolves on the
  installed PyJWT -- the fast, in-suite complement to the CI run at the floor;
- the fail-closed probe both detects a module that refuses without PyJWT and
  rejects one that silently imports (the downgrade case is what it exists to
  catch, so the degenerate path is exercised, not assumed).
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-minimum-dependencies.py"

#: The three modules whose unconditional PyJWT imports #1073 introduced and
#: #1100 gates. Keep in step with the script's DEFAULT_MODULES.
OIDC_SOURCES = [
    "packages/maistro-core/src/maistro/auth/oauth.py",
    "packages/maistro-core/src/maistro/security/auth_jwt.py",
    "packages/maistro-core/src/maistro/security/auth_demo_cookie.py",
]


@pytest.fixture(scope="module")
def gate():
    spec = spec_from_file_location("verify_minimum_dependencies", SCRIPT)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestFloorDerivation:
    def test_extras_and_upper_bound_reduce_to_the_lower_bound(self, gate):
        assert gate.derive_floor("pyjwt[crypto]>=2.14,<3") == (2, 14)

    def test_patch_precision_is_preserved(self, gate):
        assert gate.derive_floor("cryptography>=50.0.0,<51") == (50, 0, 0)

    def test_no_lower_bound_is_an_error_not_a_zero_floor(self, gate):
        """A range with no >= clause gates nothing; refuse to run."""
        with pytest.raises(SystemExit, match="no >=VERSION clause"):
            gate.derive_floor("pyjwt[crypto]<3")

    def test_wildcard_lower_bound_is_an_error(self, gate):
        """>=2.14.* is not a floor a resolver can install; refuse to guess 2.14."""
        with pytest.raises(SystemExit, match="wildcard"):
            gate.derive_floor("pyjwt[crypto]>=2.14.*,<3")

    @pytest.mark.parametrize(
        ("resolved", "floor", "expected"),
        [
            ("2.14.0", (2, 14), True),
            ("2.14", (2, 14), True),
            ("2.15.1", (2, 14), False),
            ("3.0.0", (2, 14), False),
        ],
    )
    def test_floor_resolved_requires_the_exact_floor(self, gate, resolved, floor, expected):
        assert gate.floor_resolved(resolved, floor) is expected

    def test_a_release_shorter_than_the_floor_is_not_the_floor(self, gate):
        """`2.14` cannot be the floor (2, 14, 0): the environment must be at
        least as precise as the declaration, otherwise the check below proves
        less than it claims."""
        assert gate.floor_resolved("2.14", (2, 14, 0)) is False

    def test_an_unparsable_resolved_version_is_not_the_floor(self, gate):
        assert gate.floor_resolved("unknown", (2, 14)) is False


class TestProbeEnvironment:
    def test_the_probe_env_cannot_inherit_the_repo(self, gate, monkeypatch):
        """An inherited PYTHONPATH or VIRTUAL_ENV would let the repo tree
        satisfy an import the floor install cannot -- the exact leak this gate
        exists to expose -- and a workspace uv config could redirect the
        resolution away from PyPI's floors."""
        monkeypatch.setenv("PYTHONPATH", "/repo/packages/maistro-core/src")
        monkeypatch.setenv("VIRTUAL_ENV", "/some/other/venv")
        monkeypatch.setenv("UV_NO_CONFIG", "")
        monkeypatch.setenv("KEEP_ME", "yes")
        env = gate._probe_env()
        assert "PYTHONPATH" not in env
        assert "VIRTUAL_ENV" not in env
        assert env["UV_NO_CONFIG"] == "1"
        assert env["KEEP_ME"] == "yes"


class TestFloorAssertion:
    def test_a_missing_dist_version_is_reported(self, gate):
        problem = gate._floor_assertion({}, (2, 14))
        assert problem is not None and "unreadable" in problem

    def test_resolving_above_the_floor_means_the_minimum_was_not_tested(self, gate):
        """The #1100 failure in miniature: an environment that resolved the
        current release is the current set wearing a minimum-deps label, and
        checks 1-4 would have proven nothing about the floor."""
        problem = gate._floor_assertion({"pyjwt": "2.15.1"}, (2, 14))
        assert problem is not None and "not the declared floor" in problem

    def test_resolving_the_floor_is_silent(self, gate):
        assert gate._floor_assertion({"pyjwt": "2.14.0"}, (2, 14)) is None


class TestRender:
    def test_a_clean_probe_at_the_floor_passes_with_the_resolution_named(self, gate):
        ok, detail = gate.render(
            {"checked": 7, "failures": [], "versions": {"pyjwt": "2.14.0"}}, (2, 14)
        )
        assert ok is True
        assert "7 check(s) passed" in detail and "2.14.0" in detail

    def test_a_probe_failure_is_reported_per_check(self, gate):
        ok, detail = gate.render(
            {
                "checked": 7,
                "failures": [{"check": "import maistro.auth.oauth", "error": "Boom: no"}],
                "versions": {"pyjwt": "2.14.0"},
            },
            (2, 14),
        )
        assert ok is False
        assert "import maistro.auth.oauth" in detail and "Boom: no" in detail

    def test_a_floor_mismatch_fails_even_when_every_import_passed(self, gate):
        """Imports can succeed on the current set; only the resolution proves
        the run was about the minimum, so a wrong resolution fails the render
        on its own."""
        ok, detail = gate.render(
            {"checked": 7, "failures": [], "versions": {"pyjwt": "2.15.1"}}, (2, 14)
        )
        assert ok is False
        assert "not the declared floor" in detail


class TestDeclaredFloors:
    def test_core_pyjwt_floor_stays_at_or_above_the_verified_minimum(self, gate):
        """2.14 is the CVE-2026-102274 fix (#1685) and empirically exposes every
        API the verifiers import -- the CI gate runs at exactly it. A floor
        below 2.14 re-opens either the advisory or an unverified API set, so
        the declaration may only move up."""
        requirement = gate.declared_requirement(
            ROOT / "packages/maistro-core", gate.FLOOR_DEPENDENCY
        )
        assert gate.derive_floor(requirement) >= (2, 14), requirement

    def test_both_consumers_of_the_published_range_agree_on_the_floor(self, gate):
        """#1100's "metadata and documentation agree" criterion: the published
        wheel metadata and hive-conductor's no-lockfile requirements file must
        state the same PyJWT floor, or one install path silently keeps the
        vulnerable range the other fixed."""
        core = gate.declared_requirement(ROOT / "packages/maistro-core", "pyjwt")
        text = (ROOT / "packages/hive-conductor/backend/requirements.txt").read_text(
            encoding="utf-8"
        )
        line = next(
            stripped for raw in text.splitlines() if (stripped := raw.strip()).startswith("pyjwt")
        )
        assert gate.derive_floor(core) == gate.derive_floor(line), f"{core!r} vs {line!r}"


def _jwt_api_inventory(path: Path) -> tuple[set[str], set[tuple[str, str]]]:
    """(attributes used as ``pyjwt.X``, (module, symbol) from-imports of jwt).

    Line-based on purpose: a regex over the whole file cannot tell where a
    single-line ``from jwt import X`` ends and the surrounding code begins.
    """
    src = path.read_text(encoding="utf-8")
    attrs = set(re.findall(r"\bpyjwt\.([A-Za-z_]\w*)", src))
    froms: set[tuple[str, str]] = set()
    for line in src.splitlines():
        match = re.match(r"\s*from (jwt(?:\.\w+)*) import (.+?)\s*$", line)
        if match is None:
            continue
        names, module = match.group(2).strip(), match.group(1)
        if names.startswith("("):
            # Parenthesized multi-line import: the continuation lines are not
            # `from jwt` lines, so refuse to half-parse them.
            raise AssertionError(
                f"{path}: parenthesized jwt import is not parsed by the "
                "inventory check -- extend _jwt_api_inventory for it"
            )
        for name in names.split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                froms.add((module, name))
    return attrs, froms


@pytest.mark.parametrize("relpath", OIDC_SOURCES)
def test_every_jwt_api_the_verifier_imports_exists_on_installed_pyjwt(relpath):
    """The CI gate imports these modules at the declared floor; this is the
    fast in-suite half: every referenced API must exist on the PyJWT the suite
    runs against. A symbol that no released PyJWT exposes fails here in
    seconds instead of in a release job."""
    jwt = importlib.import_module("jwt")
    path = ROOT / relpath
    attrs, froms = _jwt_api_inventory(path)
    assert attrs or froms, f"{relpath} no longer imports any jwt API -- move the gate"
    missing = [name for name in sorted(attrs) if not hasattr(jwt, name)]
    missing += [
        f"{module}:{symbol}"
        for module, symbol in sorted(froms)
        if not hasattr(importlib.import_module(module), symbol)
    ]
    assert missing == [], f"{relpath} imports APIs missing from installed pyjwt: {missing}"


class TestGateWiring:
    def test_release_and_ci_both_execute_the_floor_gate(self):
        """ "#1100's "Release CI tests ... a minimum-supported-dependencies
        environment" criterion. A workflow edit that drops the step fails
        here rather than at the next tag."""
        for workflow in (".github/workflows/release.yml", ".github/workflows/ci.yml"):
            text = (ROOT / workflow).read_text(encoding="utf-8")
            assert "verify-minimum-dependencies.py" in text, workflow
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        assert "minimum supported dependency floors" in release

    def test_gate_targets_the_oidc_verifier_surface(self, gate):
        """The gate must import the OIDC verifier modules by name: an edit
        that shrinks DEFAULT_MODULES to, say, the package root would pass
        while never importing the code the issue is about."""
        assert set(gate.DEFAULT_MODULES) >= {
            "maistro.auth.oauth",
            "maistro.security.auth_jwt",
            "maistro.security.auth_demo_cookie",
        }
        assert ("jwt.exceptions", "MissingCryptographyError") in gate.VERSION_SENSITIVE_IMPORTS
        assert ("jwt", "PyJWKClient") in gate.VERSION_SENSITIVE_IMPORTS


class TestGateEntry:
    def test_a_package_without_a_pyjwt_dependency_refuses_to_gate(self, gate, tmp_path):
        """`check()` gates the dependency it names; a package that does not
        declare it must abort loudly, not silently gate some other range."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0"\ndependencies = ["httpx>=0.28"]\n',
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="declares no 'pyjwt' dependency"):
            gate.check(tmp_path, gate.DEFAULT_MODULES, "uv", "3.12")


class TestFailClosedProbe:
    @staticmethod
    def _install(root: Path, oauth_body: str) -> Path:
        """A fake `maistro.auth.oauth` whose import behaviour stands in for the
        real module's guard (importing the real one needs the floor install)."""
        pkg = root / "site" / "maistro" / "auth"
        pkg.mkdir(parents=True)
        (root / "site" / "maistro" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "oauth.py").write_text(oauth_body, encoding="utf-8")
        cwd = root / "cwd"
        cwd.mkdir()
        return cwd

    def test_a_module_that_refuses_without_pyjwt_passes_the_probe(self, gate, tmp_path):
        body = (
            "try:\n"
            "    import jwt  # noqa: F401\n"
            "except ModuleNotFoundError as exc:\n"
            "    raise ImportError(\n"
            "        'maistro.auth.oauth requires PyJWT (install pyjwt[crypto]) for '\n"
            "        'mandatory OIDC signature verification; there is no '\n"
            "        'unverified-claims fallback and authentication fails closed'\n"
            "    ) from exc\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", gate.PROBE_FAIL_CLOSED, "jwt"],
            capture_output=True,
            text=True,
            cwd=self._install(tmp_path, body),
            env={"PYTHONPATH": str(tmp_path / "site"), "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert json.loads(proc.stdout.strip().splitlines()[-1])["refused"] is True

    def test_a_module_that_imports_without_pyjwt_is_reported_as_downgraded(self, gate, tmp_path):
        """The degenerate path the probe exists to catch: an install where the
        OIDC module loads with PyJWT absent must FAIL the gate, not pass it."""
        body = "VERIFIER = 'unverified'\n"
        proc = subprocess.run(
            [sys.executable, "-c", gate.PROBE_FAIL_CLOSED, "jwt"],
            capture_output=True,
            text=True,
            cwd=self._install(tmp_path, body),
            env={"PYTHONPATH": str(tmp_path / "site"), "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 1
        verdict = json.loads(proc.stdout.strip().splitlines()[-1])
        assert verdict["refused"] is False
        assert "imported without pyjwt" in verdict["error"]

    def test_a_wrong_error_message_does_not_count_as_refusal(self, gate, tmp_path):
        """The refusal must be the #856 actionable error (names pyjwt, states
        fail-closed), not any incidental ImportError."""
        body = (
            "try:\n"
            "    import jwt  # noqa: F401\n"
            "except ModuleNotFoundError as exc:\n"
            "    raise ImportError('boom') from exc\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", gate.PROBE_FAIL_CLOSED, "jwt"],
            capture_output=True,
            text=True,
            cwd=self._install(tmp_path, body),
            env={"PYTHONPATH": str(tmp_path / "site"), "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 1
        assert json.loads(proc.stdout.strip().splitlines()[-1])["refused"] is False
