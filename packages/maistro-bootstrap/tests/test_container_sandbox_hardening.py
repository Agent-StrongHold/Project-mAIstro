"""#77: the container the builder agent runs in is default-deny hardened.

These are argv-shape tests — they run everywhere, no Docker needed — and lock
the *create-time configuration* of the sandbox container:

- `--network=none` at `docker run` (and never re-configured afterwards —
  policy lives in the container's create config, so it survives restarts and
  cannot be widened by anything that happens later, including candidate code);
- every exec that can run candidate-influenced code carries the unprivileged
  `-u`/HOME prefix, and the only root exec is the one-shot pre-seed `chown`;
- the repo seed is built host-side through the `_SEED_EXCLUDES` denylist, not
  a blind `docker cp` of the whole tree.

The behavioral proof that an agent command actually cannot connect out under
this policy lives in `test_container_sandbox.py` (Docker-gated, the real
backend — see that file for why the fake here is not sufficient evidence).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import maistro_bootstrap.builders.container_sandbox as csbx_mod
from maistro_bootstrap.builders.container_sandbox import (
    _AGENT_UID_GID,
    _SEED_EXCLUDES,
    ContainerBuilderSandbox,
)


class _Recording:
    """A `subprocess.run` stand-in that records argv and never touches Docker."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env"))
        stdout: Any = ""
        if argv[:2] == ["docker", "run"]:
            stdout = "fake-cid\n"  # text mode
        elif argv[0] == "tar" and "-cf" in argv:
            stdout = b"SEED-ARCHIVE"  # binary pipe (no text=True)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recording:
    rec = _Recording()
    monkeypatch.setattr(csbx_mod.subprocess, "run", rec)
    return rec


def _docker_calls(rec: _Recording) -> list[list[str]]:
    return [argv for argv in rec.calls if argv[0] == "docker"]


def _run_call(rec: _Recording) -> list[str]:
    runs = [argv for argv in _docker_calls(rec) if argv[1] == "run"]
    assert len(runs) == 1, "entering the sandbox must create exactly one container"
    return runs[0]


def test_container_is_created_default_deny_offline(recorder: _Recording, tmp_path: Path) -> None:
    """The regression #77 reopened: no `--network` flag meant Docker's default
    bridge, i.e. full egress for an unattended candidate. Creation must now
    pass `--network=none`, and nothing afterwards may touch networking."""
    with ContainerBuilderSandbox(tmp_path) as sb:
        sb.read_file("x.py")

    run = _run_call(recorder)
    assert "--network=none" in run
    # Exactly one network flag, and no post-create call reconfigures networking
    # (an `exec` cannot anyway — this asserts we never try something like
    # re-creating the container differently).
    assert [flag for flag in run if flag.startswith("--network")] == ["--network=none"]
    for argv in _docker_calls(recorder):
        assert not any(flag.startswith("--network") and flag != "--network=none" for flag in argv)


def test_container_creation_pins_the_unprivileged_user(
    recorder: _Recording, tmp_path: Path
) -> None:
    """The other half of the regression: the agent used to run as container
    root. PID 1 and the default exec user must be the unprivileged uid, with
    the usual capability/privilege floor underneath it."""
    with ContainerBuilderSandbox(tmp_path) as sb:
        sb.read_file("x.py")

    run = _run_call(recorder)
    assert "--user" in run
    assert run[run.index("--user") + 1] == _AGENT_UID_GID
    assert "0" not in _AGENT_UID_GID.split(":")
    assert "--cap-drop=ALL" in run
    assert "--security-opt=no-new-privileges" in run
    assert "--memory=2g" in run
    assert "--pids-limit=512" in run


def test_the_only_root_exec_is_the_pre_seed_chown(recorder: _Recording, tmp_path: Path) -> None:
    """Exactly one exec may run as root: the `chown` of the empty workspace,
    which must happen *before* the seed extract (no repo content, no candidate
    code exists yet). Everything else — including everything the agent can
    reach — is the unprivileged uid."""
    with ContainerBuilderSandbox(tmp_path) as sb:
        sb.read_file("x.py")
        sb.write_file("y.py", "y = 1\n")
        sb.run_command("ls")
        sb.run_argv(["git", "status"])
        sb.search("y = 1")
        sb.diff()

    execs = [argv for argv in _docker_calls(recorder) if argv[1] == "exec"]
    root_execs = [argv for argv in execs if "-u" in argv and argv[argv.index("-u") + 1] == "0:0"]
    assert len(root_execs) == 1, f"expected exactly the bootstrap chown, got {root_execs}"
    chown = root_execs[0]
    assert "chown" in chown
    seed_extract = next(argv for argv in recorder.calls if argv[0] == "tar" or "tar" in argv[1:3])
    assert recorder.calls.index(chown) < recorder.calls.index(seed_extract)
    for argv in execs:
        if argv is chown:
            continue
        assert "-u" in argv, f"agent-reachable exec without explicit uid: {argv}"
        assert argv[argv.index("-u") + 1] == _AGENT_UID_GID
        assert "-e" in argv and "HOME=" in argv[argv.index("-e") + 1]


def test_seed_is_a_host_side_tar_with_the_full_denylist(
    recorder: _Recording, tmp_path: Path
) -> None:
    """#77/#78: the sandbox used to seed with a full `docker cp` of the repo —
    `.git/config` credential helpers, hooks, `.env` files and all. The archive
    must be built host-side (the trust boundary) carrying every exclude
    pattern, and extracted as the agent uid."""
    with ContainerBuilderSandbox(tmp_path):
        pass

    tar_creates = [argv for argv in recorder.calls if argv[0] == "tar" and "-cf" in argv]
    assert len(tar_creates) == 1
    create = tar_creates[0]
    for pattern in _SEED_EXCLUDES:
        assert f"--exclude={pattern}" in create, f"denylist pattern missing from seed: {pattern}"
    # Host-side: rooted at the repo, not at / or the container.
    assert create[create.index("-C") + 1] == str(tmp_path)
    # macOS bsdtar must not smugggle ._* AppleDouble files into the seed.
    create_env = recorder.envs[recorder.calls.index(create)]
    assert create_env is not None and create_env.get("COPYFILE_DISABLE") == "1"

    extracts = [
        argv
        for argv in _docker_calls(recorder)
        if argv[1] == "exec" and "tar" in argv and "-xf" in argv
    ]
    assert len(extracts) == 1
    extract = extracts[0]
    assert extract[extract.index("-u") + 1] == _AGENT_UID_GID
    assert "--no-same-owner" in extract


def test_denylist_covers_the_ambient_credential_surfaces() -> None:
    """The denylist itself is policy — lock its load-bearing entries so a
    refactor cannot silently drop one (pattern semantics verified against both
    GNU tar 1.35 and bsdtar 3.5.3: `./`-prefixed = repo root, bare = any
    depth)."""
    for pattern in (
        "./.git/config",  # credential helpers, fsmonitor/pager, remote URLs w/ tokens
        "./.git/hooks",  # host-authored scripts that would execute inside
        ".env",  # dotenv secrets, any depth
        ".env.local",
        ".env.*.local",
        ".ssh",
        ".aws",
        ".npmrc",
        ".netrc",
        "id_rsa",
        "id_ed25519",
        "*.pem",
        "*.key",
    ):
        assert pattern in _SEED_EXCLUDES
