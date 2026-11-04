"""#344: the JavaScript dependency gate fails closed, and the inventory is real.

The gate (``scripts/js_dependency_gate.py``) is the single verdict for the JS
supply chain, the role ``pip_audit_gate.py`` plays for Python. These tests pin
its fail-closed properties — the issue's acceptance, not incidental behavior:

* a package.json or lockfile the gate does not know about fails CI (adding a
  workspace without coverage is non-passing);
* a registered surface without a lockfile fails;
* lock drift, non-https or integrity-less resolutions, unapproved licenses,
  typosquat shapes, and unreviewed install scripts fail;
* a missing or unparseable scanner report is exit 3 (unavailable scanner is
  non-passing), never a silent pass;
* every exception is owned (a reason), expiring (an ISO date the gate checks),
  and version-specific (a version list the gate binds through the lockfiles);
* the real repo's inventory is complete, Dependabot covers every surface, and
  the builds reconcile to the audited lockfiles (``npm ci``, never
  ``npm install``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts" / "js_dependency_gate.py"
SCAN_SCRIPT = ROOT / "scripts" / "js_guarddog_scan.py"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
HIVE_DOCKERFILE = ROOT / "packages" / "hive-conductor" / "Dockerfile"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> Any:
    return _load("_js_dependency_gate", GATE_SCRIPT)


@pytest.fixture(scope="module")
def scanner() -> Any:
    return _load("_js_guarddog_scan", SCAN_SCRIPT)


def _lock_entry(**kwargs: Any) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "resolved": "https://registry.npmjs.org/x/-/x-1.0.0.tgz",
        "integrity": "sha512-" + "a" * 64,
        **kwargs,
    }


class TestTyposquatPolicy:
    def test_near_miss_of_popular_package_is_flagged(self, gate: Any) -> None:
        assert gate.typosquat_hits("reqeust") == ["request"]
        assert gate.typosquat_hits("reactt") == ["react"]

    def test_popular_and_legitimate_names_pass(self, gate: Any) -> None:
        assert gate.typosquat_hits("react") == []
        assert gate.typosquat_hits("react-dom") == []
        assert gate.typosquat_hits("source-map-js") == []
        assert gate.typosquat_hits("zod") == []  # short names: distance is noise

    def test_scoped_packages_are_exempt(self, gate: Any) -> None:
        assert gate.typosquat_hits("@evil/reqeust") == []

    def test_real_trees_have_no_typosquat_shapes(self, gate: Any) -> None:
        for surface in gate.SURFACES:
            lock = json.loads((ROOT / surface / "package-lock.json").read_text(encoding="utf-8"))
            assert gate.check_typosquats(surface, lock) == []


class TestLocalPolicies:
    def test_provenance_requires_https_and_sha512(self, gate: Any) -> None:
        lock = {
            "packages": {
                "": {},
                "node_modules/good": _lock_entry(),
                "node_modules/no-integrity": {"version": "1", "resolved": "https://r/x"},
                "node_modules/http": _lock_entry(resolved="http://r/x"),
                "node_modules/weak-hash": _lock_entry(integrity="sha1-abc"),
                "node_modules/link": {"link": True},
            }
        }
        findings = gate.check_provenance("s", lock)
        assert len(findings) == 3
        assert all("no-integrity" in f or "http" in f or "weak-hash" in f for f in findings)

    def test_license_policy(self, gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        lock = {
            "packages": {
                "": {},
                "node_modules/mit": _lock_entry(license="MIT"),
                "node_modules/gpl": _lock_entry(license="GPL-3.0"),
                "node_modules/unlicensed": _lock_entry(license="UNLICENSED"),
                "node_modules/quiet": _lock_entry(),  # no data: counted, not failed
            }
        }
        findings, missing = gate.check_licenses("s", lock)
        assert {f.split("'")[1] for f in findings} == {"gpl", "unlicensed"}
        assert missing == 1

        gate.LICENSE_EXCEPTIONS[("gpl", "GPL-3.0")] = gate.Exception(
            reason="triaged", expires="2999-01-01"
        )
        try:
            findings, _ = gate.check_licenses("s", lock)
            assert {f.split("'")[1] for f in findings} == {"unlicensed"}
        finally:
            del gate.LICENSE_EXCEPTIONS[("gpl", "GPL-3.0")]

    def test_expired_license_exception_fails(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate.LICENSE_EXCEPTIONS[("gpl", "GPL-3.0")] = gate.Exception(
            reason="stale", expires="2000-01-01"
        )
        try:
            lock = {"packages": {"": {}, "node_modules/gpl": _lock_entry(license="GPL-3.0")}}
            findings, _ = gate.check_licenses("s", lock)
            assert findings
        finally:
            del gate.LICENSE_EXCEPTIONS[("gpl", "GPL-3.0")]

    def test_lock_drift_in_every_direction(self, gate: Any) -> None:
        package_json = {
            "dependencies": {"kept": "^1.0.0", "changed": "^1.0.0"},
            "devDependencies": {"dropped": "^2.0.0"},
        }
        lock = {
            "packages": {
                "": {
                    "dependencies": {"kept": "^1.0.0", "changed": "^2.0.0", "extra": "^3.0.0"},
                }
            }
        }
        findings = gate.check_lock_drift("s", package_json, lock)
        assert any("changed" in f and "drifted" in f for f in findings)
        assert any("dropped" in f and "not in the lockfile" in f for f in findings)
        assert any("extra" in f and "does not declare" in f for f in findings)

    def test_install_script_review_is_version_specific(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gate,
            "INSTALL_SCRIPT_EXCEPTIONS",
            {
                "tool": gate.Exception(
                    reason="reviewed", expires="2999-01-01", versions=("1.0.0",)
                ),
            },
        )
        reviewed = {
            "packages": {
                "": {},
                "node_modules/tool": _lock_entry(version="1.0.0", hasInstallScript=True),
            }
        }
        assert gate.check_install_scripts("s", reviewed) == []

        drifted = {
            "packages": {
                "": {},
                "node_modules/tool": _lock_entry(version="9.9.9", hasInstallScript=True),
            }
        }
        findings = gate.check_install_scripts("s", drifted)
        assert any("new version needs a new review" in f for f in findings)

        unknown = {
            "packages": {"": {}, "node_modules/stranger": _lock_entry(hasInstallScript=True)}
        }
        assert gate.check_install_scripts("s", unknown)


class TestScannerReports:
    def _audit(
        self,
        name: str = "pkg",
        advisory: str = "GHSA-x",
        via_url: str = "https://osv.dev/vulnerability/GHSA-x",
    ) -> dict[str, Any]:
        return {
            "vulnerabilities": {
                name: {
                    "severity": "high",
                    "via": [{"name": name, "url": via_url, "severity": "high"}],
                }
            }
        }

    def test_advisory_without_exception_fails(self, gate: Any) -> None:
        findings = gate.check_audit_report("s", self._audit(), {"pkg": {"1.0.0"}})
        assert findings and "no exception" in findings[0]

    def test_excepted_advisory_passes_and_version_binds(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate.VULNERABILITY_EXCEPTIONS[("pkg", "GHSA-x")] = gate.Exception(
            reason="triaged", expires="2999-01-01", versions=("1.0.0",)
        )
        try:
            assert gate.check_audit_report("s", self._audit(), {"pkg": {"1.0.0"}}) == []
            findings = gate.check_audit_report("s", self._audit(), {"pkg": {"2.0.0"}})
            assert findings and "new version is a new finding" in findings[0]
        finally:
            del gate.VULNERABILITY_EXCEPTIONS[("pkg", "GHSA-x")]

    def test_via_chain_entries_are_not_separate_findings(self, gate: Any) -> None:
        report = {
            "vulnerabilities": {
                "downstream": {
                    "severity": "moderate",
                    "via": ["root-cause-pkg"],
                }
            }
        }
        assert gate.check_audit_report("s", report, {}) == []

    def test_guarddog_threat_rules_fail_and_capabilities_do_not(self, gate: Any) -> None:
        report = {
            "benign": {"results": {"capability-network-outbound": [{"message": "x"}]}},
            "suspect": {"results": {"typosquatting": [{"message": "x"}]}},
        }
        findings = gate.check_guarddog_report("s", report, {"suspect": {"1.0.0"}})
        assert len(findings) == 1 and "suspect" in findings[0]

    def test_guarddog_unusable_scan_is_never_a_pass(self, gate: Any) -> None:
        report = {"broken": None, "errored": {"errors": {"scan": "download failed"}}}
        findings = gate.check_guarddog_report("s", report, {})
        assert len(findings) == 2
        assert any("no usable scan" in f for f in findings)
        assert any("could not scan" in f for f in findings)

    def test_guarddog_exception_version_binds(
        self, gate: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gate.GUARDDOG_EXCEPTIONS[("pkg", "typosquatting")] = gate.Exception(
            reason="triaged", expires="2999-01-01", versions=("1.0.0",)
        )
        report = {"pkg": {"results": {"typosquatting": [{"message": "x"}]}}}
        try:
            assert gate.check_guarddog_report("s", report, {"pkg": {"1.0.0"}}) == []
            findings = gate.check_guarddog_report("s", report, {"pkg": {"2.0.0"}})
            assert findings and "new version is a new finding" in findings[0]
        finally:
            del gate.GUARDDOG_EXCEPTIONS[("pkg", "typosquatting")]


class TestExceptionsAreOwnedExpiringAndVersionSpecific:
    """The AC's exception contract, held structurally over every ledger."""

    @pytest.mark.parametrize(
        "ledger_name",
        [
            "VULNERABILITY_EXCEPTIONS",
            "GUARDDOG_EXCEPTIONS",
            "LICENSE_EXCEPTIONS",
        ],
    )
    def test_every_exception_expires_and_says_why(self, gate: Any, ledger_name: str) -> None:
        for key, exception in getattr(gate, ledger_name).items():
            assert exception.reason.strip(), f"{ledger_name}[{key}] has no reason"
            # A parsable ISO date, in the future: expiry is the re-review cadence.
            year = int(exception.expires[:4])
            assert 2026 <= year <= 2100, (
                f"{ledger_name}[{key}] expiry {exception.expires} is not sane"
            )

    def test_install_script_exceptions_carry_versions(self, gate: Any) -> None:
        for name, exception in gate.INSTALL_SCRIPT_EXCEPTIONS.items():
            assert exception.versions, (
                f"install-script exception for {name} is not version-specific"
            )


class TestFailClosed:
    def _surface_tree(self, tmp_path: Path, *, with_lockfile: bool = True) -> Path:
        surface = tmp_path / "packages" / "demo" / "frontend"
        surface.mkdir(parents=True)
        (surface / "package.json").write_text(
            json.dumps({"name": "demo", "dependencies": {"react": "^19.0.0"}}),
            encoding="utf-8",
        )
        if with_lockfile:
            (surface / "package-lock.json").write_text(
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {
                            "": {"dependencies": {"react": "^19.0.0"}},
                            "node_modules/react": _lock_entry(version="19.0.0", license="MIT"),
                        },
                    }
                ),
                encoding="utf-8",
            )
        return tmp_path

    def test_unclassified_surface_fails_closed(self, gate: Any, tmp_path: Path) -> None:
        self._surface_tree(tmp_path)
        findings = gate.check_inventory(tmp_path)
        assert any("unclassified dependency surface" in f for f in findings)

    def test_missing_lockfile_fails_closed(
        self, gate: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._surface_tree(tmp_path, with_lockfile=False)
        monkeypatch.setattr(
            gate,
            "SURFACES",
            {
                "packages/demo/frontend": gate.Surface(
                    "packages/demo/frontend", True, "test surface"
                ),
            },
        )
        findings = gate.check_inventory(tmp_path)
        assert any("has no lockfile" in f for f in findings)

    def test_missing_scanner_reports_exit_3(
        self,
        gate: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._surface_tree(tmp_path)
        monkeypatch.setattr(
            gate,
            "SURFACES",
            {
                "packages/demo/frontend": gate.Surface(
                    "packages/demo/frontend", True, "test surface"
                ),
            },
        )
        code = gate.main(["--root", str(tmp_path)])
        assert code == 3
        assert "no npm audit report" in capsys.readouterr().out

    def test_unparseable_report_exits_3(
        self,
        gate: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._surface_tree(tmp_path)
        monkeypatch.setattr(
            gate,
            "SURFACES",
            {
                "packages/demo/frontend": gate.Surface(
                    "packages/demo/frontend", True, "test surface"
                ),
            },
        )
        report = root / "audit.json"
        report.write_text("{not json", encoding="utf-8")
        code = gate.main(
            [
                "--root",
                str(root),
                "--audit-report",
                f"packages/demo/frontend={report}",
            ]
        )
        assert code == 3
        assert "not usable" in capsys.readouterr().out

    def test_clean_surface_with_clean_reports_passes(
        self,
        gate: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._surface_tree(tmp_path)
        monkeypatch.setattr(
            gate,
            "SURFACES",
            {
                "packages/demo/frontend": gate.Surface(
                    "packages/demo/frontend", True, "test surface"
                ),
            },
        )
        audit = root / "audit.json"
        audit.write_text(json.dumps({"vulnerabilities": {}}), encoding="utf-8")
        guarddog = root / "guarddog.json"
        guarddog.write_text(json.dumps({"react": {"results": {}}}), encoding="utf-8")
        code = gate.main(
            [
                "--root",
                str(root),
                "--audit-report",
                f"packages/demo/frontend={audit}",
                "--guarddog-report",
                f"packages/demo/frontend={guarddog}",
            ]
        )
        assert code == 0, capsys.readouterr().out


class TestTheRealRepo:
    def test_inventory_is_complete(self, gate: Any) -> None:
        assert gate.check_inventory(ROOT) == []

    def test_local_policies_pass_on_every_surface(self, gate: Any) -> None:
        for name in gate.SURFACES:
            directory = ROOT / name
            package_json = json.loads((directory / "package.json").read_text(encoding="utf-8"))
            lock = json.loads((directory / "package-lock.json").read_text(encoding="utf-8"))
            assert gate.check_lock_drift(name, package_json, lock) == []
            assert gate.check_provenance(name, lock) == []
            license_findings, _ = gate.check_licenses(name, lock)
            assert license_findings == []
            assert gate.check_install_scripts(name, lock) == []

    def test_direct_deps_listing_covers_every_surface(self, gate: Any) -> None:
        deps = gate.direct_dependencies(ROOT)
        assert set(deps) == set(gate.SURFACES)
        for surface, direct in deps.items():
            assert direct, f"{surface} lists no direct dependencies"

    def test_dependabot_covers_every_surface(self, gate: Any) -> None:
        config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
        npm_dirs = {
            update["directory"]
            for update in config["updates"]
            if update["package-ecosystem"] == "npm"
        }
        assert npm_dirs == {f"/{name}" for name in gate.SURFACES}, (
            "Dependabot npm entries and the gate's surfaces drifted: a surface "
            "without update coverage fails #344's definition of done"
        )
        for update in config["updates"]:
            if update["package-ecosystem"] == "npm":
                assert update.get("groups"), "npm updates must be grouped (rate control)"
                assert "open-pull-requests-limit" in update, "npm updates must be rate-limited"

    def test_builds_reconcile_to_the_audited_lockfiles(self, gate: Any) -> None:
        """`npm ci` (lockfile-exact), never `npm install`, in every build path."""
        ci = CI_WORKFLOW.read_text(encoding="utf-8")
        for surface in gate.SURFACES:
            if not gate.SURFACES[surface].shipped:
                continue
            assert f"working-directory: {surface}" in ci, f"{surface} lost its CI build step"
        assert "npm install" not in ci, (
            "CI must install from the lockfile (npm ci) so build artifacts "
            "reconcile to the audited lockfile"
        )
        dockerfile = HIVE_DOCKERFILE.read_text(encoding="utf-8")
        assert (
            "COPY packages/hive-conductor/frontend/package.json packages/hive-conductor/frontend/package-lock.json"
            in dockerfile
        )
        assert "RUN npm ci" in dockerfile
        assert "npm install" not in dockerfile

    def test_security_workflow_gates_every_surface(self, gate: Any) -> None:
        workflow = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
        job = workflow["jobs"]["js-supply-chain"]
        gate_steps = [
            step for step in job["steps"] if "js_dependency_gate.py" in str(step.get("run", ""))
        ]
        assert gate_steps, "security.yml must run the JS dependency gate"
        all_steps_text = "\n".join(str(step.get("run", "")) for step in job["steps"])
        for name in gate.SURFACES:
            assert name in all_steps_text, f"the js-supply-chain job lost its coverage of {name}"


class TestGuardDogScanDriver:
    def test_failed_scan_is_recorded_never_dropped(
        self, scanner: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A package GuardDog cannot scan must surface as an error, not silence."""

        def fake_run(cmd: list[str], **kwargs: Any) -> Any:
            import subprocess as real_subprocess

            return real_subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        monkeypatch.setattr(scanner.subprocess, "run", fake_run)
        written = scanner.scan_direct_dependencies(
            {"packages/demo/frontend": {"react": "19.0.0"}},
            output_dir=tmp_path,
            guarddog="guarddog",
        )
        report = json.loads(written["packages/demo/frontend"].read_text(encoding="utf-8"))
        assert report == {"react": {"errors": {"scan": "boom"}}}
