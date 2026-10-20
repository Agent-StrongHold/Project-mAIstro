"""The pressure soak driver must fail closed and prove containment (#862)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "soak-compose-pressure.py"
GiB = 1024 * 1024 * 1024
MiB = 1024 * 1024

# A profile the DEFAULT_POLICY accepts on every axis, so `main` can run against
# it with a known-good ceiling (pids 128, so a spawned count of 120 sits
# between pids_limit - SPAWN_SLACK and the attempt bound).
IN_POLICY_PROFILE = {
    "services": {
        "app": {
            "mem_limit": "512m",
            "memswap_limit": "512m",
            "pids_limit": 128,
            "cpus": 1.0,
        }
    }
}


class _FakeTime:
    """Stand-in for the module's ``time``: the deadline never passes, sleeps count."""

    def __init__(self) -> None:
        self.sleeps = 0

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, _seconds: int) -> None:
        self.sleeps += 1


def _completed(cmd: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def _serve_inspects(monkeypatch: Any, module: Any, payloads: list[Any]) -> list[list[str]]:
    """Answer each ``docker inspect`` exec with the next queued payload; record runs."""
    queue = iter(payloads)
    runs: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[:2] == ["docker", "inspect"]:
            return _completed(cmd, stdout=json.dumps(next(queue)))
        if cmd[:2] == ["docker", "run"]:
            runs.append(cmd)
        return _completed(cmd)

    monkeypatch.setattr(module, "_run", fake_run)
    return runs


@pytest.fixture(scope="module")
def driver() -> Any:
    spec = importlib.util.spec_from_file_location("soak_compose_pressure", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_load_ceiling_reads_the_shipped_engine_profile(driver: Any) -> None:
    ceiling = driver.load_ceiling(ROOT / "docker-compose.yml", "maistro-engine")

    assert ceiling == driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)


def test_load_ceiling_fails_closed_when_limits_missing_or_unbounded(
    driver: Any, tmp_path: Path
) -> None:
    profile = tmp_path / "compose.yml"
    profile.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "engine": {"image": "example/engine"},
                    "unbounded": {
                        "mem_limit": "unlimited",
                        "memswap_limit": "4g",
                        "pids_limit": 0,
                        "cpus": 0,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(driver.PolicyError, match="engine"):
        driver.load_ceiling(profile, "engine")
    with pytest.raises(driver.PolicyError, match="out of policy"):
        driver.load_ceiling(profile, "unbounded")
    with pytest.raises(driver.PolicyError, match="not found"):
        driver.load_ceiling(profile, "absent")


def test_docker_run_args_replay_the_profile_ceiling(driver: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)

    args = driver.docker_run_args(
        "maistro-soak-check",
        ceiling,
        "python:3.12-alpine",
        ["python", "-c", "pass"],
        restart="on-failure",
        detach=True,
        rm=True,
    )

    assert args[:2] == ["docker", "run"]
    # Flags must precede the image so the daemon actually applies them.
    image_index = args.index("python:3.12-alpine")
    assert "--memory" in args[:image_index]
    assert args[args.index("--memory") + 1] == str(2 * GiB)
    assert args[args.index("--memory-swap") + 1] == str(2 * GiB)
    assert args[args.index("--pids-limit") + 1] == "512"
    assert args[args.index("--cpus") + 1] == "2.0"
    assert args[args.index("--restart") + 1] == "on-failure"
    assert "-d" in args[:image_index] and "--rm" in args[:image_index]
    # Fractional CPU quotas must not lose their nano-CPU precision.
    applied = driver.applied_matches_profile(
        {
            "Memory": 512 * 1024 * 1024,
            "MemorySwap": 512 * 1024 * 1024,
            "PidsLimit": 128,
            "NanoCpus": 50_000_000,
        },
        driver.Ceiling(512 * 1024 * 1024, 512 * 1024 * 1024, 128, 0.05),
    )
    assert applied


def test_parse_spawned_reads_the_fork_count(driver: Any) -> None:
    assert driver.parse_spawned("noise\nSPAWNED 511\n") == 511
    assert driver.parse_spawned("SPAWNED 0") == 0
    assert driver.parse_spawned("python: can't fork\n") is None
    assert driver.parse_spawned("SPAWNED many") is None


def test_evaluate_flags_containment_failures(driver: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)

    proven = driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=1,
        spawned=510,
        host_pid_delta=4,
        applied_matches_profile=True,
        daemon_responsive=True,
    )
    assert driver.evaluate(proven, ceiling) == []

    leaked = driver.PressureResult(
        oom_killed=False,
        exit_code=0,
        restart_count=0,
        spawned=driver.SPAWN_ATTEMPTS,
        host_pid_delta=driver.SPAWN_ATTEMPTS,
        applied_matches_profile=False,
        daemon_responsive=False,
    )
    failures = driver.evaluate(leaked, ceiling)
    assert any("OOM" in failure for failure in failures)
    assert any("restart" in failure for failure in failures)
    assert any("attempt bound" in failure for failure in failures)
    assert any("leaked" in failure for failure in failures)
    assert any("ceiling verbatim" in failure for failure in failures)
    assert any("daemon" in failure for failure in failures)

    starved = driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=1,
        spawned=7,
        host_pid_delta=1,
        applied_matches_profile=True,
        daemon_responsive=True,
    )
    assert any("binding constraint" in failure for failure in driver.evaluate(starved, ceiling))


def test_evaluate_requires_a_spawn_count(driver: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)
    no_fanout = driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=1,
        spawned=None,
        host_pid_delta=None,
        applied_matches_profile=True,
        daemon_responsive=True,
    )

    assert driver.evaluate(no_fanout, ceiling) == ["PID fan-out phase produced no spawn count"]


def test_load_ceiling_fails_closed_when_profile_is_missing(driver: Any, tmp_path: Path) -> None:
    with pytest.raises(driver.PolicyError, match="does not exist"):
        driver.load_ceiling(tmp_path / "absent-compose.yml", "maistro-engine")

    # A profile whose top level is not a mapping has no services to find.
    scalar = tmp_path / "scalar.yml"
    scalar.write_text("[]\n", encoding="utf-8")
    with pytest.raises(driver.PolicyError, match="not found"):
        driver.load_ceiling(scalar, "app")


def test_run_is_a_capturing_non_checking_call(driver: Any, monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def fake_subprocess_run(cmd: list[str], **kwargs: Any) -> Any:
        seen.update(kwargs)
        seen["cmd"] = cmd
        return _completed(cmd, stdout="ok")

    monkeypatch.setattr(driver.subprocess, "run", fake_subprocess_run)

    completed = driver._run(["echo", "hi"], timeout=7)

    assert completed.stdout == "ok"
    assert seen["cmd"] == ["echo", "hi"]
    assert seen["timeout"] == 7
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["check"] is False


def test_inspect_helpers_fail_closed(driver: Any, monkeypatch: Any) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        name = cmd[-1]
        if name == "good":
            payload = [
                {
                    "State": {"Running": False, "Status": "exited", "OOMKilled": True},
                    "RestartCount": 2.0,
                    "HostConfig": {"Memory": 123},
                }
            ]
            return _completed(cmd, stdout=json.dumps(payload))
        if name == "weird":
            return _completed(
                cmd, stdout=json.dumps([{"State": "not-a-dict", "RestartCount": "many"}])
            )
        if name == "badjson":
            return _completed(cmd, stdout="<html>")
        return _completed(cmd, returncode=1, stderr="no such object")

    monkeypatch.setattr(driver, "_run", fake_run)

    assert driver._inspect("good")[0]["HostConfig"] == {"Memory": 123}
    assert driver._inspect("missing") == []  # docker inspect failed
    assert driver._inspect("badjson") == []  # daemon answered, not JSON
    assert driver._inspect_state("good")["Status"] == "exited"
    assert driver._inspect_state("weird") == {}
    assert driver._inspect_state("missing") == {}
    assert driver._restart_count("good") == 2  # float 2.0 is a count
    assert driver._restart_count("weird") == 0
    assert driver._restart_count("missing") == 0
    assert driver._inspect_host_config("good") == {"Memory": 123}
    assert driver._inspect_host_config("missing") == {}


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="needs /proc")
def test_host_pid_count_counts_live_processes(driver: Any) -> None:
    count = driver.host_pid_count()

    assert count is not None
    assert count > 10  # a test runner is never the only process on the host


def test_host_pid_count_returns_none_without_proc(driver: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(driver, "Path", lambda _p: SimpleNamespace(is_dir=lambda: False))

    assert driver.host_pid_count() is None


def test_docker_version_and_force_remove_speak_the_daemon_cli(
    driver: Any, monkeypatch: Any
) -> None:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen.append(cmd)
        if cmd[:2] == ["docker", "version"]:
            return _completed(cmd, stdout=" 27.0.1\n")
        return _completed(cmd)

    monkeypatch.setattr(driver, "_run", fake_run)

    assert driver.docker_version() == "27.0.1"
    driver._force_remove("maistro-soak-x")
    assert seen[-1] == ["docker", "rm", "-f", "maistro-soak-x"]


def test_docker_version_returns_none_without_a_daemon(driver: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(driver, "_run", lambda cmd, **k: _completed(cmd, returncode=1))
    assert driver.docker_version() is None
    monkeypatch.setattr(driver, "_run", lambda cmd, **k: _completed(cmd, stdout="  \n"))
    assert driver.docker_version() is None


def test_memory_kill_phase_records_contained_oom(
    driver: Any, monkeypatch: Any, fake_time: _FakeTime
) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)
    runs = _serve_inspects(
        monkeypatch,
        driver,
        [
            [
                {
                    "HostConfig": {
                        "Memory": 2 * GiB,
                        "MemorySwap": 2 * GiB,
                        "PidsLimit": 512,
                        "NanoCpus": 2_000_000_000,
                    }
                }
            ],
            [{"State": {"Running": True, "Status": "running"}}],
            [
                {
                    "State": {
                        "Running": False,
                        "Status": "exited",
                        "OOMKilled": True,
                        "ExitCode": 137,
                    }
                }
            ],
        ],
    )

    evidence = driver.memory_kill_phase(ceiling, "python:3.12-alpine")

    assert evidence == {
        "container": driver.MEM_KILL_CONTAINER,
        "oom_killed": True,
        "exit_code": 137,
        "applied_matches_profile": True,
    }
    # One poll while the hog still ran, then the loop broke on the kill.
    assert fake_time.sleeps == 1
    assert "--memory" in runs[0] and "-d" in runs[0]


def test_memory_kill_phase_reports_a_failed_launch(driver: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        driver, "_run", lambda cmd, **k: _completed(cmd, returncode=1, stderr="daemon down\n")
    )

    evidence = driver.memory_kill_phase(driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0), "img")

    assert evidence == {"error": "daemon down"}


class _ExpiringTime:
    """``monotonic`` that allows one loop iteration, then declares the deadline passed."""

    def __init__(self) -> None:
        self.calls = 0
        self.sleeps = 0

    def monotonic(self) -> float:
        self.calls += 1
        return 0.0 if self.calls <= 2 else 10_000.0

    def sleep(self, _seconds: int) -> None:
        self.sleeps += 1


def test_memory_kill_phase_gives_up_at_the_deadline(driver: Any, monkeypatch: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)
    expiring = _ExpiringTime()
    monkeypatch.setattr(driver, "time", expiring)
    _serve_inspects(
        monkeypatch,
        driver,
        [
            [{"State": {"Running": True, "Status": "running"}}],
            [{"State": {"Running": True, "Status": "running"}}],
        ],
    )

    evidence = driver.memory_kill_phase(ceiling, "img")

    # A hog that never dies must be reported as unproven, not polled forever.
    assert evidence["oom_killed"] is False
    assert evidence["exit_code"] is None
    assert expiring.sleeps == 1


def test_memory_restart_phase_gives_up_at_the_deadline(driver: Any, monkeypatch: Any) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)
    expiring = _ExpiringTime()
    monkeypatch.setattr(driver, "time", expiring)
    _serve_inspects(
        monkeypatch,
        driver,
        [
            [{"State": {"Running": False, "Status": "restarting", "OOMKilled": True}}],
            [{"RestartCount": 0}],
        ],
    )

    evidence = driver.memory_restart_phase(ceiling, "img")

    assert evidence == {
        "container": driver.MEM_RESTART_CONTAINER,
        "restart_count": 0,
        "running_after_restart": False,
        "oom_killed": True,
    }
    assert expiring.sleeps == 1


def test_memory_restart_phase_reports_a_failed_launch(driver: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        driver, "_run", lambda cmd, **k: _completed(cmd, returncode=1, stderr="daemon down\n")
    )

    evidence = driver.memory_restart_phase(driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0), "img")

    assert evidence == {"error": "daemon down"}


def test_memory_restart_phase_polls_until_policy_restart(
    driver: Any, monkeypatch: Any, fake_time: _FakeTime
) -> None:
    ceiling = driver.Ceiling(2 * GiB, 2 * GiB, 512, 2.0)
    _serve_inspects(
        monkeypatch,
        driver,
        [
            # One poll = two execs: the container State, then RestartCount.
            [{"State": {"Running": False, "Status": "restarting", "OOMKilled": True}}],
            [{"RestartCount": 0}],
            [{"State": {"Running": True, "Status": "running", "OOMKilled": True}}],
            [{"RestartCount": 1}],
        ],
    )

    evidence = driver.memory_restart_phase(ceiling, "python:3.12-alpine")

    assert evidence == {
        "container": driver.MEM_RESTART_CONTAINER,
        "restart_count": 1,
        "running_after_restart": True,
        "oom_killed": True,
    }
    assert fake_time.sleeps == 1  # not yet restarted, then the policy restart


def test_pid_fanout_phase_records_contained_spawn_count(driver: Any, monkeypatch: Any) -> None:
    ceiling = driver.Ceiling(512 * MiB, 512 * MiB, 128, 0.05)

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[1] == "run":
            assert kwargs.get("timeout") == 300  # the fan-out must never hang the soak
            assert "--rm" in cmd
        return _completed(cmd, returncode=0, stdout="noise\nSPAWNED 96\n")

    monkeypatch.setattr(driver, "_run", fake_run)

    evidence = driver.pid_fanout_phase(ceiling, "python:3.12-alpine")

    assert evidence["spawned"] == 96
    assert evidence["attempts"] == driver.SPAWN_ATTEMPTS
    assert evidence["exit_code"] == 0
    assert evidence["stdout_tail"] == ["SPAWNED 96"]

    monkeypatch.setattr(driver, "_run", lambda cmd, **k: _completed(cmd, stdout=""))
    evidence = driver.pid_fanout_phase(ceiling, "img")

    assert evidence["spawned"] is None
    assert evidence["stdout_tail"] == []


def test_build_result_maps_phase_evidence(driver: Any) -> None:
    result = driver.build_result(
        {"oom_killed": True, "exit_code": 137, "applied_matches_profile": True},
        {"restart_count": 2},
        {"spawned": 500},
        7,
        True,
    )

    assert result == driver.PressureResult(
        oom_killed=True,
        exit_code=137,
        restart_count=2,
        spawned=500,
        host_pid_delta=7,
        applied_matches_profile=True,
        daemon_responsive=True,
    )
    # Missing or null phase evidence degrades to "nothing proven", not a crash.
    assert driver.build_result({}, {}, {}, None, False) == driver.PressureResult(
        oom_killed=False,
        exit_code=None,
        restart_count=0,
        spawned=None,
        host_pid_delta=None,
        applied_matches_profile=False,
        daemon_responsive=False,
    )


def test_docker_run_args_defaults_and_applied_mismatch(driver: Any) -> None:
    ceiling = driver.Ceiling(512 * MiB, 512 * MiB, 128, 0.05)

    args = driver.docker_run_args("c", ceiling, "img", ["true"])

    assert args[2:4] == ["--name", "c"]
    assert "--restart" not in args
    assert "-d" not in args
    assert "--rm" not in args
    assert args[-2:] == ["img", "true"]

    # A daemon that quietly coerced any single ceiling value must be caught.
    base = {
        "Memory": 512 * MiB,
        "MemorySwap": 512 * MiB,
        "PidsLimit": 128,
        "NanoCpus": 50_000_000,
    }
    assert driver.applied_matches_profile(base, ceiling) is True
    assert driver.applied_matches_profile({**base, "MemorySwap": 1}, ceiling) is False
    assert driver.applied_matches_profile({**base, "PidsLimit": 1}, ceiling) is False
    assert driver.applied_matches_profile({**base, "NanoCpus": 1}, ceiling) is False
    assert driver.applied_matches_profile({}, ceiling) is False


@pytest.fixture
def fake_time(monkeypatch: Any, driver: Any) -> _FakeTime:
    fake = _FakeTime()
    monkeypatch.setattr(driver, "time", fake)
    return fake


def test_main_skips_without_a_daemon(driver: Any, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(driver, "docker_version", lambda: None)

    assert driver.main([]) == driver.EXIT_SKIP

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == "skipped"


def test_main_fails_closed_on_an_out_of_policy_profile(
    driver: Any, monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(driver, "docker_version", lambda: "27.0.0")
    profile = tmp_path / "compose.yml"
    profile.write_text(
        yaml.safe_dump({"services": {"app": {"image": "example/app"}}}), encoding="utf-8"
    )

    assert driver.main(["--profile", str(profile), "--service", "app"]) == driver.EXIT_FAIL

    assert "out of policy" in capsys.readouterr().err


def test_main_fails_when_the_pressure_image_is_unavailable(
    driver: Any, monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(driver, "docker_version", lambda: "27.0.0")
    profile = tmp_path / "compose.yml"
    profile.write_text(yaml.safe_dump(IN_POLICY_PROFILE), encoding="utf-8")

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[1] == "image":
            return _completed(cmd, returncode=1)
        return _completed(cmd, returncode=1, stderr="pull denied")

    monkeypatch.setattr(driver, "_run", fake_run)

    assert driver.main(["--profile", str(profile), "--service", "app"]) == driver.EXIT_FAIL

    assert "cannot obtain pressure image" in capsys.readouterr().out


def test_main_records_contained_evidence_and_exits_zero(
    driver: Any, monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(driver, "docker_version", lambda: "27.0.0")

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[1] == "image":
            return _completed(cmd, returncode=1)  # image absent -> pull path
        return _completed(cmd)  # pull and cleanup succeed

    monkeypatch.setattr(driver, "_run", fake_run)
    pids = iter([100, 103])
    monkeypatch.setattr(driver, "host_pid_count", lambda: next(pids))
    monkeypatch.setattr(
        driver,
        "memory_kill_phase",
        lambda ceiling, image: {
            "oom_killed": True,
            "exit_code": 137,
            "applied_matches_profile": True,
        },
    )
    monkeypatch.setattr(
        driver,
        "memory_restart_phase",
        lambda ceiling, image: {
            "restart_count": 1,
            "running_after_restart": True,
            "oom_killed": True,
        },
    )
    monkeypatch.setattr(
        driver,
        "pid_fanout_phase",
        lambda ceiling, image: {
            "spawned": 120,
            "attempts": driver.SPAWN_ATTEMPTS,
            "exit_code": 0,
        },
    )
    profile = tmp_path / "compose.yml"
    profile.write_text(yaml.safe_dump(IN_POLICY_PROFILE), encoding="utf-8")
    output = tmp_path / "evidence" / "soak.json"

    assert (
        driver.main(["--profile", str(profile), "--service", "app", "--output", str(output)])
        == driver.EXIT_OK
    )

    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["result"] == "contained"
    assert record["failures"] == []
    assert record["host_pid_count"] == {"start": 100, "end": 103}
    assert record["daemon_responsive_after_pressure"] is True
    assert record["ceiling"] == {
        "memory_bytes": 512 * MiB,
        "memory_swap_bytes": 512 * MiB,
        "pids_limit": 128,
        "cpus": 1.0,
    }
    assert json.loads(capsys.readouterr().out)["result"] == "contained"


def test_main_reports_a_containment_failure(
    driver: Any, monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(driver, "docker_version", lambda: "27.0.0")

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        return _completed(cmd)  # pressure image already present; cleanup succeeds

    monkeypatch.setattr(driver, "_run", fake_run)
    monkeypatch.setattr(driver, "host_pid_count", lambda: None)  # /proc unavailable
    monkeypatch.setattr(
        driver,
        "memory_kill_phase",
        lambda ceiling, image: {
            "oom_killed": False,
            "exit_code": 0,
            "applied_matches_profile": False,
        },
    )
    monkeypatch.setattr(driver, "memory_restart_phase", lambda ceiling, image: {"restart_count": 0})
    monkeypatch.setattr(driver, "pid_fanout_phase", lambda ceiling, image: {"spawned": None})
    profile = tmp_path / "compose.yml"
    profile.write_text(yaml.safe_dump(IN_POLICY_PROFILE), encoding="utf-8")

    assert driver.main(["--profile", str(profile), "--service", "app"]) == driver.EXIT_FAIL

    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert record["result"] == "containment-failure"
    assert record["failures"]
    assert "FAIL" in captured.err
