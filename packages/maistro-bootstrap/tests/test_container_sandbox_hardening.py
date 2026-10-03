"""#77: the container the builder agent runs in is default-deny hardened.

These are argv-shape tests — they run everywhere, no Docker needed — and lock
the *create-time configuration* of the sandbox container:

- `--network=none` at `docker run` (and never re-configured afterwards —
  policy lives in the container's create config, so it survives restarts and
  cannot be widened by anything that happens later, including candidate code);
- every exec that can run candidate-influenced code carries the unprivileged
  `-u`/HOME prefix, and the only root exec is the one-shot pre-seed `chown`;
- the repo seed is built host-side from the Git-index allowlist plus
  `_SEED_EXCLUDES`, not a blind `docker cp` of the whole tree.

The behavioral proof that an agent command actually cannot connect out under
this policy lives in `test_container_sandbox.py` (Docker-gated, the real
backend — see that file for why the fake here is not sufficient evidence).
"""

from __future__ import annotations

import os
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

    def __init__(self, uid_map: str = "0 165536 65536\n") -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self.uid_map = uid_map

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env"))
        stdout: Any = ""
        if argv[:2] == ["docker", "run"]:
            stdout = "fake-cid\n"  # text mode
        elif argv[0] == "git" and "ls-files" in argv:
            stdout = b"x.py\0"  # binary NUL-delimited index listing
        elif argv[0] == "docker" and argv[-3:] == ["ps", "-eo", "pid=,ppid=,args="]:
            stdout = "7 1 sleep infinity\n"  # the --init child harness
        elif argv[0] == "docker" and argv[-1] == "/proc/self/uid_map":
            # The userns boundary probe (ADR-093 Decision 2): default is a
            # remapped container uid 0 -> subuid 165536, i.e. not host uid 0.
            stdout = self.uid_map
        elif argv[0] == "tar" and "-cf" in argv:
            stdout = b"SEED-ARCHIVE"  # binary pipe (no text=True)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recording:
    rec = _Recording()
    monkeypatch.setattr(csbx_mod.subprocess, "run", rec)
    # These tests lock Docker argv shape only; the live suite proves the
    # host-side index allowlist against the real backend.
    monkeypatch.setattr(csbx_mod.ContainerBuilderSandbox, "_tracked_seed_files", lambda _: b"")
    return rec


def test_seed_allowlist_reads_split_git_index(tmp_path: Path) -> None:
    """A linked shared index must not break the host-side seed allowlist."""
    (tmp_path / "tracked.py").write_text("tracked = True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "add",
            "tracked.py",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "update-index", "--split-index"], cwd=tmp_path, check=True)
    (tmp_path / "added.py").write_text("added = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "added.py"], cwd=tmp_path, check=True)

    # A tracked submodule is a gitlink, not permission to archive the checked
    # out directory. Keep one in the split-index fixture so the allowlist
    # cannot regress into recursively seeding its untracked contents.
    child = tmp_path / "vendor" / "child"
    child.mkdir(parents=True)
    (child / "README").write_text("child checkout\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=child, check=True)
    subprocess.run(["git", "add", "README"], cwd=child, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=child@test",
            "-c",
            "user.name=child",
            "commit",
            "-qm",
            "child",
        ],
        cwd=child,
        check=True,
    )
    child_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=child, text=True).strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo", f"160000,{child_sha},vendor/child"],
        cwd=tmp_path,
        check=True,
    )

    shared_indexes = list((tmp_path / ".git").glob("sharedindex.*"))
    assert shared_indexes, "fixture did not create a linked Git shared index"
    listed = ContainerBuilderSandbox(tmp_path)._tracked_seed_files()

    assert listed.split(b"\0") == [b"added.py", b"tracked.py", b""]


@pytest.mark.parametrize("replacement", ["directory", "symlink-parent", "fifo"])
def test_seed_allowlist_refuses_replaced_index_paths(tmp_path: Path, replacement: str) -> None:
    """Real Git index entries authorize files, not traversal or recursion."""
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "nested" / "config.txt"
    tracked.parent.mkdir()
    tracked.write_text("indexed content\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    tracked.parent.rename(repo / "original-nested")
    if replacement == "directory":
        tracked.mkdir(parents=True)
        (tracked / "unrelated-host-secret.txt").write_text("sentinel")
    elif replacement == "fifo":
        tracked.parent.mkdir()
        os.mkfifo(tracked)
    else:
        private = tmp_path / "host-private"
        private.mkdir()
        (private / "config.txt").write_text("sentinel")
        tracked.parent.symlink_to(private, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unsafe seed path"):
        ContainerBuilderSandbox(repo)._tracked_seed_files()


@pytest.mark.parametrize("replacement", ["missing-file", "missing-parent", "leaf-symlink"])
def test_seed_allowlist_preserves_safe_worktree_changes(tmp_path: Path, replacement: str) -> None:
    tracked = tmp_path / "nested" / "config.txt"
    tracked.parent.mkdir()
    tracked.write_text("indexed content\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    tracked.unlink()
    if replacement == "missing-parent":
        tracked.parent.rmdir()
    elif replacement == "leaf-symlink":
        # A dangling leaf is copied as a link, never read through on the host.
        tracked.symlink_to("missing-target")

    listed = ContainerBuilderSandbox(tmp_path)._tracked_seed_files()
    assert listed == (b"nested/config.txt\0" if replacement == "leaf-symlink" else b"")


def test_missing_or_replaced_harness_refuses_the_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only the startup `sleep infinity` child may survive agent reaping."""
    monkeypatch.setattr(
        csbx_mod,
        "_docker",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout="123 1 unexpected command\n", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="harness process is missing"):
        ContainerBuilderSandbox(tmp_path)._find_harness_pid("cid")


def test_gitdir_marker_seed_path_is_validated_and_resolved(tmp_path: Path) -> None:
    """Linked worktrees may seed, while malformed Git markers fail closed."""
    marker = tmp_path / ".git"
    marker.write_text("not-a-gitdir\n", encoding="utf-8")
    sandbox = ContainerBuilderSandbox(tmp_path)
    with pytest.raises(RuntimeError, match="not a valid worktree gitdir marker"):
        sandbox._git_index_path()

    gitdir = tmp_path / "linked-gitdir"
    gitdir.mkdir()
    index = gitdir / "index"
    index.touch()
    marker.write_text("gitdir: linked-gitdir\n", encoding="utf-8")

    assert sandbox._git_index_path() == index


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
    assert "--memory-swap=2g" in run
    assert "--pids-limit=512" in run
    assert "--read-only" in run
    assert "--init" in run
    assert "--tmpfs" in run


def test_container_creation_pins_implicit_runtime_tmpfs_read_only(
    recorder: _Recording, tmp_path: Path
) -> None:
    """#80: `--read-only` does not cover the runtime's implicit mounts — Docker
    ordinarily mounts a writable tmpfs at /dev/shm and an mqueue filesystem at
    /dev/mqueue regardless, and a live probe could write both. Creation must
    pin each as a read-only, non-executable stub, and every tmpfs outside the
    workspace/scratch pair must be created read-only."""
    with ContainerBuilderSandbox(tmp_path):
        pass

    run = _run_call(recorder)
    specs = [run[i + 1] for i, flag in enumerate(run) if flag == "--tmpfs"]
    pinned: set[str] = set()
    for spec in specs:
        target, _, opts = spec.partition(":")
        flags = set(opts.split(","))
        if target in ("/workspace", "/tmp"):
            assert "rw" in flags, f"scratch mount lost writability: {spec}"
            continue
        assert "ro" in flags and "rw" not in flags, f"writable non-scratch tmpfs: {spec}"
        assert "noexec" in flags and "nosuid" in flags and "nodev" in flags, spec
        pinned.add(target)
    assert {"/dev/shm", "/dev/mqueue"} <= pinned, (
        f"implicit runtime tmpfs not pinned read-only: {sorted(pinned)}"
    )


def test_entry_probes_the_container_user_namespace_before_any_root_work(
    recorder: _Recording, tmp_path: Path
) -> None:
    """ADR-093 Decision 2 (#80 reopened): entry must verify, not assume, that
    the container's uids are not host uids. The probe is a `cat
    /proc/self/uid_map` exec — as the unprivileged agent uid — issued before
    the harness-pid lookup, before the bootstrap chown, and before the seed."""
    with ContainerBuilderSandbox(tmp_path):
        pass

    docker_calls = _docker_calls(recorder)
    probe = next(argv for argv in docker_calls if argv[-1] == "/proc/self/uid_map")
    assert probe[1] == "exec"
    assert probe[probe.index("-u") + 1] == _AGENT_UID_GID
    assert "chown" not in probe
    # Everything the boundary admits must already have happened: the container
    # create (`docker run`) precedes the probe, and the probe precedes the
    # harness lookup, the chown and the seed archive.
    run_ix = recorder.calls.index(_run_call(recorder))
    harness_ix = next(
        i for i, argv in enumerate(docker_calls) if argv[-3:] == ["ps", "-eo", "pid=,ppid=,args="]
    )
    probe_ix = docker_calls.index(probe)
    chown_ix = next(i for i, argv in enumerate(docker_calls) if "chown" in argv)
    seed_ix = next(i for i, argv in enumerate(recorder.calls) if argv[0] == "tar")
    assert run_ix < probe_ix < harness_ix < chown_ix < seed_ix


def test_identity_uid_map_refuses_the_sandbox_before_any_root_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A rootful, un-remapped daemon maps container uid 0 onto host uid 0
    (identity `/proc/self/uid_map`), so even the one auditable bootstrap
    chown would run as host root. Entry must refuse that daemon before the
    chown, before the seed, and remove the container it created."""
    rec = _Recording(uid_map="0 0 4294967295\n")
    monkeypatch.setattr(csbx_mod.subprocess, "run", rec)

    with pytest.raises(RuntimeError, match="rootless"):
        ContainerBuilderSandbox(tmp_path).__enter__()

    docker_calls = _docker_calls(rec)
    assert ["docker", "rm", "-f", "fake-cid"] in docker_calls
    # Nothing ran as container root and no repo content crossed the boundary
    # on a daemon that was about to be refused.
    assert not any("chown" in argv for argv in docker_calls)
    assert not any(argv[0] == "tar" for argv in rec.calls)


def test_an_unreadable_uid_map_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A boundary that cannot be proven is a boundary that does not exist."""
    monkeypatch.setattr(
        csbx_mod,
        "_docker",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, stdout="", stderr="cat: read error"
        ),
    )

    with pytest.raises(RuntimeError, match="rootless"):
        ContainerBuilderSandbox(Path("/unused"))._verify_userns_boundary("cid")


@pytest.mark.parametrize(
    ("uid_map", "maps_root_to_host_root"),
    [
        # Rootful daemon, no userns remap: container uid 0 *is* host uid 0.
        ("0          0          4294967295\n", True),
        # `dockerd --userns-remap=default`: container uids land on subuids.
        ("0          165536     65536\n", False),
        # Rootless daemon userns: uid 0 is the unprivileged daemon user, the
        # rest are that user's subuids — neither maps container root to host root.
        ("0          1000       1\n1          100000     65536\n", False),
        # A partially remapped map is still unsafe when its uid-0 range maps
        # to host root: the bootstrap chown executes as container uid 0.
        ("0          0          1\n1          100000     65536\n", True),
        # Multi-line full identity still means the host's own namespace.
        ("0          0          1\n1          1          65535\n", True),
        # A map which cannot prove what container root maps to fails closed.
        ("1          100000     65536\n", True),
        ("", True),
        ("garbage", True),
    ],
)
def test_uid_map_root_mapping_detection(uid_map: str, maps_root_to_host_root: bool) -> None:
    """The launch gate refuses every map that maps container root to host root,
    including a partially remapped map, and rejects an unproven uid-0 mapping."""
    assert csbx_mod._uid_map_maps_container_root_to_host_root(uid_map) is maps_root_to_host_root


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


def test_seed_is_a_host_side_tar_with_index_allowlist_and_denylist(
    recorder: _Recording, tmp_path: Path
) -> None:
    """#77/#78: the sandbox used to seed with a full `docker cp` of the repo —
    `.git` metadata, `.env` files and all. The archive must be built host-side
    from the Git-index allowlist, carry every explicit exclusion pattern, and
    be extracted as the agent uid."""
    with ContainerBuilderSandbox(tmp_path):
        pass

    tar_creates = [argv for argv in recorder.calls if argv[0] == "tar" and "-cf" in argv]
    assert len(tar_creates) == 1
    create = tar_creates[0]
    for pattern in _SEED_EXCLUDES:
        assert f"--exclude={pattern}" in create, f"denylist pattern missing from seed: {pattern}"
    # Host-side: rooted at the repo, not at / or the container, and fed only
    # by the NUL-delimited Git-index listing.
    assert create[create.index("-C") + 1] == str(tmp_path)
    assert "--null" in create
    assert "--verbatim-files-from" in create
    assert "--no-recursion" in create
    assert "--files-from=-" in create
    # macOS bsdtar must not smugggle ._* AppleDouble files into the seed.
    create_env = recorder.envs[recorder.calls.index(create)]
    assert create_env is not None and create_env.get("COPYFILE_DISABLE") == "1"

    extracts = [
        argv
        for argv in _docker_calls(recorder)
        if argv[1] == "exec" and "tar" in argv and "-xf" in argv
    ]
    assert len(extracts) == 2  # workspace plus the sanitized in-container baseline
    extract = extracts[0]
    assert extract[extract.index("-u") + 1] == _AGENT_UID_GID
    assert "--no-same-owner" in extract


def test_denylist_covers_the_ambient_credential_surfaces() -> None:
    """The denylist itself is policy — lock its load-bearing entries so a
    refactor cannot silently drop one (pattern semantics verified against both
    GNU tar 1.35 and bsdtar 3.5.3: `./`-prefixed = repo root, bare = any
    depth)."""
    for pattern in (
        "./.git",  # refs, credential helpers, and host-authored hooks
        ".git",  # nested submodule metadata, any depth
        ".env",  # dotenv secrets, any depth
        ".env.*",  # environment-specific dotenv variants
        ".envrc",
        ".ssh",
        ".aws",
        ".npmrc",
        ".netrc",
        "id_rsa",
        "id_ed25519",
        "*.pem",
        "*.key",
        "secrets",  # application-specific secret material, any depth
    ):
        assert pattern in _SEED_EXCLUDES


def _env_assignments(argv: list[str]) -> list[str]:
    """Every `-e`/`--env` value in a docker argv (create or exec)."""
    out: list[str] = []
    for i, tok in enumerate(argv):
        if tok in ("-e", "--env") and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif tok.startswith("--env="):
            out.append(tok[len("--env=") :])
        elif tok in ("--env-file",):
            out.append(f"__ENV_FILE__{argv[i + 1]}")
    return out


def test_container_env_is_home_and_nothing_else(recorder: _Recording, tmp_path: Path) -> None:
    """#78: no ambient host environment crosses into the container. Docker
    does not inherit the client's env by default, and that default is the
    security property — this pins it so a future edit cannot quietly add an
    `-e` passthrough, an `--env` spread, or an `--env-file` that hauls the
    operator's shell (credentials included) into the candidate's container.
    HOME is the one exception, pointed at /tmp — not the operator's home."""
    with ContainerBuilderSandbox(tmp_path) as sb:
        sb.read_file("x.py")
        sb.run_command("ls")

    for argv in _docker_calls(recorder):
        envs = _env_assignments(argv)
        # HOME=/tmp and blank proxy variables are the ONLY assignments on
        # create/exec. Blank values defeat Docker client's proxy-config
        # injection without exposing its credentials to the candidate.
        allowed = {
            f"HOME={csbx_mod._AGENT_HOME}",
            *[f"{name}=" for name in csbx_mod._PROXY_ENV_NAMES],
        }
        assert set(envs) <= allowed, argv
        if argv[1] == "run":
            assert envs == [
                f"HOME={csbx_mod._AGENT_HOME}",
                *[f"{name}=" for name in csbx_mod._PROXY_ENV_NAMES],
            ], argv


def test_failed_enter_removes_the_created_container(
    recorder: _Recording, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A seed failure must not leave a partially configured container alive."""

    def fail_seed(self: ContainerBuilderSandbox, cid: str) -> None:
        raise RuntimeError(f"cannot seed {cid}")

    monkeypatch.setattr(ContainerBuilderSandbox, "_seed", fail_seed)

    with pytest.raises(RuntimeError, match="cannot seed fake-cid"):
        ContainerBuilderSandbox(tmp_path).__enter__()

    assert ["docker", "rm", "-f", "fake-cid"] in recorder.calls


@pytest.mark.parametrize(
    ("archive_status", "extract_statuses", "message"),
    [
        (1, [], "seed tar failed"),
        (0, [1], "container tar extract failed"),
        (0, [0, 1], "container baseline extract failed"),
        (0, [0, 0], None),
    ],
)
def test_seed_failure_at_every_transfer_stage_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    archive_status: int,
    extract_statuses: list[int],
    message: str | None,
) -> None:
    """Host archive and both container extracts fail closed and clean up.

    The workspace extract and the clean Git baseline are distinct transfers; a
    failure in either must remove the container rather than leaving seed data
    accessible to a later caller.
    """
    sandbox = ContainerBuilderSandbox(tmp_path)
    cleanup: list[object] = []
    statuses = iter(extract_statuses)

    monkeypatch.setattr(sandbox, "_tracked_seed_files", lambda: b"tracked.py\0")
    monkeypatch.setattr(
        csbx_mod.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, archive_status, stdout=b"archive", stderr=b"tar error"
        ),
    )
    monkeypatch.setattr(
        sandbox,
        "_extract_seed",
        lambda cid, archive, destination: subprocess.CompletedProcess(
            ["docker", "exec"], next(statuses), stdout=b"", stderr=b"extract error"
        ),
    )
    monkeypatch.setattr(
        ContainerBuilderSandbox,
        "__exit__",
        lambda self, *exc: cleanup.append(exc),
    )

    if message is None:
        sandbox._seed("cid")
        assert cleanup == []
    else:
        with pytest.raises(RuntimeError, match=message):
            sandbox._seed("cid")
        assert cleanup == [(None, None, None)]
