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

A second surfaced on 2026-10-24 (merge-queue CI run 40098994490, also
develop's nightly 120893836854): once uv first FORKED a resolution in the
lock — beartype 0.22.9 for `python_full_version < '3.15'`, 0.23.1 for
`>= '3.15'` — the last-wins pins dict kept only the >=3.15 fork, and the
name-wise skew check red-flagged every py3.13 image for shipping exactly the
version its interpreter's marker selects. The `test_forked_pin_*` cases pin
the repair: a forked name reconciles with any version the lock resolves for
it, and only a version outside every fork stays red.
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
    required, conditional, _ = gate.parse_expected(text)
    assert required == {"fastapi==0.142.2", "cffi==2.0.0"}
    assert conditional == {"secretstorage==3.5.0", "pywin32==311"}


def test_parse_expected_names_are_canonicalized(gate):
    required, _, _ = gate.parse_expected("Some_Pkg==1.0\n")
    assert required == {"some-pkg==1.0"}


@pytest.mark.parametrize("text", ["", "# only comments\n", "\n\n"])
def test_parse_expected_empty_export_is_a_red_exit(gate, text):
    with pytest.raises(SystemExit, match="requirements-txt"):
        gate.parse_expected(text)


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


# ------------------------------------------------------ forked versions()


def test_parse_expected_reports_forked_versions_per_name(gate):
    """A uv resolution fork (one name, several marker-scoped versions) must
    surface as a name -> all-locked-versions map, whatever order the forks
    appear in the export."""
    text = "\n".join(
        [
            "beartype==0.23.1 ; python_full_version >= '3.15' \\",
            "    --hash=sha256:" + "bb" * 8,
            "beartype==0.22.9 ; python_full_version < '3.15' \\",
            "    --hash=sha256:" + "aa" * 8,
            "fastapi==0.142.2",
        ]
    )
    required, conditional, forked = gate.parse_expected(text)
    assert forked == {"beartype": {"0.22.9", "0.23.1"}}
    # Both forks are marker-conditional, so neither gates presence; the
    # conditional set itself stays last-wins (one pin per name) — that is
    # exactly the lossage the forked-versions map exists to repair.
    assert required == {"fastapi==0.142.2"}
    assert conditional == {"beartype==0.22.9"}


def test_parse_expected_single_version_name_is_not_forked(gate):
    _, _, forked = gate.parse_expected(
        "secretstorage==3.5.0 ; sys_platform == 'linux'\nfastapi==0.142.2\n"
    )
    assert forked == {}


def test_forked_pin_matching_the_image_interpreter_reconciles(gate, tmp_path, monkeypatch, capsys):
    """The 2026-10-24 merge-queue break (CI run 40098994490): the py3.13
    images ship beartype==0.22.9 — what the lock's `< '3.15'` fork prescribes
    — while the last-wins pins dict kept the `>= '3.15'` fork, and the
    name-wise skew check red-flagged a correct image. The gate must accept
    any version the lock resolves for a forked name."""
    expected = _write_expected(
        tmp_path,
        "\n".join(
            [
                "beartype==0.22.9 ; python_full_version < '3.15'",
                "beartype==0.23.1 ; python_full_version >= '3.15'",
            ]
        )
        + "\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.22.9")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "does NOT reconcile" not in out


def test_forked_pin_other_branch_reconciles_too(gate, tmp_path, monkeypatch, capsys):
    """The inverse fork (a >=3.15 image) reconciles the same way — the forks'
    order in the export must not decide the verdict."""
    expected = _write_expected(
        tmp_path,
        "\n".join(
            [
                "beartype==0.22.9 ; python_full_version < '3.15'",
                "beartype==0.23.1 ; python_full_version >= '3.15'",
            ]
        )
        + "\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.23.1")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    assert "ships exactly the locked set" in capsys.readouterr().out


def test_forked_pin_outside_every_locked_version_fails(gate, tmp_path, monkeypatch, capsys):
    """Fork leniency covers only versions the lock actually resolves: an image
    shipping beartype==0.20.0 ships something no environment of this lock
    ever installed, and that stays a red exit naming every locked fork."""
    expected = _write_expected(
        tmp_path,
        "\n".join(
            [
                "beartype==0.22.9 ; python_full_version < '3.15'",
                "beartype==0.23.1 ; python_full_version >= '3.15'",
            ]
        )
        + "\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.20.0")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "does NOT reconcile" in out
    assert "version mismatch     : beartype==0.20.0 (image) is none of the lock's versions" in out
    assert "0.22.9" in out and "0.23.1" in out


def test_forked_pin_absent_from_image_gates_nothing(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(
        tmp_path,
        "\n".join(
            [
                "fastapi==0.142.2",
                "beartype==0.22.9 ; python_full_version < '3.15'",
                "beartype==0.23.1 ; python_full_version >= '3.15'",
            ]
        )
        + "\n",
    )
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "1 marker-conditional pin(s)" in out


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
