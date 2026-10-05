"""The harvest cloud-path clone materializes a digest-pinned source, not a ref.

`test_harvest_entry_point.py` proves the policy wiring with `subprocess.run`
stubbed — and must stop at the fetch, because a stub cannot stand in for git's
own object resolution. These tests run real git for the two steps that stubbed
suite cannot reach: the refusal when `ls-remote` fails to resolve the base ref
to a full commit digest, and the fetch -> detach -> branch sequence that lands
the pinned object. The scheme gate and the argv pins are asserted there; the
immutable-source outcome is asserted here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro_rsi.__main__ import _run_harvest_clone


def _git(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A real remote with one commit on `main` — the approved harvest base."""
    directory = tmp_path / "origin"
    directory.mkdir()
    _git("init", "-q", "-b", "main", str(directory))
    _git("-C", str(directory), "config", "user.email", "t@example.com")
    _git("-C", str(directory), "config", "user.name", "t")
    (directory / "README.md").write_text("harvest base\n", encoding="utf-8")
    _git("-C", str(directory), "add", "-A")
    _git("-C", str(directory), "commit", "-qm", "base")
    return directory


class TestTheCloneLandsTheResolvedDigest:
    """The happy path the stubbed entry-point suite deliberately stops short
    of: after the resolved digest fetches, the workspace must end up with its
    branch at that object and a materialized work tree — the state the apply
    loop below `git am`s patches onto."""

    def test_the_workspace_branches_from_the_resolved_digest(
        self, origin: Path, tmp_path: Path
    ) -> None:
        repo = tmp_path / "workspace"
        digest = _git("-C", str(origin), "rev-parse", "HEAD").stdout.strip()

        _run_harvest_clone(f"file://{origin}", "main", str(repo))

        # The expected branch exists and names the verified object ...
        head = _git("-C", str(repo), "rev-parse", "refs/heads/main").stdout.strip()
        assert head == digest
        # ... HEAD sits on it, so both checkouts ran (detach FETCH_HEAD, then
        # -B onto the digest) ...
        assert _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip() == digest
        # ... and the work tree is materialized, not a bare --no-checkout state.
        assert (repo / "README.md").read_text(encoding="utf-8") == "harvest base\n"

    def test_the_clone_keeps_the_lf_worktree_pin(self, origin: Path, tmp_path: Path) -> None:
        """A host-global autocrlf must not rewrite harvested patch context:
        the clone persists `core.autocrlf=false` before the first checkout."""
        repo = tmp_path / "workspace"

        _run_harvest_clone(f"file://{origin}", "main", str(repo))

        assert _git("-C", str(repo), "config", "core.autocrlf").stdout.strip() == "false"

    def test_the_remote_is_exactly_the_approved_url(self, origin: Path, tmp_path: Path) -> None:
        repo = tmp_path / "workspace"

        _run_harvest_clone(f"file://{origin}", "main", str(repo))

        url = _git("-C", str(repo), "config", "remote.origin.url").stdout.strip()
        assert url == f"file://{origin}"


class TestAnUnresolvableBaseIsRefused:
    """`_COMMIT_DIGEST_RE` is the pin: a base ref that does not resolve to a
    full digest refuses before `git init` can create a half-opened workspace.
    Both refusal shapes take the same guard — ls-remote failing outright, and
    ls-remote succeeding but naming no matching ref."""

    def test_a_base_with_no_matching_ref_raises_before_any_workspace_exists(
        self, origin: Path, tmp_path: Path
    ) -> None:
        repo = tmp_path / "workspace"

        with pytest.raises(RuntimeError, match="refusing unpinned candidate source"):
            _run_harvest_clone(f"file://{origin}", "no-such-branch", str(repo))

        assert not repo.exists()

    def test_an_unreachable_remote_is_refused_the_same_way(self, tmp_path: Path) -> None:
        repo = tmp_path / "workspace"

        with pytest.raises(RuntimeError, match="refusing unpinned candidate source"):
            _run_harvest_clone(f"file://{tmp_path / 'missing'}", "main", str(repo))

        assert not repo.exists()
