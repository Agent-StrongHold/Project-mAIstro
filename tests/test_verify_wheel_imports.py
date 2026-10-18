"""Tests for the packaged-data half of the wheel verifier (#293).

The script's original job is to install each wheel into a clean venv and import
every module in it. That is a check about *code*, and it is complete: a wheel
whose modules import is a wheel whose modules ship.

Data is the gap it left. maistro-design's six bundled design systems are
directories of JSON, CSS and Markdown; a packaging change that dropped them
would leave every module importing perfectly and `load_bundled` raising
FileNotFoundError at container startup, which is where #293 lived for months in
a different disguise.

Building and installing wheels takes minutes, so these tests exercise the
declaration and the probe directly rather than through `check()`. What they
cannot cover -- that the probe's output reaches the report -- is covered by the
script's own end-to-end run in CI.

The sibling-pinning tests at the bottom are the exception (#1572 repair): they
drive `check()` itself through a fake `uv` shim and a real (tiny) wheel, so the
constraint file the installer is handed is asserted, not assumed. A shim keeps
them millisecond-cheap and offline; the shipped CI job still runs the script
end-to-end against the real wheels it builds.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-wheel-imports.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("verify_wheel_imports", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _probe(module, tmp_path: Path, root: str, data_files: list[str]) -> dict:
    """Run the probe source the way `check()` does, against a fake install."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            module.PROBE,
            "bare",
            root,
            json.dumps([root]),
            json.dumps(data_files),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture
def installed(tmp_path: Path) -> Path:
    """A minimal importable package with one data file, standing in for a wheel."""
    pkg = tmp_path / "fakepkg"
    (pkg / "data").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "data" / "present.json").write_text("{}", encoding="utf-8")
    return tmp_path


class TestTheProbeChecksData:
    def test_a_present_data_file_passes(self, check, installed):
        result = _probe(check, installed, "fakepkg", ["data/present.json"])
        assert result["failures"] == []

    def test_a_missing_data_file_is_a_failure(self, check, installed):
        """The state a packaging regression produces: the module imports, the
        file it needs at runtime is not there."""
        result = _probe(check, installed, "fakepkg", ["data/gone.json"])
        assert [f["module"] for f in result["failures"]] == ["fakepkg/data/gone.json"]
        assert "missing from the wheel" in result["failures"][0]["error"]

    def test_a_directory_does_not_count_as_a_file(self, check, installed):
        """`is_file`, not `exists`. An empty directory left behind by a partial
        copy would otherwise read as shipped."""
        result = _probe(check, installed, "fakepkg", ["data"])
        assert len(result["failures"]) == 1

    def test_data_files_are_counted_in_what_was_checked(self, check, installed):
        """The report says "N of M check(s)"; a data file that ran but was not
        counted would make the denominator lie about coverage."""
        result = _probe(check, installed, "fakepkg", ["data/present.json"])
        assert result["checked"] == 2  # the module, and the data file

    def test_declaring_no_data_files_checks_only_modules(self, check, installed):
        """Every other package declares none, so this is the path almost all of
        them take and it must stay exactly as it was."""
        result = _probe(check, installed, "fakepkg", [])
        assert result["failures"] == [] and result["checked"] == 1


class TestTheDeclaration:
    def test_maistro_design_declares_its_bundled_systems(self, check):
        """The package the gap was found in. Declared per file rather than per
        directory, because a partial copy is what a directory check passes."""
        pkg = next(p for p in check.PACKAGES if p.dist == "maistro-design")
        assert "systems/bundled/default/manifest.json" in pkg.data_files
        assert "systems/catalog/catalog.json" in pkg.data_files

    def test_every_declared_file_exists_in_the_source_tree(self, check):
        """A declaration naming a file that was never there would fail every
        build for a reason that has nothing to do with packaging."""
        missing = [
            f"{pkg.dist}:{rel}"
            for pkg in check.PACKAGES
            for rel in pkg.data_files
            if not (ROOT / "packages" / pkg.dist / "src" / pkg.root / rel).is_file()
        ]
        assert missing == []

    def test_the_declaration_covers_every_bundled_slug(self, check):
        """Pinned against the package's own list, so a seventh bundled system
        cannot be added without either being declared here or failing this."""
        sys.path.insert(0, str(ROOT / "packages" / "maistro-design" / "src"))
        try:
            from maistro_design.systems.importer import BUNDLED_SLUGS
        finally:
            sys.path.pop(0)
        pkg = next(p for p in check.PACKAGES if p.dist == "maistro-design")
        declared = {
            rel.split("/")[2] for rel in pkg.data_files if rel.startswith("systems/bundled/")
        }
        assert declared == set(BUNDLED_SLUGS)

    def test_packages_without_data_default_to_none(self, check):
        """The field is opt-in; a default of anything but empty would make
        every other package's check silently different."""
        assert next(p for p in check.PACKAGES if p.dist == "maistro-server").data_files == []


class TestTheReport:
    """What `check()` hands back for one probe payload. Split out of `check()`
    because everything else in it needs a built wheel and a clean venv, and the
    wording a reader acts on should not cost a five-minute build to test."""

    def test_a_clean_result_passes_and_says_how_much_it_checked(self, check):
        ok, detail = check.render({"checked": 20, "failures": []})
        assert ok
        assert "20 check(s) passed" in detail

    def test_a_failure_names_the_thing_and_the_reason(self, check):
        ok, detail = check.render(
            {
                "checked": 21,
                "failures": [
                    {
                        "module": "maistro_design/systems/bundled/default/manifest.json",
                        "error": "packaged data file missing from the wheel",
                        "traceback": "",
                    }
                ],
            }
        )
        assert not ok
        assert "1 of 21 check(s) failed" in detail
        assert "manifest.json" in detail
        assert "missing from the wheel" in detail

    def test_a_data_failure_does_not_print_an_empty_traceback_block(self, check):
        """A data file has no traceback. Printing four blank spaces under it
        reads as a truncated stack, which sends someone looking for one."""
        _, detail = check.render(
            {
                "checked": 1,
                "failures": [{"module": "x/y.json", "error": "missing", "traceback": ""}],
            }
        )
        assert detail.splitlines()[-1].strip() == "x/y.json: missing"

    def test_an_import_failure_still_carries_its_traceback(self, check):
        """The original behaviour, which the data case must not have cost."""
        _, detail = check.render(
            {
                "checked": 1,
                "failures": [
                    {
                        "module": "maistro_design.nodes",
                        "error": "ModuleNotFoundError: maistro.graph",
                        "traceback": "Traceback...\n  File x\nModuleNotFoundError",
                    }
                ],
            }
        )
        assert "Traceback..." in detail
        assert "ModuleNotFoundError" in detail

    def test_it_does_not_call_a_data_file_a_module(self, check):
        """The wording the split exists for: "module(s) failed to import" was
        wrong the moment a JSON file could appear in this list."""
        _, detail = check.render(
            {"checked": 2, "failures": [{"module": "a.json", "error": "missing", "traceback": ""}]}
        )
        assert "failed to import" not in detail


class TestTheOptionalFileIsDeclared:
    """#413. `design-tokens.json` is the one file `_read_system_files()` treats
    as optional, and the one that carries every colour and spacing token.

    Drop it in packaging and nothing complains: the wheel imports,
    `load_bundled` succeeds, startup reports ready — and every bundled system
    loads with zero tokens, which is the empty shell #293 removed, reached from
    the other direction. The file whose absence is silent is the one that most
    needs declaring."""

    def test_every_bundled_system_declares_its_tokens_file(self, check):
        pkg = next(p for p in check.PACKAGES if p.dist == "maistro-design")
        declared = {
            rel.split("/")[2]
            for rel in pkg.data_files
            if rel.startswith("systems/bundled/") and rel.endswith("/design-tokens.json")
        }
        sys.path.insert(0, str(ROOT / "packages" / "maistro-design" / "src"))
        try:
            from maistro_design.systems.importer import BUNDLED_SLUGS
        finally:
            sys.path.pop(0)
        assert declared == set(BUNDLED_SLUGS)

    def test_the_local_constant_equals_the_importers(self, check):
        """The verifier duplicates `ESSENTIAL_FILES` because it must run before
        anything is installed. Nothing tied the copy to the original, so a
        fifth file added upstream left the verifier, its declaration and this
        test all green while the wheel could omit the new requirement (#413
        review). Compared against the source of truth, not against itself."""
        import sys

        sys.path.insert(0, str(ROOT / "packages" / "maistro-design" / "src"))
        try:
            from maistro_design.systems.importer import ESSENTIAL_FILES
        finally:
            sys.path.pop(0)
        assert tuple(check.ESSENTIAL_FILES) == tuple(ESSENTIAL_FILES)

    def test_every_essential_file_is_declared_per_system(self, check):
        """Whatever the importer requires, declared for every bundled system."""
        sys.path.insert(0, str(ROOT / "packages" / "maistro-design" / "src"))
        try:
            from maistro_design.systems.importer import BUNDLED_SLUGS
        finally:
            sys.path.pop(0)
        pkg = next(p for p in check.PACKAGES if p.dist == "maistro-design")
        bundled = [r for r in pkg.data_files if r.startswith("systems/bundled/")]
        assert len(bundled) == len(BUNDLED_SLUGS) * len(check.ESSENTIAL_FILES)

    def test_a_catalog_payload_is_declared_not_only_the_index(self, check):
        """The index alone would let a wheel advertise 144 importable systems
        whose files are absent — `import_from_catalog` reads
        `systems/catalog/<slug>/`, not the index."""
        pkg = next(p for p in check.PACKAGES if p.dist == "maistro-design")
        assert "systems/catalog/catalog.json" in pkg.data_files
        payload = [
            r
            for r in pkg.data_files
            if r.startswith("systems/catalog/") and not r.endswith("catalog.json")
        ]
        assert payload, "the index is declared but no catalogue payload is"


SHIM = r"""#!/usr/bin/env python3
import json, shlex, sys, zipfile
from pathlib import Path

args = sys.argv[1:]
receipt = Path("__RECEIPT__")
state = json.loads(receipt.read_text()) if receipt.exists() else {"argv": []}
state["argv"].append(args)
if args[:1] == ["venv"]:
    Path(args[1]).mkdir(parents=True, exist_ok=True)
elif args[:2] == ["pip", "install"]:
    def flag(name):
        return args[args.index(name) + 1]

    venv = Path(flag("--python"))
    spec = args[-1]
    state["constraints_content"] = Path(flag("--constraints")).read_text()
    site = venv / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    wheel = Path(spec if spec.endswith(".whl") else spec.split(" @ ", 1)[1])
    zipfile.ZipFile(wheel).extractall(site)
    wrapper = venv / "bin" / "python"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "#!/bin/sh\nexec env PYTHONPATH=%s %s %s\n"
        % (shlex.quote(str(site)), sys.executable, '"$@"')
    )
    wrapper.chmod(0o755)
receipt.write_text(json.dumps(state))
"""


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    """A `uv` stand-in that records its argv and performs the install offline.

    `venv` creates the directory; `pip install` unpacks the requested wheel into
    the venv and writes a `bin/python` wrapper that points the interpreter at
    it. Good enough for `check()`, which only asks the installed tree to import.
    """
    shim = tmp_path / "bin" / "uv"
    shim.parent.mkdir(parents=True)
    shim.write_text(SHIM.replace("__RECEIPT__", str(tmp_path / "uv-receipt.json")))
    shim.chmod(0o755)
    return shim


def _build_wheel(dist_dir: Path, dist: str, root: str) -> Path:
    """A minimal real wheel: one importable module plus its dist-info."""
    name = f"{dist.replace('-', '_')}-0.9.0-py3-none-any.whl"
    wheel = dist_dir / name
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(f"{root}/__init__.py", f"MARKER = {dist!r}\n")
        zf.writestr(
            f"{dist.replace('-', '_')}-0.9.0.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {dist}\nVersion: 0.9.0\nRequires-Python: >=3.9\n",
        )
        zf.writestr(
            f"{dist.replace('-', '_')}-0.9.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test (#1572)\nRoot-Is-Purelib: true\n",
        )
    return wheel


class TestTheSiblingConstraintPin:
    """Sibling maistro-* wheels must resolve from dist/, never from PyPI.

    PyPI now carries same-version (0.9.0) snapshots of the unpublished maistro-*
    names, so a bare `--find-links` lets uv break the version tie either way and
    a run can import a stale published snapshot instead of the wheel under test
    (#1572 repair). The fix hands uv a direct-reference constraint pinning every
    sibling wheel to its exact local artifact; these tests hold both halves of
    that: the PEP 503 name mapping and the file the installer actually receives.
    """

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            pytest.param(
                "maistro_core-0.9.0-py3-none-any.whl",
                "maistro-core",
                id="underscored-dist-becomes-dashed",
            ),
            pytest.param(
                "My_Pkg-1.0-py3-none-any.whl",
                "my-pkg",
                id="pep503-collapses-underscores-and-cases",
            ),
            pytest.param(
                "Maistro.SDK-1.0rc0-py3-none-any.whl",
                "maistro-sdk",
                id="pep503-collapses-dots-and-cases",
            ),
        ],
    )
    def test_wheel_dist_name_normalizes_like_pep503(self, check, filename, expected):
        assert check._wheel_dist_name(Path(filename)) == expected

    def test_check_pins_every_sibling_wheel_to_its_local_artifact(self, check, tmp_path, fake_uv):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        wheel = _build_wheel(dist_dir, "dummy", "dummy")

        ok, detail = check.check(
            check.Package(dist="dummy", root="dummy"),
            "bare",
            dist_dir,
            str(fake_uv),
            "3.12",
        )

        assert ok is True, detail
        assert detail == "1 check(s) passed"
        receipt = json.loads((tmp_path / "uv-receipt.json").read_text())
        install = [argv for argv in receipt["argv"] if argv[:2] == ["pip", "install"]]
        assert len(install) == 1, receipt
        assert "--constraints" in install[0], install[0]
        # The pin names the PEP 503-normalized distribution and the exact local
        # artifact -- not a bare name uv could satisfy from the index.
        assert receipt["constraints_content"].splitlines() == [
            f"dummy @ {wheel.resolve().as_uri()}"
        ]
        # Bare mode installs the local wheel path itself, so the import probe
        # ran against this dist/ artifact, not a name uv resolved elsewhere.
        assert install[0][-1] == str(wheel.resolve())

    def test_check_fails_closed_when_the_wheel_was_never_built(self, check, tmp_path, fake_uv):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()

        ok, detail = check.check(
            check.Package(dist="absent", root="absent"),
            "bare",
            dist_dir,
            str(fake_uv),
            "3.12",
        )

        assert ok is False
        assert "no wheel found" in detail
        assert "did the build step run?" in detail
        # Nothing was installed for a package that has no wheel.
        assert not (tmp_path / "uv-receipt.json").exists()
