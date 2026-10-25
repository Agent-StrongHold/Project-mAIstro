#!/usr/bin/env python3
"""Reconcile a built image's installed Python distributions against uv.lock.

Issue #348: the scans must audit the same dependency set the image ships.
The Dockerfiles install from `uv export --locked` + `--require-hashes`, so the
shipped set IS the locked set by construction — this gate proves it from the
outside, on the built image, by dumping every installed distribution from the
image's own interpreter and comparing it, name==version for name==version,
against the export of the same lock the image was built from.

Expected side: the `uv export --locked ...` invocation the Dockerfile itself
uses, piped in or passed as a file. Workspace members are excluded from the
export (`--no-emit-workspace`) but ARE installed (non-editable, real
versions), so pass each member pin explicitly:

    --member maistro-core==0.9.0 --member maistro-server==0.9.0

Actual side: `docker run --rm --entrypoint <image-python> <image>`, dumping
`name==version` for every distribution importlib.metadata can see — plus one
`@image-env@` line carrying the interpreter's PEP 508 marker environment
(`python_full_version`, `sys_platform`, ...), so marker-conditional pins can
be judged against the environment they were installed for.

Any difference — a package in the image the lock does not name, or a locked
pin the image does not carry — is a red exit with the diff on stdout.

Marker-conditional pins (issue #93 repair round)
------------------------------------------------
`uv export` writes one line per locked artifact *with its environment marker*,
and a single package name can legitimately carry more than one version: the
develop line's lock forks `beartype` (0.22.9 for `python_full_version < '3.15'`,
0.23.1 for `>= '3.15'`) because an upstream floor moved while the interpreter
range stayed wide. A name→pin dict keyed by name cannot represent that: the
last fork overwrote the first, and a Python 3.13 image correctly shipping
0.22.9 was falsely flagged as skewing against the 3.15-only 0.23.1 pin.

The reconciler therefore groups pins by name and splits them three ways:

- **unconditional** (no marker): required, exact version, exactly as before;
- **single-version conditional** (one version behind a marker, e.g.
  `pywin32 ; sys_platform == 'win32'`): gates nothing on presence; its version
  is still checked when it ships — the pre-fork lenient behavior, unchanged;
- **forked** (more than one distinct version for one name): each fork's marker
  is evaluated against the image interpreter's own environment (the same
  evaluation `uv pip install` performed at build time), the applicable fork
  becomes required, and a wrong version is a named mismatch. Without the
  image env line — or if a marker uses syntax this stdlib-only evaluator does
  not implement — the fork degrades to the lenient rule: any of the locked
  fork versions satisfies the gate. Unknown markers can only *relax* toward
  the old behavior, never invent a requirement. A lenient-fork mismatch line
  names the full accepted set (`one of beartype==0.22.9, beartype==0.23.1`) —
  the reporting contract merged from the develop-side #1182 fix — so the
  operator sees every version the lock accepts rather than an arbitrary
  survivor.

Usage:
    uv export --locked --package maistro-server \
      --extra image --no-dev --no-emit-workspace \
      --format requirements-txt --output-file /tmp/expected.txt
    python scripts/check-image-lock-reconciliation.py \
      --image maistro-engine:pr-123 \
      --python /app/venv/bin/python \
      --expected-file /tmp/expected.txt \
      --member maistro-core==0.9.0 --member maistro-server==0.9.0 \
      --member maistro-canvas==0.9.0

The engine image's contract is maistro-server's `image` extra: the core
surfaces the API server ships (identity, llm, sandbox, observability), the
Canvas package (#1825) and the openai pin the image has always carried. The
export above is the same invocation the root Dockerfile's builder runs, and
the `--member` pins are the workspace members the image installs from the
copied sources with `--no-deps` — the export names their third-party
dependencies, not the members themselves.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# A requirement line in a uv-export requirements.txt: `name==version` at the
# start of a line, optionally followed by markers and hash continuations
# (which are separate lines and never match this prefix pattern).
_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)")


def canon(name: str) -> str:
    """PEP 503 normalized name: the lock says `bip-utils`, the wheel metadata
    says `bip_utils` (or `PyJWT` vs `pyjwt`) — same distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class LockedPin:
    """One `name==version[ ; marker]` line from the export."""

    name: str
    version: str
    marker: str | None

    @property
    def pin(self) -> str:
        return f"{self.name}=={self.version}"


# The PEP 508 marker variables whose values the gate captures from the image
# interpreter. `extras` is deliberately absent: exports never carry it.
_MARKER_ENV_VARS = frozenset(
    {
        "python_version",
        "python_full_version",
        "os_name",
        "sys_platform",
        "platform_release",
        "platform_system",
        "platform_version",
        "platform_machine",
        "platform_python_implementation",
        "implementation_name",
        "implementation_version",
    }
)

# The PEP 508 value each marker variable reads from, as a stdlib expression
# evaluated inside the image interpreter.
_PY_EXPR = {
    "python_version": "'.'.join(platform.python_version_tuple()[:2])",
    "python_full_version": "platform.python_version()",
    "os_name": "os.name",
    "sys_platform": "sys.platform",
    "platform_release": "platform.release()",
    "platform_system": "platform.system()",
    "platform_version": "platform.version()",
    "platform_machine": "platform.machine()",
    "platform_python_implementation": "platform.python_implementation()",
    "implementation_name": "sys.implementation.name",
    "implementation_version": "platform.python_version()",
}

# Runs inside the image: first the PEP 508 environment as JSON on one
# `@image-env@` line, then every installed distribution. JSON (stdlib) keeps
# values like `platform_version`'s "#58-Ubuntu SMP ..." parseable on the gate
# side. Each key is captured in its own try/except so an exotic interpreter
# degrades to a smaller env (or none) — lenient forks — instead of a red
# docker step.
_CAPTURES = "\n".join(
    f"try: _env[{k!r}] = {_PY_EXPR[k]}\nexcept Exception: pass" for k in sorted(_PY_EXPR)
)
_IMAGE_ENV_SNIPPET = (
    "import json, os, platform, sys; _env = {}\n"
    + _CAPTURES
    + "\nprint('@image-env@ ' + json.dumps(_env, sort_keys=True))"
)

_DUMP = (
    _IMAGE_ENV_SNIPPET + "; import importlib.metadata as m; "
    "print(*sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions()), "
    "sep='\\n')"
)

_IMAGE_ENV_PREFIX = "@image-env@ "


def parse_image_env(dump: str) -> dict[str, str] | None:
    """Extract the image interpreter's marker environment from its dump.

    Returns None when the dump carries no `@image-env@` line or an unparseable
    one — the fork comparison then degrades to the lenient rule rather than
    inventing a requirement from an environment it cannot see.
    """
    for line in dump.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_IMAGE_ENV_PREFIX):
            continue
        try:
            env = json.loads(stripped[len(_IMAGE_ENV_PREFIX) :])
        except ValueError:
            return None
        if not isinstance(env, dict):
            return None
        return {str(k): str(v) for k, v in env.items() if isinstance(v, (str, int, float))}
    return None


class UnsupportedMarker(Exception):
    """The marker uses syntax the stdlib-only evaluator does not implement."""


# Marker tokenizer: quoted strings, numbers-in-versions stay string literals,
# variable names, operators (including the two-word `not in`), parens, and the
# `and`/`or` keywords.
_TOKEN = re.compile(
    r"""\s*(?:
        (?P<str>'[^']*'|"[^"]*")
      | (?P<op><=|>=|===|==|!=|~=|<|>)
      | (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<word>[A-Za-z_][A-Za-z0-9_.]*)
    )""",
    re.VERBOSE,
)


def _tokenize(marker: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(marker):
        m = _TOKEN.match(marker, pos)
        if not m or m.end() == pos:
            rest = marker[pos:].strip()
            if not rest:
                break
            raise UnsupportedMarker(f"cannot tokenize near: {rest[:40]!r}")
        pos = m.end()
        kind = m.lastgroup or ""
        tokens.append((kind, m.group(kind)))
    return tokens


def _as_version(value: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return None


def _compare(lhs: str, op: str, rhs: str) -> bool:
    if op == "===":
        return lhs == rhs
    lhs_v, rhs_v = _as_version(lhs), _as_version(rhs)
    if lhs_v is not None and rhs_v is not None:
        left: tuple[int, ...] | str = lhs_v
        right: tuple[int, ...] | str = rhs_v
    else:
        left, right = lhs, rhs
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right  # type: ignore[operator]
    if op == ">":
        return left > right  # type: ignore[operator]
    if op == "<=":
        return left <= right  # type: ignore[operator]
    if op == ">=":
        return left >= right  # type: ignore[operator]
    raise UnsupportedMarker(f"operator {op!r}")


class _MarkerParser:
    """Recursive-descent evaluator over the tokenized marker subset.

    A class rather than closures so no single function concentrates the
    complexity: `evaluate_marker` is the public entry, the `parse_*` methods
    the grammar levels, and every failure path raises `UnsupportedMarker` —
    the caller's signal to degrade leniently rather than guess.
    """

    def __init__(self, tokens: list[tuple[str, str]], env: Mapping[str, str]):
        self._tokens = tokens
        self._env = env
        self._pos = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _take(self) -> tuple[str, str]:
        if self._pos >= len(self._tokens):
            raise UnsupportedMarker("unexpected end of marker")
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _operand(self, kind: str, value: str) -> str:
        if kind == "str":
            return value[1:-1]
        if kind == "word":
            if value not in _MARKER_ENV_VARS:
                raise UnsupportedMarker(f"unknown marker variable {value!r}")
            return self._env.get(value, "")
        raise UnsupportedMarker(f"expected operand, got {value!r}")

    def _parse_atom(self) -> bool:
        token = self._peek()
        if token is None:
            raise UnsupportedMarker("unexpected end of marker")
        if token[0] == "lparen":
            self._take()
            result = self._parse_or()
            if self._peek() != ("rparen", ")"):
                raise UnsupportedMarker("unbalanced parenthesis")
            self._take()
            return result
        lhs = self._operand(*self._take())
        op_token = self._take()
        if op_token == ("word", "not"):
            if self._take() != ("word", "in"):
                raise UnsupportedMarker("'not' without 'in'")
            return lhs not in self._operand(*self._take())
        if op_token == ("word", "in"):
            return lhs in self._operand(*self._take())
        if op_token[0] != "op":
            raise UnsupportedMarker(f"expected operator, got {op_token[1]!r}")
        return _compare(lhs, op_token[1], self._operand(*self._take()))

    def _parse_and(self) -> bool:
        result = self._parse_atom()
        while self._peek() == ("word", "and"):
            self._take()
            # Parse the right side unconditionally: short-circuiting here
            # would strand the remaining tokens and mis-report the marker.
            rhs = self._parse_atom()
            result = result and rhs
        return result

    def _parse_or(self) -> bool:
        result = self._parse_and()
        while self._peek() == ("word", "or"):
            self._take()
            rhs = self._parse_and()
            result = result or rhs
        return result

    def evaluate(self) -> bool:
        result = self._parse_or()
        if self._pos != len(self._tokens):
            raise UnsupportedMarker(f"trailing tokens near {self._tokens[self._pos][1]!r}")
        return result


def evaluate_marker(marker: str, env: Mapping[str, str]) -> bool:
    """Evaluate the PEP 508 marker subset uv writes into requirements exports.

    Supports parentheses, `and`/`or` (and binds tighter), the version
    comparisons, and `in`/`not in`. Comparison semantics mirror packaging's:
    both sides are compared as versions when both look like dotted-integer
    releases, otherwise as strings.
    """
    return _MarkerParser(_tokenize(marker), env).evaluate()


def parse_expected(text: str) -> dict[str, list[LockedPin]]:
    """Group every exported pin by canonical name, markers attached.

    A name may legitimately carry several versions — the lock forks an
    artifact across interpreter ranges (beartype 0.22.9 below 3.15, 0.23.1
    above) — so the value is a list, never an overwrite.
    """
    pins: dict[str, list[LockedPin]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m = _REQ.match(stripped)
        if m:
            name = canon(m.group(1))
            if ";" in stripped:
                # uv export continues the line with ` \\` when hashes follow;
                # the continuation belongs to the export format, not the marker.
                marker = stripped.split(";", 1)[1].strip().rstrip("\\").strip()
            else:
                marker = None
            pins.setdefault(name, []).append(LockedPin(name, m.group(2), marker))
    if not pins:
        raise SystemExit(
            "error: expected-file contains no `name==version` pins — is it "
            "a `uv export --format requirements-txt` output?"
        )
    return pins


def parse_actual(text: str) -> set[str]:
    pins: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("@", "+", "*", "-", "WARN", "Using", "Checked")):
            continue
        m = _REQ.match(line)
        if m:
            pins.add(f"{canon(m.group(1))}=={m.group(2)}")
    if not pins:
        raise SystemExit(f"error: no distributions dumped from the image:\n{text}")
    return pins


def _classify_expected(
    pins_by_name: dict[str, list[LockedPin]], members: list[str]
) -> tuple[dict[str, str], dict[str, str], dict[str, list[LockedPin]]]:
    """Split the export into required / lenient-conditional / forked pins.

    Members are unconditional required pins by definition (installed from the
    copied sources, not named in the export).
    """
    required: dict[str, str] = {}
    conditional: dict[str, str] = {}
    forked: dict[str, list[LockedPin]] = {}
    for name, pins in sorted(pins_by_name.items()):
        versions = {p.version for p in pins}
        if len(versions) == 1:
            if all(p.marker is None for p in pins):
                required[name] = pins[0].pin
            else:
                conditional[name] = pins[0].pin
        else:
            forked[name] = pins
    for m in members:
        name, _, version = m.partition("==")
        required[canon(name)] = f"{canon(name)}=={version}"
    return required, conditional, forked


def _expected_clause(candidates: set[str]) -> str:
    """The expected-side half of a mismatch line.

    A single pin reads exactly as it always has (`foo==1.0`); a fork evaluated
    leniently names every version the lock accepts for the name, so the
    operator sees the full accepted set rather than an arbitrary survivor
    (reporting contract merged from the develop-side #1182 fix).
    """
    ordered = sorted(candidates)
    if len(ordered) == 1:
        return ordered[0]
    return "one of " + ", ".join(ordered) + " (" + " or ".join(ordered) + ")"


def _skew_message(
    name: str,
    actual_pin: str,
    forked: dict[str, list[LockedPin]],
    image_env: dict[str, str] | None,
) -> str | None:
    """The mismatch description for a forked name, or None if it reconciles."""
    versions = {p.version for p in forked[name]}
    applicable = _applicable_forks(forked[name], image_env) if image_env is not None else []
    allowed = {p.version for p in applicable} or versions
    if actual_pin.partition("==")[2] in allowed:
        return None
    detail = (
        " or ".join(f"{p.pin} (marker: {p.marker})" for p in applicable)
        if applicable
        else _expected_clause({f"{name}=={v}" for v in versions})
    )
    return f"{actual_pin} (image) != {detail}"


def _missing_pins(
    expected_names: set[str],
    actual_by_name: dict[str, str],
    required: dict[str, str],
    forked: dict[str, list[LockedPin]],
    image_env: dict[str, str] | None,
) -> list[str]:
    missing: list[str] = []
    for name in sorted(expected_names - actual_by_name.keys()):
        if name in required:
            missing.append(required[name])
        elif name in forked and image_env is not None:
            applicable = _applicable_forks(forked[name], image_env)
            if applicable:
                locked = ", ".join(f"{p.pin} (marker: {p.marker})" for p in applicable)
                missing.append(f"{locked} — applicable to the image interpreter")
        # A conditional name absent from the image gates nothing (its marker
        # may not apply); a forked name without an interpreter environment
        # likewise degrades to lenient.
    return missing


def _reconcile(
    pins_by_name: dict[str, list[LockedPin]],
    members: list[str],
    actual: set[str],
    image_env: dict[str, str] | None,
) -> tuple[list[str], list[str], list[str], int]:
    """Classify every difference as missing/extra/skew. Returns
    (missing, extra, skewed, lenient_conditional_count)."""
    missing: list[str] = []
    extra: list[str] = []
    skewed: list[str] = []

    required, conditional, forked = _classify_expected(pins_by_name, members)

    actual_by_name = {p.partition("==")[0]: p for p in actual}
    expected_names = set(pins_by_name) | {n.partition("==")[0] for n in members}
    everything_expected = (
        set(required.values())
        | set(conditional.values())
        | {p.pin for pins in forked.values() for p in pins}
    )

    missing = _missing_pins(expected_names, actual_by_name, required, forked, image_env)

    for name in sorted(actual_by_name.keys() - expected_names):
        extra.append(actual_by_name[name])

    # Comparing by canonical NAME (not by pin string) is what makes a version
    # skew nameable: `foo==1.0` expected and `foo==2.0` installed shares no
    # exact string, so a set difference alone would report it as a confusing
    # missing+extra pair.
    for name in sorted(actual_by_name.keys() & expected_names):
        actual_pin = actual_by_name[name]
        if name in required or name in conditional:
            expected_pin = required.get(name) or conditional.get(name)
            assert expected_pin is not None
            if actual_pin != expected_pin:
                skewed.append(f"{actual_pin} (image) != {expected_pin}")
        elif name in forked:
            message = _skew_message(name, actual_pin, forked, image_env)
            if message:
                skewed.append(message)
        else:  # pragma: no cover - expected_names covers members
            raise AssertionError(f"unclassified name {name}")

    # A fork matched only leniently (no interpreter env) must not also be
    # reported extra: its pin is part of everything_expected already.
    extra = [p for p in extra if p not in everything_expected]
    return missing, extra, skewed, len(conditional)


def _applicable_forks(pins: list[LockedPin], env: Mapping[str, str]) -> list[LockedPin]:
    applicable: list[LockedPin] = []
    for pin in pins:
        if pin.marker is None:
            applicable.append(pin)
            continue
        try:
            if evaluate_marker(pin.marker, env):
                applicable.append(pin)
        except UnsupportedMarker:
            return []  # unknown syntax: caller degrades to lenient
    return applicable



def reconcile_variance(
    required: set[str], conditional: set[str], actual: set[str]
) -> tuple[list[str], list[str], list[str]]:
    """Compare an image's pins against the lock and return (missing, extra, skewed).

    Compatibility shim for the develop-side test surface: groups pins by name
    and treats any locked variant of a name as acceptable.
    """
    everything_expected = required | conditional
    allowed_by_name: dict[str, set[str]] = {}
    for pin in everything_expected:
        allowed_by_name.setdefault(pin.partition("==")[0], set()).add(pin)

    actual_by_name = {p.partition("==")[0]: p for p in actual}
    skewed_names: set[str] = set()
    skewed: list[str] = []
    for name, pin in actual_by_name.items():
        allowed = allowed_by_name.get(name)
        if allowed is not None and pin not in allowed:
            skewed_names.add(name)
            skewed.append(f"{pin} (image) != {_expected_clause(allowed)}")
    skewed.sort()

    missing = sorted(p for p in required - actual if p.partition("==")[0] not in skewed_names)
    extra = sorted(
        p for p in actual - everything_expected if p.partition("==")[0] not in skewed_names
    )
    return missing, extra, skewed

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True, help="image tag, e.g. maistro-engine:pr-123")
    ap.add_argument(
        "--python",
        default="/app/venv/bin/python",
        help="python interpreter path inside the image (docker --entrypoint)",
    )
    expected_group = ap.add_mutually_exclusive_group(required=True)
    expected_group.add_argument(
        "--expected-file", help="uv export requirements-txt output to reconcile against"
    )
    expected_group.add_argument(
        "--expected-stdin",
        action="store_true",
        help="read the uv export output from stdin",
    )
    ap.add_argument(
        "--member",
        action="append",
        default=[],
        help="workspace member pin installed but not in the export, e.g. "
        "`maistro-core==0.9.0`; repeatable",
    )
    args = ap.parse_args()

    expected_text = (
        sys.stdin.read() if args.expected_stdin else Path(args.expected_file).read_text()
    )
    pins_by_name = parse_expected(expected_text)
    for m in args.member:
        if m.partition("==")[2] == "":
            raise SystemExit(f"error: --member expects name==version, got: {m}")

    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            args.python,
            args.image,
            "-c",
            _DUMP,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return 1
    actual = parse_actual(proc.stdout)
    image_env = parse_image_env(proc.stdout)

    missing, extra, skewed, conditional_count = _reconcile(
        pins_by_name, args.member, actual, image_env
    )
    if missing or extra or skewed:
        print(f"image {args.image} does NOT reconcile to the lock:")
        for p in missing:
            print(f"  locked, not in image : {p}")
        for p in extra:
            print(f"  in image, not locked : {p}")
        for p in skewed:
            print(f"  version mismatch     : {p}")
        return 1
    print(
        f"OK: {args.image} ships exactly the locked set "
        f"({len(actual)} distributions, incl. {len(args.member)} workspace member(s); "
        f"{conditional_count} marker-conditional pin(s) evaluated leniently; "
        f"forks evaluated against the image interpreter's environment: "
        f"{'yes' if image_env is not None else 'no @image-env@ line — lenient'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
