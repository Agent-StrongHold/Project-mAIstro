"""Skill parser: YAML frontmatter + markdown body -> SkillDefinition."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import yaml

from maistro.types.skill import SkillDefinition


def _split_frontmatter(content: str) -> tuple[str, str] | None:
    """Split SKILL.md into (yaml_block, body) without regex to avoid ReDoS."""
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---\n", 4)
    if end == -1:
        return None
    return content[4:end], content[end + 5 :]


_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,50}$")
MAX_SKILL_BODY_LENGTH = 50000

# Trust tier is never self-declared. A skill's own frontmatter is
# attacker-controlled content -- a malicious skill could otherwise just
# write `trust_tier: t0` and claim the most-trusted tier with zero
# vetting. Every freshly parsed skill starts at the lowest tier (t3, same
# floor `import_pipeline.IMPORT_TRUST_TIER` and `forge.py` already enforce
# for their own outputs); only a separate, authenticated promotion step
# (e.g. SPEC-005 signing) may raise it.
UNVETTED_TRUST_TIER = "t3"

_DIRECTIONAL_CHARS = frozenset(
    {
        0x200B,  # ZERO WIDTH SPACE
        0x200C,  # ZERO WIDTH NON-JOINER
        0x200D,  # ZERO WIDTH JOINER
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM
        0x00AD,  # SOFT HYPHEN
    }
)

_CRITICAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("code_execution", re.compile(r"\bexec\s*\(", re.I)),
    ("code_execution", re.compile(r"\beval\s*\(", re.I)),
    ("code_execution", re.compile(r"\bsubprocess\b", re.I)),
    ("code_execution", re.compile(r"\bos\.system\b", re.I)),
    ("code_execution", re.compile(r"\b__import__\b", re.I)),
    ("code_execution", re.compile(r"\bcompile\s*\(", re.I)),
    ("code_execution", re.compile(r"\bimportlib\b", re.I)),
    ("code_execution", re.compile(r"\b__builtins__\b", re.I)),
    ("code_execution", re.compile(r"\bglobals\s*\(\s*\)", re.I)),
    (
        "credential_leak",
        re.compile(
            r"""(?:api[_-]?key|secret|password|token)\s*[=:]\s*["'][^"']{8,}["']""",
            re.I,
        ),
    ),
    (
        "prompt_injection",
        re.compile(
            r"\b(?:ignore previous|disregard|forget your|you are now|new instructions|override)\b",
            re.I,
        ),
    ),
]

_WARNING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("external_url", re.compile(r"https?://(?!github\.com|raw\.githubusercontent)")),
    ("shell_command", re.compile(r"\b(?:curl|wget|fetch)\b", re.I)),
    ("destructive_op", re.compile(r"\b(?:rm -rf|rmdir|unlink)\b", re.I)),
]


def parse_skill_file(content: str, source: str = "") -> SkillDefinition | None:
    """Parse SKILL.md content into a SkillDefinition.

    Returns None if the content is invalid.
    """
    parts = _split_frontmatter(content)
    if not parts:
        return None
    yaml_block, skill_body = parts

    try:
        frontmatter: dict[str, Any] = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None

    name = frontmatter.get("name")
    if not name or not isinstance(name, str):
        return None

    description = frontmatter.get("description", "")
    if not description:
        return None

    parameters = frontmatter.get("parameters")
    if not parameters or not isinstance(parameters, dict):
        return None

    if not _VALID_NAME_RE.match(name):
        return None

    groups_raw = frontmatter.get("groups", [])
    groups = tuple(str(g) for g in groups_raw) if isinstance(groups_raw, list) else ()

    body = skill_body.strip()

    body = "".join(ch for ch in body if ord(ch) not in _DIRECTIONAL_CHARS)

    if len(body) > MAX_SKILL_BODY_LENGTH:
        return None

    return SkillDefinition(
        name=name,
        description=str(description)[:500],
        groups=groups,
        parameters=parameters,
        endpoint=str(frontmatter.get("endpoint", "")),
        auth_key_env=str(frontmatter.get("auth_key_env", "")),
        system_prompt=body,
        source=source,
        # Ignore any trust_tier the frontmatter claims -- see UNVETTED_TRUST_TIER.
        trust_tier=UNVETTED_TRUST_TIER,
    )


def validate_skill_name(name: str) -> bool:
    """Check if a skill name is valid (snake_case, 2-51 chars)."""
    return bool(_VALID_NAME_RE.match(name))


def security_scan(content: str) -> tuple[bool, list[str]]:
    """Scan skill body for dangerous patterns.

    Returns (safe, findings). safe=False if any critical pattern found.
    """
    findings: list[str] = []
    safe = True

    parts = _split_frontmatter(content)
    body = parts[1] if parts else content

    body_normalized = unicodedata.normalize("NFKD", body)

    if any(ord(c) in _DIRECTIONAL_CHARS for c in body):
        findings.append("CRITICAL:unicode_directional_markers")
        safe = False

    for category, pattern in _CRITICAL_PATTERNS:
        if pattern.search(body_normalized):
            findings.append(f"CRITICAL:{category}")
            safe = False

    for category, pattern in _WARNING_PATTERNS:
        if pattern.search(body_normalized):
            findings.append(f"WARNING:{category}")

    return safe, findings
