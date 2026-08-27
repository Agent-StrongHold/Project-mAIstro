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

import os
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


class TestTheProfileListingIsTheHonestAnswer:
    """`GET /v1/rsi/test-profiles` is not a convenience for the UI. It is the
    complete list of what an RSI run can execute on this host, so it is also
    the answer to that question for anyone auditing the deployment.
    """

    def test_it_lists_every_profile_with_its_argv(self, admin_client) -> None:
        response = admin_client.get("/v1/rsi/test-profiles")

        assert response.status_code == 200
        profiles = response.json()["profiles"]
        assert profiles
        assert all(isinstance(p["argv"], list) and p["argv"] for p in profiles)

    def test_the_names_it_lists_are_the_names_a_run_accepts(
        self, admin_client, authorized_repo: Path
    ) -> None:
        """A listing that named something the route would refuse would be worse
        than no listing: it would send an operator to a request that 400s."""
        listed = {p["name"] for p in admin_client.get("/v1/rsi/test-profiles").json()["profiles"]}

        from services import rsi_execution_policy as policy

        for name in listed:
            assert policy.resolve_test_profile(name).name == name

    def test_a_broken_policy_file_is_a_server_error_not_an_empty_list(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty list reads as "this deployment runs nothing", which is a
        different and more reassuring claim than "the policy could not be
        read"."""
        from services import rsi_execution_policy as policy

        def _broken() -> None:
            raise policy.RsiPolicyError("profile file is malformed")

        monkeypatch.setattr(policy, "test_profiles", _broken)

        response = admin_client.get("/v1/rsi/test-profiles")

        assert response.status_code == 500
        assert "malformed" in response.json()["detail"]


class TestTheServiceRefusesWhatTheRouteWouldNotSend:
    """The route resolves policy before the service sees it. The service still
    checks, because an in-process caller that skipped the route would otherwise
    get a quieter version of the door the route just closed.
    """

    def _drive(self, config: dict) -> None:
        import asyncio

        from services.rsi import RunState, _RsiService

        run = RunState(run_id="t", mode="cleanup", config=config)
        asyncio.run(_RsiService()._drive_cleanup(run))

    def test_a_config_without_a_policy_resolved_argv_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="policy-resolved test_argv"):
            self._drive({"repo_path": str(tmp_path), "isolation": "container"})

    def test_a_config_that_is_not_container_isolated_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="container isolation"):
            self._drive(
                {
                    "repo_path": str(tmp_path),
                    "test_argv": ["python", "-m", "pytest"],
                    "isolation": "local",
                }
            )

    def test_absent_isolation_is_refused_rather_than_defaulted(self, tmp_path: Path) -> None:
        """The dangerous default. An absent value must not read as the
        permissive one."""
        with pytest.raises(ValueError, match="container isolation"):
            self._drive({"repo_path": str(tmp_path), "test_argv": ["python"]})


class TestTheAuthorizedRootsComeFromConfiguration:
    def test_roots_are_read_from_the_setting_and_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        first = tmp_path / "a"
        second = tmp_path / "b"
        first.mkdir()
        second.mkdir()
        monkeypatch.setattr(
            policy,
            "_settings",
            lambda: SimpleNamespace(rsi_repo_roots=os.pathsep.join([str(first), str(second)])),
        )

        assert policy._authorized_roots() == (first.resolve(), second.resolve())

    def test_a_blank_entry_is_skipped_rather_than_becoming_the_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`Path("")` resolves to the working directory, which would authorize
        wherever the process happens to have been started."""
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        monkeypatch.setattr(
            policy,
            "_settings",
            lambda: SimpleNamespace(rsi_repo_roots=f"{os.pathsep}  {os.pathsep}{tmp_path}"),
        )

        assert policy._authorized_roots() == (tmp_path.resolve(),)

    def test_a_configured_root_that_does_not_exist_is_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        monkeypatch.setattr(
            policy,
            "_settings",
            lambda: SimpleNamespace(rsi_repo_roots=str(tmp_path / "gone")),
        )

        assert policy._authorized_roots() == ()

    def test_an_empty_repo_path_is_refused_before_anything_is_resolved(self) -> None:
        from services import rsi_execution_policy as policy

        with pytest.raises(policy.RsiPolicyError, match="required"):
            policy.resolve_repo("   ")


class TestTheProfileOverlay:
    """Deployments test different things, so the built-ins cannot be the whole
    story -- but the extension point is a file on the server's disk, never a
    field in the request.
    """

    def _overlay(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str) -> None:
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        source = tmp_path / "profiles.json"
        source.write_text(content, encoding="utf-8")
        monkeypatch.setattr(
            policy,
            "_settings",
            lambda: SimpleNamespace(rsi_test_profiles_file=str(source)),
        )

    def test_an_operator_profile_joins_the_built_ins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        self._overlay(tmp_path, monkeypatch, '{"house": ["python", "-m", "pytest", "house"]}')

        names = {p.name for p in policy.test_profiles()}
        assert "house" in names and "pytest" in names

    def test_an_unreadable_file_is_an_error_not_an_empty_overlay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falling back to the built-ins would present a smaller, differently
        named policy as if it were the configured one."""
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        monkeypatch.setattr(
            policy,
            "_settings",
            lambda: SimpleNamespace(rsi_test_profiles_file=str(tmp_path / "absent.json")),
        )

        with pytest.raises(policy.RsiPolicyError, match="could not be read"):
            policy.test_profiles()

    def test_malformed_json_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        self._overlay(tmp_path, monkeypatch, "{not json")

        with pytest.raises(policy.RsiPolicyError, match="could not be read"):
            policy.test_profiles()

    def test_a_file_that_is_not_an_object_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        self._overlay(tmp_path, monkeypatch, '["python"]')

        with pytest.raises(policy.RsiPolicyError, match="name -> argv"):
            policy.test_profiles()

    @pytest.mark.parametrize("argv", ['"pytest -q"', "[]", "[1, 2]"])
    def test_a_profile_that_is_not_a_non_empty_list_of_strings_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: str
    ) -> None:
        """A string is the shape this whole change exists to remove; an empty
        list would run nothing and report it as a passing gate."""
        from services import rsi_execution_policy as policy

        self._overlay(tmp_path, monkeypatch, f'{{"bad": {argv}}}')

        with pytest.raises(policy.RsiPolicyError, match="non-empty list of strings"):
            policy.test_profiles()

    @pytest.mark.parametrize(
        "argv",
        ['["bash", "pytest"]', '["/bin/sh", "x"]', '["cmd.exe", "x"]', '["python", "-c", "x"]'],
    )
    def test_a_profile_that_smuggles_a_shell_back_in_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: str
    ) -> None:
        """`["bash", "-c", "..."]` is a well-formed argument vector that
        restores every property this module removed, behind a name that reads
        like policy."""
        from services import rsi_execution_policy as policy

        self._overlay(tmp_path, monkeypatch, f'{{"sneaky": {argv}}}')

        with pytest.raises(policy.RsiPolicyError):
            policy.test_profiles()

    def test_no_overlay_configured_leaves_the_built_ins_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "_settings", lambda: SimpleNamespace(rsi_test_profiles_file=""))

        assert policy._overlay_profiles() == {}


class TestIsolationAttestation:
    def test_both_halves_are_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An importable class with no daemon behind it runs nothing, and a
        daemon with no adapter is not reachable. Either alone attests something
        that is not the claim."""
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy.shutil, "which", lambda _name: None)

        assert policy._isolation_available() is False

    def test_an_available_backend_yields_the_required_isolation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "_isolation_available", lambda: True)

        assert policy.require_isolation() == policy.REQUIRED_ISOLATION
