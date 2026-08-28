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

    def test_this_process_does_not_claim_containment_it_cannot_provide(self) -> None:
        """The load-bearing assertion of the whole change.

        `isolation="container"` sandboxes only the builders agent's edits; the
        loop then runs the test command against the edited worktree on the
        host. `python -m pytest` over a candidate-edited tree imports that
        tree's conftest, its test modules and any plugin it declares, so an
        argument vector is not an isolation boundary. Attesting on "is the
        sandbox importable and is docker on PATH" would answer a narrower
        question than the one being asked, and read as containment to every
        caller.
        """
        from services import rsi_execution_policy as policy

        assert policy.IN_PROCESS_ISOLATION_AVAILABLE is False
        assert policy._isolation_available() is False

    def test_unavailable_isolation_is_an_error_not_a_downgrade(self) -> None:
        from services import rsi_execution_policy as policy

        with pytest.raises(policy.RsiPolicyError, match="isolation boundary"):
            policy.require_isolation()

    def test_the_refusal_names_the_path_that_does_contain(self) -> None:
        """A refusal that leaves the operator with no way to run the loop
        invites the workaround. The isolated wrapper is the answer, so the
        error says so."""
        from services import rsi_execution_policy as policy

        with pytest.raises(policy.RsiPolicyError, match=r"run_rsi_isolated\.sh"):
            policy.require_isolation()

    def test_an_available_backend_would_yield_the_required_isolation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of the gate, so this is a gate rather than a
        hard-coded refusal: when a contained backend is wired, the same call
        returns it."""
        from services import rsi_execution_policy as policy

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", True)

        assert policy.require_isolation() == policy.REQUIRED_ISOLATION


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

    def test_a_policy_resolved_config_reaches_the_loop_with_its_argv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The success branch of both checks. Without it, a service that
        refused every config would satisfy the three refusals above."""
        import maistro_rsi.local_loop as local_loop

        seen: list[object] = []

        class _Loop:
            def __init__(self, config: object, **_kw: object) -> None:
                seen.append(config)

            def run(self) -> object:
                raise AssertionError("the loop must not start in this test")

        monkeypatch.setattr(local_loop, "LocalRsiLoop", _Loop)
        monkeypatch.setattr(local_loop, "make_builders_apply_patch", lambda **_kw: None)

        with pytest.raises(AssertionError, match="must not start"):
            self._drive(
                {
                    "repo_path": str(tmp_path),
                    "test_argv": ["python", "-m", "pytest", "-q"],
                    "isolation": "container",
                    "work_root": str(tmp_path / "work"),
                }
            )

        config = seen[0]
        assert config.test_argv == ("python", "-m", "pytest", "-q")
        assert config.isolation == "container"
        # Kept only so reports can name what ran; nothing executes it.
        assert config.test_command == "python -m pytest -q"


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


class TestAValidRequestStartsARunWithTheResolvedPolicy:
    """The success path. Every test above asserts a refusal, and a route that
    refused *everything* would satisfy all of them -- so this is the one that
    proves the door still opens for a legitimate request, and that what goes
    through it is the policy's values rather than the caller's.
    """

    @pytest.fixture
    def started(self, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        from services import rsi_execution_policy as policy
        from services.rsi import RunState, get_rsi_service

        monkeypatch.setattr(policy, "IN_PROCESS_ISOLATION_AVAILABLE", True)

        configs: list[dict] = []

        def _start(mode: str, config: dict) -> RunState:
            configs.append(config)
            return RunState(run_id="started", mode=mode, config=config)

        monkeypatch.setattr(get_rsi_service(), "start_run", _start)
        monkeypatch.setattr(type(get_rsi_service()), "available", property(lambda _self: True))
        return configs

    def test_the_run_starts(self, admin_client, authorized_repo: Path, started: list[dict]) -> None:
        response = admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest",
            },
        )

        assert response.status_code == 200
        assert response.json()["run_id"] == "started"

    def test_the_service_receives_the_argv_and_never_a_command(
        self, admin_client, authorized_repo: Path, started: list[dict]
    ) -> None:
        admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest",
            },
        )

        config = started[0]
        assert config["test_argv"] == ["python", "-m", "pytest", "-q"]
        assert "test_command" not in config

    def test_the_resolved_path_is_forwarded_not_the_requested_string(
        self, admin_client, authorized_repo: Path, started: list[dict]
    ) -> None:
        """`resolve_repo` returns the realpath. Forwarding the raw string would
        hand the loop a path the containment check never actually approved."""
        admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": f"{authorized_repo}/.",
                "test_profile": "pytest",
            },
        )

        assert started[0]["repo_path"] == str(authorized_repo.resolve())

    def test_the_isolation_the_policy_attested_is_forwarded(
        self, admin_client, authorized_repo: Path, started: list[dict]
    ) -> None:
        from services import rsi_execution_policy as policy

        admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest",
            },
        )

        assert started[0]["isolation"] == policy.REQUIRED_ISOLATION

    def test_a_missing_repo_path_is_refused_before_any_policy_lookup(
        self, admin_client, started: list[dict]
    ) -> None:
        response = admin_client.post(
            "/v1/rsi/runs",
            json={"mode": "cleanup", "repo_path": "", "test_profile": "pytest"},
        )

        assert response.status_code == 400
        assert "requires repo_path" in response.json()["detail"]
        assert started == []


class TestTheCallerCannotAimTheLoopsWrites:
    """`repo_path` was not the only host path in the request. The loop WRITES
    to `work_root` and `report_dir`, and `export_promotions(..., clear=True)`
    DELETES `*.patch` and `manifest.json` under the export child -- so
    containing the repository while forwarding these verbatim left three doors
    open beside the one being shut.
    """

    @pytest.mark.parametrize("field", ["work_root", "report_dir", "export_dir"])
    def test_a_caller_supplied_output_directory_is_refused(
        self, admin_client, authorized_repo: Path, tmp_path: Path, field: str
    ) -> None:
        response = admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest",
                field: str(tmp_path / "anywhere"),
            },
        )

        assert response.status_code == 400
        assert field in response.json()["detail"]

    def test_it_is_refused_rather_than_ignored(
        self, admin_client, authorized_repo: Path, tmp_path: Path
    ) -> None:
        """Silently substituting a different directory would mislead a caller
        who named one and then went looking for their reports there."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        response = admin_client.post(
            "/v1/rsi/runs",
            json={
                "mode": "cleanup",
                "repo_path": str(authorized_repo),
                "test_profile": "pytest",
                # A real directory the test owns, not a `/tmp` literal: bandit
                # flags the literal (B108) and the literal was never the point
                # -- what matters is that a caller-named directory is refused.
                "report_dir": str(elsewhere),
            },
        )

        assert response.status_code == 400
        assert list(elsewhere.iterdir()) == []

    def test_the_service_derives_them_under_its_own_working_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And they are derived from the run id, so two runs cannot collide on
        the same reports directory."""
        import maistro_rsi.local_loop as local_loop

        seen: list[object] = []

        class _Loop:
            def __init__(self, config: object, **_kw: object) -> None:
                seen.append(config)

            def run(self) -> object:
                raise AssertionError("the loop must not start in this test")

        monkeypatch.setattr(local_loop, "LocalRsiLoop", _Loop)
        monkeypatch.setattr(local_loop, "make_builders_apply_patch", lambda **_kw: None)

        import asyncio

        from services.rsi import RunState, _RsiService

        run = RunState(
            run_id="derived",
            mode="cleanup",
            config={
                "repo_path": str(tmp_path),
                "test_argv": ["python", "-m", "pytest"],
                "isolation": "container",
            },
        )
        with pytest.raises(AssertionError, match="must not start"):
            asyncio.run(_RsiService()._drive_cleanup(run))

        config = seen[0]
        assert "derived" in config.work_root
        assert config.report_dir.startswith(config.work_root)
        assert config.export_patches.startswith(config.report_dir)
