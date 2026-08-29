from __future__ import annotations

import importlib.util
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
