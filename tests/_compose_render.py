"""Render a Compose file's environment the way `docker compose` does.

Shared by the cloud-stack tests. Interpolation is lazy and outermost-first, as
Compose's is: the default in `${A:-${B:?msg}}` is evaluated only when A is
unset. `tests/test_llm_gateway_compose.py` cross-checks this against the real
`docker compose config` wherever the CLI is installed, so it cannot quietly
drift from the renderer it stands in for.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class MissingRequired(Exception):
    """A `${VAR:?message}` with VAR unset -- what `docker compose` refuses on."""


_EXPR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])(.*))?\Z", re.S)


def _interpolate(value: str, env: dict[str, str]) -> str:
    """Compose's `${VAR}`, `${VAR:-default}` and `${VAR:?message}`, nested.

    Outermost first and *lazily*, as Compose does: the default in
    `${A:-${B:?msg}}` is only evaluated when A is unset, so an external
    gateway key makes the bundled master key optional instead of raising.
    Innermost-first would get that exact case wrong.
    """
    out: list[str] = []
    i = 0
    while i < len(value):
        if value.startswith("$$", i):
            out.append("$")
            i += 2
        elif value.startswith("${", i):
            expr, i = _read_braced(value, i + 2)
            out.append(_evaluate(expr, env))
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _read_braced(text: str, start: int) -> tuple[str, int]:
    depth, j = 1, start
    while j < len(text):
        if text.startswith("${", j):
            depth, j = depth + 1, j + 2
            continue
        if text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j], j + 1
        j += 1
    raise ValueError(f"unterminated interpolation in {text!r}")


def _evaluate(expr: str, env: dict[str, str]) -> str:
    match = _EXPR.match(expr)
    assert match, f"interpolation form this test does not model: ${{{expr}}}"
    name, op, arg = match.group(1), match.group(2), match.group(3) or ""
    current = env.get(name)
    unset = current is None or (op is not None and op.startswith(":") and current == "")
    if op in (":-", "-"):
        return _interpolate(arg, env) if unset else str(current)
    if op in (":?", "?"):
        if unset:
            raise MissingRequired(f"{name}: {arg}")
        return str(current)
    return "" if current is None else current


def _environment(service: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    raw = service.get("environment") or {}
    pairs = (
        ((item.partition("=")[0], item.partition("=")[2]) for item in raw)
        if isinstance(raw, list)
        else ((k, "" if v is None else str(v)) for k, v in raw.items())
    )
    return {key: _interpolate(val, env) for key, val in pairs}


def _render(path: Path, env: dict[str, str]) -> dict[str, dict[str, str]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: _environment(svc, env) for name, svc in doc["services"].items()}
