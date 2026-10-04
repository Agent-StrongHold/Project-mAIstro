"""Tests for the dependency-namespace gate and the production prune (#406).

The locked identity stack pulls ``pytoniq-core-fork`` into every environment
that resolves it, and its wheel ships a generic top-level ``examples``
namespace package. ``scripts/check-dependency-namespaces.py`` inventories the
top-level surface every installed distribution contributes and rejects the
unreviewed parts; ``scripts/prune-dependency-namespaces.py`` removes the
reviewed-but-never-shipped payload from the images that would otherwise carry
it.

Everything here runs against fabricated site-packages trees — a dist-info
directory, a RECORD, and a handful of files — so the gate's whole decision
surface is exercised in milliseconds. The two things a fabrication cannot
prove are covered where they live: the language's regular-package-beats-
namespace precedence (a real subprocess import), and the real synced
environment (a subprocess gate run).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "scripts" / "check-dependency-namespaces.py"
PRUNE_SCRIPT = ROOT / "scripts" / "prune-dependency-namespaces.py"


@dataclass(frozen=True)
class Scripts:
    check: ModuleType
    prune: ModuleType


@pytest.fixture(scope="module")
def scripts() -> Scripts:
    def load(path: Path, name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    return Scripts(
        load(CHECK_SCRIPT, "check_dependency_namespaces"),
        load(PRUNE_SCRIPT, "prune_dependency_namespaces"),
    )


def make_dist(
    site: Path,
    dist_name: str,
    version: str,
    files: dict[str, bytes],
    *,
    extra_record_rows: list[str] | None = None,
    metadata: str | None = None,
    omit_metadata: bool = False,
) -> Path:
    """Fabricate one installed distribution: METADATA + RECORD + payload files.

    RECORD rows carry real sha256/size columns so a prune that rewrites the
    file is exercised against the same shape syft and pip read. ``extra_record_rows``
    appends raw first-column rows (a recorded directory, a ``..`` escape) for the
    hostile-RECORD cases; ``metadata`` replaces the standard headers, and
    ``omit_metadata`` installs the dist-info without a METADATA file at all.
    """
    dist_info = site / f"{dist_name.replace('-', '_')}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    if not omit_metadata:
        (dist_info / "METADATA").write_text(
            metadata
            if metadata is not None
            else (f"Metadata-Version: 2.4\nName: {dist_name}\nVersion: {version}\n"),
            encoding="utf-8",
        )
    rows: list[list[str]] = []
    for rel, content in sorted(files.items()):
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
        rows.append([rel, f"sha256={digest}", str(len(content))])
    if not omit_metadata:
        rows.append([f"{dist_info.name}/METADATA", "", ""])
    for raw in extra_record_rows or []:
        rows.append([raw, "", ""])
    with (dist_info / "RECORD").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return dist_info


PYTONIQ_PAYLOAD = {
    # The namespace portion exactly as the wheel ships it: no __init__.py.
    "examples/boc/address.py": b"VAR = 'boc-address'\n",
    "examples/hashmaps/dict.py": b"VAR = 'dict'\n",
    "examples/tl/blocks.py": b"VAR = 'blocks'\n",
    # The package the identity stack actually imports.
    "pytoniq_core/__init__.py": b"REAL = 'pytoniq-core'\n",
}


@pytest.fixture
def site(tmp_path: Path) -> Path:
    result = tmp_path / "site-packages"
    result.mkdir()
    return result


def tops_of(scripts: Scripts, site: Path, production: bool = False):
    dists = scripts.check.scan_site_packages(site)
    return scripts.check.evaluate(dists, production=production), dists


class TestInventory:
    def test_namespace_and_package_both_count(self, scripts, site):
        """A namespace portion and a regular package both contribute a top-level
        name: the pytoniq wheel must read as {examples, pytoniq_core}."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        _, dists = tops_of(scripts, site)
        assert dists[0].top_levels == {"examples", "pytoniq_core"}

    def test_bare_module_and_config_rows(self, scripts, site):
        """A bare module counts; ``.pth`` config, scheme dirs, wheel data trees
        and ``..`` escapes do not — and each exclusion says why."""
        files = {
            "curio.py": b"x = 1\n",
            "curio.pth": b"import curio_something\n",
            "bin/curio-cli": b"#!/bin/sh\n",
            "curio-1.0.data/scripts/entry": b"#!/bin/sh\n",
        }
        make_dist(site, "curio", "1.0", files)
        di_rows = ["../../outside.txt", "", "curio-1.0.dist-info/RECORD"]
        with (site / "curio-1.0.dist-info" / "RECORD").open(
            "a", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh, lineterminator="\n").writerows([[r] for r in di_rows if r])
        _, dists = tops_of(scripts, site)
        assert dists[0].top_levels == {"curio"}
        reasons = " ".join(dists[0].skipped_rows)
        for fragment in (".pth", "scheme directory", "data tree", "escapes"):
            assert fragment in reasons, reasons

    def test_missing_record_is_a_finding_not_silence(self, scripts, site):
        """An uninventorable distribution reads the same as a safe one, so it
        must fail until it can be scanned."""
        di = site / "mystery-1.0.dist-info"
        di.mkdir()
        (di / "METADATA").write_text("Metadata-Version: 2.4\nName: mystery\nVersion: 1.0\n")
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["unscannable"]
        assert findings[0].distribution == "mystery"

    def test_metadata_name_is_normalized(self, scripts, site):
        """Registry keys are PEP 503 normalized; METADATA spellings that differ
        only in case/dots/underscores must land on the same key."""
        make_dist(site, "Pytoniq.Core_FORK", "0.1.48", {"pytoniq_core/__init__.py": b"x = 1\n"})
        _, dists = tops_of(scripts, site)
        assert dists[0].name == "pytoniq-core-fork"

    def test_top_level_extension_counts_by_import_name(self, scripts, site):
        """A top-level extension module is import surface keyed by IMPORT name:
        ``grunt.cpython-312-x86_64-linux-gnu.so`` must read as ``grunt``, not as
        a filename — the same import an attacker would shadow."""
        make_dist(site, "grunt", "1.0", {"grunt.cpython-312-x86_64-linux-gnu.so": b"\\x7fELF"})
        _, dists = tops_of(scripts, site)
        assert dists[0].top_levels == {"grunt"}

    def test_extensionless_top_level_file_is_not_import_surface(self, scripts, site):
        """A stray top-level LICENSE or README is data, not a module: excluded
        with a stated reason, and never entering the inventory as a name."""
        make_dist(site, "chatty", "1.0", {"chatty/__init__.py": b"x = 1\n"})
        di_rows = ["LICENSE", "README"]
        with (site / "chatty-1.0.dist-info" / "RECORD").open(
            "a", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh, lineterminator="\n").writerows([[r] for r in di_rows])
        _, dists = tops_of(scripts, site)
        assert dists[0].top_levels == {"chatty"}
        assert "top-level non-Python file" in " ".join(dists[0].skipped_rows)

    def test_dist_info_without_metadata_falls_back_to_the_stem(self, scripts, site):
        """A dist-info with no METADATA at all is still a distribution: its name
        comes from the directory stem (which installers keep in sync), so the
        inventory cannot be blinded by deleting one file."""
        make_dist(site, "shy-dist", "2.0", {"shy/__init__.py": b"x = 1\n"}, omit_metadata=True)
        _, dists = tops_of(scripts, site)
        assert dists[0].name == "shy-dist"
        assert dists[0].top_levels == {"shy"}

    @pytest.mark.parametrize(
        "metadata",
        [
            "Metadata-Version: 2.4\nVersion: 1.0\n\nname comes later, after a blank line\n",
            "Metadata-Version: 2.4\nVersion: 1.0\nSummary: no blank line, no Name\n",
        ],
        ids=["blank-line-before-name", "no-name-before-end"],
    )
    def test_metadata_without_a_name_header_falls_back_to_the_stem(self, scripts, site, metadata):
        """METADATA that never states ``Name:`` (both before a blank line and
        through end-of-file) must not yield an unnamed distribution: the stem
        fallback keeps every payload attributable."""
        make_dist(site, "nameless", "3.1", {"nameless/mod.py": b"x = 1\n"}, metadata=metadata)
        _, dists = tops_of(scripts, site)
        assert dists[0].name == "nameless"

    def test_a_file_named_dist_info_is_not_a_distribution(self, scripts, site):
        """A regular FILE named ``*.dist-info`` (an installer crash artifact)
        is not a distribution: scanning it would crash or, worse, invent an
        empty inventory. It must be skipped outright."""
        (site / "ghost-1.0.dist-info").write_text("not a directory", encoding="utf-8")
        make_dist(site, "real", "1.0", {"real/__init__.py": b"x = 1\n"})
        findings, dists = tops_of(scripts, site)
        assert [d.name for d in dists] == ["real"]
        assert findings == []


class TestRejection:
    def test_dev_scan_accepts_the_reviewed_examples(self, scripts, site):
        """The reviewed (examples, pytoniq-core-fork) pair passes in dev mode —
        this is the disposition the synced repo environment relies on."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        findings, _ = tops_of(scripts, site)
        assert findings == []

    def test_unreviewed_generic_is_rejected(self, scripts, site, monkeypatch):
        """Drop the review and the same payload is a finding naming the
        distribution — the gate is what stands between #406 and a relapse."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        monkeypatch.delitem(scripts.check.REVIEWED_NAMESPACES, "examples")
        findings, _ = tops_of(scripts, site)
        kinds = {(f.kind, f.top_level, f.distribution) for f in findings}
        assert ("unreviewed-generic", "examples", "pytoniq-core-fork") in kinds

    def test_the_review_is_keyed_to_the_distribution(self, scripts, site):
        """A second distribution shipping the reviewed name is a NEW unreviewed
        event — the entry must not cover it."""
        make_dist(site, "some-other-fork", "9.9", {"examples/stuff.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["unreviewed-generic"]
        assert findings[0].distribution == "some-other-fork"
        assert "some-other-fork" in findings[0].detail

    def test_production_mode_rejects_reviewed_presence(self, scripts, site):
        """Reviewed means dev/CI. In production mode the reviewed-but-present
        namespace is exactly the thing --production exists to catch."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        findings, dists = tops_of(scripts, site, production=True)
        assert [f.kind for f in findings] == ["pruned-present"]
        assert findings[0].top_level == "examples"
        # The finding names its remediation tool at runtime (scripts/
        # <PRUNE_TOOL_STEM>.py), and so does the rendered report — the named
        # constant is live output, not documentation.
        assert scripts.check.PRUNE_TOOL_STEM in findings[0].detail
        report = scripts.check._render(dists, findings, [site], production=True)
        assert f"scripts/{scripts.check.PRUNE_TOOL_STEM}.py" in report

    def test_production_mode_passes_after_prune(self, scripts, site):
        """Simulate the image-build prune (rows and files gone) and the strict
        scan is clean: this is the state every shipped image is held to."""
        payload = dict(PYTONIQ_PAYLOAD)
        payload.pop("pytoniq_core/__init__.py")
        make_dist(site, "pytoniq-core-fork", "0.1.48", {"pytoniq_core/__init__.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site, production=True)
        assert [f.kind for f in findings if f.kind == "pruned-present"] == []
        assert payload  # the fixture above is the pruned shape, not an empty one

    def test_generic_dependency_name_without_review_is_rejected(self, scripts, site):
        """Any generic name — not just examples — arrives rejected by default."""
        make_dist(site, "sloppy-pkg", "1.0", {"utils/helpers.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert [(f.kind, f.top_level) for f in findings] == [("unreviewed-generic", "utils")]

    def test_multi_owner_rejected_even_as_namespaces(self, scripts, site):
        """Two distributions contributing one top-level name is a collision in
        a shared site-packages even when both are namespace portions."""
        make_dist(site, "split-a", "1.0", {"zope/one.py": b"x = 1\n"})
        make_dist(site, "split-b", "1.0", {"zope/two.py": b"x = 2\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["multi-owner"]
        assert findings[0].distribution == "split-a,split-b"

    @pytest.mark.parametrize("split", ["jaraco", "google", "opentelemetry"])
    def test_regular_package_in_a_split_is_never_reviewed_away(self, scripts, site, split):
        """A reviewed split covers namespace portions only: one regular package
        among contributors re-opens the collision — for every reviewed split."""
        make_dist(site, "split-a", "1.0", {f"{split}/one.py": b"x = 1\n"})
        make_dist(site, "split-b", "1.0", {f"{split}/two.py": b"x = 2\n"})
        make_dist(site, "impostor", "1.0", {f"{split}/__init__.py": b"x = 0\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["multi-owner"]
        assert findings[0].top_level == split

    def test_the_real_upstream_splits_pass(self, scripts, site):
        """The exact contributor sets the shipped images resolve — protobuf +
        googleapis-common-protos under google/, the otel family under
        opentelemetry/ — are namespace portions and pass review."""
        make_dist(site, "protobuf", "5.29.6", {"google/protobuf/message.py": b"x = 1\n"})
        make_dist(
            site,
            "googleapis-common-protos",
            "1.70.0",
            {"google/api/annotations_pb2.py": b"x = 1\n"},
        )
        for name in (
            "opentelemetry-api",
            "opentelemetry-sdk",
            "opentelemetry-exporter-otlp-proto-grpc",
            "opentelemetry-semantic-conventions",
        ):
            make_dist(site, name, "1.45.0", {f"opentelemetry/{name.split('-')[-1]}.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert findings == []

    def test_the_py_debt_pair_is_accepted_with_its_regular_package(self, scripts, site):
        """The rsi-runner's exact collision — pytest's bare py.py shim plus the
        legacy py distribution's regular py/ package — is accepted debt with an
        owner (#348), the only review that may include a regular package."""
        make_dist(site, "pytest", "9.1.1", {"py.py": b"from _pytest import py\n"})
        make_dist(site, "py", "1.11.0", {"py/__init__.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert findings == []

    def test_the_py_debt_cannot_grow_a_third_contributor(self, scripts, site):
        """The accepted pair stays accepted; anything wider re-opens it."""
        make_dist(site, "pytest", "9.1.1", {"py.py": b"shim\n"})
        make_dist(site, "py", "1.11.0", {"py/__init__.py": b"x = 1\n"})
        make_dist(site, "py-again", "2.0", {"py/extra.py": b"x = 2\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["multi-owner"]
        assert findings[0].distribution == "py,py-again,pytest"

    def test_reviewed_namespace_split_passes(self, scripts, site):
        """The upstream-coordinated jaraco PEP 420 split (disjoint portions, no
        __init__.py anywhere) is the reviewed exception and passes."""
        make_dist(site, "jaraco.classes", "3.4", {"jaraco/classes.py": b"x = 1\n"})
        make_dist(site, "jaraco.context", "5.3", {"jaraco/context.py": b"x = 2\n"})
        findings, _ = tops_of(scripts, site)
        assert findings == []

    def test_first_party_shadow_has_no_review_escape(self, scripts, site):
        """A dependency wheel contributing `maistro` is the shadowing hazard
        #406 exists to prevent; nothing in the registries can allow it."""
        make_dist(site, "typosquat-core", "1.0", {"maistro/__init__.py": b"EVIL = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["first-party-shadow"]
        assert findings[0].distribution == "typosquat-core"

    def test_the_entitled_owner_passes(self, scripts, site):
        """maistro-core installing its own `maistro` package is the one legal
        claim (what a wheel-installed first-party env looks like)."""
        make_dist(site, "maistro-core", "0.9.0", {"maistro/__init__.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert findings == []

    def test_a_lookalike_name_is_not_entitled(self, scripts, site):
        """Entitlement is a map, not a spelling heuristic: `not-maistro-core`
        must not pass for maistro-core."""
        make_dist(site, "not-maistro-core", "1.0", {"maistro/__init__.py": b"x = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["first-party-shadow"]

    def test_first_party_name_shared_with_a_dependency(self, scripts, site):
        """When our wheel and a dependency both land the same top-level in one
        site-packages, that is the overwrite collision, named as ours."""
        make_dist(site, "maistro-core", "0.9.0", {"maistro/__init__.py": b"OURS = 1\n"})
        make_dist(site, "typosquat-core", "1.0", {"maistro/other.py": b"THEIRS = 1\n"})
        findings, _ = tops_of(scripts, site)
        assert [f.kind for f in findings] == ["first-party-shadow"]
        assert "typosquat-core" in findings[0].distribution


class TestReportAndCli:
    """The report and the argument surface: what an operator actually sees and
    runs. A gate whose remediation text or exit codes are wrong is a gate that
    gets rerun with --force until it goes away."""

    def test_clean_report_says_no_unreviewed_namespaces(self, scripts, site):
        """The empty-finding report is explicit, not blank — silence reads the
        same as a crash in a build log."""
        report = scripts.check._render([], [], [site], production=False)
        assert "no unreviewed top-level namespaces." in report

    def test_default_site_packages_distinguishes_platlib(self, scripts, monkeypatch):
        """The default scan scope is purelib plus platlib WHEN THEY DIFFER:
        a split-layout environment must not leave its platlib payload
        unscanned, and a merged layout must not scan one directory twice."""
        pure = "/env/pure"
        monkeypatch.setattr(
            scripts.check.sysconfig,
            "get_paths",
            lambda: {"purelib": pure, "platlib": "/env/plat"},
        )
        assert scripts.check.default_site_packages() == [Path(pure), Path("/env/plat")]
        monkeypatch.setattr(
            scripts.check.sysconfig,
            "get_paths",
            lambda: {"purelib": pure, "platlib": pure},
        )
        assert scripts.check.default_site_packages() == [Path(pure)]

    def test_uninventorable_contributor_proves_no_regular_package(self, scripts, site):
        """A distribution whose payload cannot be listed cannot PROVE it ships
        ``<top>/__init__.py``, so it must not satisfy a namespace-split review:
        otherwise an unscannable wheel could ride in as a reviewed co-owner."""
        di = site / "shadowy-1.0.dist-info"
        di.mkdir()  # no RECORD: the unscannable case
        unscannable = scripts.check.Distribution(name="shadowy", dist_info=di, top_levels=set())
        assert scripts.check._ships_regular_package(unscannable, "zope") is False

    def test_cli_json_inventory_exits_zero_and_parses(self, scripts, site):
        """--json on a clean fabricated site: exit 0, and the payload is the
        machine inventory the gate's callers consume."""
        make_dist(site, "calm", "1.0", {"calm/__init__.py": b"x = 1\n"})
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = scripts.check.main(["--site-packages", str(site), "--json"])
        assert code == 0
        payload = json.loads(buffer.getvalue())
        assert payload["production"] is False
        assert payload["distributions"] == {"calm": ["calm"]}
        assert payload["findings"] == []

    def test_cli_production_json_exits_one_with_the_finding(self, scripts, site):
        """--production --json on a shipped-shaped env carrying the reviewed
        namespace: exit 1, and the finding is in the machine payload."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = scripts.check.main(["--site-packages", str(site), "--production", "--json"])
        assert code == 1
        payload = json.loads(buffer.getvalue())
        assert [f["kind"] for f in payload["findings"]] == ["pruned-present"]

    def test_cli_missing_site_packages_exits_two(self, scripts):
        """A mistyped --site-packages path is a usage error (exit 2), not an
        empty scan that would report a clean bill for nothing."""
        assert scripts.check.main(["--site-packages", "/definitely/not/here-406"]) == 2

    def test_cli_human_report_names_the_remediation(self, scripts, site):
        """The human report on a production finding prints the prune tool by
        its real path — the operator's next command is in the output."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = scripts.check.main(["--site-packages", str(site), "--production"])
        assert code == 1
        assert f"scripts/{scripts.check.PRUNE_TOOL_STEM}.py" in buffer.getvalue()


class TestShadowingSemantics:
    """The language-level claim behind the gate: a first-party REGULAR package
    shadows a dependency's namespace portion regardless of sys.path order, and
    the dependency's namespace is only reachable when nothing of ours claims
    the name. Proven with a real interpreter, not by re-stating the rule."""

    @pytest.fixture
    def trees(self, tmp_path: Path) -> tuple[Path, Path]:
        ours = tmp_path / "first_party_src"
        dep = tmp_path / "site-packages"
        (ours / "examples").mkdir(parents=True)
        (ours / "examples" / "__init__.py").write_text("MARKER = 'first-party'\n", encoding="utf-8")
        (dep / "examples" / "boc").mkdir(parents=True)
        (dep / "examples" / "boc" / "address.py").write_text(
            "VAR = 'pytoniq-example'\n", encoding="utf-8"
        )
        return ours, dep

    def _import_examples(
        self, trees: tuple[Path, Path], order: tuple[Path, Path]
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PYTHONPATH": str(order[0]) + ":" + str(order[1]),
            "PATH": "/usr/bin:/bin",
        }
        probe = (
            "import importlib, json, sys\n"
            "examples = importlib.import_module('examples')\n"
            "boc = None\n"
            "try:\n"
            "    boc = importlib.import_module('examples.boc.address')\n"
            "except ModuleNotFoundError:\n"
            "    pass\n"
            "print(json.dumps({'file': examples.__file__, 'path': list(examples.__path__),\n"
            "                  'marker': getattr(examples, 'MARKER', None), 'boc': getattr(boc, 'VAR', None)}))\n"
        )
        return subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_first_party_regular_package_wins_from_either_position(self, trees):
        ours, dep = trees
        for order in ((ours, dep), (dep, ours)):
            proc = self._import_examples(trees, order)
            assert proc.returncode == 0, proc.stderr
            result = json.loads(proc.stdout.strip().splitlines()[-1])
            assert result["marker"] == "first-party"
            assert result["file"].startswith(str(ours))
            assert str(dep / "examples") not in result["path"]
            assert result["boc"] is None, "the dependency's payload must not leak into ours"

    def test_dependency_namespace_is_the_residual_dev_surface(self, trees):
        """With no first-party claim on the name, the dependency's namespace is
        what `import examples` resolves to — the surface the gate documents and
        the shipped images remove."""
        _, dep = trees
        proc = self._import_examples(trees, (dep, Path("/nonexistent")))
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["marker"] is None
        assert result["boc"] == "pytoniq-example"
        # The dependency's namespace portion is on __path__. When this test
        # runs under the repo's own synced interpreter, the REAL pytoniq
        # `examples` portion merges in as well — which is exactly the residual
        # dev-environment surface the gate documents and the images prune.
        assert str(dep / "examples") in result["path"]


class TestPruneScript:
    @pytest.fixture
    def installed(self, site: Path) -> Path:
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        return site

    def _run(self, scripts: Scripts, site: Path, *extra: str) -> int:
        return scripts.prune.main(["--site-packages", str(site), "--no-import-check", *extra])

    def test_prune_removes_the_namespace_and_rewrites_record(self, scripts, installed):
        """The payload goes, the RECORD loses exactly its rows, and the rows the
        identity stack needs stay verbatim (hash included) — that rewritten
        RECORD is what makes the syft SBOM record the patch."""
        record = installed / "pytoniq_core_fork-0.1.48.dist-info" / "RECORD"
        before = record.read_text(encoding="utf-8")
        assert self._run(scripts, installed) == 0
        assert not (installed / "examples").exists()
        kept = [row for row in record.read_text(encoding="utf-8").splitlines() if row]
        assert [row[0] for row in csv.reader(kept)] == [
            "pytoniq_core/__init__.py",
            "pytoniq_core_fork-0.1.48.dist-info/METADATA",
        ]
        # The three payload rows that existed before are exactly what went.
        assert (
            sum(
                1
                for row in csv.reader(before.splitlines())
                if row and row[0].startswith("examples")
            )
            == 3
        )
        # The kept payload row survived with its hash column intact.
        assert "sha256=" in kept[0]

    def test_prune_keeps_the_fork_provenance_for_sbom(self, scripts, installed):
        """The distribution stays installed and named: syft catalogs from
        dist-info, so the SBOM keeps recording pkg:pypi/pytoniq-core-fork."""
        assert self._run(scripts, installed) == 0
        meta = (installed / "pytoniq_core_fork-0.1.48.dist-info" / "METADATA").read_text(
            encoding="utf-8"
        )
        assert "Name: pytoniq-core-fork" in meta

    def test_prune_is_idempotent(self, scripts, installed):
        assert self._run(scripts, installed) == 0
        assert self._run(scripts, installed) == 0
        assert not (installed / "examples").exists()

    def test_prune_is_keyed_to_the_distribution(self, scripts, site):
        """A second distribution shipping the same generic name is NOT pruned:
        an unreviewed namespace must surface in the production gate, not be
        silently removed."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        make_dist(site, "some-other-fork", "1.0", {"examples/other.py": b"x = 1\n"})
        assert self._run(scripts, site) == 0
        assert (site / "examples" / "other.py").exists()
        dists = scripts.check.scan_site_packages(site)
        findings = scripts.check.evaluate(dists, production=True)
        kinds = {(f.kind, f.distribution) for f in findings}
        assert ("pruned-present", "some-other-fork") in kinds

    def test_absent_distribution_is_a_noop(self, scripts, site):
        """Images that never install the identity stack (Dockerfile.research)
        run the same step; it must pass through, not fail."""
        assert self._run(scripts, site) == 0

    def test_import_check_flags_a_still_importable_name(self, scripts):
        """The build-time assertion detects an importable name — and does not
        pass vacuously for names that resolve."""
        assert scripts.prune.assert_not_importable("definitely_not_a_module_406") is True
        assert scripts.prune.assert_not_importable("csv") is False

    def test_prune_fails_loudly_when_the_gate_companion_is_unloadable(
        self, scripts, tmp_path, monkeypatch
    ):
        """The prune is keyed to PRUNED_IN_PRODUCTION, loaded live from the
        check script; the images COPY the two together. A companion that is
        missing or not a module must be a loud RuntimeError, never a prune
        against a silently empty target list."""
        impostor = tmp_path / "check-dependency-namespaces.txt"
        impostor.write_text("not python", encoding="utf-8")
        monkeypatch.setattr(scripts.prune, "_CHECK_SCRIPT", impostor)
        monkeypatch.delitem(sys.modules, "check_dependency_namespaces")
        with pytest.raises(RuntimeError):
            scripts.prune._load_check_module()

    def test_prune_reports_a_distribution_it_cannot_inventory(self, scripts, site):
        """A target distribution whose RECORD is gone cannot state what it
        installed, so the prune refuses (exit 1) instead of shipping an
        unaccounted payload."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        (site / "pytoniq_core_fork-0.1.48.dist-info" / "RECORD").unlink()
        assert scripts.prune.main(["--site-packages", str(site), "--no-import-check"]) == 1
        assert (site / "examples").exists()  # nothing was silently removed

    def test_finder_skips_non_dir_and_metadataless_dist_infos(self, scripts, site):
        """The dist-info finder walks every candidate: a FILE named
        ``*.dist-info`` and a directory without METADATA are skipped, and the
        real target behind them is still found and pruned."""
        (site / "ghost-1.0.dist-info").write_text("not a directory", encoding="utf-8")
        (site / "quiet-1.0.dist-info").mkdir()  # no METADATA inside
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        assert scripts.prune.main(["--site-packages", str(site), "--no-import-check"]) == 0
        assert not (site / "examples").exists()

    def test_finder_returns_none_when_no_candidate_matches(self, scripts, site):
        """A distribution whose METADATA names something else is rejected by
        name (not by directory spelling), and an absent target ends the search
        as None — the no-op path the research image relies on."""
        make_dist(site, "unrelated", "1.0", {"unrelated/__init__.py": b"x = 1\n"})
        results = scripts.prune.prune_site_packages(site)
        assert results == [("examples", "pytoniq-core-fork", 0)]

    def test_finder_stem_fallback_without_name_header(self, scripts, site):
        """METADATA with no ``Name:`` line still yields the distribution via
        the directory-stem fallback, so deleting one metadata line cannot hide
        a payload from the prune."""
        make_dist(
            site,
            "pytoniq-core-fork",
            "0.1.48",
            PYTONIQ_PAYLOAD,
            metadata="Metadata-Version: 2.4\nVersion: 0.1.48\n",
        )
        results = scripts.prune.prune_site_packages(site)
        assert results == [("examples", "pytoniq-core-fork", 3)]
        assert not (site / "examples").exists()

    def test_prune_never_deletes_outside_site_on_escaped_rows(self, scripts, site):
        """A hostile RECORD row that escapes site-packages (``examples/../../x``)
        is dropped from the deletion set: the prune deletes exactly the rows it
        can prove were inside the scanned environment, and nothing beside it."""
        outside = site.parent / "outside-406.txt"
        outside.write_text("do not touch", encoding="utf-8")
        make_dist(
            site,
            "pytoniq-core-fork",
            "0.1.48",
            PYTONIQ_PAYLOAD,
            extra_record_rows=["examples/../../outside-406.txt"],
        )
        assert scripts.prune.main(["--site-packages", str(site), "--no-import-check"]) == 0
        assert outside.exists()
        assert not (site / "examples").exists()

    def test_prune_removes_a_recorded_directory_row(self, scripts, site):
        """Some installers record directories as bare rows. A row naming a
        directory goes through the same deletion as a file row — removed, and
        only when the prune's own RECORD listed it."""
        legacy = site / "examples" / "legacy"
        legacy.mkdir(parents=True)
        (legacy / "old.py").write_text("x = 1\n", encoding="utf-8")
        make_dist(
            site,
            "pytoniq-core-fork",
            "0.1.48",
            PYTONIQ_PAYLOAD,
            extra_record_rows=["examples/legacy"],
        )
        assert scripts.prune.main(["--site-packages", str(site), "--no-import-check"]) == 0
        assert not legacy.exists()

    def test_prune_rejects_a_missing_site(self, scripts):
        """A mistyped --site-packages is a usage error (exit 2), not a
        successful no-op against nothing."""
        assert scripts.prune.main(["--site-packages", "/definitely/not/here-406"]) == 2

    def test_prune_import_check_failure_fails_the_run(self, scripts, site, monkeypatch, capsys):
        """When a pruned name still resolves afterwards, the run fails with the
        named payload — a build whose prune stopped working must break, not
        ship."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        monkeypatch.setattr(scripts.prune, "assert_not_importable", lambda top: False)
        assert scripts.prune.main(["--site-packages", str(site)]) == 1
        assert "still importable after the prune" in capsys.readouterr().err

    def test_prune_reports_verified_when_the_import_check_holds(
        self, scripts, site, monkeypatch, capsys
    ):
        """The default (no --no-import-check) run states what it verified, so a
        build log shows the assertion ran rather than nothing at all."""
        make_dist(site, "pytoniq-core-fork", "0.1.48", PYTONIQ_PAYLOAD)
        monkeypatch.setattr(scripts.prune, "assert_not_importable", lambda top: True)
        assert scripts.prune.main(["--site-packages", str(site)]) == 0
        assert "verified: 1 pruned namespace(s) no longer importable" in capsys.readouterr().out


class TestRealEnvironment:
    def test_gate_passes_on_the_synced_repo_environment(self):
        """The dev/CI disposition is real: this environment has the full lock
        installed, and the gate passes on it without --production."""
        proc = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_examples_is_attributed_and_reviewed(self):
        """In the environment that has pytoniq-core-fork, the gate's inventory
        attributes `examples` to exactly the reviewed distribution."""
        proc = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(proc.stdout)
        tops = payload["distributions"].get("pytoniq-core-fork")
        if tops is None:
            pytest.skip("pytoniq-core-fork not installed in this environment")
        assert "examples" in tops
        assert "pytoniq_core" in tops
        assert payload["findings"] == []


class TestWiring:
    """The mitigation must not be able to silently vanish: the Dockerfiles that
    ship the identity stack run the prune + strict gate in one layer, and CI
    holds the dev environment and the built images to the same contract."""

    @pytest.mark.parametrize(
        "dockerfile",
        [ROOT / "Dockerfile", ROOT / "packages" / "hive-conductor" / "Dockerfile"],
        ids=["engine", "hive-conductor"],
    )
    def test_shipped_images_prune_and_assert_in_one_layer(self, dockerfile):
        text = dockerfile.read_text(encoding="utf-8")
        assert (
            "COPY scripts/check-dependency-namespaces.py scripts/prune-dependency-namespaces.py"
            in text
        )
        assert "prune-dependency-namespaces.py" in text
        assert "check-dependency-namespaces.py --production" in text

    def test_research_image_installs_no_identity_so_needs_no_prune(self):
        """Dockerfile.research is clean only while it stays off the identity
        extra; adding it must drag the prune along (this test fails first)."""
        text = (ROOT / "Dockerfile.research").read_text(encoding="utf-8")
        assert "identity" not in text

    def test_rsi_runner_prunes_after_the_frozen_sync(self):
        text = (ROOT / "Dockerfile.rsi-runner").read_text(encoding="utf-8")
        sync_at = text.index("uv sync --python 3.12 --frozen")
        prune_at = text.index("prune-dependency-namespaces.py")
        check_at = text.index("check-dependency-namespaces.py --production")
        assert sync_at < prune_at < check_at

    def test_ci_holds_the_dev_environment_to_the_gate(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "python scripts/check-dependency-namespaces.py" in ci

    @pytest.mark.parametrize(
        ("tag", "label"),
        [("maistro-engine:test", "engine"), ("hive-conductor:ci", "hive-conductor")],
    )
    def test_ci_asserts_the_built_images(self, tag, label):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert f"docker run --rm --entrypoint python {tag}" in ci
        assert "find_spec('examples') is None" in ci

    def test_the_live_prune_tool_stays_reachable_to_the_import_graph(self, scripts):
        """scripts/check-reachability.py roots tooling from WORKFLOW text only,
        and the places the prune actually runs — the shipped-image Dockerfiles
        and Dockerfile.rsi-runner — are not workflow text. A live tool the
        graph cannot root re-banks as a NEW unreachable identity, which fails
        the reachability provenance gate ("not previously authorized": a floor
        raise takes two merges). The gate's runtime reference — PRUNE_TOOL_STEM,
        printed by the pruned-present finding and the report remediation — is
        the sibling edge check-reachability.py's own rules accept, so this
        test holds that edge with the scanner's own edge walker: dropping the
        reference fails HERE, named, instead of as an unexplained provenance
        failure on an unrelated future change."""

        def load(path: Path, name: str) -> ModuleType:
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        reach = load(ROOT / "scripts" / "check-reachability.py", "check_reachability_for_406")
        tooling = reach._collect_tooling(reach.ROOT)
        workflows = reach._workflow_text(reach.ROOT)

        # Root half: the gate itself is executed by ci.yml, so the graph roots it.
        assert reach._tool_key("check-dependency-namespaces") in reach._tooling_roots(
            tooling, workflows
        )

        # Edge half: the rooted gate names the Dockerfile-run prune at runtime.
        edges = reach._tooling_edges(CHECK_SCRIPT, tooling)
        assert reach._tool_key(scripts.check.PRUNE_TOOL_STEM) in edges
        assert (ROOT / "scripts" / f"{scripts.check.PRUNE_TOOL_STEM}.py").is_file()


class TestFirstPartyMap:
    def test_map_covers_every_source_tree_top_level(self, scripts):
        """FIRST_PARTY_OWNERS is held against what packages/*/src actually
        contains — the map cannot drift from the workspace it protects."""
        src = ROOT / "packages"
        seen: dict[str, str] = {}
        for pkg in sorted(src.iterdir()):
            tree = pkg / "src"
            if not tree.is_dir():
                continue
            for entry in sorted(tree.iterdir()):
                name = entry.name.removesuffix(".py") if entry.suffix == ".py" else entry.name
                if name.startswith("__") or not (entry.is_dir() or entry.suffix == ".py"):
                    continue
                assert name not in seen, f"{name} claimed by both {seen[name]} and {pkg.name}"
                seen[name] = pkg.name
                assert name in scripts.check.FIRST_PARTY_OWNERS, (
                    f"{pkg.name} ships top-level {name!r} but FIRST_PARTY_OWNERS does not "
                    "entitle it — a dependency shipping the same name would be "
                    "indistinguishable from ours"
                )
        assert seen["maistro"] == "maistro-core"
        assert seen["_vulture_whitelist"] == "maistro-core"

    def test_hive_conductor_entry_names_its_remapped_wheel_root(self, scripts):
        """hive-conductor's flat backend has no src package root; the wheel
        remaps it under hive_conductor/ (the verify-wheel-imports skip
        documents the same fact). The map must still claim that name."""
        assert scripts.check.FIRST_PARTY_OWNERS["hive_conductor"] == {"hive-conductor"}
        assert (ROOT / "packages" / "hive-conductor" / "backend").is_dir()

    def test_prune_targets_are_gate_targets(self, scripts):
        """The prune loads PRUNED_IN_PRODUCTION from the gate module: one
        registry, so a prune target that the gate would not demand absent — or
        vice versa — is impossible by construction."""
        check = scripts.check
        assert check.PRUNED_IN_PRODUCTION == {"examples": "pytoniq-core-fork"}
        assert "examples" in check.REVIEWED_NAMESPACES
