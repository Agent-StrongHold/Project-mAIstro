from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-autonomous-merge.py"
SPEC = importlib.util.spec_from_file_location("check_autonomous_merge_review", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def cf(path: str, status: str = "M", old_path: str | None = None):
    return mod.ChangedFile(status=status, path=path, old_path=old_path)


def test_actual_codeowners_path_is_red_for_autonomous_change():
    result = mod.assess([cf(".github/CODEOWNERS")], "", head_ref="chatgpt/x")
    assert result.risk == "red" and not result.eligible


def test_hive_requirements_change_is_yellow():
    result = mod.assess(
        [cf("packages/hive-conductor/backend/requirements.txt")], "", head_ref="chatgpt/x"
    )
    assert result.risk == "yellow" and not result.eligible


def test_filename_auth_boundary_is_yellow():
    result = mod.assess(
        [cf("packages/hive-conductor/backend/routes/auth.py")], "", head_ref="chatgpt/x"
    )
    assert result.risk == "yellow" and not result.eligible


def test_test_files_outside_tests_directories_are_protected():
    findings = mod.integrity_findings(
        "", [cf("packages/hive-conductor/frontend/e2e/app.spec.ts", "D")]
    )
    assert findings == ["test file deleted: packages/hive-conductor/frontend/e2e/app.spec.ts"]


def test_rename_out_of_test_discovery_is_protected():
    findings = mod.integrity_findings(
        "", [cf("docs/archived_case.py", "R100", "tests/test_security.py")]
    )
    assert findings == [
        "test file moved out of test discovery: tests/test_security.py -> docs/archived_case.py"
    ]


def test_rsi_branch_is_autonomous():
    assert mod.is_autonomous("rsi/run-123", [])
