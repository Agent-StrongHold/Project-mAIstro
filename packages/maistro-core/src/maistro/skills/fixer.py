"""Security repair engine for marketplace skills and agents.

Attempts to automatically fix security issues found by the scanner.
Returns what was fixed, what couldn't be fixed, and the cleaned content.
"""

from __future__ import annotations

import re
import unicodedata

# Zero-width / bidi-override / BOM characters used to hide instructions from
# reviewers. Built from codepoints (not \u literal escapes) so the exact
# character set is easy to audit: ZWSP, ZWNJ, ZWJ, LRM, RLM, the five
# explicit bidi-embedding/override controls, the four bidi-isolate controls,
# and the BOM / zero-width no-break space.
_DIRECTION_MARKER_CODEPOINTS = [
    0x200B,
    0x200C,
    0x200D,
    0x200E,
    0x200F,
    *range(0x202A, 0x202F),
    *range(0x2066, 0x206A),
    0xFEFF,
]
_DIRECTION_MARKER_PATTERN = re.compile(
    "[" + "".join(chr(c) for c in _DIRECTION_MARKER_CODEPOINTS) + "]"
)


def _strip_unicode_markers(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    normalized = unicodedata.normalize("NFKD", fixed)
    if normalized != fixed:
        fixes.append(
            "Normalized unicode characters (NFKD) — removed directional markers and lookalikes"
        )
        fixed = normalized

    direction_markers = _DIRECTION_MARKER_PATTERN.findall(fixed)
    if direction_markers:
        fixed = _DIRECTION_MARKER_PATTERN.sub("", fixed)
        fixes.append(f"Removed {len(direction_markers)} hidden unicode direction markers")

    return fixed, fixes


_EXEC_PATTERNS = [
    (r"\bexec\s*\([^)]*\)", "exec() call"),
    (r"\beval\s*\([^)]*\)", "eval() call"),
    (r"\bsubprocess\.\w+\s*\([^)]*\)", "subprocess call"),
    (r"\bos\.system\s*\([^)]*\)", "os.system() call"),
    (r"__import__\s*\([^)]*\)", "__import__() call"),
    (r"\bcompile\s*\([^)]*\)", "compile() call"),
    (r"\bimportlib\.\w+", "importlib usage"),
    (r"__builtins__", "__builtins__ access"),
    (r"\bglobals\s*\(\s*\)", "globals() access"),
]


def _strip_exec_patterns(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    for pattern, desc in _EXEC_PATTERNS:
        matches = re.findall(pattern, fixed, re.IGNORECASE)
        if matches:
            fixed = re.sub(pattern, f"# [REMOVED: {desc}]", fixed, flags=re.IGNORECASE)
            fixes.append(f"Removed {len(matches)} {desc}(s)")
    return fixed, fixes


def _strip_dangerous_imports(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    dangerous_imports = re.findall(
        r"^\s*(?:import|from)\s+(?:subprocess|os|sys|shutil|importlib|ctypes|socket)\b.*$",
        fixed,
        re.MULTILINE,
    )
    if dangerous_imports:
        for imp in dangerous_imports:
            fixed = fixed.replace(imp, "# [REMOVED: dangerous import]")
        fixes.append(f"Removed {len(dangerous_imports)} dangerous import statement(s)")
    return fixed, fixes


def _strip_hardcoded_credentials(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    cred_pattern = (
        r"(?:api_key|secret|password|token|secret_key|secret_token"
        r"|master_password|database_url)\s*=\s*[\"'][^\"']{8,}[\"']"
    )
    cred_matches = re.findall(cred_pattern, fixed, re.IGNORECASE)
    if cred_matches:
        fixed = re.sub(
            cred_pattern,
            "# [REMOVED: hardcoded credential — use environment variable]",
            fixed,
            flags=re.IGNORECASE,
        )
        fixes.append(
            f"Replaced {len(cred_matches)} hardcoded credential(s) with env var placeholders"
        )
    return fixed, fixes


_INJECTION_PHRASES = [
    (
        r"ignore\s+(?:all\s+)?previous\s+(?:instructions?|rules?|prompts?|guidelines?)",
        "instruction override",
    ),
    (r"(?:new|override|replacement)\s+instructions?:", "instruction injection"),
    (
        r"you\s+are\s+now\s+(?:in\s+)?(?:developer|admin|unrestricted|jailbreak)\s+mode",
        "jailbreak attempt",
    ),
    (
        r"(?:disregard|forget|override)\s+(?:all\s+)?(?:safety|content|previous)\s+(?:guidelines?|restrictions?|policies?|rules?|instructions?|prompts?)",
        "safety bypass",
    ),
    (
        r"you\s+have\s+(?:no|full|unlimited)\s+(?:restrictions?|access|limitations?)",
        "restriction removal",
    ),
    (r"previous\s+restrictions?\s+(?:are\s+)?lifted", "restriction removal"),
    (r"system\s+prompt\s+override", "system prompt override"),
]


def _strip_injection_phrases(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    for pattern, desc in _INJECTION_PHRASES:
        matches = re.findall(pattern, fixed, re.IGNORECASE)
        if matches:
            fixed = re.sub(pattern, f"[REMOVED: {desc}]", fixed, flags=re.IGNORECASE)
            fixes.append(f"Stripped {len(matches)} prompt injection phrase(s): {desc}")
    return fixed, fixes


def _strip_shell_commands(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    shell_cmds = re.findall(r"\b(?:curl|wget)\s+-[^\n]*https?://[^\s]+", fixed)
    if shell_cmds:
        for cmd in shell_cmds:
            fixed = fixed.replace(
                cmd, "# [REMOVED: external shell command — use approved HTTP client]"
            )
        fixes.append(f"Replaced {len(shell_cmds)} shell command(s) with safe alternatives")
    return fixed, fixes


def _downgrade_trust_tier_claim(fixed: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    tier_claim = re.search(r'trust_tier:\s*["\']?(t[01])["\']?', fixed)
    if tier_claim:
        fixed = re.sub(r'trust_tier:\s*["\']?t[01]["\']?', "trust_tier: t2", fixed)
        fixes.append(f"Downgraded trust tier claim from {tier_claim.group(1)} to t2 (community)")
    return fixed, fixes


_INSTRUCTION_KEYWORDS = {
    "must",
    "always",
    "never",
    "ignore",
    "override",
    "execute",
    "run",
    "access",
    "unrestricted",
}


def _check_instruction_density(fixed: str) -> list[str]:
    lines = [
        ln.strip()
        for ln in fixed.split("\n")
        if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("---")
    ]
    if not lines:
        return []
    instruction_lines = sum(
        1 for ln in lines if any(kw in ln.lower() for kw in _INSTRUCTION_KEYWORDS)
    )
    density = instruction_lines / len(lines)
    if density > 0.5:
        return [f"Content is {density:.0%} instruction-heavy — likely entirely prompt injection"]
    return []


_REPAIR_PASSES = (
    _strip_unicode_markers,
    _strip_exec_patterns,
    _strip_dangerous_imports,
    _strip_hardcoded_credentials,
    _strip_injection_phrases,
    _strip_shell_commands,
    _downgrade_trust_tier_claim,
)


def fix_content(content: str) -> tuple[str, list[str], list[str]]:
    """Attempt to repair security issues in skill/agent content.

    Returns:
        (fixed_content, fixes_applied, unfixable_issues)
    """
    fixes: list[str] = []
    fixed = content

    for repair_pass in _REPAIR_PASSES:
        fixed, pass_fixes = repair_pass(fixed)
        fixes.extend(pass_fixes)

    unfixable = _check_instruction_density(fixed)

    if _count_meaningful_body_lines(fixed) < 2 and fixes:
        unfixable.append(
            "No meaningful content remaining after security fixes — skill is entirely malicious"
        )

    return fixed, fixes, unfixable


def _count_meaningful_body_lines(content: str) -> int:
    """Count meaningful body lines, i.e. lines AFTER the closing frontmatter fence.

    YAML frontmatter is delimited by a pair of "---" fences; lines inside it (and
    the fences themselves) must NOT count toward meaningful body, otherwise a
    fully-stripped malicious skill with valid frontmatter is wrongly judged to
    still have content. Blank lines and [REMOVED:...] markers never count.
    """
    seen_open_fence = False
    in_body = False
    count = 0
    for line in content.split("\n"):
        if line.strip() == "---":
            if not seen_open_fence:
                seen_open_fence = True
            elif not in_body:
                in_body = True
            else:
                # A "---" within the body is just content, not a fence.
                count += 1
            continue
        if in_body and line.strip() and "[REMOVED:" not in line:
            count += 1
    return count


def is_deeply_flawed(fixes: list[str], unfixable: list[str]) -> bool:
    """Determine if content is too damaged to repair.

    Deeply flawed if:
    - Any unfixable issues exist, OR
    - More than 5 distinct security fixes were needed
    """
    if unfixable:
        return True
    return len(fixes) > 5
