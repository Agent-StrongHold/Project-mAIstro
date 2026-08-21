"""Coverage for maistro.agents.auditor.checks pure-function PR review checks (was 0%)."""

from __future__ import annotations

from maistro.agents.auditor.checks import (
    check_architecture_update,
    check_bundled_changes,
    check_hardcoded_secrets,
    check_missing_tests,
    check_mock_usage,
    check_private_field_access,
    check_production_code_in_test_pr,
    check_protocol_compliance,
    check_type_annotations,
)
from maistro.types.feedback import Severity, ViolationCategory

# --- check_mock_usage ---------------------------------------------------------


def test_check_mock_usage_detects_magicmock_import() -> None:
    diff = ["+from unittest.mock import MagicMock"]
    findings = check_mock_usage(diff, file_path="tests/test_foo.py")
    assert len(findings) == 1
    f = findings[0]
    assert f.category == ViolationCategory.MOCK_USAGE
    assert f.severity == Severity.HIGH
    assert f.file_path == "tests/test_foo.py"
    assert f.line_number == 1
    assert "MagicMock" in f.description or "mock" in f.description


def test_check_mock_usage_detects_patch_decorator() -> None:
    diff = ['+@patch("module.func")']
    findings = check_mock_usage(diff, file_path="x.py")
    assert len(findings) == 1


def test_check_mock_usage_ignores_removed_lines() -> None:
    diff = ["-from unittest.mock import MagicMock"]
    findings = check_mock_usage(diff, file_path="x.py")
    assert findings == []


def test_check_mock_usage_ignores_context_lines() -> None:
    diff = [" from unittest.mock import MagicMock"]
    findings = check_mock_usage(diff, file_path="x.py")
    assert findings == []


def test_check_mock_usage_clean_diff_returns_empty() -> None:
    diff = ["+def real_function():", "+    return 1"]
    findings = check_mock_usage(diff, file_path="x.py")
    assert findings == []


def test_check_mock_usage_only_reports_once_per_line_even_with_multiple_patterns() -> None:
    # Line matches both MagicMock and AsyncMock patterns conceptually but break stops at first match.
    diff = ["+x = MagicMock()"]
    findings = check_mock_usage(diff, file_path="x.py")
    assert len(findings) == 1


def test_check_mock_usage_correct_line_number_with_multiple_lines() -> None:
    diff = ["+normal line", "+import unittest.mock"]
    findings = check_mock_usage(diff, file_path="x.py")
    assert len(findings) == 1
    assert findings[0].line_number == 2


# --- check_architecture_update -------------------------------------------------


def test_check_architecture_update_flags_new_module_without_doc_update() -> None:
    findings = check_architecture_update(["src/maistro/newthing/__init__.py"])
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.ARCHITECTURE_UPDATE
    assert findings[0].severity == Severity.HIGH
    assert findings[0].file_path == "ARCHITECTURE.md"


def test_check_architecture_update_passes_when_doc_updated_too() -> None:
    findings = check_architecture_update(["src/maistro/newthing/__init__.py", "ARCHITECTURE.md"])
    assert findings == []


def test_check_architecture_update_no_new_module_no_findings() -> None:
    findings = check_architecture_update(["src/maistro/existing/other.py"])
    assert findings == []


def test_check_architecture_update_arch_doc_alone_no_findings() -> None:
    findings = check_architecture_update(["ARCHITECTURE.md"])
    assert findings == []


# --- check_protocol_compliance -------------------------------------------------


def test_check_protocol_compliance_flags_new_module_without_protocol() -> None:
    findings = check_protocol_compliance(["src/maistro/widgets/__init__.py"])
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.PROTOCOL_MISSING
    assert findings[0].severity == Severity.MEDIUM
    assert findings[0].file_path == "src/maistro/widgets/__init__.py"


def test_check_protocol_compliance_passes_when_protocol_also_changed() -> None:
    findings = check_protocol_compliance(
        ["src/maistro/widgets/__init__.py", "src/maistro/protocols/widget.py"]
    )
    assert findings == []


def test_check_protocol_compliance_ignores_types_init_files() -> None:
    findings = check_protocol_compliance(["src/maistro/types/__init__.py"])
    assert findings == []


def test_check_protocol_compliance_ignores_protocols_init_files() -> None:
    findings = check_protocol_compliance(["src/maistro/protocols/__init__.py"])
    assert findings == []


def test_check_protocol_compliance_reports_one_finding_per_new_module() -> None:
    findings = check_protocol_compliance(["src/maistro/a/__init__.py", "src/maistro/b/__init__.py"])
    assert len(findings) == 2
    assert {f.file_path for f in findings} == {
        "src/maistro/a/__init__.py",
        "src/maistro/b/__init__.py",
    }


# --- check_production_code_in_test_pr ------------------------------------------


def test_check_production_code_in_test_pr_not_a_test_pr_short_circuits() -> None:
    findings = check_production_code_in_test_pr(["src/maistro/foo.py"], is_test_pr=False)
    assert findings == []


def test_check_production_code_in_test_pr_flags_src_changes() -> None:
    findings = check_production_code_in_test_pr(["src/maistro/foo.py"], is_test_pr=True)
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.PRODUCTION_CODE_IN_TEST
    assert findings[0].severity == Severity.HIGH
    assert findings[0].file_path == "src/maistro/foo.py"


def test_check_production_code_in_test_pr_exempts_test_fakes() -> None:
    findings = check_production_code_in_test_pr(["tests/fakes.py"], is_test_pr=True)
    assert findings == []


def test_check_production_code_in_test_pr_exempts_conftest_and_factories() -> None:
    findings = check_production_code_in_test_pr(
        ["tests/conftest.py", "tests/factories.py"], is_test_pr=True
    )
    assert findings == []


def test_check_production_code_in_test_pr_non_src_paths_are_fine() -> None:
    findings = check_production_code_in_test_pr(["docs/adr/ADR-100.md"], is_test_pr=True)
    assert findings == []


# --- check_type_annotations ---------------------------------------------------


def test_check_type_annotations_flags_any_return_type() -> None:
    diff = ["+def foo() -> Any:"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.TYPE_ANNOTATIONS
    assert findings[0].severity == Severity.MEDIUM


def test_check_type_annotations_flags_any_param_type() -> None:
    diff = ["+def foo(x: Any) -> int:"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert len(findings) == 1


def test_check_type_annotations_skips_test_files_entirely() -> None:
    diff = ["+def foo() -> Any:"]
    findings = check_type_annotations(diff, file_path="tests/test_foo.py")
    assert findings == []


def test_check_type_annotations_skips_nested_tests_path() -> None:
    diff = ["+def foo() -> Any:"]
    findings = check_type_annotations(diff, file_path="src/maistro/tests/test_foo.py")
    assert findings == []


def test_check_type_annotations_ignores_type_checking_guarded_lines() -> None:
    diff = ["+x: Any  # TYPE_CHECKING"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_type_annotations_ignores_comment_only_lines() -> None:
    diff = ["+    # x: Any"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_type_annotations_ignores_noqa_lines() -> None:
    diff = ["+x: Any  # noqa"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_type_annotations_clean_code_no_findings() -> None:
    diff = ["+def foo(x: int) -> str:"]
    findings = check_type_annotations(diff, file_path="src/maistro/foo.py")
    assert findings == []


# --- check_hardcoded_secrets ---------------------------------------------------


def test_check_hardcoded_secrets_detects_api_key_assignment() -> None:
    diff = ['+api_key = "sk-this-is-a-fake-secret-value"']
    findings = check_hardcoded_secrets(diff, file_path="src/maistro/config.py")
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.HARDCODED_SECRETS
    assert findings[0].severity == Severity.CRITICAL


def test_check_hardcoded_secrets_detects_github_token_pattern() -> None:
    diff = ['+token = "ghp_' + "a" * 36 + '"']
    findings = check_hardcoded_secrets(diff, file_path="src/maistro/config.py")
    assert len(findings) == 1


def test_check_hardcoded_secrets_detects_aws_access_key() -> None:
    diff = ["+AKIA1234567890123456"]
    findings = check_hardcoded_secrets(diff, file_path="src/maistro/config.py")
    assert len(findings) == 1


def test_check_hardcoded_secrets_skips_test_files() -> None:
    diff = ['+api_key = "sk-this-is-a-fake-secret-value"']
    findings = check_hardcoded_secrets(diff, file_path="tests/test_config.py")
    assert findings == []


def test_check_hardcoded_secrets_short_value_not_flagged() -> None:
    # Pattern requires 8+ chars inside quotes.
    diff = ['+password = "short"']
    findings = check_hardcoded_secrets(diff, file_path="src/maistro/config.py")
    assert findings == []


def test_check_hardcoded_secrets_clean_line_no_findings() -> None:
    diff = ["+x = compute_value()"]
    findings = check_hardcoded_secrets(diff, file_path="src/maistro/config.py")
    assert findings == []


# --- check_missing_tests -------------------------------------------------------


def test_check_missing_tests_flags_src_change_without_tests() -> None:
    findings = check_missing_tests(["src/maistro/foo.py"], is_test_pr=False)
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.MISSING_TESTS
    assert findings[0].severity == Severity.HIGH


def test_check_missing_tests_passes_when_test_file_included() -> None:
    findings = check_missing_tests(["src/maistro/foo.py", "tests/test_foo.py"], is_test_pr=False)
    assert findings == []


def test_check_missing_tests_test_pr_always_passes() -> None:
    findings = check_missing_tests(["src/maistro/foo.py"], is_test_pr=True)
    assert findings == []


def test_check_missing_tests_no_src_changes_passes() -> None:
    findings = check_missing_tests(["docs/adr/ADR-100.md"], is_test_pr=False)
    assert findings == []


def test_check_missing_tests_non_py_test_file_does_not_count() -> None:
    # tests/fixtures/data.json starts with tests/ but doesn't end with .py.
    findings = check_missing_tests(
        ["src/maistro/foo.py", "tests/fixtures/data.json"], is_test_pr=False
    )
    assert len(findings) == 1


# --- check_private_field_access ------------------------------------------------


def test_check_private_field_access_flags_external_private_access() -> None:
    diff = ["+result = other_obj._internal_state"]
    findings = check_private_field_access(diff, file_path="src/maistro/foo.py")
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.PRIVATE_FIELD_ACCESS
    assert findings[0].severity == Severity.MEDIUM


def test_check_private_field_access_allows_self_access() -> None:
    diff = ["+result = self._internal_state"]
    findings = check_private_field_access(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_private_field_access_skips_test_files() -> None:
    diff = ["+result = other_obj._internal_state"]
    findings = check_private_field_access(diff, file_path="tests/test_foo.py")
    assert findings == []


def test_check_private_field_access_ignores_comment_lines() -> None:
    diff = ["+# result = other_obj._internal_state"]
    findings = check_private_field_access(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_private_field_access_dunder_not_matched_by_lowercase_pattern() -> None:
    # Pattern is \._[a-z]\w* -- a leading-underscore-then-underscore (dunder) like __init__
    # does NOT match because the char after the first underscore must be a-z, and here it's
    # another underscore. This is surprising but correct per the regex.
    diff = ["+result = other_obj.__init__"]
    findings = check_private_field_access(diff, file_path="src/maistro/foo.py")
    assert findings == []


def test_check_private_field_access_ignores_removed_lines() -> None:
    diff = ["-result = other_obj._internal_state"]
    findings = check_private_field_access(diff, file_path="src/maistro/foo.py")
    assert findings == []


# --- check_bundled_changes -----------------------------------------------------


def test_check_bundled_changes_flags_too_many_modules() -> None:
    files = [
        "src/maistro/mod1/a.py",
        "src/maistro/mod2/a.py",
        "src/maistro/mod3/a.py",
        "src/maistro/mod4/a.py",
        "src/maistro/mod5/a.py",
    ]
    findings = check_bundled_changes(files, commit_count=1)
    assert len(findings) == 1
    assert findings[0].category == ViolationCategory.BUNDLED_CHANGES
    assert "5 distinct modules" in findings[0].description


def test_check_bundled_changes_four_modules_does_not_trigger() -> None:
    files = [
        "src/maistro/mod1/a.py",
        "src/maistro/mod2/a.py",
        "src/maistro/mod3/a.py",
        "src/maistro/mod4/a.py",
    ]
    findings = check_bundled_changes(files, commit_count=1)
    assert findings == []


def test_check_bundled_changes_flags_high_commit_count() -> None:
    findings = check_bundled_changes([], commit_count=11)
    assert len(findings) == 1
    assert "11 commits" in findings[0].description


def test_check_bundled_changes_exactly_threshold_commit_count_does_not_trigger() -> None:
    findings = check_bundled_changes([], commit_count=10)
    assert findings == []


def test_check_bundled_changes_both_conditions_produce_two_findings() -> None:
    files = [
        "src/maistro/mod1/a.py",
        "src/maistro/mod2/a.py",
        "src/maistro/mod3/a.py",
        "src/maistro/mod4/a.py",
        "src/maistro/mod5/a.py",
    ]
    findings = check_bundled_changes(files, commit_count=20)
    assert len(findings) == 2


def test_check_bundled_changes_ignores_paths_without_enough_segments() -> None:
    # "src/maistro/onlytwoparts.py" splits to ["src", "maistro", "onlytwoparts.py"] -- len 3, < 4.
    files = ["src/maistro/onlytwoparts.py"]
    findings = check_bundled_changes(files, commit_count=1)
    assert findings == []


def test_check_bundled_changes_no_findings_when_clean() -> None:
    findings = check_bundled_changes(["src/maistro/mod1/a.py"], commit_count=1)
    assert findings == []
