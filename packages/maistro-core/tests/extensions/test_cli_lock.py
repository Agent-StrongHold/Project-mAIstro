"""`maistro extensions lock|explain` over a resolved lock file (M9-C2).

The CLI is the operator surface for the acceptance criterion "operator can
explain why each dependency/version was selected": these tests write a real
resolved lock to disk, run the typer commands against it, and check the
rendered explanation names the version, the reason it is present, the
constraints that bounded it, and the candidates that were rejected — and that
missing data exits non-zero instead of printing nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from extensions.extension_fixtures import catalog_entry, install_bundle
from maistro.cli._extensions import app
from maistro.extensions.resolution import (
    ExtensionCatalog,
    ExtensionDependency,
    RootRequest,
    resolve_lock,
)

runner = CliRunner()


def _write_lock(path: Path) -> Any:
    """Resolve a small ecosystem and write its canonical lock JSON."""
    entries = [
        catalog_entry(
            install_bundle(name="tool-a", version="1.0.0"),
            dependencies=(
                ExtensionDependency(target="lib-b", range_text=">=1.0.0"),
                ExtensionDependency(target="opt-c", range_text=">=1.0.0", required=False),
            ),
        ),
        catalog_entry(install_bundle(name="lib-b", version="1.2.0")),
        catalog_entry(install_bundle(name="opt-c", version="1.0.0")),
    ]
    lock = resolve_lock(
        [RootRequest(extension_name="tool-a")], ExtensionCatalog(entries=tuple(entries))
    )
    assert any(entry.kind.value == "optional" for entry in lock.entries)
    path.write_text(lock.to_json())
    return lock


def test_lock_command_renders_every_entry_and_the_digest(tmp_path: Path) -> None:
    lock = _write_lock(tmp_path / "lock.json")

    result = runner.invoke(app, ["lock", str(tmp_path / "lock.json")])

    assert result.exit_code == 0
    for entry in lock.entries:
        assert entry.extension_name in result.output
        assert entry.semantic_version in result.output
    # The source column is width-wrapped by rich, so assert the host.
    assert "catalog.example" in result.output
    assert "optional" in result.output
    assert lock.lock_digest() in result.output


def test_lock_command_reports_an_empty_lock(tmp_path: Path) -> None:
    empty = resolve_lock([], ExtensionCatalog(entries=()))
    (tmp_path / "lock.json").write_text(empty.to_json())

    result = runner.invoke(app, ["lock", str(tmp_path / "lock.json")])

    assert result.exit_code == 0
    assert "Nothing locked." in result.output


def test_explain_command_answers_why_extension_and_version(tmp_path: Path) -> None:
    lock = _write_lock(tmp_path / "lock.json")
    lib_b = lock.get("lib-b")
    assert lib_b is not None

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "lib-b"])

    assert result.exit_code == 0
    output = result.output
    assert f"lib-b@{lib_b.semantic_version}" in output
    assert "required by tool-a" in output
    assert f"sha256:{lib_b.package_sha256}" in output
    assert "'>=1.0.0'" in output and "tool-a" in output  # the bounding constraint
    assert "policy:" in output
    assert "sha256:" in output  # manifest digest is rendered too


def test_explain_command_reports_skipped_optional_dependencies(tmp_path: Path) -> None:
    entries = [
        catalog_entry(
            install_bundle(name="tool-a", version="1.0.0"),
            dependencies=(
                ExtensionDependency(target="opt-c", range_text=">=9.0.0", required=False),
            ),
        ),
        catalog_entry(install_bundle(name="opt-c", version="1.0.0")),
    ]
    lock = resolve_lock(
        [RootRequest(extension_name="tool-a")], ExtensionCatalog(entries=tuple(entries))
    )
    assert lock.skipped_optional, "the scenario must produce a recorded skip"
    (tmp_path / "lock.json").write_text(lock.to_json())

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "tool-a"])

    assert result.exit_code == 0
    assert "skipped optional" in result.output
    assert "opt-c" in result.output
    assert "cannot resolve" in result.output


def test_explain_exits_nonzero_for_an_unlocked_extension(tmp_path: Path) -> None:
    _write_lock(tmp_path / "lock.json")

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "no-such-extension"])

    assert result.exit_code == 1
    assert "not in the lock" in result.output


def test_lock_commands_exit_nonzero_for_a_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["lock", str(tmp_path / "absent.json")])
    assert result.exit_code == 1
    assert "Cannot read" in result.output


def test_lock_commands_exit_nonzero_for_an_invalid_lock(tmp_path: Path) -> None:
    (tmp_path / "garbage.json").write_text('{"format": "something-else"}')

    result = runner.invoke(app, ["explain", str(tmp_path / "garbage.json"), "tool-a"])

    assert result.exit_code == 1
    assert "not a valid extension lock" in result.output


def test_explain_renders_rejected_candidates_with_their_reason(tmp_path: Path) -> None:
    """A constraint that passes over a higher version names the loser and why."""
    entries = [
        catalog_entry(
            install_bundle(name="tool-a", version="1.0.0"),
            dependencies=(ExtensionDependency(target="lib-b", range_text=">=1.0.0,<2.0.0"),),
        ),
        catalog_entry(install_bundle(name="lib-b", version="1.0.0")),
        catalog_entry(install_bundle(name="lib-b", version="2.0.0")),
    ]
    lock = resolve_lock(
        [RootRequest(extension_name="tool-a")], ExtensionCatalog(entries=tuple(entries))
    )
    lib_b = lock.get("lib-b")
    assert lib_b is not None and lib_b.semantic_version == "1.0.0"
    assert lib_b.rejected, "the scenario must leave a rejected candidate to explain"
    (tmp_path / "lock.json").write_text(lock.to_json())

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "lib-b"])

    assert result.exit_code == 0
    assert "rejected candidates:" in result.output
    assert "2.0.0" in result.output
    assert "<2.0.0" in result.output  # the constraint that excluded it


def test_explain_marks_an_optional_branch_head(tmp_path: Path) -> None:
    """An optional pin says what it is present *for*, alongside its requirer."""
    _write_lock(tmp_path / "lock.json")  # tool-a optionally depends on opt-c

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "opt-c"])

    assert result.exit_code == 0
    assert "optional dependency of tool-a" in result.output
    assert "optional for:" in result.output
    assert "required by:     tool-a" in result.output


def test_explain_reports_a_skip_on_the_target_side(tmp_path: Path) -> None:
    """The skipped-optional target explains the skip aimed *at* it."""
    entries = [
        catalog_entry(
            install_bundle(name="tool-a", version="1.0.0"),
            dependencies=(
                ExtensionDependency(target="opt-c", range_text=">=9.0.0", required=False),
            ),
        ),
        catalog_entry(install_bundle(name="opt-c", version="1.0.0")),
    ]
    # opt-c is installed on its own behalf, so the lock pins it at 1.0.0 —
    # the optional >=9.0.0 edge from tool-a then skips without touching it.
    lock = resolve_lock(
        [RootRequest(extension_name="tool-a"), RootRequest(extension_name="opt-c")],
        ExtensionCatalog(entries=tuple(entries)),
    )
    assert lock.get("opt-c") is not None
    assert any(skip.target == "opt-c" for skip in lock.skipped_optional)
    (tmp_path / "lock.json").write_text(lock.to_json())

    result = runner.invoke(app, ["explain", str(tmp_path / "lock.json"), "opt-c"])

    assert result.exit_code == 0
    assert "skipped optional on this: tool-a wanted '>=9.0.0'" in result.output
