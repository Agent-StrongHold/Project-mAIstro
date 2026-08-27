"""The wrapper itself, driven with a fake `docker` (#309).

`test_model_identifiers.py` proves the grammar refuses the payloads. That is
the second line of defence. This is the first: even a value that somehow
reached the container must arrive as *data* rather than as shell source.

So these run the real `tools/run_rsi_isolated.sh` with a `docker` on PATH that
records its argv and exits, and assert on what the wrapper was about to run.
Nothing is pulled, nothing is built, and no credential is mounted, because the
wrapper is stopped at the first `docker` call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "tools" / "run_rsi_isolated.sh"

#: The payload from the issue: close the single quote the roster sat inside,
#: run a command in a container that has just sourced /run/gateway.env, and
#: comment out the remainder so the rest of the line does not break.
DEMONSTRATED_PAYLOAD = "x'; cat /run/gateway.env #"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the wrapper is a bash script")


@pytest.fixture
def fake_docker(tmp_path: Path) -> Path:
    """A `docker` that records every invocation and never runs anything.

    `docker inspect` has to answer, because the wrapper resolves the compose
    network from it before it does anything else; everything else records and
    exits 0.
    """
    log = tmp_path / "docker-calls.jsonl"
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "with open(log, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:2] == ['inspect']:\n"
        "    print('maistro_default')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return log


def _run(
    fake_docker: Path, genome_models: str, **environment: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run the wrapper for one cycle with `genome_models`, and read the calls."""
    env = dict(os.environ)
    env["PATH"] = f"{fake_docker.parent / 'bin'}{os.pathsep}{env['PATH']}"
    env["MAISTRO_RSI_NETWORK"] = "test-network"
    # `__cwd` is the harness's own knob, not an environment variable.
    cwd = environment.pop("__cwd", None) or str(ROOT)
    env.update(environment)

    # The wrapper refuses to start without a gateway .env to mount. Nothing
    # reads this one — `docker` is the stub — but its presence is what lets a
    # valid run reach the `docker run` whose argv these tests are about. Its
    # absence would make every "no container started" assertion pass vacuously.
    gateway_env = fake_docker.parent / "gateway.env"
    gateway_env.write_text("LITELLM_API_KEY=not-a-real-key\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "bash",
            str(WRAPPER),
            "1",
            str(gateway_env),
            "code",
            "5",
            str(fake_docker.parent / "reports"),
            genome_models,
        ],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=120,
        check=False,
    )
    calls = (
        [
            json.loads(line)
            for line in fake_docker.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if fake_docker.exists()
        else []
    )
    return completed, calls


def _payload(calls: list[list[str]]) -> str:
    """The `bash -lc` argument of the last recorded `docker run`."""
    for call in reversed(calls):
        if "-lc" in call:
            return call[call.index("-lc") + 1]
    raise AssertionError(f"no `bash -lc` invocation recorded in {calls}")


def _env_flags(calls: list[list[str]]) -> dict[str, str]:
    """The `-e NAME=value` pairs of the last recorded `docker run`."""
    for call in reversed(calls):
        if "-lc" in call:
            pairs = [call[i + 1] for i, token in enumerate(call) if token == "-e"]
            return dict(pair.split("=", 1) for pair in pairs if "=" in pair)
    raise AssertionError("no `bash -lc` invocation recorded")


class TestTheDemonstratedPayloadCannotExecute:
    def test_the_wrapper_refuses_it(self, fake_docker: Path) -> None:
        completed, _calls = _run(fake_docker, DEMONSTRATED_PAYLOAD)

        assert completed.returncode == 64
        assert "GENOME_MODELS rejected" in completed.stderr

    def test_it_is_refused_before_any_container_runs(self, fake_docker: Path) -> None:
        """ "Failed validation occurs before credentials are mounted." The
        gateway .env is only ever mounted by a `docker run`, so the check is
        that no `docker run` happened at all — not that the mount flag was
        absent from one."""
        _completed, calls = _run(fake_docker, DEMONSTRATED_PAYLOAD)

        assert [call for call in calls if call[:1] == ["run"]] == []

    @pytest.mark.parametrize(
        "payload",
        [DEMONSTRATED_PAYLOAD, "x$(id)", "x`id`", "code\nid", "--free-count", "a b"],
    )
    def test_every_variant_is_refused_the_same_way(self, fake_docker: Path, payload: str) -> None:
        completed, calls = _run(fake_docker, payload)

        assert completed.returncode == 64
        assert [call for call in calls if call[:1] == ["run"]] == []


class TestTheEnvironmentIsAlsoValidated:
    """`MAISTRO_RSI_EMERGENCY_MODELS` and `MAISTRO_RSI_LOCAL_FALLBACK_MODEL`
    rode into the same payload from the environment. Validating only the
    positional argument would leave two doors open beside the one being shut.
    """

    @pytest.mark.parametrize(
        "variable", ["MAISTRO_RSI_EMERGENCY_MODELS", "MAISTRO_RSI_LOCAL_FALLBACK_MODEL"]
    )
    def test_a_hostile_value_is_refused_before_any_container_runs(
        self, fake_docker: Path, variable: str
    ) -> None:
        completed, calls = _run(fake_docker, "code", **{variable: DEMONSTRATED_PAYLOAD})

        assert completed.returncode == 64
        assert variable in completed.stderr
        assert [call for call in calls if call[:1] == ["run"]] == []


class TestNothingIsInterpolatedIntoThePayload:
    """The primary fix, and the one that would still hold if the grammar were
    widened tomorrow: the inner command is a fixed string, and every value
    reaches it as an environment variable the container expands.
    """

    def test_the_roster_is_not_in_the_command_text(self, fake_docker: Path) -> None:
        _completed, calls = _run(fake_docker, "openrouter/x/y:free,gemini/flash")

        assert "openrouter/x/y:free" not in _payload(calls)

    def test_the_roster_arrives_as_an_environment_variable(self, fake_docker: Path) -> None:
        _completed, calls = _run(fake_docker, "openrouter/x/y:free,gemini/flash")

        assert _env_flags(calls)["RSI_GENOME_MODELS"] == "openrouter/x/y:free,gemini/flash"

    def test_the_payload_references_it_as_a_quoted_variable(self, fake_docker: Path) -> None:
        """`"$RSI_GENOME_MODELS"` rather than the value: the container's bash
        expands it after parsing, so its contents cannot become tokens."""
        _completed, calls = _run(fake_docker, "code")

        assert '"$RSI_GENOME_MODELS"' in _payload(calls)

    @pytest.mark.parametrize(
        "value",
        ["code", "openrouter/meta-llama/llama-3.1-8b-instruct:free"],
    )
    def test_the_model_argument_is_not_interpolated_either(
        self, fake_docker: Path, value: str
    ) -> None:
        """`--model '$MODEL'` was the same shape one line down. It is operator
        -supplied rather than network-derived, which makes it lower risk and
        not a different defect."""
        _completed, calls = _run(fake_docker, "code", MAISTRO_RSI_IMAGE="img")

        assert '"$RSI_MODEL"' in _payload(calls)
        assert _env_flags(calls)["RSI_MODEL"] == "code"

    def test_the_goal_still_rides_as_a_variable(self, fake_docker: Path) -> None:
        """It always did — the comment beside it said so while the line under
        it interpolated the roster. The regression guard is that it stayed."""
        _completed, calls = _run(fake_docker, "code")

        assert '"$RSI_GOAL"' in _payload(calls)

    def test_no_single_quoted_argument_survives_in_the_payload(self, fake_docker: Path) -> None:
        """The construction this issue is about was `--flag '$VALUE'`. None of
        that shape should remain: every argument is now a double-quoted
        variable expansion."""
        payload = _payload(calls=_run(fake_docker, "code")[1])

        offending = [line for line in payload.splitlines() if "--" in line and "'$" in line]
        assert offending == []


class TestTheFlagsAreBuiltAsAnArray:
    def test_a_run_without_a_roster_passes_no_genome_flags(self, fake_docker: Path) -> None:
        """The classic non-evolving run. Previously `$LIVE_FLAGS` expanded to
        an empty string and vanished by word-splitting; now an empty array
        expands to no arguments, which is the same outcome by a rule rather
        than by accident."""
        _completed, calls = _run(fake_docker, "")

        assert _env_flags(calls)["RSI_GENOME_MODELS"] == ""
        assert 'if [ -n "$RSI_GENOME_MODELS" ]' in _payload(calls)

    def test_the_promotion_review_flag_is_a_value_not_a_string_of_flags(
        self, fake_docker: Path
    ) -> None:
        _completed, calls = _run(fake_docker, "code", MAISTRO_RSI_PROMOTION_REVIEW="off")

        assert _env_flags(calls)["RSI_PROMOTION_REVIEW"] == "off"
        assert "--no-promotion-review" in _payload(calls)


class TestTheValidatorIsFoundWhereverTheWrapperRuns:
    def test_a_run_from_another_directory_still_refuses_the_payload(
        self, fake_docker: Path, tmp_path: Path
    ) -> None:
        """The check resolves its PYTHONPATH from the script's own location.
        Resolving it from `$PWD` would make "refuse the roster" quietly become
        "skip the check" for anyone who invoked the wrapper by absolute path."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        completed, calls = _run(fake_docker, DEMONSTRATED_PAYLOAD, __cwd=str(elsewhere))

        assert completed.returncode == 64
        assert [call for call in calls if call[:1] == ["run"]] == []

    def test_a_valid_roster_from_another_directory_still_reaches_docker(
        self, fake_docker: Path, tmp_path: Path
    ) -> None:
        """The other half: a validator that cannot be imported would fail every
        roster, and a gate that refuses everything is as broken as one that
        refuses nothing."""
        elsewhere = tmp_path / "elsewhere-ok"
        elsewhere.mkdir()

        _completed, calls = _run(fake_docker, "code", __cwd=str(elsewhere))

        assert _env_flags(calls)["RSI_GENOME_MODELS"] == "code"
