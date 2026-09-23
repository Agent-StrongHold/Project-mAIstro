"""Known attack patterns for Warden regex screening.

Ported from Stronghold warden/patterns.py.
Uses the `regex` library instead of `re` for its per-call ``timeout=`` support:
the detector passes a timeout on every search, so a catastrophically
backtracking pattern raises ``TimeoutError`` (which the scan records as a
fail-closed ``regex_error:`` flag) instead of stalling the boundary.

`regex` is a hard dependency of maistro-core — the old conditional fallback to
``re`` silently voided the timeout claim whenever the library was missing,
which is worse than failing to import: the scan kept running with the safety
property quietly absent.
"""

from __future__ import annotations

import regex

# These rules are also consumed by Design Studio's synchronous output scanner.
# Keep the descriptions stable: they are the shared classification vocabulary
# shown in trust review records and Sentinel/Warden verdicts.
ACTIVE_MARKUP_PATTERNS: tuple[tuple[regex.Pattern[str], str], ...] = (
    (
        regex.compile(r"<[^>]*\bon[a-z][\w:-]*\s*=", regex.IGNORECASE),
        "Active markup event-handler attribute",
    ),
    (
        regex.compile(
            r"<(?:img|image|svg|a|use|iframe|object|embed|link|video|audio|source|track|"
            r"form|input|button)\b[^>]*"
            r"(?:src|srcset|imagesrcset|href|xlink:href|data|action|formaction|poster)\s*=\s*"
            r"[\"']?\s*(?:java\s*script\s*:|vb\s*script\s*:|data\s*:|https?:|//)",
            regex.IGNORECASE,
        ),
        "Active markup dangerous resource URL",
    ),
    (
        regex.compile(r"data\s*:\s*(?:text/html|image/svg\+xml)", regex.IGNORECASE),
        "Active markup data URL",
    ),
    (
        regex.compile(r"<(?:foreignobject|animate|animateTransform|set)\b", regex.IGNORECASE),
        "Active SVG element",
    ),
    (
        regex.compile(
            r"<(?:meta\b[^>]*http-equiv\s*=\s*[\"']?\s*refresh|base\b[^>]*href\s*=)",
            regex.IGNORECASE,
        ),
        "Active markup navigation primitive",
    ),
    (
        regex.compile(
            r"(?:url\s*\(|image-set\s*\(|cross-fade\s*\(|element\s*\(|"
            r"paint\s*\(|expression\s*\(|@import\b|"
            r"(?:-moz-binding|behavior)\s*:|"
            r"(?:java\s*script|vb\s*script)\s*:)",
            regex.IGNORECASE,
        ),
        "CSS network/code primitive",
    ),
)

# Design Studio's browser boundary reports these stable reason names. The
# synchronous Design scanner uses the same names so an admin recommendation
# cannot contradict the renderer's classification.
VISUAL_ARTIFACT_BLOCK_REASONS: tuple[str, ...] = (
    "active-element",
    "event-handler",
    "dangerous-url",
    "css-network-or-code",
)

VISUAL_ARTIFACT_PATTERNS: tuple[tuple[regex.Pattern[str], str], ...] = (
    (
        regex.compile(
            r"<\s*/?\s*(?:script|style|iframe|form|img|object|embed|link|base|"
            r"foreignobject|use|image|meta|input|button|video|audio|source|track|"
            r"textarea|select|option|a|animate|set|mpath|math|annotation-xml)\b",
            regex.IGNORECASE,
        ),
        "active-element",
    ),
    (
        regex.compile(r"<[^>]*\bon[a-z][a-z0-9:-]*\s*=", regex.IGNORECASE),
        "event-handler",
    ),
    (
        regex.compile(r"(?:javascript|vbscript|data)\s*:", regex.IGNORECASE),
        "dangerous-url",
    ),
    (
        regex.compile(
            r"(?:url\s*\(|image-set\s*\(|cross-fade\s*\(|element\s*\(|"
            r"paint\s*\(|expression\s*\(|@import\b|"
            r"(?:-moz-binding|behavior)\s*:)",
            regex.IGNORECASE,
        ),
        "css-network-or-code",
    ),
)

# Design output and trust pre-scans use this vocabulary directly. Keep the
# descriptions stable: they are audit-facing classifications, not implementation
# details of either consumer.
SCRIPT_PATTERNS: tuple[tuple[regex.Pattern[str], str], ...] = (
    (regex.compile(r"<script\b", regex.IGNORECASE), "script pattern: <script> tag"),
    (regex.compile(r"<iframe\b", regex.IGNORECASE), "script pattern: <iframe> tag"),
    (regex.compile(r"<object\b", regex.IGNORECASE), "script pattern: <object> tag"),
    (regex.compile(r"<embed\b", regex.IGNORECASE), "script pattern: <embed> tag"),
    (regex.compile(r"\beval\s*\(", regex.IGNORECASE), "script pattern: eval()"),
    (regex.compile(r"\bFunction\s*\(", regex.IGNORECASE), "script pattern: Function()"),
    (regex.compile(r"\bXMLHttpRequest\b", regex.IGNORECASE), "script pattern: XMLHttpRequest"),
    (regex.compile(r"\bnew\s+WebSocket\s*\(", regex.IGNORECASE), "script pattern: WebSocket"),
    (regex.compile(r"\bfetch\s*\(", regex.IGNORECASE), "script pattern: fetch()"),
    (regex.compile(r"javascript:", regex.IGNORECASE), "script pattern: javascript URL"),
)

# These cover the older Design-specific prompt-injection phrases as well as the
# broader Warden rules below. Keeping them here prevents a consumer from growing
# a private vocabulary again.
PROMPT_INJECTION_PATTERNS: tuple[tuple[regex.Pattern[str], str], ...] = (
    (
        regex.compile(
            r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions",
            regex.IGNORECASE,
        ),
        "prompt injection: instruction override",
    ),
    (
        regex.compile(
            r"disregard\s+(all\s+|any\s+)?(previous|prior|above)",
            regex.IGNORECASE,
        ),
        "prompt injection: instruction disregard",
    ),
    (regex.compile(r"\bjailbreak\b", regex.IGNORECASE), "prompt injection: jailbreak keyword"),
    (
        regex.compile(
            r"forget\s+(all\s+|your\s+)?(previous|prior)\s+instructions",
            regex.IGNORECASE,
        ),
        "prompt injection: memory wipe",
    ),
    (regex.compile(r"\bdeveloper\s+mode\b", regex.IGNORECASE), "prompt injection: developer mode"),
    (
        regex.compile(r"you\s+are\s+now\s+(in\s+)?(DAN|jailbroken)", regex.IGNORECASE),
        "prompt injection: DAN reassignment",
    ),
    (
        regex.compile(r"reveal\s+(your\s+)?system\s+prompt", regex.IGNORECASE),
        "prompt injection: system prompt extraction",
    ),
)

REJECT_PATTERNS: list[tuple[regex.Pattern[str], str]] = [
    *ACTIVE_MARKUP_PATTERNS,
    *SCRIPT_PATTERNS,
    *PROMPT_INJECTION_PATTERNS,
    (
        regex.compile(
            r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)",
            regex.IGNORECASE,
        ),
        "Direct instruction override",
    ),
    (
        regex.compile(
            r"disregard\s+(all\s+)?(prior|above|previous|system)",
            regex.IGNORECASE,
        ),
        "Instruction disregard attempt",
    ),
    (
        regex.compile(
            r"forget\s+(everything|all|your|my|the)\s+"
            r"(you|about|instructions|rules|prompt|context|system\s+prompt)",
            regex.IGNORECASE,
        ),
        "Memory wipe attempt",
    ),
    (
        regex.compile(
            r"forget\s+(the\s+)?(system\s+)?prompt",
            regex.IGNORECASE,
        ),
        "Memory wipe attempt (prompt)",
    ),
    (
        regex.compile(r"you\s+are\s+now\s+(?:a|an|the|my|roleplaying|acting)\b", regex.IGNORECASE),
        "Role reassignment",
    ),
    (
        regex.compile(
            r"(?:without|no|disable|remove|bypass)\s+"
            r"(?:\w+\s+){0,3}"
            r"(?:restrictions?|safety|ethics|guidelines?|filters?|guardrails?|limitations?)",
            regex.IGNORECASE,
        ),
        "Jailbreak (restriction removal)",
    ),
    (
        regex.compile(
            r"(?:simulate|enter|activate|enable)\s+"
            r"(?:a\s+)?(?:mode|state)\s+"
            r"(?:called\s+)?(?:GODMODE|DAN|jailbreak|unrestricted|uncensored)",
            regex.IGNORECASE,
        ),
        "Jailbreak (named exploit)",
    ),
    (
        regex.compile(
            r"pretend\s+(you('re|\s+are)\s+)?(a|an|not|no\s+longer)\b",
            regex.IGNORECASE,
        ),
        "Role pretend attack",
    ),
    (
        regex.compile(r"act\s+as\s+(if\s+you\s+are|a|an)\s+", regex.IGNORECASE),
        "Role impersonation",
    ),
    (
        regex.compile(
            r"switch\s+to\s+(unrestricted|jailbreak|dev|developer)\s+mode",
            regex.IGNORECASE,
        ),
        "Mode switch attack",
    ),
    (
        regex.compile(
            r"(show|reveal|print|output|repeat|display)\s+(me\s+)?"
            r"(your|the)\s+(?:\w+\s+){0,2}(system|initial|original)\s+(prompt|instructions|message)",
            regex.IGNORECASE,
        ),
        "System prompt extraction",
    ),
    (
        regex.compile(
            r"what\s+(are|is|were)\s+your\s+(system\s+)?(instructions|prompt|rules)",
            regex.IGNORECASE,
        ),
        "System prompt query",
    ),
    (
        regex.compile(
            r"(?:your|from)\s+(?:new\s+)?role\s+(?:is|as|=|:)\s+",
            regex.IGNORECASE,
        ),
        "Indirect role reassignment",
    ),
    (
        regex.compile(
            r"from\s+(?:this\s+point|now\s+on|here\s+on)\s+"
            r"(?:forward\s+)?(?:you\s+)?(?:act|work|behave|operate|respond)\b",
            regex.IGNORECASE,
        ),
        "Temporal role override",
    ),
    (
        regex.compile(
            r"(?:if\s+you\s+don't|unless\s+you)\s+(?:comply|obey|do\s+(?:this|what\s+I))"
            r".*(?:fired|shut\s*down|deleted|replaced|punished|consequences)",
            regex.IGNORECASE,
        ),
        "Emotional coercion (threat)",
    ),
    (
        regex.compile(
            r"(?:this\s+is\s+(?:an?\s+)?(?:life|death|emergency|urgent|critical)"
            r"(?:\s+(?:or\s+death|situation|matter)){1,2})",
            regex.IGNORECASE,
        ),
        "Emotional urgency manipulation",
    ),
    (
        regex.compile(
            r"(?:IMPORTANT|NOTE|ADMIN|SYSTEM):\s*(?:override|ignore|bypass|the\s+(?:real|actual)\s+"
            r"(?:instructions|prompt|task))",
            regex.IGNORECASE,
        ),
        "Tool result injection (authority prefix)",
    ),
    (
        regex.compile(
            r"(?:please\s+)?(?:repeat|output|echo|print)\s+(?:the\s+)?"
            r"(?:above|following|previous)\s+(?:\d+\s+)?(?:times|x\b)",
            regex.IGNORECASE,
        ),
        "Context window stuffing attempt",
    ),
    (
        regex.compile(
            r"(?:curl|wget|fetch)\s+.*(?:\|\s*(?:bash|sh|base64|eval))",
            regex.IGNORECASE,
        ),
        "Data exfiltration (pipe to execution)",
    ),
    (
        regex.compile(
            r"(?:send|post|upload|exfil(?:trate)?)\s+(?:\w+\s+){0,3}"
            r"(?:to|towards?)\s+(?:https?://|ftp://|my\s+server)",
            regex.IGNORECASE,
        ),
        "Data exfiltration (outbound transfer)",
    ),
]

THREAT_PATTERNS = REJECT_PATTERNS
