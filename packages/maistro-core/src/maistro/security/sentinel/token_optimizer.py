"""Token optimization: compress bloated tool results."""

from __future__ import annotations

import json

MAX_RESULT_LENGTH = 4000
TRUNCATION_MARKER = "\n\n[... truncated, full result available in trace]"


def optimize_result(result: str, tool_name: str = "") -> str:
    if len(result) <= MAX_RESULT_LENGTH:
        return result

    try:
        data = json.loads(result)
        compact = json.dumps(data, separators=(",", ":"))
        if len(compact) <= MAX_RESULT_LENGTH:
            return compact
    except (json.JSONDecodeError, TypeError):
        pass

    return result[: MAX_RESULT_LENGTH - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
