"""Tests for the image-lock reconciliation gate (#348).

The security.yml `containers` job ends with this gate: dump every installed
distribution from a built image's own interpreter and compare it name==version
against the `uv export --locked` output the image's Dockerfile installed from.
Its first CI appearance failed the coverage gate, not the reconciliation: the
file existed only in workflow text, so no suite imported it and its changed
lines measured 0%. These tests import the script and drive its pure logic —
export parsing (conditional vs unconditional pins), dump parsing (docker/uv
noise lines), and every reconcile verdict through a faked `docker run` — so a
gate regression is a red test instead of a red workflow an hour into a build.

One real defect surfaced while writing them: the original `skewed`
comprehension compared each pin against itself (`for pin in actual &
everything_expected ... .pop() != pin`) and could never fire, so a version
skew was misreported as a missing+extra pair. `test_version_skew_*` pins the
fixed, name-keyed behaviour the script's own "version mismatch" heading
documents.

A second surfaced on 2026-10-24 (#1837 lane CI repair): fastmcp 4.1.3 made
beartype the first marker-split name in the engine export, and the per-name
collapse (last line wins) expected 0.23.1 while the python:3.13 image
correctly installed 0.22.9 — the hosted gate failed a correct image with
`version mismatch: beartype==0.22.9 (image) != beartype==0.23.1`.
`test_marker_split_*` and `test_version_outside_the_marker_split_*` pin the
name -> set-of-emitted-versions comparison.
"""

from __future__ import annotations

import importlib.util
import io
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-image-lock-reconciliation.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_image_lock_reconciliation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- canon()


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("fastapi", "fastapi"),
        ("PyJWT", "pyjwt"),
        ("bip_utils", "bip-utils"),
        ("typing.extensions", "typing-extensions"),
        ("maistro--core", "maistro-core"),
    ],
)
def test_canon_is_pep503_normalization(gate, raw, normalized):
    assert gate.canon(raw) == normalized


# -------------------------------------------------------- parse_expected()


def test_parse_expected_splits_conditional_from_required_pins(gate):
    text = "\n".join(
        [
            "# a comment line",
            "fastapi==0.142.2",
            "secretstorage==3.5.0 ; sys_platform == 'linux'",
            "pywin32==311 ; sys_platform == 'win32'",
            "cffi==2.0.0 \\",
            "    --hash=sha256:" + "aa" * 8,
            "",
        ]
    )
    required, conditional = gate.parse_expected(text)
    assert required == {"fastapi==0.142.2", "cffi==2.0.0"}
    assert conditional == {"secretstorage==3.5.0", "pywin32==311"}


def test_parse_expected_names_are_canonicalized(gate):
    required, _ = gate.parse_expected("Some_Pkg==1.0\n")
    assert required == {"some-pkg==1.0"}


@pytest.mark.parametrize("text", ["", "# only comments\n", "\n\n"])
def test_parse_expected_empty_export_is_a_red_exit(gate, text):
    with pytest.raises(SystemExit, match="requirements-txt"):
        gate.parse_expected(text)


# A lock that splits one package across environment markers exports several
# `name==version` lines for the SAME name, each with its own marker — beartype
# 0.22.9 for python_full_version < '3.15' and 0.23.1 for >= '3.15' in one
# export (uv.lock since the fastmcp re-lock, merge-queue run 40085096483,
# where a correct Python 3.13 engine image shipping 0.22.9 was failed against
# the surviving >= '3.15' pin).
SPLIT_EXPORT = "\n".join(
    [
        "beartype==0.22.9 ; python_full_version < '3.15' \\",
        "    --hash=sha256:" + "aa" * 8,
        "beartype==0.23.1 ; python_full_version >= '3.15' \\",
        "    --hash=sha256:" + "bb" * 8,
        "",
    ]
)


def test_parse_expected_keeps_every_version_of_a_split_resolution(gate):
    """The name-keyed dict kept only the LAST line's pin (0.23.1) and then
    demanded it from an interpreter that correctly resolved 0.22.9."""
    required, conditional = gate.parse_expected(SPLIT_EXPORT)
    assert required == set()  # every line is marker-conditioned
    assert conditional == {"beartype==0.22.9", "beartype==0.23.1"}


@pytest.mark.parametrize("shipped", ["0.22.9", "0.23.1"])
def test_split_resolution_reconciles_with_whichever_branch_the_image_resolved(
    gate, tmp_path, monkeypatch, capsys, shipped
):
    expected = _write_expected(tmp_path, SPLIT_EXPORT)
    _install_docker(monkeypatch, gate, _Docker(_dump(f"beartype=={shipped}")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "2 marker-conditional pin(s)" in out


def test_split_resolution_still_fails_on_a_version_neither_branch_pins(
    gate, tmp_path, monkeypatch, capsys
):
    expected = _write_expected(tmp_path, SPLIT_EXPORT)
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.20.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert (
        "version mismatch     : beartype==0.20.0 (image)"
        " != one of beartype==0.22.9, beartype==0.23.1" in out
    )
    # Still a single named mismatch — not a confusing missing/extra pair.
    assert "locked, not in image" not in out
    assert "in image, not locked" not in out


def test_split_resolution_leaves_single_pin_skews_and_requirements_alone(
    gate, tmp_path, monkeypatch, capsys
):
    """Adding a split package does not loosen anything else: an unconditional
    pin still must ship at its exact version (single-candidate mismatch lines
    keep their historical exact format)."""
    expected = _write_expected(
        tmp_path,
        SPLIT_EXPORT + "fastapi==0.142.2\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.22.9", "fastapi==0.21.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "version mismatch     : fastapi==0.21.0 (image) != fastapi==0.142.2" in out


# ---------------------------------------------------------- parse_actual()


def test_parse_actual_ignores_docker_and_uv_noise(gate):
    dump = "\n".join(
        [
            "",
            "+ already-installed==9.9.9",
            "* pressed==1.0.0",
            "- removed==0.1.0",
            "WARN something nonfatal",
            "Using CPython 3.13.16",
            "Checked 128 packages",
            # A non-empty, non-noise line that is simply not a pin — the arc
            # that reads a line, matches nothing, and carries on.
            "Resolved 128 packages in 3ms",
            "auditable==1.2.3",
            "bip_utils==2.12.2",
        ]
    )
    assert gate.parse_actual(dump) == {"auditable==1.2.3", "bip-utils==2.12.2"}


def test_parse_actual_empty_dump_is_a_red_exit(gate):
    with pytest.raises(SystemExit, match="no distributions"):
        gate.parse_actual("WARN nothing came out\n")


# ---------------------------------------------------------------- main()


class _Docker:
    """Stands in for `subprocess.run` on the `docker run` dump call."""

    def __init__(self, dump: str, returncode: int = 0, stderr: str = ""):
        self.dump = dump
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(
            argv, self.returncode, stdout=self.dump, stderr=self.stderr
        )


def _install_docker(monkeypatch, gate, docker: _Docker) -> _Docker:
    monkeypatch.setattr(gate.subprocess, "run", docker)
    return docker


def _write_expected(tmp_path: Path, text: str) -> Path:
    expected = tmp_path / "expected.txt"
    expected.write_text(text)
    return expected


def _argv(expected: Path, *members: str, image: str = "img:test") -> list[str]:
    argv = [
        "check-image-lock-reconciliation.py",
        "--image",
        image,
        "--expected-file",
        str(expected),
    ]
    for member in members:
        argv.extend(["--member", member])
    return argv


def _dump(*pins: str) -> str:
    return "\n".join(pins) + "\n"


def test_exact_match_reconciles(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\ncffi==2.0.0\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "cffi==2.0.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "2 distributions" in out
    assert "0 workspace member(s)" in out


def test_docker_invocation_targets_the_image_interpreter(gate, tmp_path, monkeypatch):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    docker = _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected, image="maistro-engine:pr-7"))
    assert gate.main() == 0
    assert docker.calls == [
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/app/venv/bin/python",
            "maistro-engine:pr-7",
            "-c",
            gate._DUMP,
        ]
    ]


def test_locked_pin_missing_from_image_fails(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\nuvloop==0.23.0\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "does NOT reconcile" in out
    assert "locked, not in image : uvloop==0.23.0" in out


def test_image_extra_not_in_lock_fails(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "shadowpkg==1.0.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    assert "in image, not locked : shadowpkg==1.0.0" in capsys.readouterr().out


def test_version_skew_is_named_as_a_mismatch(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.21.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "version mismatch     : fastapi==0.21.0 (image) != fastapi==0.142.2" in out
    # The skew is reported once, as a mismatch — not also as a confusing
    # missing/extra pair on either side of it.
    assert "locked, not in image" not in out
    assert "in image, not locked" not in out


def test_conditional_pin_absent_from_image_gates_nothing(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(
        tmp_path, "fastapi==0.142.2\npywin32==311 ; sys_platform == 'win32'\n"
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "1 marker-conditional pin(s)" in out


def test_conditional_pin_version_is_checked_when_it_ships(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "secretstorage==3.5.0 ; sys_platform == 'linux'\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("secretstorage==3.6.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "version mismatch     : secretstorage==3.6.0 (image) != secretstorage==3.5.0" in out


# ------------------------------------------------- marker-split versions
# fastmcp 4.1.3 resolves beartype per python_full_version, so the engine
# export legitimately carries TWO pins for one name (`beartype==0.22.9 ;
# python_full_version < '3.15'` and `beartype==0.23.1 ; python_full_version
# >= '3.15'`). Collapsing the export to one pin per name made the hosted
# 2026-10-24 gate fail a correct python:3.13 image that installed 0.22.9
# because the last-emitted line said 0.23.1: the split, not the install,
# chose that pair. Every emitted version of a split name must reconcile.

_SPLIT = (
    "fastapi==0.142.2\n"
    "beartype==0.22.9 ; python_full_version < '3.15'\n"
    "beartype==0.23.1 ; python_full_version >= '3.15'\n"
)


def test_parse_expected_keeps_every_marker_split_version(gate):
    required, conditional = gate.parse_expected(_SPLIT)
    assert required == {"fastapi==0.142.2"}
    assert conditional == {"beartype==0.22.9", "beartype==0.23.1"}


@pytest.mark.parametrize("installed", ["beartype==0.22.9", "beartype==0.23.1"])
def test_marker_split_reconciles_whichever_branch_the_interpreter_chose(
    gate, tmp_path, monkeypatch, capsys, installed
):
    expected = _write_expected(tmp_path, _SPLIT)
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", installed)))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "2 marker-conditional pin(s)" in out


def test_marker_split_pin_absent_from_image_still_gates_nothing(
    gate, tmp_path, monkeypatch, capsys
):
    # A split name is still all-conditional: no branch of it may become a
    # missing obligation, exactly like `pywin32` on a linux image.
    expected = _write_expected(tmp_path, _SPLIT)
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0


def test_version_outside_the_marker_split_fails_naming_every_branch(
    gate, tmp_path, monkeypatch, capsys
):
    expected = _write_expected(tmp_path, _SPLIT)
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "beartype==0.24.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    # `_expected_clause` names every accepted branch of the split (the
    # develop resolution of the duplicate fix, run 40085096483, is canonical;
    # the clause also appends an `or`-joined form for operators).
    assert (
        "version mismatch     : beartype==0.24.0 (image) != "
        "one of beartype==0.22.9, beartype==0.23.1" in out
    )
    # The out-of-split version is a single named mismatch — not also a
    # confusing missing/extra pair.
    assert "locked, not in image" not in out
    assert "in image, not locked" not in out


def test_conditional_pin_with_multiple_marker_versions_accepts_either_branch(
    gate, tmp_path, monkeypatch, capsys
):
    """A lock can resolve one name to several marker-conditional versions
    (beartype 0.22.9 for python<3.15 and 0.23.1 for python>=3.15). The image
    ships one branch, so matching ANY branch must reconcile. Regression for
    #5: collapsing the name to one pin compared the installed branch against
    the other branch and red-lit a correct image."""
    expected = _write_expected(
        tmp_path,
        "fastapi==0.142.2\n"
        "beartype==0.22.9 ; python_full_version < '3.15'\n"
        "beartype==0.23.1 ; python_full_version >= '3.15'\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "beartype==0.22.9")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "2 marker-conditional pin(s)" in out


def test_conditional_pin_with_multiple_marker_versions_still_names_an_unknown_branch(
    gate, tmp_path, monkeypatch, capsys
):
    """The leniency is for the lock's OWN branches. A third, unnamed version
    is still a real divergence and must be reported as a version mismatch."""
    expected = _write_expected(
        tmp_path,
        "fastapi==0.142.2\n"
        "beartype==0.22.9 ; python_full_version < '3.15'\n"
        "beartype==0.23.1 ; python_full_version >= '3.15'\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "beartype==0.24.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "version mismatch     : beartype==0.24.0 (image) != " in out
    assert "beartype==0.22.9 or beartype==0.23.1" in out
    assert "locked, not in image" not in out
    assert "in image, not locked" not in out
def test_member_pin_satisfies_the_contract(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(
        monkeypatch,
        gate,
        _Docker(_dump("fastapi==0.142.2", "maistro-core==0.9.0")),
    )
    monkeypatch.setattr(sys, "argv", _argv(expected, "maistro-core==0.9.0"))
    assert gate.main() == 0
    assert "1 workspace member(s)" in capsys.readouterr().out


def test_member_pin_missing_from_image_fails(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected, "maistro-core==0.9.0"))
    assert gate.main() == 1
    assert "locked, not in image : maistro-core==0.9.0" in capsys.readouterr().out


def test_member_version_skew_is_named_as_a_mismatch(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2", "maistro-core==0.8.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected, "maistro-core==0.9.0"))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "version mismatch     : maistro-core==0.8.0 (image) != maistro-core==0.9.0" in out
    assert "locked, not in image" not in out


def test_malformed_member_pin_is_rejected(gate, tmp_path, monkeypatch):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected, "maistro-core"))
    with pytest.raises(SystemExit, match="--member expects name==version"):
        gate.main()


def test_docker_failure_is_surfaced_verbatim(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(
        monkeypatch,
        gate,
        _Docker("", returncode=125, stderr="docker: cannot connect to the daemon\n"),
    )
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    captured = capsys.readouterr()
    assert "cannot connect to the daemon" in captured.err


def test_expected_stdin_path(gate, monkeypatch, capsys):
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "stdin", io.StringIO("fastapi==0.142.2\n"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["check-image-lock-reconciliation.py", "--image", "img:test", "--expected-stdin"],
    )
    assert gate.main() == 0
    assert "ships exactly the locked set" in capsys.readouterr().out


def test_expected_file_and_stdin_are_mutually_exclusive(gate, tmp_path, monkeypatch):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check-image-lock-reconciliation.py",
            "--image",
            "img:test",
            "--expected-file",
            str(expected),
            "--expected-stdin",
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        gate.main()
    assert excinfo.value.code == 2  # argparse's usage-error exit


def test_dunder_main_entrypoint_runs_the_real_gate(tmp_path, monkeypatch, capsys):
    """`python scripts/check-image-lock-reconciliation.py ...` — the security.yml
    invocation — must dispatch through the __main__ guard and exit 0 on a
    reconciling image. In-process under the coverage producer only runpy can
    execute that guard, so this also keeps the entry point itself measured."""
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n")
    exits: list[object] = []
    monkeypatch.setattr(sys, "argv", _argv(expected))
    monkeypatch.setattr(sys, "exit", exits.append)

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=_dump("fastapi==0.142.2"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exits == [0]
    assert "ships exactly the locked set" in capsys.readouterr().out
