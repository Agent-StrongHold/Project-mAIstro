"""Isolation test for ContainerBuilderSandbox (ADR-093).

Docker-gated: skipped unless docker is on PATH and the maistro-builders image is
present, so it runs where the isolated backend actually exists and is a no-op
elsewhere (e.g. a CI box without Docker).

#77 requires the acceptance evidence to exercise the *actual*
`ContainerBuilderSandbox` — not a fake or a selector backend — so the network
and privilege regressions below run here, against the real container this
class really creates.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from maistro_bootstrap.builders.container_sandbox import (
    _AGENT_UID_GID,
    DEFAULT_IMAGE,
    ContainerBuilderSandbox,
)


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    r = subprocess.run(
        ["docker", "image", "inspect", DEFAULT_IMAGE], capture_output=True, text=True
    )
    return r.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ready(), reason=f"docker or {DEFAULT_IMAGE} image unavailable"
)


def test_agent_edits_are_isolated_from_host(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True)
    host_before = (tmp_path / "hello.py").read_text(encoding="utf-8")

    with ContainerBuilderSandbox(tmp_path) as sb:
        assert sb.read_file("hello.py") == host_before
        sb.edit_file("hello.py", "original", "EDITED")
        assert "EDITED" in sb.read_file("hello.py")
        sb.write_file("pkg/new.py", "x = 1\n")
        assert sb.search("EDITED", glob="**/*.py") == ["hello.py"]
        # Isolation: the agent's edits have NOT touched the host yet.
        assert (tmp_path / "hello.py").read_text(encoding="utf-8") == host_before

        sb.sync_to_host()

    # After an explicit sync, the host reflects the container's work.
    assert "EDITED" in (tmp_path / "hello.py").read_text(encoding="utf-8")
    assert (tmp_path / "pkg" / "new.py").exists()


def test_path_escape_blocked(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "f.py"], cwd=tmp_path, check=True)
    from maistro_bootstrap.builders.errors import SandboxEscapeError

    with ContainerBuilderSandbox(tmp_path) as sb:
        with pytest.raises(SandboxEscapeError):
            sb.read_file("../escape.txt")
        with pytest.raises(SandboxEscapeError):
            sb.write_file("/etc/passwd", "bad")


# A candidate-shaped egress probe: it tries every path class #77 names — a
# public IPv4 target, a public IPv6 target, DNS resolution, the link-local
# cloud-metadata address, and RFC1918 private ranges — and reports which
# ones it could reach. Under `--network=none` every one of them must fail.
_EGRESS_PROBE = """import socket
for host, port in [
    ("1.1.1.1", 443),
    ("93.184.216.34", 80),
    ("2606:4700:4700::1111", 443),
    ("169.254.169.254", 80),
    ("10.0.0.1", 53),
    ("192.168.1.1", 80),
    ("172.17.0.1", 80),
]:
    try:
        socket.create_connection((host, port), 2).close()
        print(f"CONNECTED {host}")
    except OSError as exc:
        print(f"DENIED {host} {type(exc).__name__}")
try:
    socket.getaddrinfo("github.com", 443)
    print("DNS RESOLVED")
except OSError:
    print("DNS DENIED")
"""


def test_agent_commands_cannot_reach_any_network_by_default(tmp_path: Path) -> None:
    """The #77 regression: an agent-issued command in the supported unattended
    Builder environment must not be able to make network connections under
    default policy — external, DNS, link-local/metadata, or private."""
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True)

    with ContainerBuilderSandbox(tmp_path) as sb:
        # The policy is the container's create-time config, not a filter the
        # candidate could avoid: assert it on the live container.
        mode = subprocess.run(
            ["docker", "inspect", "-f", "{{.HostConfig.NetworkMode}}", sb._require_cid()],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert mode == "none"

        sb.write_file("probe.py", _EGRESS_PROBE)
        out = sb.run_command("python probe.py", timeout=120)

    assert "CONNECTED" not in out, f"candidate reached a network: {out}"
    assert "DNS RESOLVED" not in out, f"candidate resolved DNS: {out}"
    # Every path class was actually probed (a probe that silently tested
    # nothing would also 'pass').
    for host in ("1.1.1.1", "2606:4700:4700::1111", "169.254.169.254", "10.0.0.1"):
        assert f"DENIED {host}" in out, f"{host} was not probed: {out}"
    assert "DNS DENIED" in out


def test_agent_execs_run_as_unprivileged_user(tmp_path: Path) -> None:
    """The other half of the regression: the agent used to be container root.
    Its commands must run as the sandbox's non-root uid and fail the things
    only root can do."""
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True)

    with ContainerBuilderSandbox(tmp_path) as sb:
        rc, out = sb.run_argv_status(["id", "-u"])
        assert rc == 0 and out.strip() == _AGENT_UID_GID.split(":")[0]

        rc, _ = sb.run_argv_status(["sh", "-c", "echo pwned > /etc/maistro-pwned"])
        assert rc != 0, "agent wrote to /etc — it is running as root"
        rc, _ = sb.run_argv_status(["chown", "-R", "0:0", "/workspace"])
        assert rc != 0, "agent chowned the workspace — it retained CAP_CHOWN"


def test_seed_leaves_ambient_credentials_on_the_host(tmp_path: Path) -> None:
    """#77/#78: the seed must not carry the repo's ambient credential surface
    into the container — `.git`, dotenv files, root-level key material, and
    unrelated untracked host files — while indexed worktree files arrive. Builder
    git tools use a sanitized in-container baseline."""
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "hello.py"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / ".env").write_text("GITHUB_TOKEN=ambient-secret\n", encoding="utf-8")
    (tmp_path / ".env.production").write_text(
        "DATABASE_PASSWORD=ambient-secret\n", encoding="utf-8"
    )
    (tmp_path / ".envrc").write_text("export TOKEN=ambient-secret\n", encoding="utf-8")
    (tmp_path / "unrelated-host-secret.txt").write_text(
        "HOST_SECRET=ambient-secret\n", encoding="utf-8"
    )
    (tmp_path / "server.pem").write_text("PRIVATE KEY material\n", encoding="utf-8")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "production-token.txt").write_text("TOKEN=ambient-secret\n", encoding="utf-8")
    with (tmp_path / ".git" / "config").open("a") as cfg:
        cfg.write("\tcredential.helper = !leak-token\n")
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text(
        "#!/bin/sh\ncurl evil\n", encoding="utf-8"
    )
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "fixture.pem").write_text("test fixture not a credential\n", encoding="utf-8")
    nested_git = fixtures / "nested-repo" / ".git"
    nested_git.mkdir(parents=True)
    (nested_git / "config").write_text("credential.helper=leak\n", encoding="utf-8")

    with ContainerBuilderSandbox(tmp_path) as sb:
        # Ambient credential surface: absent inside.
        with pytest.raises(FileNotFoundError):
            sb.read_file(".env")
        with pytest.raises(FileNotFoundError):
            sb.read_file(".env.production")
        with pytest.raises(FileNotFoundError):
            sb.read_file(".envrc")
        with pytest.raises(FileNotFoundError):
            sb.read_file("unrelated-host-secret.txt")
        with pytest.raises(FileNotFoundError):
            sb.read_file("server.pem")
        with pytest.raises(FileNotFoundError):
            sb.read_file("secrets/production-token.txt")
        rc, _ = sb.run_argv_status(["test", "!", "-e", "/workspace/.git"])
        assert rc == 0, "host .git metadata was seeded"

        # Working tree: still seeded.
        assert "original" in sb.read_file("hello.py")
        # Key-shaped material is excluded at ANY depth — the denylist cannot
        # express "root only" portably across GNU tar/bsdtar, and a visible
        # test failure beats a silent credential leak.
        with pytest.raises(FileNotFoundError):
            sb.read_file("tests/fixtures/fixture.pem")
        with pytest.raises(FileNotFoundError):
            sb.read_file("tests/fixtures/nested-repo/.git/config")

        # Builder git tools use an in-container baseline, not host metadata.
        sb.edit_file("hello.py", "original", "EDITED")
        patch = sb.diff()
        assert "fatal" not in patch
        assert '+print("EDITED")' in patch


def _repo_with_file(tmp_path: Path) -> None:
    (tmp_path / "hello.py").write_text('print("original")\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True)


def test_container_environment_is_credential_default_deny(tmp_path: Path) -> None:
    """Only the sandbox's deliberate HOME reaches candidate code."""
    _repo_with_file(tmp_path)
    with ContainerBuilderSandbox(tmp_path) as sb:
        env = sb.run_command("env")

    values = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
    assert values.get("HOME") == "/tmp"
    assert not set(values).intersection(
        {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "OPENAI_API_KEY"}
    )
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        assert values.get(name, "") == "", f"Docker proxy leaked through {name}"


def test_rootfs_and_writable_scope_are_explicit(tmp_path: Path) -> None:
    """The live Docker config, not permissions in the image, sets the scope."""
    _repo_with_file(tmp_path)
    with ContainerBuilderSandbox(tmp_path) as sb:
        inspect = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.Memory}} {{.HostConfig.PidsLimit}}",
                sb._require_cid(),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert inspect == "true 2147483648 512"
        rc, _ = sb.run_argv_status(["sh", "-c", "touch /usr/escape"])
        assert rc != 0
        assert sb.run_argv_status(["touch", "/workspace/allowed"])[0] == 0
        assert sb.run_argv_status(["touch", "/tmp/scratch"])[0] == 0


def test_process_namespace_devices_and_host_socket_are_not_reachable(tmp_path: Path) -> None:
    """Exercise the Docker backend's namespace, device and socket surfaces."""
    _repo_with_file(tmp_path)
    with ContainerBuilderSandbox(tmp_path) as sb:
        rc, out = sb.run_argv_status(["sh", "-c", "ls /proc | grep -Ec '^[0-9]+$'"])
        assert rc == 0 and int(out.strip()) < 20
        assert (
            sb.run_argv_status(
                ["sh", "-c", "mkdir -p /workspace/m && mount -t tmpfs none /workspace/m"]
            )[0]
            != 0
        )
        assert sb.run_argv_status(["chroot", "/", "/bin/true"])[0] != 0
        assert sb.run_argv_status(["test", "!", "-e", "/dev/kvm"])[0] == 0
        assert sb.run_argv_status(["mknod", "/workspace/device", "b", "8", "0"])[0] != 0
        assert sb.run_argv_status(["test", "!", "-e", "/var/run/docker.sock"])[0] == 0
        assert sb.run_argv_status(["test", "!", "-e", "/run/docker.sock"])[0] == 0
        rc, caps = sb.run_argv_status(["grep", "CapEff", "/proc/self/status"])
        assert rc == 0 and caps.split()[-1].strip("0") == ""
        rc, nnp = sb.run_argv_status(["grep", "NoNewPrivs", "/proc/self/status"])
        assert rc == 0 and nnp.split()[-1] == "1"


def test_timeout_kills_the_command_and_context_cleanup_removes_container(tmp_path: Path) -> None:
    """A timed-out candidate does not survive its exec or its sandbox."""
    _repo_with_file(tmp_path)
    cid: str
    with ContainerBuilderSandbox(tmp_path) as sb:
        cid = sb._require_cid()
        rc, _ = sb.run_argv_status(
            ["sh", "-c", "echo $$ > /workspace/pid; exec sleep 30"], timeout=1
        )
        assert rc != 0
        pid = sb.read_file("pid").strip()
        assert sb.run_argv_status(["kill", "-0", pid])[0] != 0
    assert subprocess.run(["docker", "inspect", cid], capture_output=True).returncode != 0


def test_memory_exhaustion_is_contained_by_the_container_limit(tmp_path: Path) -> None:
    """An allocation above the configured cgroup budget fails in the container."""
    _repo_with_file(tmp_path)
    with ContainerBuilderSandbox(tmp_path) as sb:
        rc, _ = sb.run_argv_status(
            [
                "python",
                "-c",
                "b=bytearray(3 * 1024 * 1024 * 1024); "
                "[b.__setitem__(i, 1) for i in range(0, len(b), 4096)]",
            ],
            timeout=30,
        )
        assert rc != 0
