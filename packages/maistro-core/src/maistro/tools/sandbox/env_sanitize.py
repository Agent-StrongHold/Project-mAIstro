"""Environment variable sanitization for sandbox containers.

Uses an ALLOWLIST approach — only explicitly approved env vars pass through.
This is the inverse of the original blocklist approach, which could miss
secrets in non-standard formats.
"""

from __future__ import annotations

import re

# MAJ-07: Allowlist of env var names safe to pass into sandbox containers.
# Only these prefixes/names are permitted; everything else is blocked.
ALLOWED_PREFIXES = (
    "LANG",  # Locale (LANG, LANGUAGE)
    "LC_",  # Locale categories
    "TZ",  # Timezone
    "TERM",  # Terminal type
    "PATH",  # Executable search path
    "PYTHONPATH",  # Python module path
    "NODE_PATH",  # Node module path
    "PYTHONDONTWRITEBYTECODE",
    "PIP_NO_CACHE_DIR",
    "NPM_CONFIG_",
    "VIRTUAL_ENV",
    "CONDA_",
    "CARGO_",
    "GOPATH",
    "RUSTUP_",
)

ALLOWED_EXACT = frozenset(
    {
        "PATH",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TERM",
        "SHELL",
        "EDITOR",
        "PYTHONDONTWRITEBYTECODE",
        "PIP_NO_CACHE_DIR",
        "VIRTUAL_ENV",
        "GOPATH",
        "CI",
        "DEBIAN_FRONTEND",
    }
)

# Legacy blocklist patterns kept for defense-in-depth on value heuristics
_SECRET_PATTERN = re.compile(
    r"^(sk-[a-zA-Z0-9]{20,}|"  # OpenAI-style keys
    r"ghp_[a-zA-Z0-9]{36}|"  # GitHub PATs
    r"ghs_[a-zA-Z0-9]{36}|"  # GitHub App tokens
    r"Bearer\s+[a-zA-Z0-9._-]{20,}|"  # Bearer tokens
    r"[a-fA-F0-9]{64}|"  # 256-bit hex keys (case-insensitive — hex secrets aren't always lowercase)
    r"eyJ[a-zA-Z0-9._-]{20,})$"  # JWTs
)


def is_allowed_name(name: str) -> bool:
    """Check if an env var name is in the allowlist."""
    upper = name.upper()
    if upper in ALLOWED_EXACT:
        return True
    return any(upper.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def looks_like_secret(value: str) -> bool:
    """Heuristic check if a value looks like a secret/token."""
    return bool(_SECRET_PATTERN.match(value.strip()))


def sanitize_env(env: dict[str, str]) -> dict[str, str]:
    """Filter environment variables using allowlist approach.

    Only explicitly allowed env var names pass through, and values
    are still checked against secret patterns as defense-in-depth.
    """
    return {k: v for k, v in env.items() if is_allowed_name(k) and not looks_like_secret(v)}


# Keep legacy blocklist functions available for other uses
BLOCKED_PREFIXES = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "ANTHROPIC_",
    "OPENAI_",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "NPM_TOKEN",
    "PYPI_TOKEN",
    "DOCKER_",
    "KUBECONFIG",
    "SSH_",
    "PGP_",
    "GPG_",
    "LANGFUSE_",
    "LITELLM_",
    "DB_PASSWORD",
    "DATABASE_URL",
    "REDIS_URL",
    "MAISTRO_API",
)

BLOCKED_EXACT = frozenset({"HOME", "USER", "LOGNAME", "HOSTNAME", "MAIL"})


def is_blocked_name(name: str) -> bool:
    """Check if an env var name should be blocked (legacy blocklist)."""
    upper = name.upper()
    if upper in BLOCKED_EXACT:
        return True
    return any(upper.startswith(prefix) for prefix in BLOCKED_PREFIXES)
