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

A second defect surfaced in the #93 repair round: `uv export` writes one line
per locked artifact *with its environment marker*, and a lock forked across
interpreter ranges legitimately carries two versions of one name (beartype
0.22.9 below Python 3.15, 0.23.1 above). The name→pin dict kept only the last
fork, so a Python 3.13 image correctly shipping 0.22.9 was flagged as skewing
against the 3.15-only pin — hosted run 40101751150's `version mismatch :
beartype==0.22.9 (image) != beartype==0.23.1`. The script now groups pins by
name, captures the image interpreter's PEP 508 environment in the dump
(`@image-env@`), evaluates each fork's marker against it, and requires the
applicable fork — with a lenient degradation when no environment is
available. `test_forked_pin_*` and `test_evaluate_marker_*` pin that behavior,
including the negative paths (wrong fork still red, extra/missing still red).
"""

from __future__ import annotations

import importlib.util
import io
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-image-lock-reconciliation.py"

# The exact shape uv export writes for a lock forked across interpreter
# ranges: one line per fork, hash continuations on their own lines (#93).
# The develop line's lock carries this beartype fork, and the maistro-engine
# image (Python 3.13.16) correctly installs the < '3.15' fork.
BEARTYPE_FORK = "\n".join(
    [
        "beartype==0.22.9 ; python_full_version < '3.15' \\",
        "    --hash=sha256:" + "aa" * 8,
        "beartype==0.23.1 ; python_full_version >= '3.15' \\",
        "    --hash=sha256:" + "bb" * 8,
        "",
    ]
)


def _image_env(**overrides: str) -> dict[str, str]:
    """The PEP 508 environment of a Python 3.13.16 linux image interpreter,
    the shape the gate's in-image snippet emits."""
    env = {
        "implementation_name": "cpython",
        "implementation_version": "3.13.16",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_python_implementation": "CPython",
        "platform_release": "6.1.0-generic",
        "platform_system": "Linux",
        "platform_version": "#1 SMP",
        "python_full_version": "3.13.16",
        "python_version": "3.13",
        "sys_platform": "linux",
    }
    env.update(overrides)
    return env


def _env_line(**overrides: str) -> str:
    return "@image-env@ " + json.dumps(_image_env(**overrides), sort_keys=True)


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


def test_parse_expected_groups_pins_by_name_and_keeps_markers(gate):
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
    pins = gate.parse_expected(text)
    assert set(pins) == {"fastapi", "secretstorage", "pywin32", "cffi"}
    assert [p.pin for p in pins["fastapi"]] == ["fastapi==0.142.2"]
    assert pins["fastapi"][0].marker is None
    assert pins["pywin32"][0].marker == "sys_platform == 'win32'"
    assert pins["secretstorage"][0].marker == "sys_platform == 'linux'"
    assert pins["cffi"][0].marker is None


def test_parse_expected_names_are_canonicalized(gate):
    pins = gate.parse_expected("Some_Pkg==1.0\n")
    assert set(pins) == {"some-pkg"}
    assert pins["some-pkg"][0].pin == "some-pkg==1.0"


def test_parse_expected_keeps_every_forked_version(gate):
    """The lock forks one name across interpreter ranges (#93): uv export
    writes one line per fork, and overwriting by name — the old dict behavior
    — is what sent a Python 3.13 image's correct beartype==0.22.9 up against
    the 3.15-only 0.23.1 pin."""
    pins = gate.parse_expected(BEARTYPE_FORK)
    assert [p.pin for p in pins["beartype"]] == [
        "beartype==0.22.9",
        "beartype==0.23.1",
    ]
    assert pins["beartype"][0].marker == "python_full_version < '3.15'"
    assert pins["beartype"][1].marker == "python_full_version >= '3.15'"


@pytest.mark.parametrize("text", ["", "# only comments\n", "\n\n"])
def test_parse_expected_empty_export_is_a_red_exit(gate, text):
    with pytest.raises(SystemExit, match="requirements-txt"):
        gate.parse_expected(text)


# ---------------------------------------------------------- parse_actual()


def test_parse_actual_ignores_docker_and_uv_noise(gate):
    dump = "\n".join(
        [
            "",
            "@image-env@ {}",  # the interpreter's marker environment line
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


# ------------------------------------------------------ parse_image_env()


def test_parse_image_env_reads_the_json_env_line(gate):
    dump = "@image-env@ " + json.dumps({"python_full_version": "3.13.16"}) + "\nfoo==1.0\n"
    assert gate.parse_image_env(dump) == {"python_full_version": "3.13.16"}


@pytest.mark.parametrize(
    "dump", ["foo==1.0\n", "@image-env@ not json\nfoo==1.0\n", "@image-env@ [1, 2]\nfoo==1.0\n"]
)
def test_parse_image_env_missing_or_unparseable_is_none(gate, dump):
    # None is the lenient signal: forks degrade instead of inventing a
    # requirement from an environment the gate cannot see.
    assert gate.parse_image_env(dump) is None


def test_dump_snippet_and_env_parser_stay_in_contract(gate):
    """`_DUMP` runs inside the image and `parse_image_env` runs on its output;
    executing the real snippet here pins both halves of that protocol."""
    proc = subprocess.run([sys.executable, "-c", gate._DUMP], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    env = gate.parse_image_env(proc.stdout)
    assert env is not None
    assert env["python_full_version"].count(".") == 2
    assert env["sys_platform"] == sys.platform
    assert gate.parse_actual(proc.stdout)  # the same dump still yields pins


# --------------------------------------------------- evaluate_marker()


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        # the beartype fork, evaluated the way uv evaluated it at build time
        ("python_full_version < '3.15'", True),
        ("python_full_version >= '3.15'", False),
        # the uvloop chain from the same exports
        (
            "platform_python_implementation != 'PyPy' and sys_platform != 'cygwin' "
            "and sys_platform != 'win32'",
            True,
        ),
        ("sys_platform == 'win32'", False),
        ("sys_platform == 'linux'", True),
        ("sys_platform != 'emscripten'", True),
        ("os_name == 'posix'", True),
        ("python_version >= '3.9'", True),
        # version (numeric), not lexicographic: 3.13.16 is NOT below 3.9.10,
        # and 3.13.16 >= 3.10 even though the string '3.13.16' sorts first
        ("python_full_version < '3.9.10'", False),
        ("python_full_version >= '3.10'", True),
        # parentheses, and or/and precedence (and binds tighter)
        (
            "(sys_platform == 'linux' or sys_platform == 'win32') and python_version >= '3.9'",
            True,
        ),
        (
            "sys_platform == 'win32' or sys_platform == 'linux' and os_name == 'posix'",
            True,
        ),
        (
            "sys_platform == 'linux' and os_name != 'posix' or sys_platform == 'win32'",
            False,
        ),
        # in / not in are substring tests per PEP 508
        ("'inux' in sys_platform", True),
        ("'win' not in sys_platform", True),
        # the arbitrary-precision === operator is string equality
        ("sys_platform === 'linux'", True),
    ],
)
def test_evaluate_marker_against_a_3_13_16_linux_image(gate, marker, expected):
    assert gate.evaluate_marker(marker, _image_env()) is expected


@pytest.mark.parametrize(
    "marker",
    [
        "python_version ~= '3.9'",  # compatible-release: not implemented
        "extras == 'x'",  # exports never carry extras; not a captured var
        "python_version <",  # truncated marker
        "(sys_platform == 'linux'",  # unbalanced
        "sys_platform == 'linux' garbage",  # trailing junk
        "agentummy == '1'",  # unknown variable
    ],
)
def test_evaluate_marker_raises_unsupported_rather_than_guessing(gate, marker):
    with pytest.raises(gate.UnsupportedMarker):
        gate.evaluate_marker(marker, _image_env())


def test_evaluate_marker_missing_env_value_is_empty_string(gate):
    # A variable the image dump could not capture evaluates against '' —
    # comparisons fail honestly instead of inheriting some default truth.
    assert gate.evaluate_marker("sys_platform == 'linux'", {}) is False


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


# --------------------------------------- forked pins through main() (#93)


def test_forked_pin_matching_the_image_interpreter_reconciles(gate, tmp_path, monkeypatch, capsys):
    """The hosted red this repairs: run 40101751150 failed
    `version mismatch : beartype==0.22.9 (image) != beartype==0.23.1` because
    the expected-side dict kept one pin per name and the last fork (the
    3.15-only one) won. A Python 3.13.16 image shipping the < '3.15' fork is
    exactly what the lock prescribes for that interpreter."""
    expected = _write_expected(tmp_path, BEARTYPE_FORK)
    dump = "\n".join(
        [_env_line(python_full_version="3.13.16", python_version="3.13"), "beartype==0.22.9"]
    )
    _install_docker(monkeypatch, gate, _Docker(dump))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "ships exactly the locked set" in out
    assert "forks evaluated against the image interpreter's environment: yes" in out


def test_forked_pin_wrong_version_for_the_interpreter_still_fails(
    gate, tmp_path, monkeypatch, capsys
):
    """The fix must not loosen the gate: a 3.13 image shipping the 3.15-only
    fork is a real skew and is named with the applicable fork's marker."""
    expected = _write_expected(tmp_path, BEARTYPE_FORK)
    dump = "\n".join(
        [_env_line(python_full_version="3.13.16", python_version="3.13"), "beartype==0.23.1"]
    )
    _install_docker(monkeypatch, gate, _Docker(dump))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "does NOT reconcile" in out
    assert (
        "version mismatch     : beartype==0.23.1 (image) != "
        "beartype==0.22.9 (marker: python_full_version < '3.15')" in out
    )


def test_forked_pin_without_image_env_degrades_leniently(gate, tmp_path, monkeypatch, capsys):
    """No @image-env@ line (an older dump, an exotic interpreter): either
    locked fork version satisfies the gate — the pre-fork lenient rule — and
    the OK line says so."""
    expected = _write_expected(tmp_path, BEARTYPE_FORK)
    _install_docker(monkeypatch, gate, _Docker(_dump("beartype==0.22.9")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0
    assert "no @image-env@ line — lenient" in capsys.readouterr().out


def test_forked_pin_absent_from_image_is_missing_when_a_fork_applies(
    gate, tmp_path, monkeypatch, capsys
):
    dump = "\n".join(
        [_env_line(python_full_version="3.13.16", python_version="3.13"), "fastapi==0.142.2"]
    )
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n" + BEARTYPE_FORK)
    _install_docker(monkeypatch, gate, _Docker(dump))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "locked, not in image : beartype==0.22.9 (marker: python_full_version < '3.15')" in out


def test_forked_pin_absent_without_image_env_gates_nothing(gate, tmp_path, monkeypatch, capsys):
    expected = _write_expected(tmp_path, "fastapi==0.142.2\n" + BEARTYPE_FORK)
    _install_docker(monkeypatch, gate, _Docker(_dump("fastapi==0.142.2")))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 0


def test_extra_image_package_is_still_extra_when_a_fork_is_expected(
    gate, tmp_path, monkeypatch, capsys
):
    """A fork's other version must not be mistaken for an extra when the
    image ships one fork, and an unknown package must still be named."""
    expected = _write_expected(tmp_path, BEARTYPE_FORK)
    dump = "\n".join(
        [
            _env_line(python_full_version="3.13.16", python_version="3.13"),
            "beartype==0.22.9",
            "shadowpkg==1.0.0",
        ]
    )
    _install_docker(monkeypatch, gate, _Docker(dump))
    monkeypatch.setattr(sys, "argv", _argv(expected))
    assert gate.main() == 1
    out = capsys.readouterr().out
    assert "in image, not locked : shadowpkg==1.0.0" in out
    assert "beartype" not in out.split("in image, not locked")[1]


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
