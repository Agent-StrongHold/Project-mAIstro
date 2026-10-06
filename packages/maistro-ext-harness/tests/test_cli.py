"""The CLI: the shape a third-party CI invokes (#974)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from maistro_ext_harness.cli import main


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI exactly as a foreign CI would: a subprocess, no repo path
    repair, exit code as the verdict."""
    return subprocess.run(
        [sys.executable, "-m", "maistro_ext_harness", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).parent),
    )


def test_cli_passes_a_conforming_extension_and_writes_the_report(
    conforming_extension: Path, tmp_path: Path
) -> None:
    report_path = tmp_path / "report.json"
    proc = _cli("run", "--path", str(conforming_extension), "--report", str(report_path))
    assert proc.returncode == 0, proc.stderr
    assert "0 failed" in proc.stdout
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert document["summary"]["failed"] == 0
    assert document["certification"]["platform_certified"] is False


def test_cli_fails_a_broken_subject_with_exit_1(make_extension: Callable[..., Path]) -> None:
    """A nonconforming subject is a red exit with the failed cases named —
    here a handler the entrypoint names but the module does not provide."""
    plugin = """
PLUGIN: dict[str, object] = {"kind": "tool", "handler": "absent"}

HANDLERS: dict[str, object] = {}
"""
    root = make_extension(plugin_source=plugin)
    proc = _cli("run", "--path", str(root))
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr


def test_cli_invalid_manifest_exits_2(
    make_extension: Callable[..., Path], valid_manifest: dict
) -> None:
    root = make_extension(manifest={**valid_manifest, "family": "nope"})
    proc = _cli("run", "--path", str(root))
    assert proc.returncode == 2
    assert "error:" in proc.stderr


def test_cli_missing_extension_exits_2(tmp_path: Path) -> None:
    proc = _cli("run", "--path", str(tmp_path / "absent"))
    assert proc.returncode == 2


def test_cli_with_reference_runs_both_subjects(conforming_extension: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    proc = _cli(
        "run",
        "--path",
        str(conforming_extension),
        "--with-reference",
        "--report",
        str(report_path),
    )
    assert proc.returncode == 0, proc.stderr
    document = json.loads(report_path.read_text(encoding="utf-8"))
    assert {subject["role"] for subject in document["subjects"]} == {
        "external",
        "reference",
    }


def test_cli_in_process_main_matches_subprocess_verdict(
    conforming_extension: Path,
) -> None:
    assert main(["run", "--path", str(conforming_extension)]) == 0


def test_cli_reports_skip_lines_for_waived_backends(
    conforming_extension: Path, capsys: object
) -> None:
    """Waivers surface as SKIP lines; nothing is silently absent. In-process
    (main) so the gated family case and its backend probe are registered the
    way a third-party suite would register them."""
    from maistro_ext_harness.families import (
        CaseOutcome,
        ConformanceCase,
        FamilyPlugin,
        family_plugin,
        register_family,
    )

    gated = ConformanceCase(
        case_id="acme/needs-real-service",
        description="a property that cannot be mocked honestly",
        run=lambda env: CaseOutcome(True, "ran"),
        requires_backend="acme-real-service",
    )
    original = family_plugin("tool")
    register_family(FamilyPlugin(family="tool", extra_cases=(*original.extra_cases, gated)))
    try:
        code = main(
            [
                "run",
                "--path",
                str(conforming_extension),
                "--allow-missing-backend",
                "acme-real-service",
            ]
        )
    finally:
        register_family(original)
    assert code == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "SKIP" in captured.out
