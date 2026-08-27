"""The RSI API cannot pick a host path or a host shell command (#305).

`POST /v1/rsi/runs` took `repo_path` and `test_command` as free strings and
passed both into `LocalRsiConfig`, whose `_run_tests` executes the command with
`shell=True` on the host. A principal holding `rsi.execute` -- a scope that says
"you may run the self-improvement loop" -- therefore held "you may run any
command as the Conductor process, against any directory on the box". Those are
not the same grant, and nothing in between them was checked.

The exploit is kept here as a regression test, per the issue's definition of
done. It asserts on refusal, never on execution: the canary path is one the
test then proves was never created.
"""

from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture
def authorized_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository the deployment has actually authorized."""
    from services import rsi_execution_policy as policy

    root = tmp_path / "authorized"
    repo = root / "checkout"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(policy, "_authorized_roots", lambda: (root.resolve(),))
    return repo


class TestTheExploit:
    """The demonstrated attack, retained. Each of these was a 200 before #305."""

    def test_an_arbitrary_host_path_is_refused(self, admin_client, authorized_repo: Path) -> None:
        """With a root configured and a legitimate profile named, so the only
        thing wrong with this request is the path it points at."""
        response = admin_client.post(
            "/v1/rsi/runs",
            json={"mode": "cleanup", "repo_path": "/etc", "test_profile": "pytest"},
        )

        assert response.status_code == 400
        assert "not beneath an authorized root" in response.json()["detail"]

    def test_a_shell_command_is_refused(self, admin_client, tmp_path: Path) -> None:
        """The payload writes a canary. The assertion is that it does not
        exist -- a test that asserted only on the status code would pass
        against a route that refused *and* ran it."""
        canary = tmp_path / "pwned"

        response = admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(tmp_path),
                "test_command": f"touch {canary}",
            },
        )

        assert response.status_code == 400
        assert not canary.exists()

    @pytest.mark.parametrize(
        "payload",
        ["pytest; id", "pytest && id", "pytest | id", "pytest $(id)", "pytest `id`", "pytest\nid"],
    )
    def test_no_shell_metacharacter_reaches_a_command(
        self, admin_client, authorized_repo: Path, payload: str
    ) -> None:
        """With a legitimate repository, so the refusal is about the command
        and not about the path -- otherwise these would pass against a route
        that took any command inside an authorized root."""
        response = admin_client.post(
            "/v1/rsi/runs",
            json={"mode": "cleanup", "repo_path": str(authorized_repo), "test_command": payload},
        )

        assert response.status_code == 400
        assert "test_command" in response.json()["detail"]

    def test_a_command_cannot_arrive_as_a_profile_name_either(
        self, admin_client, authorized_repo: Path
    ) -> None:
        """Renaming the field would be no fix at all if the new one were still
        a command. `test_profile` is looked up, never executed."""
        response = admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest; id",
            },
        )

        assert response.status_code == 400
        assert "unknown test profile" in response.json()["detail"]


class TestPathContainment:
    def test_a_path_outside_the_authorized_root_is_refused(
        self, admin_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        root = tmp_path / "root"
        (root / "repo" / ".git").mkdir(parents=True)
        outside = tmp_path / "outside"
        (outside / ".git").mkdir(parents=True)
        monkeypatch.setattr(policy, "_authorized_roots", lambda: (root.resolve(),))

        with pytest.raises(policy.RsiPolicyError, match="not beneath"):
            policy.resolve_repo(str(outside))

    def test_a_symlink_out_of_the_root_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`..` is the obvious escape and the easy one to block. A symlink
        planted inside the root points outward while every path component
        reads as legal, which is why containment is decided after resolution."""
        from services import rsi_execution_policy as policy

        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        (outside / ".git").mkdir(parents=True)
        link = root / "escape"
        link.symlink_to(outside, target_is_directory=True)
        monkeypatch.setattr(policy, "_authorized_roots", lambda: (root.resolve(),))

        with pytest.raises(policy.RsiPolicyError, match="not beneath"):
            policy.resolve_repo(str(link))

    def test_a_repo_inside_the_root_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        root = tmp_path / "root"
        repo = root / "repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setattr(policy, "_authorized_roots", lambda: (root.resolve(),))

        assert policy.resolve_repo(str(repo)) == repo.resolve()

    def test_a_directory_that_is_not_a_repository_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        root = tmp_path / "root"
        (root / "plain").mkdir(parents=True)
        monkeypatch.setattr(policy, "_authorized_roots", lambda: (root.resolve(),))

        with pytest.raises(policy.RsiPolicyError, match="git"):
            policy.resolve_repo(str(root / "plain"))

    def test_no_configured_root_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset allow-list means "nothing is authorized", never
        "everything is"."""
        from services import rsi_execution_policy as policy

        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setattr(policy, "_authorized_roots", tuple)

        with pytest.raises(policy.RsiPolicyError, match="no authorized"):
            policy.resolve_repo(str(repo))


class TestTestCommandPolicy:
    def test_a_profile_resolves_to_an_argument_vector(self) -> None:
        from services import rsi_execution_policy as policy

        profile = policy.resolve_test_profile("pytest")

        assert isinstance(profile.argv, tuple)
        assert all(isinstance(token, str) for token in profile.argv)
        assert profile.argv[0] != ""

    def test_an_unknown_profile_is_refused_and_lists_what_exists(self) -> None:
        from services import rsi_execution_policy as policy

        with pytest.raises(policy.RsiPolicyError) as caught:
            policy.resolve_test_profile("rm -rf /")

        assert "pytest" in str(caught.value)

    def test_no_profile_argv_goes_through_a_shell(self) -> None:
        """The whole point of an argv: there is no shell to interpret it. A
        profile that smuggled one back in -- `sh -c "..."` -- would restore the
        defect behind a name that reads as policy."""
        from services import rsi_execution_policy as policy

        for profile in policy.test_profiles():
            assert Path(profile.argv[0]).name not in {"sh", "bash", "zsh", "dash", "cmd", "cmd.exe"}
            assert "-c" not in profile.argv


class TestIsolationFailsClosed:
    def test_the_route_never_selects_the_host_backed_sandbox(self) -> None:
        """`LocalSandbox` runs on the host with no isolation at all. It is a
        development convenience for the CLI; reaching it over HTTP is the
        escalation this issue is about."""
        from services import rsi_execution_policy as policy

        assert policy.REQUIRED_ISOLATION == "container"

    def test_unavailable_isolation_is_an_error_not_a_downgrade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "_isolation_available", lambda: False)

        with pytest.raises(policy.RsiPolicyError, match="isolation"):
            policy.require_isolation()
