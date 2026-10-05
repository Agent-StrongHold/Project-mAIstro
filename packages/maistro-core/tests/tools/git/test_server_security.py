"""Security tests for git MCP workspace boundaries."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from maistro.tools.git.server import (
    _CLONE_CONFIG_HARDENING,
    _TRANSPORT_PIN,
    _TRUSTED_SIGNERS_ENV,
    _git,
    _trusted_signature_fprs,
    git_clone,
    git_status,
)


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

    # github.com: on the default host allowlist, so the URL passes the
    # source policy and the test exercises the dest gate it exists for.
    result = await git_clone("https://github.com/repo.git", dest)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


# --- candidate source policy (issue #404) -------------------------------


class _ScriptedProc:
    def __init__(self, stdout: bytes, returncode: int) -> None:
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, None]:
        return self._stdout, None


class _ScriptedGit:
    """Fake create_subprocess_exec driven by a step list: the first step whose
    match fragments all appear (as exact argv elements) is popped and served.
    An argv matching no remaining step fails the test immediately — so the
    verification sequence itself is under test, not just its outcome."""

    def __init__(self, steps: list[tuple[tuple[str, ...], bytes, int]]) -> None:
        self._steps = list(steps)
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args: object, **kwargs: object) -> _ScriptedProc:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        for index, (match, stdout, code) in enumerate(self._steps):
            if all(fragment in argv for fragment in match):
                del self._steps[index]
                return _ScriptedProc(stdout, code)
        raise AssertionError(f"unexpected subprocess argv: {argv}")

    def argv_of(self, fragment: str) -> tuple[str, ...]:
        for argv in self.calls:
            if fragment in argv:
                return argv
        raise AssertionError(f"no call with {fragment!r} in {self.calls}")


_DIGEST = "b" * 40
_ATTACKER_DIGEST = "a" * 40


def _pin_steps() -> list[tuple[tuple[str, ...], bytes, int]]:
    """Post-clone transport-pin persistence: one `git config` write per
    whitelist key, into the destination repo's local config."""
    return [(("config", key), b"", 0) for key, _ in _TRANSPORT_PIN]


def _resolve_step() -> tuple[tuple[str, ...], bytes, int]:
    """Tip resolution: an un-pinned clone first resolves the vetted remote's
    HEAD via `git ls-remote` (the same transport pins ride along); the
    returned digest becomes the pin the clone is verified against."""
    return (("ls-remote",), f"{_DIGEST}\tHEAD\n".encode(), 0)


def _success_steps() -> list[tuple[tuple[str, ...], bytes, int]]:
    """Minimal happy-path script: clone succeeds, the destination config is
    pinned to the transport whitelist, and HEAD resolves to a digest. No
    .gitmodules step: the default destination does not exist, so the tool
    skips the submodule scan."""
    return [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
    ]


async def _run_scripted_clone(
    monkeypatch: pytest.MonkeyPatch,
    steps: list[tuple[tuple[str, ...], bytes, int]],
    url: str = "https://github.com/org/repo.git",
    **kwargs: object,
) -> tuple[dict[str, object], _ScriptedGit]:
    monkeypatch.delenv("MAISTRO_GIT_CLONE_HOSTS", raising=False)
    scripted = _ScriptedGit([_resolve_step(), *steps])
    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", scripted)
    result = await git_clone(url, "/repos/dest", **kwargs)  # type: ignore[arg-type]
    return result, scripted


@pytest.mark.parametrize(
    "url",
    [
        "git://example.com/repo.git",  # unauthenticated daemon transport
        "GIT://example.com/repo.git",  # case variance
        "Git://example.com/repo.git",  # mixed case
        "git:%2F%2Fexample.com/repo.git",  # encoded separator, same scheme
        "%67it://example.com/repo.git",  # percent-encoded scheme spelling
        "git+ssh://example.com/repo.git",  # scheme lookalike
        "/etc",  # bare local path
        "git@example.com:org/repo.git",  # scp-like syntax
        "https:///no-host",  # allowed scheme but no host
        "http://example.com/repo.git",  # plaintext HTTP
    ],
)
async def test_git_clone_rejects_nonpolicy_source_urls(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError(f"git clone should not run for {url!r}")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(url, "/repos/dest")

    assert result["success"] is False
    assert result["error_code"] == "blocked_url_scheme"


async def test_git_clone_rejects_git_protocol_even_when_allowlist_widened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production invariant: git:// stays rejected even if some caller or
    test widens the scheme tuple — the hard deny is checked first."""
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
        ("https://", "git://", "ssh://", "file://"),
    )

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git:// must never reach a subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("git://example.com/repo.git", "/repos/dest")

    assert result["success"] is False
    assert result["error_code"] == "blocked_url_scheme"


async def test_git_clone_enforces_configured_host_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAISTRO_GIT_CLONE_HOSTS", "github.com")

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("clone of a non-policy host should not run")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("https://gitlab.com/org/repo.git", "/repos/dest")

    assert result["success"] is False
    assert result["error_code"] == "blocked_clone_host"


async def test_git_clone_host_allowlist_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAISTRO_GIT_CLONE_HOSTS", "GitHub.COM")

    result, _ = await _run_scripted_clone(
        monkeypatch, _success_steps(), url="https://GitHub.com/org/repo.git"
    )

    assert result["success"] is True


async def test_git_clone_passes_transport_hardening_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirects (and with them any protocol-downgrade hop) are refused, TLS
    verification is pinned on, and the git transport whitelist is deny-by-
    default — and the `--` separator still lands before url/dest so neither
    can smuggle flags."""
    result, scripted = await _run_scripted_clone(monkeypatch, _success_steps())

    assert result["success"] is True
    clone_argv = scripted.argv_of("clone")
    for config in (
        "protocol.allow=never",
        "protocol.https.allow=always",
        "protocol.ssh.allow=always",
        "protocol.file.allow=user",
        "http.followRedirects=false",
        "http.sslVerify=true",
    ):
        assert config in clone_argv, f"missing hardening flag {config}"
    assert clone_argv[clone_argv.index("--") + 1 :] == (
        "https://github.com/org/repo.git",
        "/repos/dest",
    )
    assert clone_argv.index("http.followRedirects=false") < clone_argv.index("clone")


async def test_git_clone_reports_resolved_head_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = await _run_scripted_clone(monkeypatch, _success_steps())

    assert result["success"] is True
    assert result["head_commit"] == _DIGEST


async def test_git_clone_pinned_commit_survives_branch_ref_moving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOCTOU: the branch tip moved to attacker content between resolution and
    fetch. The pin flow must fetch the pinned digest itself, detach, and land
    exactly on it — the attacker commit never becomes the checkout."""
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_ATTACKER_DIGEST}\n".encode(), 0),
        (("fetch", _DIGEST), b"", 0),
        (("checkout",), b"", 0),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
    ]

    result, scripted = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST)

    assert result["success"] is True
    assert result["head_commit"] == _DIGEST
    fetch_argv = scripted.argv_of("fetch")
    assert _DIGEST in fetch_argv and "origin" in fetch_argv
    checkout_argv = scripted.argv_of("checkout")
    assert "--detach" in checkout_argv and _DIGEST in checkout_argv


async def test_git_clone_rejects_when_head_still_mismatches_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If even after fetch+checkout HEAD is not the pinned digest, the
    workspace is rejected outright — identity must equal the pin or nothing
    ships."""
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_ATTACKER_DIGEST}\n".encode(), 0),
        (("fetch", _DIGEST), b"", 0),
        (("checkout",), b"", 0),
        (("rev-parse", "HEAD"), f"{_ATTACKER_DIGEST}\n".encode(), 0),
    ]

    result, _ = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST)

    assert result["success"] is False
    assert result["error_code"] == "commit_pin_mismatch"


async def test_git_clone_pin_fetch_failure_is_pin_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_ATTACKER_DIGEST}\n".encode(), 0),
        (("fetch", _DIGEST), b"fatal: could not fetch\n", 128),
    ]

    result, _ = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST)

    assert result["success"] is False
    assert result["error_code"] == "commit_pin_mismatch"


@pytest.mark.parametrize("pin", ["main", "abc123", "z" * 40])
async def test_git_clone_rejects_non_digest_pins(monkeypatch: pytest.MonkeyPatch, pin: str) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("non-digest pins must not reach a subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("https://github.com/org/repo.git", "/repos/dest", commit=pin)

    assert result["success"] is False
    assert result["error_code"] == "invalid_commit_pin"


async def test_git_clone_accepts_uppercase_digest_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = await _run_scripted_clone(monkeypatch, _success_steps(), commit=_DIGEST.upper())

    assert result["success"] is True
    assert result["head_commit"] == _DIGEST


async def test_git_clone_require_signed_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("verify-commit",), b"error: no signature\n", 1),
    ]

    result, _ = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST, require_signed=True)

    assert result["success"] is False
    assert result["error_code"] == "commit_signature_unverified"


async def test_git_clone_require_signed_passes_when_signature_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("verify-commit",), b"gpg: Good signature\n", 0),
    ]

    result, _ = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST, require_signed=True)

    assert result["success"] is True
    assert result["head_commit"] == _DIGEST


# --- deployment-wide signature trust anchor (#404 AC3) ------------------
# MAISTRO_GIT_CLONE_TRUSTED_SIGNERS — the develop-side API the develop-sync
# merge had dropped, restored by the repair round. A configured anchor makes
# EVERY successful clone prove its landed HEAD: a cryptographically good
# signature (%G? G or U) by a key whose fingerprint (%GP/%GF) is on the
# allowlist. Without the anchor no signature read is spawned at all.

_SIGNER_FPR = "c" * 40
_OTHER_SIGNER_FPR = "d" * 40


def test_trusted_fprs_normalize_entries_and_drop_empties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grouped = f"{_OTHER_SIGNER_FPR[0:8]} {_OTHER_SIGNER_FPR[8:]}"  # spaced like gpg prints them
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, f"  {_SIGNER_FPR.upper()} , {grouped.upper()} ,,")

    assert _trusted_signature_fprs() == frozenset({_SIGNER_FPR, _OTHER_SIGNER_FPR})


def _anchor_steps(
    verdict: str, fprs: str | None = None
) -> list[tuple[tuple[str, ...], bytes, int]]:
    """Happy-path clone script plus the `git log` reads the trust anchor runs
    after the pin verdict: the %G? signature verdict, then the %GF/%GP signer
    fingerprints."""
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("--pretty=format:%G?",), f"{verdict}\n".encode(), 0),
    ]
    if fprs is not None:
        steps.append((("--pretty=format:%GF%n%GP",), fprs.encode(), 0))
    return steps


async def test_signature_policy_is_off_without_the_trust_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No anchor configured -> no signature read is spawned at all: the
    default policy (digest identity over authenticated transport) is the
    documented off-state, and an unset knob must not add latency or a second
    failure mode."""
    monkeypatch.delenv(_TRUSTED_SIGNERS_ENV, raising=False)
    result, scripted = await _run_scripted_clone(monkeypatch, _success_steps(), commit=_DIGEST)

    assert result["success"] is True, result
    assert not any("%G?" in fragment for argv in scripted.calls for fragment in argv)
    assert "signature_verified" not in result


async def test_signature_policy_when_git_status_is_unreadable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
    result, _ = await _run_scripted_clone(monkeypatch, _anchor_steps(""), commit=_DIGEST)

    assert result["success"] is False
    assert result["error_code"] == "commit_signature_missing"


@pytest.mark.parametrize("verdict", ["N", "B", "X", "E"])
async def test_signature_policy_rejects_not_good_verdicts(
    monkeypatch: pytest.MonkeyPatch, verdict: str
) -> None:
    """N (unsigned), B (bad), X (expired), E (cannot check) each name a real
    failure mode; only G/U — cryptographic goodness — can proceed to the
    fingerprint check."""
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
    result, _ = await _run_scripted_clone(monkeypatch, _anchor_steps(verdict), commit=_DIGEST)

    assert result["success"] is False
    if verdict == "N":
        assert result["error_code"] == "commit_signature_missing"
    else:
        assert result["error_code"] == "commit_signature_invalid"


async def test_signature_policy_rejects_good_signature_by_untrusted_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
    fprs = f"{_OTHER_SIGNER_FPR}\n{_OTHER_SIGNER_FPR}\n"  # %GF then %GP, both foreign
    result, _ = await _run_scripted_clone(monkeypatch, _anchor_steps("G", fprs), commit=_DIGEST)

    assert result["success"] is False
    assert result["error_code"] == "commit_signature_untrusted"
    assert _TRUSTED_SIGNERS_ENV in result["suggested_action"]


@pytest.mark.parametrize(
    "fprs",
    [f"{_SIGNER_FPR}\n{_SIGNER_FPR}", f"{_OTHER_SIGNER_FPR}\n{_SIGNER_FPR}"],
    ids=["primary", "subkey"],
)
async def test_signature_policy_accepts_trusted_signer(
    monkeypatch: pytest.MonkeyPatch, fprs: str
) -> None:
    """A good signature by a trusted key — named as primary (%GP) or as the
    signing subkey (%GF) — passes and the result attests it."""
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
    result, _ = await _run_scripted_clone(monkeypatch, _anchor_steps("G", fprs), commit=_DIGEST)

    assert result["success"] is True, result
    assert result["signature_verified"] is True


async def test_git_clone_trust_anchor_composes_with_require_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both signature policies run when both apply: the per-call
    `require_signed` verify-commit first, then the deployment anchor's
    %G?/%GF reads — the result may only land once each policy has had its
    verdict."""
    monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("verify-commit",), b"gpg: Good signature\n", 0),
        (("--pretty=format:%G?",), b"G\n", 0),
        (("--pretty=format:%GF%n%GP",), f"{_SIGNER_FPR}\n{_SIGNER_FPR}\n".encode(), 0),
    ]
    result, _ = await _run_scripted_clone(monkeypatch, steps, commit=_DIGEST, require_signed=True)

    assert result["success"] is True, result
    assert result["signature_verified"] is True


async def _run_clone_in_workspace(
    monkeypatch: pytest.MonkeyPatch,
    dest: Path,
    steps: list[tuple[tuple[str, ...], bytes, int]],
) -> tuple[dict[str, object], _ScriptedGit]:
    monkeypatch.delenv("MAISTRO_GIT_CLONE_HOSTS", raising=False)
    # The git server imports validate_workspace_path directly, so relax the
    # roots inside the sandbox workspace module (same shape the RSI hermetic
    # tests use).
    monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (dest,))
    scripted = _ScriptedGit([_resolve_step(), *steps])
    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", scripted)
    result = await git_clone("https://github.com/org/repo.git", str(dest))
    return result, scripted


async def test_git_clone_accepts_policy_compliant_submodule_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dest = tmp_path / "ws"
    dest.mkdir()
    (dest / ".gitmodules").write_text(
        '[submodule "lib"]\n\tpath = lib\n\turl = https://github.com/org/lib.git\n'
    )
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("--get-regexp",), b"submodule.lib.url https://github.com/org/lib.git\n", 0),
    ]

    result, _ = await _run_clone_in_workspace(monkeypatch, dest, steps)

    assert result["success"] is True
    assert result["head_commit"] == _DIGEST


@pytest.mark.parametrize(
    "submodule_url",
    [
        "git://evil.example/lib.git",  # unauthenticated transport via submodule
        "../lib",  # relative URL: no explicit host/repository policy
        "http://github.com/org/lib.git",  # plaintext downgrade
        "file:///tmp/maistro-workspace/lib",  # local source outside verified roots
    ],
)
async def test_git_clone_rejects_nonpolicy_submodule_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, submodule_url: str
) -> None:
    dest = tmp_path / "ws"
    dest.mkdir()
    (dest / ".gitmodules").write_text(f'[submodule "lib"]\n\tpath = lib\n\turl = {submodule_url}\n')
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("--get-regexp",), f"submodule.lib.url {submodule_url}\n".encode(), 0),
    ]

    result, _ = await _run_clone_in_workspace(monkeypatch, dest, steps)

    assert result["success"] is False
    assert result["error_code"] == "blocked_submodule_url"


async def test_git_clone_rejects_malformed_gitmodules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dest = tmp_path / "ws"
    dest.mkdir()
    (dest / ".gitmodules").write_text("this is not a valid config file\n")
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        *_pin_steps(),
        (("rev-parse", "HEAD"), f"{_DIGEST}\n".encode(), 0),
        (("--get-regexp",), b"fatal: bad config line\n", 128),
    ]

    result, _ = await _run_clone_in_workspace(monkeypatch, dest, steps)

    assert result["success"] is False
    assert result["error_code"] == "submodule_policy_error"


async def test_git_clone_rejects_file_source_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("file:// sources must not reach a subprocess by default")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("file:///tmp/maistro-workspace/src", "/repos/dest")

    assert result["success"] is False
    assert result["error_code"] == "blocked_url_scheme"


async def test_git_clone_file_source_requires_verified_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even with file:// explicitly opted into, a source outside the verified
    local roots is refused — "local" is not automatically "trusted"."""
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
        ("https://", "ssh://", "file://"),
    )
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_LOCAL_SOURCE_ROOTS",
        (str(tmp_path / "vendor"),),
    )
    origin = tmp_path / "elsewhere" / "repo"
    origin.mkdir(parents=True)

    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("unverified local source must not reach a subprocess")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone(f"file://{origin}", "/repos/dest")

    assert result["success"] is False
    assert result["error_code"] == "blocked_local_source"


async def test_git_clone_allows_file_source_under_verified_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
        ("https://", "ssh://", "file://"),
    )
    monkeypatch.setattr("maistro.tools.git.server._ALLOWED_LOCAL_SOURCE_ROOTS", (str(tmp_path),))
    origin = tmp_path / "origin"
    origin.mkdir()

    result, scripted = await _run_scripted_clone(
        monkeypatch, _success_steps(), url=f"file://{origin}"
    )

    assert result["success"] is True
    assert scripted.argv_of("clone")[-2:] == (f"file://{origin}", "/repos/dest")


async def test_git_clone_persists_transport_pin_into_destination_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clone destination's local config receives the full transport
    whitelist. `-c` flags are invocation-scoped and `git clone` ignores the
    enclosing repo's local config, so this persisted copy is what later
    in-repo fetch/pull/push run under."""
    result, scripted = await _run_scripted_clone(monkeypatch, _success_steps())

    assert result["success"] is True
    rev_parse_argv = scripted.argv_of("rev-parse")
    for key, value in _TRANSPORT_PIN:
        argv = scripted.argv_of(key)
        assert argv[argv.index("config") :] == ("config", key, value)
        # the pin writes themselves run through the same pinned chokepoint
        assert argv[:3] == ("git", "-C", "/repos/dest")
        assert "-c" in argv and "protocol.allow=never" in argv
        # the whitelist is on disk before any content of the tree is inspected
        assert scripted.calls.index(argv) < scripted.calls.index(rev_parse_argv)


async def test_git_clone_fails_closed_when_destination_pin_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A destination whose config cannot be pinned never becomes a candidate
    source — the clone is rejected outright, before any tree inspection."""
    steps: list[tuple[tuple[str, ...], bytes, int]] = [
        (("clone",), b"Cloned\n", 0),
        (("config", "protocol.allow"), b"error: could not write config\n", 1),
    ]

    result, scripted = await _run_scripted_clone(monkeypatch, steps)

    assert result["success"] is False
    assert result["error_code"] == "transport_pin_failed"
    assert all("rev-parse" not in argv for argv in scripted.calls)


async def test_git_commands_in_workspace_carry_transport_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every git command the server issues in a workspace re-applies the
    whitelist ahead of the subcommand — GIT_CONFIG_PARAMETERS carries it into
    child git processes, which is how a server-issued `git submodule update`
    pins the submodule's internal clone."""
    captured: list[tuple[object, ...]] = []

    async def fake_exec(*args: object, **kwargs: object) -> _ScriptedProc:
        captured.append(tuple(args))
        return _ScriptedProc(b"", 0)

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await _git("/repos/ws", "submodule", "update", "--init")

    assert result["success"] is True
    argv = captured[0]
    assert argv[:3] == ("git", "-C", "/repos/ws")
    pin_flags = tuple(str(a) for a in _CLONE_CONFIG_HARDENING)
    assert argv[3 : 3 + len(pin_flags)] == pin_flags
    assert argv[3 + len(pin_flags) :] == ("submodule", "update", "--init")


async def test_pinned_workspace_refuses_submodule_update_over_git_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real git, end to end: a policy clone of a repo whose HEAD declares a
    compliant submodule, then the .gitmodules URL flipped to git:// (what a
    hostile ref checkout would produce — the URL policy ran at clone time on
    the *original* file). A server-issued `git submodule update --init`
    re-applies the whitelist and GIT_CONFIG_PARAMETERS reaches the submodule's
    internal clone, so git refuses the unauthenticated transport before any
    network I/O (previously this invocation ran unpinned)."""

    def git(*args: str, cwd: Path) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    libsrc = tmp_path / "libsrc"
    libsrc.mkdir()
    git("init", "-q", "-b", "main", cwd=libsrc)
    git(
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "commit",
        "--allow-empty",
        "-qm",
        "lib",
        cwd=libsrc,
    )

    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    git(
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "commit",
        "--allow-empty",
        "-qm",
        "init",
        cwd=origin,
    )
    git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        f"file://{libsrc}",
        "lib",
        cwd=origin,
    )
    git(
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        "add submodule",
        cwd=origin,
    )

    monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (tmp_path,))
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
        ("https://", "ssh://", "file://"),
    )
    monkeypatch.setattr(
        "maistro.tools.git.server._ALLOWED_LOCAL_SOURCE_ROOTS",
        (str(tmp_path),),
    )

    dest = tmp_path / "ws" / "dest"
    clone = await git_clone(f"file://{origin}", str(dest))
    assert clone["success"] is True, clone

    # the persisted whitelist is really in the destination's local config
    persisted = subprocess.run(
        ["git", "-C", str(dest), "config", "protocol.allow"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert persisted.stdout.strip() == "never"

    # attacker flips the declared submodule URL after the clone
    (dest / ".gitmodules").write_text(
        '[submodule "lib"]\n\tpath = lib\n\turl = git://127.0.0.1:9418/evil.git\n'
    )

    result = await _git(str(dest), "submodule", "update", "--init", timeout=20)

    assert result["success"] is False
    assert "clone of 'git://127.0.0.1:9418/evil.git'" in result["stdout"]
    assert result["error_code"] != "git_timeout"


# The live proofs below run real gpg: a throwaway keyring (GNUPGHOME), an
# Ed25519 key, a signed origin commit, and the same `git log %G?`/`%GF` path
# production runs. Skipped when gpg is absent rather than silently weakening
# the policy under test. (Restored with the trust anchor from the
# develop-side #404 suite the develop-sync merge had dropped.)


def _raw_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=120
    )


def _gpg(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gpg", *args], check=False, capture_output=True, text=True, timeout=120)


@pytest.fixture
def _gpg_signer_fpr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    if not shutil.which("gpg"):
        pytest.skip("gpg is not installed; live signature policy cannot be exercised")
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))
    gen = _gpg(
        "--batch",
        "--passphrase",
        "",
        "--quick-generate-key",
        "maistro clone policy <signer@example.invalid>",
        "ed25519",
        "sign",
        "never",
    )
    if gen.returncode != 0:
        pytest.skip(f"gpg key generation failed: {gen.stderr.strip()}")
    colons = _gpg("--list-keys", "--with-colons").stdout
    for line in colons.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9].lower()
    pytest.fail(f"no fingerprint in gpg output: {colons!r}")


class TestLiveSignaturePolicy:
    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.root = tmp_path / "workspaces"
        monkeypatch.setattr("maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS", (self.root,))
        # file:// is refused by default; the live proofs opt in exactly the
        # way the source policy requires: the widened scheme tuple AND an
        # origin under a verified local root.
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "ssh://", "file://"),
        )
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_LOCAL_SOURCE_ROOTS",
            (str(tmp_path / "origins"),),
        )

    async def test_signed_clone_passes_when_signer_is_trusted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _gpg_signer_fpr: str
    ) -> None:
        origin = tmp_path / "origins" / "signed"
        origin.mkdir(parents=True)
        assert _raw_git("init", "-q", "-b", "main", str(origin)).returncode == 0
        _raw_git("-C", str(origin), "config", "user.email", "s@s")
        _raw_git("-C", str(origin), "config", "user.name", "s")
        (origin / "f.txt").write_text("signed\n", encoding="utf-8")
        assert _raw_git("-C", str(origin), "add", "-A").returncode == 0
        sign = _raw_git(
            "-C",
            str(origin),
            "-c",
            f"user.signingkey={_gpg_signer_fpr}",
            "commit",
            "-qS",
            "-m",
            "s",
        )
        assert sign.returncode == 0, sign.stderr
        tip = _raw_git("-C", str(origin), "rev-parse", "HEAD").stdout.strip()

        monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _gpg_signer_fpr)
        dest = self.root / "signed-dest"
        result = await git_clone(f"file://{origin}", str(dest), commit=tip)

        assert result["success"] is True, result
        assert result["pinned_commit"] == tip
        assert result["signature_verified"] is True

    async def test_signed_clone_fails_when_trust_anchor_names_another_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _gpg_signer_fpr: str
    ) -> None:
        origin = tmp_path / "origins" / "foreign"
        origin.mkdir(parents=True)
        assert _raw_git("init", "-q", "-b", "main", str(origin)).returncode == 0
        _raw_git("-C", str(origin), "config", "user.email", "s@s")
        _raw_git("-C", str(origin), "config", "user.name", "s")
        (origin / "f.txt").write_text("signed\n", encoding="utf-8")
        assert _raw_git("-C", str(origin), "add", "-A").returncode == 0
        sign = _raw_git(
            "-C",
            str(origin),
            "-c",
            f"user.signingkey={_gpg_signer_fpr}",
            "commit",
            "-qS",
            "-m",
            "s",
        )
        assert sign.returncode == 0, sign.stderr

        monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _OTHER_SIGNER_FPR)  # a different, valid anchor
        result = await git_clone(f"file://{origin}", str(self.root / "foreign-dest"))

        assert result["success"] is False
        assert result["error_code"] == "commit_signature_untrusted"
        assert "do not use this workspace" in result["suggested_action"].lower()

    async def test_unsigned_origin_fails_when_trust_anchor_is_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Unsigned HEAD under a configured anchor fails closed — and this
        direction needs no gpg at all (git reports N without one), so the
        fail-closed default holds even on gpg-less runners."""
        origin = tmp_path / "origins" / "unsigned"
        origin.mkdir(parents=True)
        assert _raw_git("init", "-q", "-b", "main", str(origin)).returncode == 0
        _raw_git("-C", str(origin), "config", "user.email", "s@s")
        _raw_git("-C", str(origin), "config", "user.name", "s")
        (origin / "f.txt").write_text("unsigned\n", encoding="utf-8")
        assert _raw_git("-C", str(origin), "add", "-A").returncode == 0
        assert _raw_git("-C", str(origin), "commit", "-qm", "u").returncode == 0

        monkeypatch.setenv(_TRUSTED_SIGNERS_ENV, _SIGNER_FPR)
        result = await git_clone(f"file://{origin}", str(self.root / "unsigned-dest"))

        assert result["success"] is False
        assert result["error_code"] == "commit_signature_missing"
        assert "do not use this workspace" in result["suggested_action"].lower()
