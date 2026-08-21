"""Path-escape hardening for the builders shell guard.

The agent's ``run_command`` tool must not be able to read files outside its
worktree — in particular the RSI scoring evidence the reviewer keeps at
``/run/reports/`` (RLPHD state, flagged patches). A bare absolute token
(``cat /run/reports/x``) was already blocked, but three literal-path forms
slipped through token inspection and are closed here:

* flag-glued long form   — ``--file=/etc/passwd``
* flag-glued short form   — ``grep -f/run/reports/x``, clustered ``grep -RFf/abs``
* interpreter string arg  — ``python -c "open('/run/reports/x').read()"``
* bare root literal       — ``os.chdir('/')`` then relative reads
* ``file://`` local path  — ``curl file:///run/reports/x``

...while still allowing approved network URLs (``curl https://host/p``, whose
scheme ``//`` is not a filesystem escape) and relative long-flag values
(``--ignore=packages/foo``).

Token inspection fundamentally cannot see a path an interpreter *constructs*
at runtime (``open('/ru'+'n/reports/x')``); the real guarantee for the report
dir is the OS filesystem boundary (non-root agent user + a 0700 report dir),
added in the container-hardening pass. These tests lock in the literal-path
defense-in-depth layer, which stops the realistic cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro_bootstrap.builders.errors import SandboxEscapeError
from maistro_bootstrap.builders.sandbox import SandboxedShell


@pytest.fixture()
def shell(tmp_path: Path) -> SandboxedShell:
    return SandboxedShell(tmp_path)


# --- blocked: every literal absolute-path exfil form ------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "cat /run/reports/rlphd_state.json",  # bare absolute (already blocked)
        "cat /etc/passwd",
        "cat ../../../etc/passwd",  # dotdot traversal
        "cat --file=/etc/passwd",  # flag-glued, long form
        "cat --output=/run/reports/x.json",
        "grep -f/run/reports/x .",  # flag-glued, short form
        "grep -RFf/run/reports/x .",  # clustered short flags (-R -F -f/abs)
        "python -c print(open('/run/reports/rlphd_state.json').read())",  # interpreter string
        "python -c open('/etc/passwd')",
        "python3 -c __import__('os').chdir('/')",  # bare root literal, then relative reads
        "curl file:///run/reports/x",  # file:// URL to a local path
    ],
)
def test_absolute_path_exfil_is_blocked(shell: SandboxedShell, cmd: str) -> None:
    with pytest.raises(SandboxEscapeError):
        shell.run(cmd)


def test_embedded_proc_environ_is_blocked(shell: SandboxedShell) -> None:
    with pytest.raises(SandboxEscapeError):
        shell.run("python -c open('/proc/1/environ')")


# --- allowed: legitimate in-workspace usage must still run ------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "python -m pytest tests/",
        "grep pat src/f.py",
        "pytest -x --maxfail=1 tests/unit",
        "cat report.json",
        "git diff",
        "ls src/maistro",
        # Scoped test/coverage runs — relative paths in long-flag values must
        # NOT be mistaken for absolute-path escapes.
        "pytest --ignore=packages/maistro-evolve/tests/benchmarks",
        "coverage run --source=packages/app -m pytest",
        # Approved network URLs are not filesystem escapes (the scheme "//" must
        # not read as an absolute path).
        "curl http://localhost:8080/health",
        "pip install --index-url https://pypi.org/simple somepkg",
    ],
)
def test_legitimate_relative_commands_are_allowed(
    shell: SandboxedShell, cmd: str, tmp_path: Path
) -> None:
    # Exercise the guard directly; the command need not succeed at the OS level,
    # only pass the path check without raising SandboxEscapeError.
    import shlex

    shell._check_paths(shlex.split(cmd))  # must not raise


def test_absolute_path_inside_workspace_is_allowed(shell: SandboxedShell, tmp_path: Path) -> None:
    # An absolute path that genuinely resolves *inside* the root is fine.
    inside = str(tmp_path / "src" / "f.py")
    shell._check_paths(["cat", inside])  # must not raise


def test_single_dash_flag_glued_to_relative_subpath_is_conservatively_blocked(
    shell: SandboxedShell,
) -> None:
    # ``-Isrc/foo`` (short flag glued to a relative subpath) is structurally
    # identical to the ``-f/abs`` exfil form (``-<letters>/<rest>``) and can't
    # be told apart by token shape, so it's blocked; the space-separated form
    # ``-I src/foo`` stays allowed. (Long options ``--x=rel/path`` are exempt.)
    import shlex

    with pytest.raises(SandboxEscapeError):
        shell._check_paths(shlex.split("gcc -Isrc/include main.c"))
    shell._check_paths(shlex.split("gcc -I src/include main.c"))  # separated form: allowed
