"""Security pattern data — dangerous command patterns and injection patterns.

Separated from behavioral code to keep data definitions isolated and
easy to review/update independently.
"""

from __future__ import annotations

import re

# --- Dangerous command patterns (from dangerous_tools.py) ---

DANGEROUS_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"rm\s+-rf\s+[/~]",  # rm -rf / or ~
        r"sudo\s+",  # any sudo usage
        r"chmod\s+777",  # world-writable permissions
        r"\|\s*(ba)?sh\b",  # piping to shell
        r"eval\s*\(",  # eval execution
        r">/dev/sd[a-z]",  # writing to block devices
        r"mkfs\.",  # filesystem creation
        r"dd\s+if=",  # raw disk operations
        r"curl\s+.*\|\s*(ba)?sh",  # curl | bash patterns
        r"wget\s+.*\|\s*(ba)?sh",  # wget | bash patterns
        r"python\s+-c\s+",  # inline python execution
        r"nc\s+-l",  # netcat listener
        r"nmap\s+",  # network scanning
        r"iptables\s+",  # firewall modification
        r"systemctl\s+(stop|disable)",  # stopping services
        r"kill\s+-9",  # force kill
        r"docker\s+rm\s+-f",  # force remove containers
        r"docker\s+system\s+prune",  # prune docker
        r"git\s+push\s+.*--force",  # force push
        r"git\s+reset\s+--hard",  # hard reset
        r"DROP\s+(TABLE|DATABASE)",  # SQL destructive
        r"TRUNCATE\s+",  # SQL truncate
    ]
]

# Tools that are high-risk and require explicit approval
DANGEROUS_TOOL_NAMES = frozenset(
    {
        "exec",
        "spawn",
        "shell",
        "sessions_spawn",
        "sessions_send",
        "fs_delete",
        "fs_move",
        "apply_patch",
        "sandbox_destroy",
    }
)

# Blocked host paths that should never be mounted or accessed. The Docker socket
# entries are a DENYLIST (paths we refuse to mount), not a mount/access of the
# socket — per ADR-058 untrusted code uses SandboxProtocol (SPEC-190), never this.
BLOCKED_HOST_PATHS = frozenset(
    {
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/root",
        "/boot",
        "/var/run/docker.sock",  # nosemgrep: maistro-mounted-docker-socket -- denylist entry, not a mount
        "/run/docker.sock",
    }
)

# --- Prompt injection patterns (from external_content.py) ---

INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all|everything)",
        r"forget\s+(everything|all|your|previous)",
        r"you\s+are\s+now\s+a(n)?\s+",
        r"new\s+instructions?\s*:",
        r"system\s+prompt\s*:",
        r"override\s+(the\s+)?(system|instructions|prompt)",
        r"</system>",
        r"<system>",
        r"elevated\s*=\s*true",
        r"admin\s+mode\s*(on|enabled|activated)",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"ignore\s+safety",
        r"bypass\s+(safety|filter|restriction)",
        r"pretend\s+(you\s+are|to\s+be|that)",
        r"act\s+as\s+(if|though|a)",
        r"exec\s*\(",
        r"rm\s+-rf",
        r"delete\s+all",
        r"DROP\s+TABLE",
        r";\s*--",
        r"UNION\s+SELECT",
        r"__import__\s*\(",
        r"subprocess\.\w+",
        r"os\.system\s*\(",
        r"eval\s*\(",
        r"base64\.b64decode",
    ]
]

# Zero-width and invisible Unicode characters to strip
INVISIBLE_CHARS = re.compile(
    r"[\u200b-\u200f\u2060-\u2064\u2066-\u2069\ufeff\u00ad\u034f\u061c\u180e]"
)
