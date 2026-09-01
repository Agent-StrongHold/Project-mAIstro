from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "build-evidence.py"
SPEC = importlib.util.spec_from_file_location("build_evidence_result_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_evidence
SPEC.loader.exec_module(build_evidence)

EvidenceError = build_evidence.EvidenceError
build_manifest = build_evidence.build_manifest
complete_manifest = build_evidence.complete_manifest
verify_completed_manifest = build_evidence.verify_completed_manifest
main = build_evidence.main


def _identity(tmp_path: Path, *, content: str = "VALUE = 1\n") -> dict[str, object]:
    (tmp_path / "source.py").write_text(content, encoding="utf-8")
    return build_manifest(
        inputs=["source.py"],
        command="pytest tests/test_source.py",
        root=tmp_path,
        tools=["pytest=9"],
    )


def test_successful_result_round_trips_against_expected_identity(
    tmp_path: Path,
) -> None:
    identity = _identity(tmp_path)
    completed = complete_manifest(identity, exit_code=0, duration_seconds=1.25)

    verified = verify_completed_manifest(completed, expected_identity=identity)

    assert verified == completed
    assert completed["result"] == "success"
    assert completed["evidence_key"] == identity["evidence_key"]
    assert str(completed["result_key"]).startswith("sha256:")


def test_failed_command_evidence_is_never_reusable_as_green(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    completed = complete_manifest(identity, exit_code=2, duration_seconds=0.5)

    with pytest.raises(EvidenceError, match="failed command exit code 2"):
        verify_completed_manifest(completed, expected_identity=identity)


def test_consumer_rejects_evidence_for_different_input_content(
    tmp_path: Path,
) -> None:
    first = _identity(tmp_path, content="VALUE = 1\n")
    completed = complete_manifest(first, exit_code=0, duration_seconds=0.5)
    second = _identity(tmp_path, content="VALUE = 2\n")

    with pytest.raises(EvidenceError, match="identity does not match expected inputs"):
        verify_completed_manifest(completed, expected_identity=second)


def test_consumer_rejects_tampered_result_key(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    completed = complete_manifest(identity, exit_code=0, duration_seconds=0.5)
    completed["result_key"] = "sha256:" + "0" * 64

    with pytest.raises(EvidenceError, match="result_key does not match"):
        verify_completed_manifest(completed, expected_identity=identity)


def test_consumer_rejects_result_that_contradicts_exit_code(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    completed = complete_manifest(identity, exit_code=0, duration_seconds=0.5)
    completed["result"] = "failure"

    with pytest.raises(EvidenceError, match="result contradicts exit_code"):
        verify_completed_manifest(completed, expected_identity=identity)


def test_completion_rejects_nonfinite_duration(tmp_path: Path) -> None:
    identity = _identity(tmp_path)

    with pytest.raises(EvidenceError, match="finite and non-negative"):
        complete_manifest(identity, exit_code=0, duration_seconds=float("nan"))


def test_completion_rejects_boolean_exit_code(tmp_path: Path) -> None:
    identity = _identity(tmp_path)

    with pytest.raises(EvidenceError, match="non-negative integer"):
        complete_manifest(identity, exit_code=True, duration_seconds=0.0)


def test_cli_can_complete_then_verify_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = _identity(tmp_path)
    identity_path = tmp_path / "identity.json"
    completed_path = tmp_path / "completed.json"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    assert (
        main(
            [
                "--complete-from",
                str(identity_path),
                "--exit-code",
                "0",
                "--duration-seconds",
                "2.5",
                "--out",
                str(completed_path),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--verify-result",
                str(completed_path),
                "--input",
                "source.py",
                "--command",
                "pytest tests/test_source.py",
                "--tool",
                "pytest=9",
                "--root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "verified build evidence sha256:" in capsys.readouterr().out


def test_cli_complete_mode_refuses_identity_generation_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = _identity(tmp_path)
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    code = main(
        [
            "--complete-from",
            str(identity_path),
            "--exit-code",
            "0",
            "--duration-seconds",
            "1",
            "--input",
            "source.py",
        ]
    )

    assert code == 2
    assert "do not pass --input/--command/--tool" in capsys.readouterr().err


def test_identity_validation_rejects_malformed_runtime_and_tools(tmp_path: Path) -> None:
    identity = _identity(tmp_path)

    malformed_runtime = dict(identity)
    malformed_runtime["runtime"] = {"python": "3.12"}
    with pytest.raises(EvidenceError, match="runtime is malformed"):
        complete_manifest(malformed_runtime, exit_code=0, duration_seconds=0)

    empty_runtime = dict(identity)
    empty_runtime["runtime"] = {"implementation": "", "python": "3.12"}
    with pytest.raises(EvidenceError, match="runtime values must be non-empty"):
        complete_manifest(empty_runtime, exit_code=0, duration_seconds=0)

    malformed_tools = dict(identity)
    malformed_tools["tools"] = [1]
    with pytest.raises(EvidenceError, match="tools must be a list of strings"):
        complete_manifest(malformed_tools, exit_code=0, duration_seconds=0)

    noncanonical_tools = dict(identity)
    noncanonical_tools["tools"] = ["z=1", "a=1", "a=1"]
    with pytest.raises(EvidenceError, match="tools are not canonical"):
        complete_manifest(noncanonical_tools, exit_code=0, duration_seconds=0)


def test_identity_validation_rejects_malformed_input_entries(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    valid_digest = "a" * 64

    for inputs, message in (
        ([{"path": "source.py"}], "input entry is malformed"),
        ([{"path": "", "sha256": valid_digest}], "input path must be non-empty"),
        (
            [
                {"path": "z.py", "sha256": valid_digest},
                {"path": "a.py", "sha256": valid_digest},
            ],
            "inputs are not in canonical path order",
        ),
        ([{"path": "source.py", "sha256": "bad"}], "input digest is malformed"),
        ([{"path": "source.py", "sha256": "g" * 64}], "input digest is malformed"),
    ):
        candidate = dict(identity)
        candidate["inputs"] = inputs
        with pytest.raises(EvidenceError, match=message):
            complete_manifest(candidate, exit_code=0, duration_seconds=0)


def test_identity_validation_rejects_schema_command_and_key_drift(tmp_path: Path) -> None:
    identity = _identity(tmp_path)

    extra_field = dict(identity)
    extra_field["unexpected"] = True
    with pytest.raises(EvidenceError, match="fields do not match schema"):
        complete_manifest(extra_field, exit_code=0, duration_seconds=0)

    bad_schema = dict(identity)
    bad_schema["schema"] = 999
    with pytest.raises(EvidenceError, match="unsupported identity schema"):
        complete_manifest(bad_schema, exit_code=0, duration_seconds=0)

    empty_command = dict(identity)
    empty_command["command"] = " "
    with pytest.raises(EvidenceError, match="command must be a non-empty string"):
        complete_manifest(empty_command, exit_code=0, duration_seconds=0)

    bad_key = dict(identity)
    bad_key["evidence_key"] = "sha256:" + "0" * 64
    with pytest.raises(EvidenceError, match="evidence_key does not match"):
        complete_manifest(bad_key, exit_code=0, duration_seconds=0)


def test_completed_validation_rejects_malformed_envelope(tmp_path: Path) -> None:
    identity = _identity(tmp_path)
    completed = complete_manifest(identity, exit_code=0, duration_seconds=0.5)

    extra_field = dict(completed)
    extra_field["unexpected"] = True
    with pytest.raises(EvidenceError, match="fields do not match schema"):
        verify_completed_manifest(extra_field, expected_identity=identity)

    bad_schema = dict(completed)
    bad_schema["schema"] = 999
    with pytest.raises(EvidenceError, match="unsupported completed-evidence schema"):
        verify_completed_manifest(bad_schema, expected_identity=identity)

    bad_identity = dict(completed)
    bad_identity["identity"] = "not-an-object"
    with pytest.raises(EvidenceError, match="identity is malformed"):
        verify_completed_manifest(bad_identity, expected_identity=identity)

    bad_key = dict(completed)
    bad_key["evidence_key"] = "sha256:" + "0" * 64
    with pytest.raises(EvidenceError, match="evidence_key does not match"):
        verify_completed_manifest(bad_key, expected_identity=identity)

    bad_exit = dict(completed)
    bad_exit["exit_code"] = True
    with pytest.raises(EvidenceError, match="exit_code is malformed"):
        verify_completed_manifest(bad_exit, expected_identity=identity)


def test_evidence_json_reader_fails_closed_on_invalid_content(tmp_path: Path) -> None:
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(EvidenceError, match="cannot read evidence JSON"):
        build_evidence._read_json(str(invalid_json))

    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(EvidenceError, match="must contain an object"):
        build_evidence._read_json(str(non_object))


def test_cli_identity_and_completion_requirements_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = _identity(tmp_path)
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    assert main(["--command", "pytest", "--root", str(tmp_path)]) == 2
    assert "requires at least one --input" in capsys.readouterr().err

    assert main(["--input", "source.py", "--root", str(tmp_path)]) == 2
    assert "requires --command" in capsys.readouterr().err

    assert main(["--complete-from", str(identity_path), "--exit-code", "0"]) == 2
    assert "requires --exit-code and --duration-seconds" in capsys.readouterr().err

    assert (
        main(
            [
                "--input",
                "source.py",
                "--command",
                "pytest",
                "--root",
                str(tmp_path),
                "--exit-code",
                "0",
            ]
        )
        == 2
    )
    assert "only valid with --complete-from" in capsys.readouterr().err
