"""Security tests for git MCP workspace boundaries."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from maistro.tools.git.server import git_clone, git_status


@pytest.mark.parametrize("workspace", ["/etc", "/root/.ssh", "/tmp/maistro-workspace-evil/repo"])
async def test_git_status_rejects_disallowed_workspace_before_git(
    monkeypatch: pytest.MonkeyPatch, workspace: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git subprocess should not be created for blocked workspaces")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_status(workspace)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


async def test_git_status_allows_workspace_under_allowed_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = Path("/tmp/maistro-workspace/git-server-test")
    workspace.mkdir(parents=True, exist_ok=True)

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"", None

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        assert args[:3] == ("git", "-C", str(workspace.resolve()))
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_status(str(workspace))

    assert result["success"] is True


@pytest.mark.parametrize("dest", ["/etc/repo", "/tmp/maistro-workspace-evil/repo"])
async def test_git_clone_rejects_disallowed_dest_before_git(
    monkeypatch: pytest.MonkeyPatch, dest: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should not be created for blocked destinations")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("https://github.com/repo.git", dest)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


# --- Unauthenticated git:// transport is rejected (#404) ---------------------
#
# `git://` provides neither transport encryption nor server authentication, so
# an on-path attacker can substitute repository content that the RSI cycle
# then branches, patches, builds, and tests. The gate is an allowlist
# (`https://`, `ssh://`); these tests pin that the unauthenticated protocol is
# rejected *by name* — its own error code, not a generic scheme verdict — and
# that no git subprocess is ever spawned for it.


@pytest.mark.parametrize(
    "url",
    [
        "git://example.com/repo.git",
        "git://127.0.0.1:9418/repo",
        "git://github.com/python/cpython",
    ],
)
async def test_git_clone_rejects_git_protocol_before_git(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should never spawn for the git:// protocol")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-protocol-test")

    assert result["success"] is False
    assert result["error_code"] == "blocked_unauthenticated_transport"
    assert "git://" in result["stdout"]


@pytest.mark.parametrize("url", ["GIT://example.com/repo.git", "Git://example.com/repo"])
async def test_git_clone_rejects_git_protocol_case_insensitively(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """git parses remote schemes case-insensitively (RFC 3986), so a cased
    variant names the same unauthenticated transport and must not sneak past a
    case-sensitive comparison into the generic allowlist verdict."""

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("cased git:// must never reach a git subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-protocol-test")

    assert result["success"] is False
    assert result["error_code"] == "blocked_unauthenticated_transport"


@pytest.mark.parametrize(
    "url", ["https://github.com/example/repo.git", "ssh://git@gitlab.com/example/repo"]
)
async def test_git_clone_allows_authenticated_transports(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """The policy targets the unauthenticated protocol and unknown hosts:
    authenticated transports to allowlisted hosts still pass the gate and
    reach git."""

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"Cloned", None

    seen: dict[str, object] = {}

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        seen["argv"] = args
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/git-transport-test")

    assert result["success"] is True
    assert seen["argv"][0] == "git"
    # Executable #404 enforcement rides in the argv as `-c` pins: git itself
    # refuses the git:// transport (protocol.git.allow=never) and refuses to
    # follow redirects (http.followRedirects=false), whatever a URL, a
    # redirect response, or a .gitmodules entry asks for. These assertions
    # turn the comment-level argument into a pinned contract.
    argv = list(seen["argv"])
    assert argv[1:5] == [
        "-c",
        "protocol.git.allow=never",
        "-c",
        "http.followRedirects=false",
    ]
    assert argv[5] == "clone"
    assert "submodule" not in argv[5:]
    # The URL is passed after `--`, so no scheme can be reinterpreted as a
    # git flag on the way into the subprocess.
    assert argv[-3] == "--"
    assert argv[-2] == url
    assert argv[-1] == "/tmp/maistro-workspace/git-transport-test"


# --- Explicit host/repository source policy (#404 AC2) -----------------------
#
# The scheme gate alone accepts every https host on earth; AC2 requires the
# source itself to be explicit. https/ssh URLs must name a host on the module
# allowlist (env-overridable per deployment); the repository half of the
# source identity is the commit-digest pin tested further below.


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/repo.git",
        "https://github.com.evil.com/repo.git",
        "https://github.com@evil.com/repo.git",  # userinfo ≠ host: evil.com wins
    ],
)
async def test_git_clone_rejects_hosts_off_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should never spawn for a non-allowlisted host")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/host-policy-test")

    assert result["success"] is False
    assert result["error_code"] == "blocked_clone_host"
    assert "MAISTRO_GIT_CLONE_ALLOWED_HOSTS" in result["suggested_action"]


@pytest.mark.parametrize(
    "url",
    [
        "https://GITHUB.COM/example/repo.git",  # hosts compare case-insensitively
        "https://git@github.com/example/repo.git",  # user-info does not change the host
        "https://github.com:8443/example/repo.git",  # a port is not a different host
    ],
)
async def test_git_clone_host_policy_is_not_overstrict(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"Cloned", None

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/host-policy-test")

    assert result["success"] is True, result


async def test_git_clone_host_allowlist_is_env_overridable_per_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment points the allowlist at its own forges via env, without a
    code change — the same policy, a different source list."""

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"Cloned", None

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setenv("MAISTRO_GIT_CLONE_ALLOWED_HOSTS", "example.com, internal-git.corp")

    result = await git_clone("https://example.com/repo.git", "/tmp/maistro-workspace/host-env")

    assert result["success"] is True, result


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:example/repo.git",  # scp-style: git reads it as ssh://
        "SSH://git@github.com/example/repo.git",  # uppercase scheme: refuse, don't parse
        "git+ssh://git@github.com/example/repo.git",
        "%67it://github.com/example/repo.git",  # percent-encoding is not a scheme
    ],
)
async def test_git_clone_rejects_scheme_syntax_games(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Alternative spellings that git could resolve to an authenticated or
    unauthenticated transport are refused on spelling: the gate names exact
    schemes, and fail-closed beats a permissive parser."""

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError(f"git clone should never spawn for {url!r}")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/tmp/maistro-workspace/scheme-games")

    assert result["success"] is False
    assert result["error_code"] == "blocked_url_scheme"


async def test_git_clone_percent_encoded_host_cannot_resurrect_git_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Encoding games inside the unauthenticated transport change nothing: the
    git:// verdict is a prefix match on the scheme, which percent-encoding in
    the host portion cannot alter."""

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("encoded git:// must never reach a git subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("git://%67ithub.com/example/repo.git", "/tmp/maistro-workspace/enc")

    assert result["success"] is False
    assert result["error_code"] == "blocked_unauthenticated_transport"


# --- Verified local sources (#404 AC2) ----------------------------------------


async def test_git_clone_allows_a_workspace_local_path_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC2's 'verified local sources': a bare path is accepted only when it
    passes the same workspace-root validation the destination undergoes."""

    root = tmp_path / "workspaces"
    origin = root / "origin"
    origin.mkdir(parents=True)
    monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (root,))

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"Cloned", None

    seen: dict[str, object] = {}

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        seen["argv"] = args
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_clone(str(origin), str(root / "dest"))

    assert result["success"] is True, result
    argv = list(seen["argv"])
    assert argv[-3] == "--"
    assert argv[-2] == str(origin)


async def test_git_clone_rejects_paths_outside_verified_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should never spawn for an unverified local source")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    for source in ("/etc", "-oProxyCommand=echo"):
        result = await git_clone(source, "/tmp/maistro-workspace/local-source-test")
        assert result["success"] is False
        assert result["error_code"] in {"blocked_url_scheme", "blocked_workspace"}


# --- Redirect/protocol-downgrade enforcement is executable (#404 AC4) --------
#
# The claim "redirects cannot smuggle the scheme back" used to be comment-only.
# It is now two `-c` pins in the argv (asserted above) plus functional proof:
# git itself refuses a 302 under http.followRedirects=false, and refuses the
# git:// transport under protocol.git.allow=never — including when a
# .gitmodules entry asks for it.


@pytest.fixture
def _redirecting_http_server():
    """A local HTTP server whose every response is a 302 to another http URL."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/moved.git/info/refs")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/x.git"
    server.shutdown()
    thread.join(timeout=5)


async def test_git_clone_functionally_refuses_redirects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _redirecting_http_server: str
) -> None:
    """Real git, real HTTP: the redirect is refused ('302' in git's output),
    the destination is never populated — a server response cannot move the
    fetch to a URL the host/scheme policy never vetted."""

    root = tmp_path / "workspaces"
    dest = root / "dest"
    monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (root,))
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES", ("https://", "ssh://", "http://")
    )

    result = await git_clone(_redirecting_http_server, str(dest), timeout=60)

    assert result["success"] is False
    assert result["error_code"] == "git_clone_failed"
    assert "302" in result["stdout"]
    assert not dest.exists() or not any(dest.iterdir())


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=120
    )


@pytest.fixture
def _origin_with_git_submodule(tmp_path: Path) -> Path:
    """A repo whose tree carries a gitlink + a .gitmodules URL over git://.

    A plain `git clone` of this repo fetches the parent only — the submodule
    URL is metadata, not fetched content — which is exactly why the clone gate
    can allow it and why the *fetch* must still be dead if anything ever
    tries `git submodule update`.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    assert _git("init", "-q", "-b", "main", str(origin)).returncode == 0
    (origin / ".gitmodules").write_text(
        '[submodule "evil"]\n\tpath = evil\n\turl = git://127.0.0.1:9418/evil.git\n',
        encoding="utf-8",
    )
    assert _git("-C", str(origin), "add", ".gitmodules").returncode == 0
    assert _git("-C", str(origin), "commit", "-qm", "submodule").returncode == 0
    gitlink = _git("-C", str(origin), "rev-parse", "HEAD").stdout.strip()
    # A gitlink entry without an actual submodule checkout: mode 160000.
    index = _git(
        "-C", str(origin), "update-index", "--add", "--cacheinfo", f"160000,{gitlink},evil"
    )
    assert index.returncode == 0, index.stderr
    assert _git("-C", str(origin), "commit", "-qm", "gitlink").returncode == 0
    return origin


def test_git_protocol_submodule_fetch_is_dead_under_the_policy_pin(
    tmp_path: Path, _origin_with_git_submodule: Path
) -> None:
    """AC4's submodule clause, proven against real git: with the same
    `protocol.git.allow=never` pin the clone argv carries, `git submodule
    update` refuses the git:// URL in transport selection — before any
    connection — so a .gitmodules entry cannot re-introduce the
    unauthenticated transport even if a future surface runs submodule
    updates."""
    dest = tmp_path / "clone"
    clone = _git("clone", "-q", "--", str(_origin_with_git_submodule), str(dest))
    if clone.returncode != 0:
        pytest.fail(f"fixture clone failed: {clone.stderr}")

    update = _git(
        "-C",
        str(dest),
        "-c",
        "protocol.git.allow=never",
        "submodule",
        "update",
        "--init",
        "--depth=1",
    )

    assert update.returncode != 0
    assert "transport 'git' not allowed" in (update.stderr + update.stdout)


def test_git_protocol_transport_refusal_comes_from_git_itself() -> None:
    """The pin delegates the verdict to git's own protocol layer: `ls-remote`
    over git:// dies in transport selection (no server, no connection), which
    is what makes the enforcement hold for redirects and submodules alike —
    any fetch path through git's protocol layer gets the same answer."""
    probe = _git("-c", "protocol.git.allow=never", "ls-remote", "git://127.0.0.1:9418/x")

    assert probe.returncode != 0
    assert "transport 'git' not allowed" in (probe.stderr + probe.stdout)


# --- Commit-digest pinning and TOCTOU (#404 AC3, AC5) ------------------------
#
# A pin is only a pin if it names an object: full hex digests only, fetched
# directly, and the final `rev-parse HEAD` verdict runs after all fetching —
# so a ref that moves mid-clone cannot change what the caller receives.


@pytest.mark.parametrize("pin", ["main", "HEAD", "abc123", "z" * 40, "a" * 39, "a" * 41])
async def test_git_clone_rejects_non_digest_pins_before_git(
    monkeypatch: pytest.MonkeyPatch, pin: str
) -> None:
    """A ref name or short sha can be repointed by the remote; only a full
    digest is immutable. Anything else is refused before git spawns."""

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should never spawn for a malformed pin")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(
        "https://github.com/example/repo.git", "/tmp/maistro-workspace/pin-test", commit=pin
    )

    assert result["success"] is False
    assert result["error_code"] == "blocked_commit_digest"


async def _cloned_head(dest: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(dest),
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    return stdout.decode().strip()


class TestCommitPinning:
    @pytest.fixture(autouse=True)
    def _hermetic_origins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:

        self.root = tmp_path / "workspaces"
        self.origin = tmp_path / "origins" / "origin"
        self.origin.mkdir(parents=True)
        monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (self.root,))
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "ssh://", "file://"),
        )
        assert _git("init", "-q", "-b", "main", str(self.origin)).returncode == 0
        _git("-C", str(self.origin), "config", "user.email", "t@t")
        _git("-C", str(self.origin), "config", "user.name", "t")
        (self.origin / "f.txt").write_text("one\n", encoding="utf-8")
        assert _git("-C", str(self.origin), "add", "-A").returncode == 0
        assert _git("-C", str(self.origin), "commit", "-qm", "one").returncode == 0
        (self.origin / "f.txt").write_text("two\n", encoding="utf-8")
        assert _git("-C", str(self.origin), "commit", "-qam", "two").returncode == 0
        self.first = _git("-C", str(self.origin), "rev-parse", "HEAD~1").stdout.strip()
        self.tip = _git("-C", str(self.origin), "rev-parse", "HEAD").stdout.strip()

    async def test_pin_to_non_tip_digest_fetches_and_verifies_it(self) -> None:
        dest = self.root / "dest1"
        result = await git_clone(f"file://{self.origin}", str(dest), commit=self.first)

        assert result["success"] is True, result
        assert result["pinned_commit"] == self.first
        assert await _cloned_head(dest) == self.first

    async def test_pin_to_tip_digest_verifies_without_refetch(self) -> None:
        dest = self.root / "dest2"
        result = await git_clone(f"file://{self.origin}", str(dest), commit=self.tip)

        assert result["success"] is True, result
        assert result["pinned_commit"] == self.tip
        assert await _cloned_head(dest) == self.tip

    async def test_pin_is_case_insensitive_and_normalized(self) -> None:
        dest = self.root / "dest3"
        result = await git_clone(f"file://{self.origin}", str(dest), commit=self.first.upper())

        assert result["success"] is True, result
        assert result["pinned_commit"] == self.first

    async def test_unknown_digest_fails_closed(self) -> None:
        dest = self.root / "dest4"
        result = await git_clone(
            f"file://{self.origin}",
            str(dest),
            commit="0" * 40,
        )

        assert result["success"] is False
        assert result["error_code"] == "commit_fetch_failed"
        assert "do not use the workspace" in result["suggested_action"].lower()

    async def test_pin_defeats_toctou_ref_movement(self) -> None:
        """AC5's TOCTOU case, end to end: between the caller's policy decision
        (pin digest D) and the fetch, the remote's ref moves to new content.
        An unpinned clone faithfully tracks the moved ref — the pinned one
        still delivers exactly D, because D is fetched by digest and the
        final rev-parse verdict runs after all fetching."""
        moved_dest = self.root / "moved"
        moved = await git_clone(f"file://{self.origin}", str(moved_dest))
        assert moved["success"] is True
        assert await _cloned_head(moved_dest) == self.tip

        # The "attacker" moves the ref the unpinned clone just tracked.
        (self.origin / "f.txt").write_text("attacker\n", encoding="utf-8")
        assert _git("-C", str(self.origin), "commit", "-qam", "moved").returncode == 0

        fresh_dest = self.root / "fresh"
        unpinned = await git_clone(f"file://{self.origin}", str(fresh_dest))
        assert unpinned["success"] is True
        assert await _cloned_head(fresh_dest) != self.tip  # the ref moved; so did the clone

        pinned_dest = self.root / "pinned"
        pinned = await git_clone(f"file://{self.origin}", str(pinned_dest), commit=self.first)
        assert pinned["success"] is True, pinned
        assert await _cloned_head(pinned_dest) == self.first  # the pin did not

    async def test_pinned_clone_argv_verifies_before_returning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pin verdict is a rev-parse of what actually landed in the
        checkout, run before the call reports success — and the clone itself
        carries the protocol/redirect enforcement pins."""
        calls: list[tuple[str, ...]] = []

        class _Proc:
            returncode = 0

            def __init__(self, out: bytes = b"") -> None:
                self._out = out

            async def communicate(self) -> tuple[bytes, None]:
                return self._out, None

        async def fake_exec(*args: object, **kwargs: object) -> _Proc:
            argv = tuple(str(a) for a in args)
            calls.append(argv)
            if "rev-parse" in argv:
                return _Proc(out=f"{self.first}\n".encode())
            return _Proc()

        monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

        dest = str(self.root / "pin-argv")
        result = await git_clone("https://github.com/example/repo.git", dest, commit=self.first)

        assert result["success"] is True, result
        verbs = [
            next((a for a in call[1:] if a in {"clone", "fetch", "rev-parse"}), "")
            for call in calls
        ]
        # Fast path: the pinned digest is the clone's own HEAD, so verifying
        # it needs no refetch — one clone, one rev-parse verdict.
        assert verbs == ["clone", "rev-parse"]
        clone_calls = [call for call in calls if "clone" in call]
        assert clone_calls[0][1:5] == (
            "-c",
            "protocol.git.allow=never",
            "-c",
            "http.followRedirects=false",
        )
        assert list(clone_calls[0][-3:]) == [
            "--",
            "https://github.com/example/repo.git",
            dest,
        ]
