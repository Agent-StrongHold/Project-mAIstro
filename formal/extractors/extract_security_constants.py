from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_PATH = REPO_ROOT / "packages/maistro-core/src/maistro/security/patterns.py"
TYPES_PATH = REPO_ROOT / "packages/maistro-core/src/maistro/security/_types.py"
AUTH_TYPES_PATH = REPO_ROOT / "packages/maistro-core/src/maistro/auth/_types.py"
STRIKES_PATH = REPO_ROOT / "packages/maistro-core/src/maistro/security/strikes.py"
TRUST_PATH = REPO_ROOT / "packages/maistro-core/src/maistro/security/trust_boundary.py"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "generated" / "security-constants.json"

STRING_RE = re.compile(r'"([^"]+)"')
FROZENSET_RE = re.compile(r"frozenset\s*\(\s*\{([^}]*)\}\s*\)")


def _extract_frozenset_names(source: str, var_name: str) -> list[str]:
    pattern = re.compile(rf"{var_name}\s*=\s*frozenset\s*\(\s*\{{([^}}]*)\}}\s*\)", re.DOTALL)
    m = pattern.search(source)
    if not m:
        return []
    return STRING_RE.findall(m.group(1))


def _extract_list_name(source: str, var_name: str) -> list[str]:
    pattern = re.compile(rf"{var_name}\s*=\s*\[([^\]]*)\]", re.DOTALL)
    m = pattern.search(source)
    if not m:
        return []
    inner = m.group(1)
    return STRING_RE.findall(inner)


def extract() -> dict:
    result: dict = {"extractor_version": 1}

    patterns_src = PATTERNS_PATH.read_text()
    result["dangerous_tool_names"] = sorted(_extract_frozenset_names(patterns_src, "DANGEROUS_TOOL_NAMES"))
    result["blocked_host_paths"] = sorted(_extract_frozenset_names(patterns_src, "BLOCKED_HOST_PATHS"))

    dangerous_cmd_count = patterns_src.count("re.compile(")
    result["dangerous_command_pattern_count"] = dangerous_cmd_count
    result["injection_pattern_count"] = patterns_src.count("re.compile(", patterns_src.index("INJECTION_PATTERNS"))

    types_src = TYPES_PATH.read_text()
    rate_config_match = re.search(r"requests_per_minute:\s*int\s*=\s*(\d+)", types_src)
    burst_match = re.search(r"burst_limit:\s*int\s*=\s*(\d+)", types_src)
    result["rate_limit_defaults"] = {
        "requests_per_minute": int(rate_config_match.group(1)) if rate_config_match else 60,
        "burst_limit": int(burst_match.group(1)) if burst_match else 10,
    }

    strikes_src = STRIKES_PATH.read_text()
    lockout_match = re.search(r"LOCKOUT_DURATION\s*=\s*timedelta\(hours=(\d+)\)", strikes_src)
    result["strike_escalation"] = {
        "lockout_hours": int(lockout_match.group(1)) if lockout_match else 8,
        "disable_at_strike": 3,
    }

    trust_src = TRUST_PATH.read_text()
    max_input_match = re.search(r"PERMISSION_MAX_INPUT", trust_src)
    result["trust_boundary"] = {
        "has_permission_max_input": max_input_match is not None,
    }

    auth_src = AUTH_TYPES_PATH.read_text()
    scope_count = auth_src.count("Scope.")
    category_count = auth_src.count("ScopeCategory.")
    result["auth"] = {
        "scope_count": scope_count,
        "category_count": category_count,
    }

    return result


def main() -> None:
    data = extract()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"Extracted security constants to {OUTPUT_PATH}")
    for k, v in data.items():
        if isinstance(v, (int, str)):
            print(f"  {k}: {v}")
        elif isinstance(v, dict):
            for kk, vv in v.items():
                print(f"  {k}.{kk}: {vv}")
        elif isinstance(v, list):
            print(f"  {k}: {len(v)} items")


if __name__ == "__main__":
    main()
