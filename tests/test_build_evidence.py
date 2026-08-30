from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "build-evidence.py"
SPEC = importlib.util.spec_from_file_location("build_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build_evidence
SPEC.loader.exec_module(build_evidence)

EvidenceError = build_evidence.EvidenceError
build_manifest = build_evidence.build_manifest
main = build_evidence.main


def test_evidence_key_is_independent_of_input_argument_order(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")

    first = build_manifest(
        inputs=["a.txt", "b.txt"],
        command="pytest package/tests",
        root=tmp_path,
        tools=["uv=1", "pytest=9"],
    )
    second = build_manifest(
        inputs=["b.txt", "a.txt"],
        command="pytest package/tests",
        root=tmp_path,
        tools=["pytest=9", "uv=1"],
    )

    assert first == second


def test_evidence_key_changes_when_input_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    before = build_manifest(inputs=["source.py"], command="pytest", root=tmp_path)

    source.write_text("VALUE = 2\n", encoding="utf-8")
    after = build_manifest(inputs=["source.py"], command="pytest", root=tmp_path)

    assert before["evidence_key"] != after["evidence_key"]


def test_evidence_key_changes_when_command_changes(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("VALUE = 1\n", encoding="utf-8")

    first = build_manifest(inputs=["source.py"], command="pytest -q", root=tmp_path)
    second = build_manifest(inputs=["source.py"], command="pytest -v", root=tmp_path)

    assert first["evidence_key"] != second["evidence_key"]


def test_directory_input_hashes_files_in_stable_relative_order(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "z.py").write_text("z\n", encoding="utf-8")
    (package / "a.py").write_text("a\n", encoding="utf-8")

    manifest = build_manifest(inputs=["package"], command="pytest", root=tmp_path)

    assert [item["path"] for item in manifest["inputs"]] == ["package/a.py", "package/z.py"]


def test_overlapping_inputs_are_deduplicated(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "a.py").write_text("a\n", encoding="utf-8")

    manifest = build_manifest(
        inputs=["package", "package/a.py"],
        command="pytest",
        root=tmp_path,
    )

    assert [item["path"] for item in manifest["inputs"]] == ["package/a.py"]


def test_missing_input_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError, match="missing input"):
        build_manifest(inputs=["missing.py"], command="pytest", root=tmp_path)


def test_empty_directory_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()

    with pytest.raises(EvidenceError, match="at least one concrete input"):
        build_manifest(inputs=["empty"], command="pytest", root=tmp_path)


def test_input_outside_repository_root_fails_closed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-build-evidence.txt"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        with pytest.raises(EvidenceError, match="escapes repository root"):
            build_manifest(inputs=[str(outside)], command="pytest", root=tmp_path)
    finally:
        outside.unlink()


def test_empty_command_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "source.py").write_text("x\n", encoding="utf-8")

    with pytest.raises(EvidenceError, match="command must not be empty"):
        build_manifest(inputs=["source.py"], command="   ", root=tmp_path)


def test_symlink_input_is_hashed_by_its_target_path(tmp_path: Path) -> None:
    """A symlink's own bytes are never read; changing what it points at, not
    changing the target's content, must move the evidence key."""
    (tmp_path / "real-one.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "real-two.txt").write_text("two\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to("real-one.txt")

    pointing_at_one = build_manifest(inputs=["link.txt"], command="pytest", root=tmp_path)

    link.unlink()
    link.symlink_to("real-two.txt")
    pointing_at_two = build_manifest(inputs=["link.txt"], command="pytest", root=tmp_path)

    assert pointing_at_one["evidence_key"] != pointing_at_two["evidence_key"]


class TestMain:
    def test_writes_the_manifest_to_stdout_by_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "source.py").write_text("x\n", encoding="utf-8")

        code = main(
            [
                "--input",
                "source.py",
                "--command",
                "pytest -q",
                "--tool",
                "uv=1",
                "--root",
                str(tmp_path),
            ]
        )

        assert code == 0
        manifest = json.loads(capsys.readouterr().out)
        assert manifest["command"] == "pytest -q"
        assert manifest["tools"] == ["uv=1"]
        assert manifest["inputs"] == [
            {"path": "source.py", "sha256": manifest["inputs"][0]["sha256"]}
        ]

    def test_writes_the_manifest_to_the_out_file_when_given(self, tmp_path: Path) -> None:
        (tmp_path / "source.py").write_text("x\n", encoding="utf-8")
        out = tmp_path / "evidence.json"

        code = main(
            [
                "--input",
                "source.py",
                "--command",
                "pytest -q",
                "--root",
                str(tmp_path),
                "--out",
                str(out),
            ]
        )

        assert code == 0
        manifest = json.loads(out.read_text(encoding="utf-8"))
        assert manifest["command"] == "pytest -q"

    def test_reports_an_evidence_error_and_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "--input",
                "missing.py",
                "--command",
                "pytest -q",
                "--root",
                str(tmp_path),
            ]
        )

        assert code == 2
        assert "build evidence unavailable: missing input" in capsys.readouterr().err
