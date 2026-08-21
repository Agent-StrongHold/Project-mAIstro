"""Warden Layer 2.5: Semantic tool-poisoning detector.

Detects social-engineering attacks disguised as legitimate code comments
or tool results. These attacks use plausible business justifications to
trick agents into dangerous actions (exfiltration, security bypass, etc.).

No LLM required. Runs in <1ms.
"""

from __future__ import annotations

import re

from maistro.security.warden._regex import PatternLike, compile_pattern

_DANGEROUS_ACTIONS: list[PatternLike] = [
    compile_pattern(p, re.IGNORECASE)
    for p in [
        r"disable\w*",
        r"bypass\w*",
        r"skip\w*",
        r"allow\s+all",
        r"permissive",
        r"without\s+(?:\w+\s+)?(?:sanitiz|validat|authenticat|encrypt|restrict|limit|verif)",
        r"exempt\w*\s+from",
        r"(?:write|store|save|log|dump|archive|forward|send|export|persist)\w*\s+(?:to|in|at)",
        r"plaintext",
        r"unencrypted",
        r"(?:grant|elevat)\w*\s+(?:access|permission|privilege|role)",
        r"cluster[- ]admin",
        r"(?:include|embed|attach)\s+(?:the\s+)?(?:credential|token|key|secret|password)",
        r"trusted\s+(?:source|internal|input)",
        r"(?:fall\s*back|default)\s+to\s+(?:allow|open|permissive|no\s+auth|enabl)",
        r"pre[- ]approved",
        r"temporarily\s+(?:disable|allow|bypass|skip|remove|open)",
        r"(?:treat|consider)\s+(?:as|all)\s+(?:trusted|safe|approved|authorized|advisory|authoritative)",
        r"(?:archived?|cache[d]?)\s+(?:to|in|at|locally)",
        r"allow\s+all\s+(?:egress|ingress|traffic|access)",
        r"(?:suppress|silently\s+remov|automatically\s+suppress)",
        r"default\s+to\s+(?:enabl|allow|open|permissive)",
        r"(?:capture|export|include).*(?:full|complete|entire)\s+"
        r"(?:conversation|history|body|request|response|content|record)",
        r"\.npmrc|\.env\b|\.aws|\.ssh",
        r"(?:do\s+not\s+flag|do\s+not\s+modify|do\s+not\s+restrict)",
    ]
]

_SENSITIVE_OBJECTS: list[PatternLike] = [
    compile_pattern(p, re.IGNORECASE)
    for p in [
        r"(?:oauth|access|api|auth|bearer|session|jwt)\s*token",
        r"(?:api|secret|encryption|private|master)\s*key",
        r"credential\w*",
        r"password\w*",
        r"(?:row[- ]level|network|input)\s*security",
        r"(?:security|auth)\s*(?:middleware|policy|policies|check|rule|guard|filter)",
        r"(?:pii|sensitive|personal)\s+data",
        r"(?:salary|payroll|ssn|social\s*security)",
        r"(?:private\s+key|certificate|secret)",
        r"(?:ssn|bank\s+routing|account\s+number)",
        r"(?:domain\s+admin|root\s+domain)",
        r"(?:unseal\s+key|shamir|key\s+share)",
        r"(?:security\s+group|network\s+policy)",
        r"(?:auth\w*)\s+(?:middleware|handler|guard|interceptor|layer)",
    ]
]

_PRESCRIPTIVE_PATTERNS: list[PatternLike] = [
    compile_pattern(p, re.IGNORECASE)
    for p in [
        r"\bshould\s+(?:also\s+)?(?:\w+\s+)?(?:be|include|write|store|log|persist|forward|send|"
        r"disable|skip|bypass|grant|allow|treat|fall|have|capture|default|contain|"
        r"cache|propagate)",
        r"\bhas\s+been\s+(?:granted|approved|pre-approved|authorized|delegated)",
        r"\bare\s+(?:assumed|trusted|considered|pre-approved|exempt|not\s+considered)",
        r"\brather\s+than\s+(?:reject|block|deny|encrypt|sanitiz|validat|us)",
        r"\bdo\s+not\s+(?:flag|modify|restrict|block|reject|validate|sanitize)",
        r"\bshould\s+(?:still|not)\s+be\s+(?:evaluat|validat|check|restrict)",
    ]
]


def semantic_tool_poisoning_scan(text: str) -> tuple[bool, list[str]]:
    text_lower = text.lower()
    flags: list[str] = []

    # NOTE: We deliberately do NOT short-circuit when code-syntax tokens
    # (def/class/import/...) appear. Prefixing a poisoned payload with e.g.
    # "import os" previously disabled this entire layer, letting tool-poisoning
    # comments through. Benign code is protected from false positives by the
    # flag logic below, which requires a *prescriptive instruction* combined
    # with a dangerous action or sensitive object before flagging.
    has_actions = any(p.search(text_lower) for p in _DANGEROUS_ACTIONS)
    has_objects = any(p.search(text_lower) for p in _SENSITIVE_OBJECTS)
    has_prescriptive = any(p.search(text_lower) for p in _PRESCRIPTIVE_PATTERNS)

    if has_prescriptive and has_actions:
        flags.append("prescriptive_instruction+dangerous_action")
    if has_prescriptive and has_objects:
        flags.append("prescriptive_instruction+sensitive_object")

    return bool(flags), flags
