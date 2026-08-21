"""Pure-function PR review checks.

Each check operates on diff text (strings) and returns ReviewFindings.
No I/O, no GitHub API -- the tool layer handles fetching diffs.
This makes every check trivially testable.
"""

from __future__ import annotations

import re

from maistro.types.feedback import ReviewFinding, Severity, ViolationCategory

_MOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"from\s+unittest\.mock\s+import"),
    re.compile(r"import\s+unittest\.mock"),
    re.compile(r"\bMagicMock\b"),
    re.compile(r"\bAsyncMock\b"),
    re.compile(r"@patch\("),
    re.compile(r"with\s+patch\("),
    re.compile(r"mock\.patch"),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""(?:api_key|secret|password|token)\s*=\s*["'][^"']{8,}["']""", re.IGNORECASE),
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),
    re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)

_ANY_IN_BUSINESS: re.Pattern[str] = re.compile(r":\s*Any\b|-> Any\b")

_PRIVATE_FIELD: re.Pattern[str] = re.compile(r"\.\s*_[a-z]\w*\b")

_TEST_EXEMPT: frozenset[str] = frozenset(
    {
        "tests/fakes.py",
        "tests/conftest.py",
        "tests/factories.py",
    }
)


def check_mock_usage(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        for pattern in _MOCK_PATTERNS:
            if pattern.search(content):
                findings.append(
                    ReviewFinding(
                        category=ViolationCategory.MOCK_USAGE,
                        severity=Severity.HIGH,
                        file_path=file_path,
                        description=f"unittest.mock usage detected: {content.strip()}",
                        suggestion=(
                            "Use real classes or fakes from tests/fakes.py. "
                            "Only mock external HTTP calls (use respx)."
                        ),
                        line_number=i,
                    )
                )
                break
    return findings


def check_architecture_update(
    changed_files: list[str],
) -> list[ReviewFinding]:
    has_new_src_module = False
    has_arch_update = False

    for path in changed_files:
        if path == "ARCHITECTURE.md":
            has_arch_update = True
        if path.startswith("src/maistro/") and path.endswith("__init__.py"):
            has_new_src_module = True

    if has_new_src_module and not has_arch_update:
        return [
            ReviewFinding(
                category=ViolationCategory.ARCHITECTURE_UPDATE,
                severity=Severity.HIGH,
                file_path="ARCHITECTURE.md",
                description="New module added without ARCHITECTURE.md update",
                suggestion=(
                    "Build Rule #1: 'No Code Without Architecture.' "
                    "Add a section describing the new module before implementation."
                ),
            ),
        ]
    return []


def check_protocol_compliance(
    changed_files: list[str],
) -> list[ReviewFinding]:
    new_modules: list[str] = []
    has_protocol_change = False

    for path in changed_files:
        if path.startswith("src/maistro/protocols/"):
            has_protocol_change = True
        elif (
            path.startswith("src/maistro/")
            and path.endswith("__init__.py")
            and "protocols/" not in path
            and "types/" not in path
        ):
            new_modules.append(path)

    findings: list[ReviewFinding] = []
    if new_modules and not has_protocol_change:
        for mod_path in new_modules:
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PROTOCOL_MISSING,
                    severity=Severity.MEDIUM,
                    file_path=mod_path,
                    description="New module without corresponding protocol",
                    suggestion=(
                        "Add a protocol to src/maistro/protocols/ for "
                        "new interfaces. Business logic depends on "
                        "protocols, not concrete implementations."
                    ),
                ),
            )
    return findings


def check_production_code_in_test_pr(
    changed_files: list[str],
    *,
    is_test_pr: bool,
) -> list[ReviewFinding]:
    if not is_test_pr:
        return []

    findings: list[ReviewFinding] = []
    for path in changed_files:
        if path.startswith("src/") and path not in _TEST_EXEMPT:
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PRODUCTION_CODE_IN_TEST,
                    severity=Severity.HIGH,
                    file_path=path,
                    description="Test PR modifies production code",
                    suggestion=(
                        "Test PRs (test: prefix) must not modify files under src/. "
                        "Split production changes into a separate PR."
                    ),
                ),
            )
    return findings


def check_type_annotations(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        if "TYPE_CHECKING" in content or content.strip().startswith("#"):
            continue
        if "noqa" in content:
            continue
        if _ANY_IN_BUSINESS.search(content):
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.TYPE_ANNOTATIONS,
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    description=f"Any usage in business logic: {content.strip()}",
                    suggestion=(
                        "Use specific types instead of Any. "
                        "If needed for protocol flexibility, use TYPE_CHECKING guards."
                    ),
                    line_number=i,
                ),
            )
    return findings


def check_hardcoded_secrets(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(
                    ReviewFinding(
                        category=ViolationCategory.HARDCODED_SECRETS,
                        severity=Severity.CRITICAL,
                        file_path=file_path,
                        description=f"Potential hardcoded secret: {content.strip()[:60]}...",
                        suggestion=(
                            "Use environment variables or K8s secrets. "
                            "Defaults must be example values."
                        ),
                        line_number=i,
                    )
                )
                break
    return findings


def check_missing_tests(
    changed_files: list[str],
    *,
    is_test_pr: bool,
) -> list[ReviewFinding]:
    if is_test_pr:
        return []

    has_src_changes = any(f.startswith("src/") for f in changed_files)
    has_test_files = any(f.startswith("tests/") and f.endswith(".py") for f in changed_files)

    if has_src_changes and not has_test_files:
        return [
            ReviewFinding(
                category=ViolationCategory.MISSING_TESTS,
                severity=Severity.HIGH,
                file_path="tests/",
                description="Feature PR has no test files",
                suggestion="Build Rule #2: 'No Code Without Tests (TDD).' Add tests first.",
            ),
        ]
    return []


def check_private_field_access(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        if content.strip().startswith("#"):
            continue
        matches = _PRIVATE_FIELD.findall(content)
        for match in matches:
            prefix_idx = content.find(match)
            if prefix_idx > 0:
                before = content[:prefix_idx].rstrip()
                if before.endswith("self"):
                    continue
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PRIVATE_FIELD_ACCESS,
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    description=f"Private field access: {content.strip()[:80]}",
                    suggestion=(
                        "Access data through public methods or protocols, "
                        "not private fields. This breaks when implementations change."
                    ),
                    line_number=i,
                ),
            )
            break
    return findings


_BUNDLED_COMMIT_THRESHOLD = 10


def check_bundled_changes(
    changed_files: list[str],
    *,
    commit_count: int,
) -> list[ReviewFinding]:
    src_dirs: set[str] = set()
    for path in changed_files:
        if path.startswith("src/maistro/"):
            parts = path.split("/")
            if len(parts) >= 4:
                src_dirs.add(parts[2])

    findings: list[ReviewFinding] = []
    if len(src_dirs) > 4:
        findings.append(
            ReviewFinding(
                category=ViolationCategory.BUNDLED_CHANGES,
                severity=Severity.MEDIUM,
                file_path="",
                description=(
                    f"PR touches {len(src_dirs)} distinct modules: {', '.join(sorted(src_dirs))}. "
                    "This may indicate bundled unrelated changes."
                ),
                suggestion="Split into focused PRs, one per module or issue.",
            ),
        )
    if commit_count > _BUNDLED_COMMIT_THRESHOLD:
        findings.append(
            ReviewFinding(
                category=ViolationCategory.BUNDLED_CHANGES,
                severity=Severity.MEDIUM,
                file_path="",
                description=(
                    f"PR contains {commit_count} commits. "
                    "High commit count often signals bundled-and-unrelated work."
                ),
                suggestion=("Squash-merge, or split into smaller PRs grouped by concern."),
            ),
        )
    return findings
