"""Retained-output bound for `ContainerBuilderSandbox._exec` (#1197).

`_exec` is the seam where candidate-influenced command output arrives on the
host, and it is otherwise exercised only against a live Docker daemon (which
this host may not have). What the #1197 contract decides about it does not
need a container: `run_bounded` must retain at most the output limit per
stream, declare truncation, and keep the child's exit status — so a fake
`docker` executable stands in for the daemon, the same
not-stubbed-for-convenience principle as `test_container_sandbox_argv_status`
(the subprocess boundary, not the container, is the subject).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from maistro.sandbox.protocol import DEFAULT_MAX_OUTPUT_BYTES
from maistro_bootstrap.builders.container_sandbox import ContainerBuilderSandbox

_FAKE_DOCKER = """#!/bin/sh
# Emit far beyond the output bound on both streams simultaneously, then exit 3.
python3 -c "import sys; sys.stdout.write('o' * 3000000); sys.stderr.write('e' * 3000000)"
exit 3
"""


def _sandbox_with_fake_docker(tmp_path: Path, monkeypatch) -> ContainerBuilderSandbox:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(_FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    sandbox = ContainerBuilderSandbox(tmp_path)
    sandbox._cid = "fakecid"  # bypass __enter__: no daemon is involved here
    return sandbox


def test_exec_output_is_bounded_and_truncation_declared(tmp_path: Path, monkeypatch) -> None:
    sandbox = _sandbox_with_fake_docker(tmp_path, monkeypatch)
    code, out = sandbox._exec(["echo", "huge"])

    assert code == 3  # the child's real exit status survives the drain
    retained = DEFAULT_MAX_OUTPUT_BYTES
    assert out[:retained] == "o" * retained
    assert out.endswith("[maistro: output truncated at 1048576 bytes; the rest was discarded]")
    # The stderr stream was bounded independently: its bytes cannot hide past
    # the stdout cut plus the notice.
    assert "truncated" in out


def test_exec_under_the_limit_is_verbatim(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text("#!/bin/sh\necho modest\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    sandbox = ContainerBuilderSandbox(tmp_path)
    sandbox._cid = "fakecid"

    code, out = sandbox._exec(["echo", "modest"])
    assert (code, out) == (0, "modest\n")


# -- read_file: bounded but ERRORING, never truncating (#1197 review) -------


def _sandbox_whose_cat_emits(tmp_path: Path, monkeypatch, body: str):
    bin_dir = tmp_path / "bin-cat"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    escaped = body.replace("'", "'\\''")
    fake.write_text(f"#!/bin/sh\nprintf '%s' '{escaped}'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    sandbox = ContainerBuilderSandbox(tmp_path)
    sandbox._cid = "fakecid"
    return sandbox


def test_read_file_under_the_limit_is_verbatim(tmp_path: Path, monkeypatch) -> None:
    sandbox = _sandbox_whose_cat_emits(tmp_path, monkeypatch, "modest file body")
    assert sandbox.read_file("note.txt") == "modest file body"


def test_read_file_over_limit_errors_without_truncation_notice(
    tmp_path: Path, monkeypatch
) -> None:
    """An over-limit file must raise, not return "prefix + notice" as content."""
    sandbox = _sandbox_whose_cat_emits(tmp_path, monkeypatch, "o" * 3000000)

    with pytest.raises(ValueError, match="exceeds the sandbox read bound"):
        sandbox.read_file("big.txt")


def test_edit_file_refuses_oversized_file_before_any_write(
    tmp_path: Path, monkeypatch
) -> None:
    """The P1 scenario: a match inside the retained prefix must not let
    edit_file write the truncated text back and destroy the file's tail."""
    body = "original " + "x" * 3000000
    sandbox = _sandbox_whose_cat_emits(tmp_path, monkeypatch, body)

    with pytest.raises(ValueError, match="exceeds the sandbox read bound"):
        sandbox.edit_file("big.txt", "original", "EDITED")
