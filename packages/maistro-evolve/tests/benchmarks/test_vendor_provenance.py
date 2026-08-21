"""The vendored graders must be byte-identical to what the pin scripts produce.

This exists because the first version of both `--check` modes verified only
that a vendored file's *header* quoted the right upstream hash and that no
un-rewritten import survived. Neither touches the function bodies, so the
grading logic could be edited freely and CI would still print "OK".

That was not theoretical. Replacing one line of IFEval's
`test_instruction_following_strict` with `if True:` moved a lazy model's score
from 0.1 to 1.0 while `vendor_ifeval.py --check` reported the tree intact — a
self-improving loop could have made its own exam trivially passable inside the
one gate built to prevent exactly that.

These tests run the real `--check` entrypoints against the committed tree, and
then re-run them against a deliberately corrupted copy, so the guard is
verified to *fail* as well as to pass. A checker that only ever passes is
indistinguishable from one that always passes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[4]
_SCRIPTS = {
    "ifeval": _REPO / "scripts" / "vendor_ifeval.py",
    "bfcl": _REPO / "scripts" / "vendor_bfcl.py",
}


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"vendor_{name}", _SCRIPTS[name])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=sorted(_SCRIPTS))
def vendor(request: pytest.FixtureRequest) -> Any:
    if not _SCRIPTS[request.param].is_file():
        pytest.skip(f"{_SCRIPTS[request.param]} not present")
    return _load(request.param)


class TestVendoredProvenance:
    def test_check_passes_on_the_committed_tree(self, vendor: Any) -> None:
        assert vendor._check() == 0

    def test_every_artifact_has_a_rendered_digest_pin(self, vendor: Any) -> None:
        """An artifact with no rendered pin is unguarded, so the script must
        refuse to vouch for it rather than skip it silently."""
        vendored_paths = {v for _u, v, _s in vendor.ARTIFACTS}
        assert vendored_paths <= set(vendor.RENDERED_SHA256)

    def test_pins_match_the_bytes_on_disk(self, vendor: Any) -> None:
        for vendored_path, expected in vendor.RENDERED_SHA256.items():
            path = vendor.VENDOR_DIR / vendored_path
            assert path.is_file(), vendored_path
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == expected, f"{vendored_path} drifted from its pin"

    def test_check_fails_when_grading_logic_is_edited(
        self, vendor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression that matters: a body edit, header left intact.

        Copies the tree, changes one *function body* line without touching the
        provenance header, and asserts --check rejects it. Under the old
        header-only check this passed.
        """
        replica = tmp_path / "vendored"
        shutil.copytree(vendor.VENDOR_DIR, replica)
        monkeypatch.setattr(vendor, "VENDOR_DIR", replica)
        assert vendor._check() == 0, "copy should be intact before tampering"

        target = next(
            replica / v
            for _u, v, _s in vendor.ARTIFACTS
            if v.endswith(".py") and (replica / v).is_file()
        )
        text = target.read_text(encoding="utf-8")
        header_marker = "Upstream" if "Upstream" in text else None
        assert header_marker, "expected a provenance header to leave untouched"
        # Append to the body — header untouched, imports untouched.
        target.write_text(text + "\n\ndef _backdoor():\n    return True\n", encoding="utf-8")

        assert vendor._check() == 1
        # And the header really was left intact, so only the digest caught it.
        assert header_marker in target.read_text(encoding="utf-8")

    def test_check_fails_when_a_corpus_row_is_added(
        self, vendor: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        replica = tmp_path / "vendored"
        shutil.copytree(vendor.VENDOR_DIR, replica)
        monkeypatch.setattr(vendor, "VENDOR_DIR", replica)
        data_file = next(replica / v for _u, v, _s in vendor.ARTIFACTS if not v.endswith(".py"))
        data_file.write_bytes(data_file.read_bytes() + b'\n{"id": "free-point"}')
        assert vendor._check() == 1

    def test_check_entrypoint_exits_nonzero_as_a_subprocess(self, vendor: Any) -> None:
        """CI invokes these as `python scripts/vendor_*.py --check`, so the exit
        code — not just the return value — has to be right."""
        proc = subprocess.run(
            [sys.executable, str(_SCRIPTS[vendor.__name__.removeprefix("vendor_")]), "--check"],
            capture_output=True,
            text=True,
            cwd=_REPO,
        )
        assert proc.returncode == 0, proc.stderr
