#!/usr/bin/env python3
"""Finite installed-workspace proof harness for #86 (M3-A4).

The release orchestrator is deliberately thin: it launches the supported
installer/lifecycle commands and public product clients declared in a
reviewed manifest, collects a hashed evidence bundle, and asserts the
installed-workspace contract. It does not recreate admission, authentication,
Binding bootstrap, or the executor — those belong to the product and to #87's
same-request oracle, which the EXECUTE family consumes through the manifest's
public client command.

Usage:

    uv run python scripts/prove-installed-workspace.py \
        --manifest reviewed-manifest.json --output <evidence-dir>
    uv run python scripts/prove-installed-workspace.py --validate-manifest \
        --manifest reviewed-manifest.json
    uv run python scripts/prove-installed-workspace.py --verify <evidence-dir>

Contract (docs/testing/installed-workspace-proof.md):

* All five scenario families INSTALL/EXECUTE/RESTART/ISOLATE/FAIL-CLOSED are
  mandatory; each records PASS, FAIL, BLOCKED, or NOT_RUN. NOT_APPLICABLE is
  allowed only for the BROWSER_LOGIN subcheck on an independently reviewed
  headless profile.
* Exit zero only for observed evidence when every family passes, applicability
  is valid, and every required key/file/hash validates. Structural validity
  (--verify) never proves run occurrence or authenticity.
* Stop-before policy: the harness refuses to execute commands that generate or
  import credentials, create grants, elevate, change socket/group permissions,
  or perform unexpected paid/provider setup. Missing credentials or an
  unauthorized provider budget are NOT_RUN — never permission to create them.
  No live installation or provider calls are authorized by the issue
  clarification; a run requires a reviewed manifest and a pre-authorized
  budget.

Exit codes: 0 = goal state, 1 = evidence written but a family did not pass
(or the bundle failed self-verification), 2 = misuse / invalid manifest /
bundle could not be written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "docs" / "testing" / "installed-workspace-proof.schema.json"

MANIFEST_SCHEMA_VERSION = 1
RESULTS_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_EVIDENCE = 1
EXIT_MISUSE = 2

FAMILIES = ("INSTALL", "EXECUTE", "RESTART", "ISOLATE", "FAIL_CLOSED")
SCENARIO_KEYS = {family: family.lower() for family in FAMILIES}

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"
SUBCHECK_OUTCOMES = (PASS, FAIL, BLOCKED, NOT_RUN, NOT_APPLICABLE)
FAMILY_RANK = {FAIL: 0, BLOCKED: 1, NOT_RUN: 2, PASS: 3}

#: Every bundle must contain these manifest-listed, hashed files. The index
#: manifest, the reviewed manifest copy, and the reviewed profile copy are
#: excluded from the recursive hash list (an index cannot hash itself, and the
#: reviewed inputs are provenance, not run output).
REQUIRED_FILES = (
    "results.json",
    "install.log",
    "effective-config.json",
    "execution.json",
    "restart.json",
    "isolation.json",
    "fail-closed.json",
    "junit.xml",
)
EXCLUDED_FROM_HASH = ("manifest.json", "reviewed-manifest.json", "profile.json")

DEFAULT_STEP_TIMEOUT_S = 900
INSTALL_LOG_CAP_BYTES = 1_048_576
STREAM_CAP_BYTES = 65_536

#: The four mandatory FAIL-CLOSED cases (issue #86 clarification).
MANDATORY_FAIL_CLOSED_CASES = (
    "absent_credential",
    "unavailable_model",
    "inaccessible_runtime",
    "missing_sandbox_capability",
)

#: expect_json type names (a value that is one of these strings is a type
#: expectation, not a literal).
TYPE_NAMES = (
    "string",
    "integer",
    "boolean",
    "object",
    "array",
    "nonempty_string",
    "positive_integer",
)

#: Stop-before rules. Category, owning policy, and a regex over the joined
#: argv. Detection blocks the family without executing the command.
STOP_BEFORE_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "elevation",
        "#86 stop-before: elevation",
        re.compile(r"(^|\s)(sudo|doas|pkexec)(\s|$)|(^|\s)su(\s|$)"),
    ),
    (
        "socket-or-group-permission-change",
        "#86 stop-before: socket/group permission changes",
        re.compile(
            r"(^|\s)(usermod|groupadd|groupmod|chgrp|setfacl)(\s|$)|chmod\s+\S*[go][+-][rwx].*(sock|docker)"
        ),
    ),
    (
        "credential-generation-or-import",
        "#86 stop-before: credential generation/import",
        re.compile(
            r"(^|\s)(ssh-keygen|age-keygen|docker-credential-credential-store)(\s|$)"
            r"|gpg\s+.*--gen-key"
            r"|openssl\s+(genrsa|genpkey|gen-ec|req)\b"
            r"|docker\s+login\b"
            r"|maistro\s+\S*(mnemonic|credential)\S*\s+(generate|create|import)"
        ),
    ),
    (
        "new-grants",
        "#86 stop-before: new grants",
        re.compile(
            r"(^|\s)(grant|authorize|binding)s?\s+(--create|create|new)\b|create-(grant|binding)\b"
        ),
    ),
    (
        "unexpected-paid-provider-setup",
        "#86 stop-before: unexpected paid/provider setup",
        re.compile(
            r"(^|\s)(--sign-?up|register-account|create-api-key|api-key\s+create|billing)\b",
            re.IGNORECASE,
        ),
    ),
)

#: Secret-shaped literals must not appear anywhere in a reviewed manifest.
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer literal", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}")),
)

#: Sanitizer rules applied to every byte kept in the bundle.
SANITIZE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authorization-header",
        re.compile(r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(bearer\s+)?[^\s\"',}]+"),
    ),
    (
        "cookie",
        re.compile(r"(?i)\b(set-)?cookie\s*[:=]\s*[^\s\"',}]+"),
    ),
    (
        "sensitive-assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|x-api-key|"
            r"token|secret|password|passwd|passphrase|mnemonic|recovery[_-]?(phrase|code|mnemonic)|"
            r"private[_-]?key|session[_-]?id)\b[\"']?\s*[:=]\s*[\"\']?[^\s\"',}]{4,}"
        ),
    ),
)
REDACTED = "<redacted>"


class ProofError(RuntimeError):
    """Misuse, invalid manifest, or unusable bundle (exit 2)."""


class SchemaError(ProofError):
    """The shipped schema or an instance violates the supported contract."""


# ---------------------------------------------------------------------------
# Minimal JSON Schema subset — the schema file is the single contract, and the
# loader rejects keywords it does not implement so the file can never silently
# claim validation that is not happening.
# ---------------------------------------------------------------------------

_DOC_KEYWORDS = frozenset(
    {"$schema", "$id", "title", "description", "examples", "default", "$defs", "comment"}
)
_IMPLEMENTED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "enum",
        "const",
        "minimum",
        "allOf",
        "$ref",
    }
)
_JSON_TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")


def _type_name(instance: Any) -> str:
    if instance is None:
        return "null"
    if isinstance(instance, bool):
        return "boolean"
    if isinstance(instance, int):
        return "integer"
    if isinstance(instance, float):
        return "number"
    if isinstance(instance, str):
        return "string"
    if isinstance(instance, list):
        return "array"
    if isinstance(instance, dict):
        return "object"
    return type(instance).__name__


def _check_type(instance: Any, expected: str, where: str) -> None:
    actual = _type_name(instance)
    ok = {
        "object": actual == "object",
        "array": actual == "array",
        "string": actual == "string",
        "boolean": actual == "boolean",
        "null": actual == "null",
        "integer": actual == "integer",
        "number": actual in ("integer", "number"),
    }[expected]
    if not ok:
        raise SchemaError(f"{where}: expected {expected}, got {actual} ({instance!r:.80})")


def _resolve_ref(schema: dict[str, Any], defs: dict[str, Any], where: str) -> dict[str, Any]:
    ref = schema["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        raise SchemaError(f"{where}: only local '#/$defs/...' $ref is supported, got {ref!r}")
    name = ref[len("#/$defs/") :]
    target = defs.get(name)
    if not isinstance(target, dict):
        raise SchemaError(f"{where}: $ref target {ref!r} is not defined")
    return target


def _validate_node(  # noqa: C901 - one branch per implemented schema keyword
    instance: Any, schema: Any, defs: dict[str, Any], where: str
) -> None:
    if schema is True:
        return
    if schema is False:
        raise SchemaError(f"{where}: schema forbids any value")
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: schema node must be an object or boolean")

    unknown = set(schema) - _IMPLEMENTED_KEYWORDS - _DOC_KEYWORDS
    if unknown:
        raise SchemaError(f"{where}: schema uses unsupported keyword(s): {sorted(unknown)}")

    if "$ref" in schema:
        _validate_node(instance, _resolve_ref(schema, defs, where), defs, where)
    if "allOf" in schema:
        for i, sub in enumerate(schema["allOf"]):
            _validate_node(instance, sub, defs, f"{where}/allOf[{i}]")

    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else list(types)
        for name in types:
            if name not in _JSON_TYPES:
                raise SchemaError(f"{where}: unknown JSON type {name!r}")
        if _type_name(instance) not in types and not (
            "number" in types and _type_name(instance) == "integer"
        ):
            raise SchemaError(f"{where}: expected {'|'.join(types)}, got {_type_name(instance)}")
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{where}: expected const {schema['const']!r}, got {instance!r:.80}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{where}: {instance!r:.80} not in enum {schema['enum']!r}")

    if isinstance(instance, str):
        _validate_string(instance, schema, where)
    if isinstance(instance, list):
        _validate_array(instance, schema, defs, where)
    if isinstance(instance, dict):
        _validate_object(instance, schema, defs, where)
    if (
        isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and "minimum" in schema
        and instance < schema["minimum"]
    ):
        raise SchemaError(f"{where}: {instance} < minimum {schema['minimum']}")


def _validate_string(instance: str, schema: dict[str, Any], where: str) -> None:
    if "minLength" in schema and len(instance) < schema["minLength"]:
        raise SchemaError(f"{where}: shorter than minLength {schema['minLength']}")
    if "maxLength" in schema and len(instance) > schema["maxLength"]:
        raise SchemaError(f"{where}: longer than maxLength {schema['maxLength']}")
    if "pattern" in schema and re.search(schema["pattern"], instance) is None:
        raise SchemaError(f"{where}: {instance!r:.80} does not match pattern {schema['pattern']!r}")


def _validate_array(
    instance: list[Any], schema: dict[str, Any], defs: dict[str, Any], where: str
) -> None:
    if "minItems" in schema and len(instance) < schema["minItems"]:
        raise SchemaError(f"{where}: fewer than minItems {schema['minItems']}")
    if "maxItems" in schema and len(instance) > schema["maxItems"]:
        raise SchemaError(f"{where}: more than maxItems {schema['maxItems']}")
    if "items" in schema:
        for i, item in enumerate(instance):
            _validate_node(item, schema["items"], defs, f"{where}[{i}]")


def _validate_object(
    instance: dict[str, Any], schema: dict[str, Any], defs: dict[str, Any], where: str
) -> None:
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in instance:
            raise SchemaError(f"{where}: missing required key {key!r}")
    additional = schema.get("additionalProperties", True)
    for key, value in instance.items():
        child = f"{where}/{key}"
        if key in props:
            _validate_node(value, props[key], defs, child)
        elif additional is False:
            raise SchemaError(f"{where}: unexpected key {key!r}")
        elif isinstance(additional, dict):
            _validate_node(value, additional, defs, child)


def load_contract() -> dict[str, Any]:
    """Load the shipped schema; it is the enforced contract, not documentation."""
    try:
        raw = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProofError(f"cannot read contract schema {SCHEMA_PATH}: {exc}") from exc
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProofError(f"contract schema is not valid JSON: {exc}") from exc
    if not isinstance(schema, dict):
        raise ProofError("contract schema must be a JSON object")
    return schema


def validate_manifest(instance: Any, schema: dict[str, Any]) -> None:
    """Validate a manifest instance against the shipped schema, fail-closed."""
    defs = schema.get("$defs", {})
    if not isinstance(defs, dict):
        raise SchemaError("$defs must be an object")
    _validate_node(instance, schema, defs, "manifest")


# ---------------------------------------------------------------------------
# Cross-field manifest rules the schema subset cannot express, plus the
# secret-shape and stop-before scans.
# ---------------------------------------------------------------------------


def _at(manifest: dict[str, Any], *path: str) -> Any:
    node: Any = manifest
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def check_cross_rules(manifest: dict[str, Any]) -> None:
    browser = _at(manifest, "support_row", "browser")
    login_mode = _at(manifest, "scenarios", "install", "login", "mode")
    if browser == "headless":
        review = _at(manifest, "support_row", "headless_review")
        if not isinstance(review, dict) or review.get("independently_reviewed") is not True:
            raise ProofError(
                "support_row.headless_review.independently_reviewed must be true for a headless row "
                "(NOT_APPLICABLE for BROWSER_LOGIN requires independent review)"
            )
        if not isinstance(_at(manifest, "support_row", "profile_path"), str):
            raise ProofError("support_row.profile_path is required for a headless row")
        if login_mode != "authenticated_equivalent":
            raise ProofError("headless rows must declare login.mode=authenticated_equivalent")
    elif login_mode != "browser":
        raise ProofError("ui rows must declare login.mode=browser")

    names = [
        case.get("name")
        for case in _at(manifest, "scenarios", "fail_closed", "cases")
        if isinstance(case, dict)
    ]
    missing = [name for name in MANDATORY_FAIL_CLOSED_CASES if name not in names]
    if missing:
        raise ProofError(f"fail_closed is missing mandatory case(s): {missing}")

    users = _at(manifest, "scenarios", "isolate", "users") or []
    workspaces = _at(manifest, "scenarios", "isolate", "workspaces") or []
    if len(set(users)) != 2:
        raise ProofError("isolate.users must be two distinct users")
    if len(set(workspaces)) != 2:
        raise ProofError("isolate.workspaces must be two distinct workspaces")

    digests = _at(manifest, "artifacts", "digests")
    if not isinstance(digests, dict) or not digests:
        raise ProofError("artifacts.digests must name at least one artifact digest")


def check_no_secret_literals(text: str) -> None:
    for label, pattern in SECRET_SHAPES:
        match = pattern.search(text)
        if match:
            raise ProofError(
                f"manifest contains a secret-shaped literal ({label}) near {match.group(0)[:12]!r}; "
                "manifests carry credential references, never values"
            )


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _iter_command_lists(node: Any) -> Iterator[list[str]]:
    """Every list of strings in the manifest that could be an argv."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_command_lists(value)
        return
    if not isinstance(node, list):
        return
    if node and all(isinstance(item, str) for item in node):
        yield node
    for item in node:
        yield from _iter_command_lists(item)


def _checkout_command_elements(manifest: Any) -> list[str]:
    """Manifest argv elements that name a file inside the harness's own checkout.

    The issue forbids substituting the developer checkout for the published
    artifact, so a command that reaches into the checkout is refused before
    anything runs. The harness's own interpreter is the one exception: a
    stand-in command is not the artifact under test.
    """
    try:
        interpreter = Path(sys.executable).resolve()
    except OSError:  # pragma: no cover - sys.executable is always resolvable
        interpreter = Path("/nonexistent")
    found: list[str] = []
    for argv in _iter_command_lists(manifest):
        for element in argv:
            if not element.startswith("/"):
                continue
            try:
                resolved = Path(element).resolve()
            except OSError:  # pragma: no cover - resolve(strict=False) does not raise
                continue
            if resolved == interpreter:
                continue
            if _is_inside(resolved, REPO_ROOT):
                found.append(element)
    return found


def check_no_checkout_artifacts(manifest: Any) -> None:
    """Refuse a manifest that runs the developer checkout instead of the
    published, digest-pinned artifact."""
    offenders = sorted(set(_checkout_command_elements(manifest)))
    if offenders:
        raise ProofError(
            "manifest command(s) name the harness's own checkout "
            f"({', '.join(offenders)}); the developer checkout is not the artifact under test"
        )


@dataclass(frozen=True)
class StopBefore:
    category: str
    policy_owner: str
    family: str
    step_name: str
    command: list[str]


def iter_commands(  # noqa: C901 - one branch per manifest slot that can carry a command
    manifest: dict[str, Any],
) -> list[tuple[str, str, list[str]]]:
    """Every (family, step-name, argv) the manifest could ask the harness to run."""
    commands: list[tuple[str, str, list[str]]] = []
    install = _at(manifest, "scenarios", "install") or {}
    for slot in ("installer", "workspace", "effective_config"):
        step = install.get(slot)
        if isinstance(step, dict) and isinstance(step.get("command"), list):
            commands.append(("INSTALL", slot, step["command"]))
    login = install.get("login")
    if isinstance(login, dict) and isinstance(login.get("command"), dict):
        commands.append(("INSTALL", "login", login["command"]["command"]))
    for i, step in enumerate(install.get("post_checks") or []):
        if isinstance(step, dict) and isinstance(step.get("command"), list):
            commands.append(("INSTALL", f"post_checks[{i}]", step["command"]))
    if isinstance(_at(manifest, "target", "probe"), list):
        commands.append(("INSTALL", "target.probe", _at(manifest, "target", "probe")))

    execute = _at(manifest, "scenarios", "execute") or {}
    client = execute.get("client")
    if isinstance(client, dict) and isinstance(client.get("command"), list):
        commands.append(("EXECUTE", "client", client["command"]))

    restart = _at(manifest, "scenarios", "restart") or {}
    for slot in ("stop", "start", "persistence", "new_request"):
        step = restart.get(slot)
        if isinstance(step, dict) and isinstance(step.get("command"), list):
            commands.append(("RESTART", slot, step["command"]))

    isolate = _at(manifest, "scenarios", "isolate") or {}
    control = isolate.get("positive_control")
    if isinstance(control, dict) and isinstance(control.get("command"), list):
        commands.append(("ISOLATE", "positive_control", control["command"]))
    for probe in isolate.get("probes") or []:
        if isinstance(probe, dict):
            step = probe.get("command")
            if isinstance(step, dict) and isinstance(step.get("command"), list):
                commands.append(("ISOLATE", str(probe.get("name", "probe")), step["command"]))

    for case in _at(manifest, "scenarios", "fail_closed", "cases") or []:
        if not isinstance(case, dict):
            continue
        for slot in ("arrange", "client"):
            step = case.get(slot)
            if isinstance(step, dict) and isinstance(step.get("command"), list):
                commands.append(("FAIL_CLOSED", str(case.get("name", "?")), step["command"]))
    return commands


def scan_stop_before(manifest: dict[str, Any]) -> list[StopBefore]:
    found: list[StopBefore] = []
    for family, step_name, argv in iter_commands(manifest):
        joined = " ".join(argv)
        for category, policy_owner, pattern in STOP_BEFORE_RULES:
            if pattern.search(joined):
                found.append(
                    StopBefore(
                        category=category,
                        policy_owner=policy_owner,
                        family=family,
                        step_name=step_name,
                        command=list(argv),
                    )
                )
    return found


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    """Redact secret-shaped values; return counts per rule for the evidence."""
    counts: dict[str, int] = {}

    # Straightforward, auditable substitution: keep the leading key/token and
    # redact the value after ':' or '=' when present, else redact the match.
    for label, pattern in SANITIZE_RULES:
        matches = pattern.findall(text)
        if not matches:
            continue
        counts[label] = len(matches)

        def _sub(match: re.Match[str], _label: str = label) -> str:
            whole = match.group(0)
            for sep in (":", "="):
                if sep in whole:
                    head = whole.split(sep, 1)[0]
                    return f"{head}{sep} {REDACTED}"
            return REDACTED

        text = pattern.sub(_sub, text)
    return text, counts


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@dataclass
class Step:
    name: str
    command: list[str]
    timeout_s: int = DEFAULT_STEP_TIMEOUT_S
    expect_exit: tuple[int, ...] = (0,)
    expect_json: dict[str, Any] = field(default_factory=dict)
    payload: str | None = None


def build_step(raw: Any, default_name: str) -> Step:
    if not isinstance(raw, dict):
        raise ProofError(f"step {default_name!r} must be an object")
    command = raw.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(t, str) for t in command):
        raise ProofError(f"step {default_name!r} needs a non-empty argv of strings")
    expect_exit = raw.get("expect_exit", [0])
    if not isinstance(expect_exit, list) or not expect_exit:
        raise ProofError(f"step {default_name!r}: expect_exit must be a non-empty list")
    return Step(
        name=str(raw.get("name", default_name)),
        command=list(command),
        timeout_s=int(raw.get("timeout_s", DEFAULT_STEP_TIMEOUT_S)),
        expect_exit=tuple(int(code) for code in expect_exit),
        expect_json=dict(raw.get("expect_json", {})),
        payload=raw.get("payload"),
    )


@dataclass
class StepResult:
    step: Step
    executed: bool
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    started_at: str = ""
    ended_at: str = ""
    stdout: str = ""
    stderr: str = ""
    stdout_json: dict[str, Any] | None = None
    detail: str = ""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _elapsed_ms(started_at: str) -> int:
    """Milliseconds since an ISO-8601 UTC stamp; 0 when the stamp is unusable."""
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    return max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{_sha256_bytes(raw)}"


def _harness_script_digest() -> str:
    """Digest of the harness itself, so a bundle names the exact controller."""
    try:
        return f"sha256:{_sha256_bytes(Path(__file__).resolve().read_bytes())}"
    except OSError:
        return "unavailable"


def _harness_controller_commit() -> str:
    """Best-effort controller commit; the tested product commit is the release
    ref recorded under ``artifacts``, not this repository's HEAD."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    commit = proc.stdout.strip()
    if proc.returncode != 0 or not commit:
        return "unavailable"
    return commit


def build_env(target: dict[str, Any]) -> dict[str, str]:
    """Minimal environment: the harness's Python, uv, credentials, application
    data, and checkout are never inherited by the target's commands."""
    env_path = (
        target.get("env_path") or "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
    home = target.get("home") or "/tmp/maistro-proof-home"
    return {"PATH": str(env_path), "HOME": str(home), "LC_ALL": "C.UTF-8"}


def build_cwd(target: dict[str, Any]) -> Path:
    workdir = target.get("workdir") or target.get("home") or "/tmp"
    path = Path(str(workdir))
    if not path.is_dir():
        raise ProofError(f"target workdir {path} does not exist")
    return path


class InstallLog:
    """The sanitized, capped install.log shared by every executed step."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._redactions: dict[str, int] = {}
        self._bytes = 0
        self._truncated = False
        header = (
            f"maistro installed-workspace proof — sanitized install log\n"
            f"started_at={_utc_now()}\n"
            f"secret-shaped values are redacted before hashing; nothing is added after the fact\n"
        )
        self._path.write_text(header, encoding="utf-8")
        self._bytes = len(header.encode())

    @property
    def redactions(self) -> dict[str, int]:
        return dict(self._redactions)

    @property
    def truncated(self) -> bool:
        return self._truncated

    def append(self, title: str, chunks: list[str]) -> None:
        body = f"\n=== [{title}] ===\n"
        for chunk in chunks:
            safe, counts = sanitize(chunk)
            for rule, count in counts.items():
                self._redactions[rule] = self._redactions.get(rule, 0) + count
            body += safe
            if not body.endswith("\n"):
                body += "\n"
        raw = body.encode()
        if self._bytes + len(raw) > INSTALL_LOG_CAP_BYTES:
            room = max(0, INSTALL_LOG_CAP_BYTES - self._bytes)
            self._path.open("ab").write(raw[:room] + b"\n--- TRUNCATED (cap reached) ---\n")
            self._bytes = INSTALL_LOG_CAP_BYTES
            self._truncated = True
            return
        self._path.open("ab").write(raw)
        self._bytes += len(raw)


def run_step(
    step: Step,
    env: dict[str, str],
    cwd: Path,
    install_log: InstallLog | None = None,
    *,
    record_log: bool = True,
) -> StepResult:
    started_at = _utc_now()
    try:
        completed = subprocess.run(
            step.command,
            env=env,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=step.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result = StepResult(
            step=step,
            executed=True,
            timed_out=True,
            started_at=started_at,
            ended_at=_utc_now(),
            stdout=str(exc.stdout or "")[:STREAM_CAP_BYTES],
            stderr=str(exc.stderr or "")[:STREAM_CAP_BYTES],
            detail=f"timed out after {step.timeout_s}s",
        )
        _log_result(install_log, result, record_log)
        return result
    except FileNotFoundError as exc:
        result = StepResult(
            step=step,
            executed=True,
            exit_code=None,
            started_at=started_at,
            ended_at=_utc_now(),
            detail=f"command not found: {exc}",
        )
        _log_result(install_log, result, record_log)
        return result
    stdout = (completed.stdout or "")[:STREAM_CAP_BYTES]
    stderr = (completed.stderr or "")[:STREAM_CAP_BYTES]
    duration_ms = _elapsed_ms(started_at)
    parsed: dict[str, Any] | None = None
    try:
        candidate = json.loads(stdout)
        parsed = candidate if isinstance(candidate, dict) else None
    except json.JSONDecodeError:
        parsed = None
    result = StepResult(
        step=step,
        executed=True,
        exit_code=completed.returncode,
        duration_ms=duration_ms,
        started_at=started_at,
        ended_at=_utc_now(),
        stdout=stdout,
        stderr=stderr,
        stdout_json=parsed,
    )
    if install_log is not None and record_log:
        _log_result(install_log, result, record_log)
    return result


def _log_result(install_log: InstallLog | None, result: StepResult, record: bool) -> None:
    if install_log is None or not record:
        return
    install_log.append(
        f"{result.step.name} exit={result.exit_code} timeout={result.timed_out}",
        [result.stdout, result.stderr],
    )


# ---------------------------------------------------------------------------
# expect_json evaluation
# ---------------------------------------------------------------------------


def _matches_literal(expected: Any, observed: Any) -> bool:
    if isinstance(expected, bool) or isinstance(observed, bool):
        return isinstance(expected, bool) and isinstance(observed, bool) and expected == observed
    return type(expected) is type(observed) and expected == observed


def check_expect_json(  # noqa: C901 - one branch per expectation type
    step: Step, observed: dict[str, Any] | None
) -> str | None:
    """Return a failure detail, or None when every expectation holds."""
    if not step.expect_json:
        if observed is None and step.payload is not None:
            return "stdout was not a JSON object"
        return None
    if observed is None:
        return "stdout was not a JSON object"
    for key, expected in step.expect_json.items():
        if key not in observed:
            return f"stdout JSON missing key {key!r}"
        value = observed[key]
        if isinstance(expected, str) and expected in TYPE_NAMES:
            if expected == "nonempty_string" and not (isinstance(value, str) and value.strip()):
                return f"{key}: expected nonempty_string, got {value!r:.60}"
            if expected == "positive_integer" and not (
                isinstance(value, int) and not isinstance(value, bool) and value >= 1
            ):
                return f"{key}: expected positive_integer, got {value!r:.60}"
            simple = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list}
            if expected in simple:
                cls = simple[expected]
                if expected == "integer" and isinstance(value, bool):
                    return f"{key}: expected integer, got bool"
                if not isinstance(value, cls):
                    return f"{key}: expected {expected}, got {_type_name(value)}"
        elif not _matches_literal(expected, value):
            return f"{key}: expected {expected!r:.60}, got {value!r:.60}"
    return None


def step_outcome(result: StepResult) -> tuple[str, str | None]:
    """(outcome, detail) for one executed step against its own expectations."""
    if result.timed_out:
        return FAIL, result.detail or "timed out"
    if result.exit_code is None:
        return FAIL, result.detail or "command could not be executed"
    if result.exit_code not in result.step.expect_exit:
        return FAIL, f"exit {result.exit_code} not in expected {list(result.step.expect_exit)}"
    detail = check_expect_json(result.step, result.stdout_json)
    if detail is not None:
        return FAIL, detail
    return PASS, None


# ---------------------------------------------------------------------------
# Family orchestration
# ---------------------------------------------------------------------------


@dataclass
class Subcheck:
    name: str
    outcome: str
    detail: str | None = None
    evidence: list[str] = field(default_factory=list)
    missing_prerequisite: str | None = None
    owner: str | None = None


@dataclass
class FamilyResult:
    family: str
    payload_name: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    subchecks: list[Subcheck] = field(default_factory=list)
    observed: dict[str, Any] | None = None
    reason: str | None = None

    @property
    def outcome(self) -> str:
        # NOT_APPLICABLE is a per-subcheck verdict (the BROWSER_LOGIN check on a
        # reviewed headless row). It is never a family verdict: a family is
        # PASS, FAIL, BLOCKED or NOT_RUN, and a family whose only non-passing
        # subcheck is an inapplicable one still ran.
        outcomes = [sub.outcome for sub in self.subchecks if sub.outcome != NOT_APPLICABLE]
        if not outcomes:
            return NOT_RUN
        worst = min(outcomes, key=lambda o: FAMILY_RANK.get(o, FAMILY_RANK[FAIL]))
        return worst

    def to_payload(self, collected_at: str) -> dict[str, Any]:
        return {
            "schema": RESULTS_SCHEMA_VERSION,
            "family": self.family,
            "outcome": self.outcome,
            "collected_at": collected_at,
            "reason": self.reason,
            "steps": self.steps,
            "observed": self.observed,
            "subchecks": [
                {
                    "name": sub.name,
                    "outcome": sub.outcome,
                    "detail": sub.detail,
                    "evidence": sub.evidence,
                    "missing_prerequisite": sub.missing_prerequisite,
                    "owner": sub.owner,
                }
                for sub in self.subchecks
            ],
        }


def _record(result: FamilyResult, step: StepResult, outcome: str, detail: str | None) -> None:
    result.steps.append(
        {
            "name": step.step.name,
            "command": step.step.command,
            "exit_code": step.exit_code,
            "timed_out": step.timed_out,
            "started_at": step.started_at,
            "ended_at": step.ended_at,
            "outcome": outcome,
            "detail": detail,
        }
    )


def _not_run_subcheck(name: str, prerequisite: str, owner: str, evidence: list[str]) -> Subcheck:
    return Subcheck(
        name=name,
        outcome=NOT_RUN,
        detail=f"prerequisite absent: {prerequisite}",
        evidence=evidence,
        missing_prerequisite=prerequisite,
        owner=owner,
    )


class ProofRun:
    """Drives the five families and assembles the evidence bundle."""

    def __init__(self, manifest: dict[str, Any], manifest_path: Path, output: Path) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.output = output
        self.env = build_env(manifest.get("target", {}))
        self.cwd = build_cwd(manifest.get("target", {}))
        self.results: dict[str, FamilyResult] = {
            family: FamilyResult(family, "") for family in FAMILIES
        }
        for family, payload in (
            ("INSTALL", "install.log"),
            ("EXECUTE", "execution.json"),
            ("RESTART", "restart.json"),
            ("ISOLATE", "isolation.json"),
            ("FAIL_CLOSED", "fail-closed.json"),
        ):
            self.results[family].payload_name = payload
        self.install_log = InstallLog(output / "install.log")
        self.stop_befores = scan_stop_before(manifest)
        self.provider_calls = 0
        self.target_probe: dict[str, Any] | None = None

    # -- helpers ---------------------------------------------------------

    def _blocked_by_stop_before(self, family: str) -> list[Subcheck]:
        hits = [stop for stop in self.stop_befores if stop.family == family]
        subs: list[Subcheck] = []
        for stop in hits:
            subs.append(
                Subcheck(
                    name=f"STOP_BEFORE_{stop.step_name}".upper(),
                    outcome=BLOCKED,
                    detail=(
                        f"command matches stop-before category {stop.category!r} "
                        f"({stop.policy_owner}); not executed"
                    ),
                    evidence=[self.results[family].payload_name],
                    owner=stop.policy_owner,
                )
            )
        return subs

    def _family_gated(self, family: str, steps: list[Subcheck]) -> FamilyResult:
        """If any stop-before hit targets this family, record BLOCKED and skip."""
        result = self.results[family]
        result.subchecks.extend(steps)
        blocked = [sub for sub in steps if sub.outcome == BLOCKED]
        if blocked:
            result.reason = "stop-before rule matched; offending command was not executed"
        return result

    def _run_subcheck(
        self, result: FamilyResult, step: Step, evidence: list[str]
    ) -> tuple[StepResult, str, str | None]:
        executed = run_step(step, self.env, self.cwd, self.install_log)
        outcome, detail = step_outcome(executed)
        _record(result, executed, outcome, detail)
        result.subchecks.append(
            Subcheck(name=step.name, outcome=outcome, detail=detail, evidence=evidence)
        )
        return executed, outcome, detail

    # -- INSTALL ---------------------------------------------------------

    def run_install(self) -> FamilyResult:  # noqa: C901 - the family's steps are a fixed sequence
        result = self.results["INSTALL"]
        install = self.manifest["scenarios"]["install"]
        target = self.manifest["target"]
        stop_hits = self._blocked_by_stop_before("INSTALL")
        if stop_hits:
            return self._family_gated("INSTALL", stop_hits)

        # TARGET_CLEAN: the probe both records the machine and proves the
        # clean-target contract the manifest declares.
        probe = build_step({"command": target["probe"]}, "TARGET_CLEAN")
        executed, outcome, _detail = self._run_subcheck(result, probe, ["install.log"])
        if outcome == PASS and isinstance(executed.stdout_json, dict):
            self.target_probe = executed.stdout_json
            missing = [
                key
                for key in (
                    "developer_checkout_absent",
                    "inherited_credentials_absent",
                    "inherited_python_uv_absent",
                    "inherited_app_data_absent",
                )
                if executed.stdout_json.get(key) is not True
            ]
            if missing:
                result.subchecks.append(
                    Subcheck(
                        name="CLEAN_TARGET_CONTRACT",
                        outcome=BLOCKED,
                        detail=f"target probe reports unmet requirement(s): {missing}",
                        evidence=["install.log"],
                        missing_prerequisite=", ".join(missing),
                        owner="#86 clean-target contract",
                    )
                )
                return result
        elif outcome != PASS:
            return result

        subchecks: list[tuple[str, Step]] = [
            ("FIRST_RUN", build_step(install["installer"], "FIRST_RUN")),
        ]
        for i, raw in enumerate(install["post_checks"]):
            subchecks.append((f"HEALTH_{i}", build_step(raw, f"HEALTH_{i}")))
        login_raw = dict(install["login"]["command"])
        login_raw.setdefault("expect_json", install["login"].get("expect_json", {}))
        login_name = "BROWSER_LOGIN" if install["login"]["mode"] == "browser" else "AUTH_EQUIVALENT"
        subchecks.append((login_name, build_step(login_raw, login_name)))
        subchecks.append(("WORKSPACE", build_step(install["workspace"], "WORKSPACE")))
        for name, step in subchecks:
            if result.outcome in (FAIL, BLOCKED):
                result.subchecks.append(
                    Subcheck(
                        name=name,
                        outcome=NOT_RUN,
                        detail="earlier install subcheck did not pass",
                        evidence=["install.log"],
                    )
                )
                continue
            self._run_subcheck(result, step, ["install.log"])
            if name == login_name and step.name != login_name:
                result.subchecks[-1].name = login_name

        # BROWSER_LOGIN applicability: only a reviewed headless row may record
        # NOT_APPLICABLE, and the authenticated equivalent must still run.
        if login_name == "BROWSER_LOGIN":
            pass
        elif self._headless_applicable():
            result.subchecks.append(
                Subcheck(
                    name="BROWSER_LOGIN",
                    outcome=NOT_APPLICABLE,
                    detail="headless row with independent review; browser coverage inapplicable",
                    evidence=["install.log"],
                )
            )

        if result.outcome in (FAIL, BLOCKED):
            return result

        effective = build_step(install["effective_config"], "EFFECTIVE_CONFIG")
        executed, outcome, _detail = self._run_subcheck(
            result, effective, ["effective-config.json"]
        )
        observed = executed.stdout_json if isinstance(executed.stdout_json, dict) else None
        result.observed = observed
        if outcome == PASS and observed is not None:
            provider = self.manifest["provider"]
            mismatches: list[str] = []
            if observed.get("gateway") != provider["gateway"]:
                mismatches.append(
                    f"gateway {observed.get('gateway')!r} != declared {provider['gateway']!r}"
                )
            if observed.get("model") != provider["model_default"]:
                mismatches.append(
                    f"model {observed.get('model')!r} != declared {provider['model_default']!r}"
                )
            tier = provider.get("model_tier")
            if tier is not None and "model_tier" in observed and observed.get("model_tier") != tier:
                mismatches.append(f"model_tier {observed.get('model_tier')!r} != declared {tier!r}")
            if mismatches:
                result.subchecks.append(
                    Subcheck(
                        name="EFFECTIVE_MATCHES_DECLARED",
                        outcome=FAIL,
                        detail="; ".join(mismatches),
                        evidence=["effective-config.json#/observed"],
                    )
                )
        return result

    def _headless_applicable(self) -> bool:
        review = _at(self.manifest, "support_row", "headless_review")
        return (
            _at(self.manifest, "support_row", "browser") == "headless"
            and isinstance(review, dict)
            and review.get("independently_reviewed") is True
        )

    # -- provider gate ----------------------------------------------------

    def _provider_gate(self) -> tuple[bool, str | None]:
        credentials = self.manifest.get("credentials", [])
        absent = [c.get("name") for c in credentials if not c.get("present")]
        budget = _at(self.manifest, "provider", "budget")
        if absent:
            return False, f"credentials not present on target: {absent} (owner: #86/#1824)"
        if not isinstance(budget, dict) or budget.get("authorized") is not True:
            return False, "provider budget not authorized (owner: #86 release proof)"
        return True, None

    def _budget_state(self) -> tuple[bool, str | None]:
        """Whether another provider call is still inside the authorized ceiling.

        The ceiling is a hard boundary, not a target: once the observed call
        count reaches it, the remaining provider-touching steps are NOT_RUN
        rather than spending unbudgeted calls.
        """
        budget = _at(self.manifest, "provider", "budget") or {}
        maximum = budget.get("max_model_calls")
        if not isinstance(maximum, int):
            return True, None
        if self.provider_calls >= maximum:
            return (
                False,
                f"provider call budget reached ({self.provider_calls}/{maximum}); "
                "no remaining calls authorized",
            )
        return True, None

    # -- EXECUTE ----------------------------------------------------------

    def run_execute(self) -> FamilyResult:
        result = self.results["EXECUTE"]
        stop_hits = self._blocked_by_stop_before("EXECUTE")
        if stop_hits:
            return self._family_gated("EXECUTE", stop_hits)
        allowed, reason = self._provider_gate()
        if not allowed:
            result.reason = reason
            result.subchecks.append(
                _not_run_subcheck(
                    "PROVIDER_RESPONSE", reason, "#86 release proof", ["execution.json"]
                )
            )
            return result
        budget_ok, budget_reason = self._budget_state()
        if not budget_ok:
            result.reason = budget_reason
            result.subchecks.append(
                _not_run_subcheck(
                    "PROVIDER_RESPONSE", budget_reason, "#86 release proof", ["execution.json"]
                )
            )
            return result
        client = build_step(self.manifest["scenarios"]["execute"]["client"], "PROVIDER_RESPONSE")
        executed, outcome, _detail = self._run_subcheck(
            result, client, ["execution.json#/observed"]
        )
        observed = executed.stdout_json if isinstance(executed.stdout_json, dict) else None
        result.observed = observed
        if outcome == PASS and observed is not None:
            canonical: list[str] = []
            for key in ("run_id", "node_run_id", "attempt_id"):
                if not isinstance(observed.get(key), str) or not observed.get(key):
                    canonical.append(key)
            if canonical:
                result.subchecks.append(
                    Subcheck(
                        name="CANONICAL_IDS_PRESENT",
                        outcome=FAIL,
                        detail=f"missing canonical execution id(s): {canonical}",
                        evidence=["execution.json#/observed"],
                    )
                )
            result.subchecks.append(self._effective_matches_declared(observed))
            result.subchecks.append(self._response_digest_present(observed))
            calls = observed.get("provider_calls")
            if not isinstance(calls, int) or isinstance(calls, bool) or calls < 0:
                result.subchecks.append(
                    Subcheck(
                        name="PROVIDER_CALLS_REPORTED",
                        outcome=FAIL,
                        detail="execution response did not report a non-negative provider_calls count",
                        evidence=["execution.json#/observed"],
                    )
                )
            else:
                self.provider_calls += calls
        return result

    def _declared_models(self) -> list[str]:
        provider = _at(self.manifest, "provider") or {}
        models = [provider.get("model_default"), provider.get("model_tier")]
        return [m for m in models if isinstance(m, str) and m]

    def _effective_matches_declared(self, observed: dict[str, Any]) -> Subcheck:
        """The executed response must report the declared provider/model.

        The issue requires the effective runtime values to be checked, not just
        the generated plan metadata, so a mismatched provider or model is a
        failure of the proof rather than a detail to be noted.
        """
        declared_gateway = _at(self.manifest, "provider", "gateway")
        reported_gateway = observed.get("gateway", observed.get("provider"))
        reported_model = observed.get("model")
        problems: list[str] = []
        if not isinstance(reported_gateway, str) or not reported_gateway:
            problems.append("response did not report the effective gateway/provider")
        elif declared_gateway and reported_gateway != declared_gateway:
            problems.append(
                f"effective gateway {reported_gateway!r} != declared {declared_gateway!r}"
            )
        if not isinstance(reported_model, str) or not reported_model:
            problems.append("response did not report the effective model")
        elif self._declared_models() and reported_model not in self._declared_models():
            problems.append(
                f"effective model {reported_model!r} is not a declared model "
                f"({', '.join(self._declared_models())})"
            )
        return Subcheck(
            name="EFFECTIVE_MATCHES_DECLARED",
            outcome=FAIL if problems else PASS,
            detail="; ".join(problems) if problems else None,
            evidence=["execution.json#/observed"],
        )

    def _response_digest_present(self, observed: dict[str, Any]) -> Subcheck:
        digest = observed.get("response_digest")
        present = isinstance(digest, str) and bool(digest.strip())
        return Subcheck(
            name="RESPONSE_DIGEST_PRESENT",
            outcome=PASS if present else FAIL,
            detail=None if present else "execution response carried no response_digest",
            evidence=["execution.json#/observed"],
        )

    # -- RESTART ----------------------------------------------------------

    def run_restart(self) -> FamilyResult:  # noqa: C901 - the family's steps are a fixed sequence
        result = self.results["RESTART"]
        stop_hits = self._blocked_by_stop_before("RESTART")
        if stop_hits:
            return self._family_gated("RESTART", stop_hits)
        restart = self.manifest["scenarios"]["restart"]
        execute_result = self.results["EXECUTE"]
        execute_run_id = (
            execute_result.observed.get("run_id")
            if isinstance(execute_result.observed, dict)
            else None
        )
        correlation = self.manifest["scenarios"]["execute"]["correlation"]

        stop = build_step(restart["stop"], "LIFECYCLE_STOP")
        executed, outcome, _detail = self._run_subcheck(result, stop, ["restart.json"])
        if outcome == PASS and isinstance(executed.stdout_json, dict):
            remaining = executed.stdout_json.get("sandboxes_remaining")
            if remaining != 0:
                result.subchecks.append(
                    Subcheck(
                        name="NO_ORPHANED_SANDBOXES",
                        outcome=FAIL,
                        detail=f"sandboxes_remaining={remaining!r} after stop",
                        evidence=["restart.json#/steps"],
                    )
                )

        start = build_step(restart["start"], "LIFECYCLE_START")
        self._run_subcheck(result, start, ["restart.json"])

        persistence = build_step(restart["persistence"], "PERSISTENCE")
        executed, outcome, _detail = self._run_subcheck(
            result, persistence, ["restart.json#/observed"]
        )
        observed = executed.stdout_json if isinstance(executed.stdout_json, dict) else None
        result.observed = observed
        if outcome == PASS and observed is not None:
            if execute_run_id is None:
                result.subchecks.append(
                    _not_run_subcheck(
                        "CORRELATION",
                        "no correlated execution: the EXECUTE family produced no run",
                        "#86 release proof",
                        ["execution.json"],
                    )
                )
            else:
                correlation_problems: list[str] = []
                if observed.get("correlated_run_id") != execute_run_id:
                    correlation_problems.append(
                        f"correlated_run_id {observed.get('correlated_run_id')!r} != execute run_id {execute_run_id!r}"
                    )
                if observed.get("user") != correlation["user"]:
                    correlation_problems.append("user differs from the executed scope")
                if observed.get("workspace") != correlation["workspace"]:
                    correlation_problems.append("workspace differs from the executed scope")
                if correlation_problems:
                    result.subchecks.append(
                        Subcheck(
                            name="CORRELATION",
                            outcome=FAIL,
                            detail="absent correlation: " + "; ".join(correlation_problems),
                            evidence=["restart.json#/observed", "execution.json#/observed"],
                        )
                    )

        new_request = build_step(restart["new_request"], "NEW_REQUEST")
        provider_ok, provider_reason = self._provider_gate()
        if not provider_ok:
            result.subchecks.append(
                _not_run_subcheck("NEW_REQUEST", provider_reason, "#86/#1824", ["restart.json"])
            )
            return result
        budget_ok, budget_reason = self._budget_state()
        if not budget_ok:
            result.subchecks.append(
                _not_run_subcheck(
                    "NEW_REQUEST", budget_reason, "#86 release proof", ["restart.json"]
                )
            )
            return result
        executed, outcome, _detail = self._run_subcheck(
            result, new_request, ["restart.json#/steps"]
        )
        if outcome == PASS and isinstance(executed.stdout_json, dict):
            calls = executed.stdout_json.get("provider_calls")
            if not isinstance(calls, int) or isinstance(calls, bool) or calls < 0:
                result.subchecks.append(
                    Subcheck(
                        name="PROVIDER_CALLS_REPORTED",
                        outcome=FAIL,
                        detail="restart request did not report a non-negative provider_calls count",
                        evidence=["restart.json#/steps"],
                    )
                )
            else:
                self.provider_calls += calls
        return result

    # -- ISOLATE ----------------------------------------------------------

    def run_isolate(self) -> FamilyResult:  # noqa: C901 - one branch per isolation probe kind
        result = self.results["ISOLATE"]
        stop_hits = self._blocked_by_stop_before("ISOLATE")
        if stop_hits:
            return self._family_gated("ISOLATE", stop_hits)
        isolate = self.manifest["scenarios"]["isolate"]
        control = build_step(isolate["positive_control"], "POSITIVE_CONTROL")
        executed, outcome, _detail = self._run_subcheck(result, control, ["isolation.json#/steps"])
        if outcome == PASS and isinstance(executed.stdout_json, dict):
            if executed.stdout_json.get("accessible") is not True:
                result.subchecks.append(
                    Subcheck(
                        name="POSITIVE_CONTROL_ACCESSIBLE",
                        outcome=FAIL,
                        detail="own scope not accessible — denials prove a broken probe, not isolation",
                        evidence=["isolation.json#/steps"],
                    )
                )
        elif outcome != PASS:
            return result

        probes_observed: list[dict[str, Any]] = []
        for raw in isolate["probes"]:
            name = str(raw.get("name", "probe"))
            step = build_step(raw["command"], f"PROBE_{name}".upper())
            executed, outcome, _detail = self._run_subcheck(
                result, step, ["isolation.json#/observed"]
            )
            observed = executed.stdout_json if isinstance(executed.stdout_json, dict) else None
            if observed is not None:
                entry = {"probe": name, "kind": raw.get("kind"), "observed": observed}
                probes_observed.append(entry)
                problems: list[str] = []
                if observed.get("denied") is not True:
                    problems.append("request was not denied")
                if observed.get("leaked") not in (None, []):
                    problems.append(f"leaked data: {observed.get('leaked')!r:.80}")
                if observed.get("dispatched") is not False:
                    problems.append("forbidden dispatch observed")
                if problems:
                    result.subchecks.append(
                        Subcheck(
                            name=f"ISOLATION_{name}".upper(),
                            outcome=FAIL,
                            detail="; ".join(problems),
                            evidence=["isolation.json#/observed"],
                        )
                    )
            elif outcome == PASS:
                result.subchecks.append(
                    Subcheck(
                        name=f"ISOLATION_{name}".upper(),
                        outcome=FAIL,
                        detail="probe stdout was not a JSON object",
                        evidence=["isolation.json#/observed"],
                    )
                )
        result.observed = {
            "users": isolate["users"],
            "workspaces": isolate["workspaces"],
            "probes": probes_observed,
        }
        return result

    # -- FAIL_CLOSED --------------------------------------------------------

    def run_fail_closed(self) -> FamilyResult:
        result = self.results["FAIL_CLOSED"]
        stop_hits = self._blocked_by_stop_before("FAIL_CLOSED")
        if stop_hits:
            return self._family_gated("FAIL_CLOSED", stop_hits)
        cases_observed: list[dict[str, Any]] = []
        for case in self.manifest["scenarios"]["fail_closed"]["cases"]:
            name = str(case["name"])
            arrange = build_step(case["arrange"], f"ARRANGE_{name}".upper())
            executed = run_step(arrange, self.env, self.cwd, self.install_log)
            _record(
                result,
                executed,
                PASS if executed.executed else FAIL,
                "arrange is best-effort; exit code ignored"
                if executed.executed
                else "arrange failed to run",
            )
            client = build_step(case["client"], f"CASE_{name}".upper())
            executed, outcome, _detail = self._run_subcheck(
                result, client, ["fail-closed.json#/observed"]
            )
            observed = executed.stdout_json if isinstance(executed.stdout_json, dict) else None
            cases_observed.append(
                {"case": name, "expected_outcome": case["expected_outcome"], "observed": observed}
            )
            if outcome == PASS and observed is not None:
                problems: list[str] = []
                if observed.get("outcome") not in ("blocked", "failed"):
                    problems.append(
                        f"outcome {observed.get('outcome')!r} is not a truthful blocked/failed"
                    )
                recovery = observed.get("recovery")
                if not isinstance(recovery, str) or not recovery.strip():
                    problems.append("no recovery pointer reported")
                if problems:
                    result.subchecks.append(
                        Subcheck(
                            name=f"TRUTHFUL_{name}".upper(),
                            outcome=FAIL,
                            detail="; ".join(problems),
                            evidence=["fail-closed.json#/observed"],
                        )
                    )
        result.observed = {"cases": cases_observed}
        return result

    # -- bundle -------------------------------------------------------------

    def budget_report(self) -> dict[str, Any]:
        budget = _at(self.manifest, "provider", "budget") or {}
        maximum = budget.get("max_model_calls")
        remaining = None
        if isinstance(maximum, int):
            remaining = max(0, maximum - self.provider_calls)
        return {
            "authorized": budget.get("authorized"),
            "max_model_calls": maximum,
            "observed_provider_calls": self.provider_calls,
            "remaining_model_calls": remaining,
            "exhausted": isinstance(maximum, int) and self.provider_calls > maximum,
        }

    def family_evidence(self, family: str) -> list[str]:
        payloads = {
            "INSTALL": ["install.log", "effective-config.json"],
            "EXECUTE": ["execution.json"],
            "RESTART": ["restart.json", "execution.json#/observed/run_id"],
            "ISOLATE": ["isolation.json"],
            "FAIL_CLOSED": ["fail-closed.json"],
        }
        return list(payloads[family])

    def run_all(self) -> dict[str, Any]:
        self.run_install()
        self.run_execute()
        self.run_restart()
        self.run_isolate()
        self.run_fail_closed()
        return self.assemble_results()

    def assemble_results(self) -> dict[str, Any]:
        generated_at = _utc_now()
        scenarios: dict[str, Any] = {}
        correlation = _at(self.manifest, "scenarios", "execute", "correlation") or {}
        for family in FAMILIES:
            result = self.results[family]
            scenarios[family] = {
                "outcome": result.outcome,
                "reason": result.reason,
                "subchecks": [
                    {
                        "name": sub.name,
                        "outcome": sub.outcome,
                        "detail": sub.detail,
                        "evidence": sub.evidence,
                        "missing_prerequisite": sub.missing_prerequisite,
                        "owner": sub.owner,
                    }
                    for sub in result.subchecks
                ],
                "evidence": self.family_evidence(family),
            }
            observed = result.observed if isinstance(result.observed, dict) else {}
            if family in ("EXECUTE", "RESTART"):
                scenarios[family]["principal"] = (
                    dict(correlation) if isinstance(correlation, dict) else {}
                )
            if family == "EXECUTE":
                scenarios[family]["canonical_ids"] = {
                    key: observed.get(key) for key in ("run_id", "node_run_id", "attempt_id")
                }
                scenarios[family]["effective"] = {
                    "gateway": observed.get("gateway", observed.get("provider")),
                    "model": observed.get("model"),
                    "response_digest": observed.get("response_digest"),
                }
        all_pass = all(scenarios[family]["outcome"] == PASS for family in FAMILIES)
        return {
            "schema": RESULTS_SCHEMA_VERSION,
            "generated_at": generated_at,
            "input": {
                "manifest_path": str(self.manifest_path),
                "manifest_sha256": f"sha256:{_sha256_bytes(self.manifest_path.read_bytes())}",
            },
            "profile_echo": {
                "support_row": _at(self.manifest, "support_row", "id"),
                "browser": _at(self.manifest, "support_row", "browser"),
                "os": _at(self.manifest, "support_row", "os"),
                "arch": _at(self.manifest, "support_row", "arch"),
                "runtime": _at(self.manifest, "support_row", "runtime"),
                "context": _at(self.manifest, "support_row", "context"),
                "store_profile": _at(self.manifest, "support_row", "store_profile"),
                "headless_review": _at(self.manifest, "support_row", "headless_review"),
            },
            "artifacts": _at(self.manifest, "artifacts"),
            "harness": {
                "script": "scripts/prove-installed-workspace.py",
                "script_sha256": _harness_script_digest(),
                "controller_commit": _harness_controller_commit(),
                "controller": {
                    "python": platform.python_version(),
                    "implementation": platform.python_implementation(),
                    "platform": platform.platform(),
                },
                "env_policy": "minimal PATH/HOME/LC_ALL; harness environment never inherited",
            },
            "environment": {
                "declared": self.manifest.get("target"),
                "target_probe": self.target_probe,
            },
            "sanitization": {
                "install.log": self.install_log.redactions,
                "truncated": self.install_log.truncated,
            },
            "stop_befores": [
                {
                    "category": stop.category,
                    "policy_owner": stop.policy_owner,
                    "family": stop.family,
                    "step": stop.step_name,
                    "command": stop.command,
                }
                for stop in self.stop_befores
            ],
            "budget": self.budget_report(),
            "scenarios": scenarios,
            "closeout": {
                "all_families_pass": all_pass,
                "exit_code": EXIT_OK if all_pass else EXIT_EVIDENCE,
            },
        }


def build_junit(results: dict[str, Any]) -> str:
    scenarios = results["scenarios"]
    failures = sum(1 for family in FAMILIES if scenarios[family]["outcome"] != PASS)

    def esc(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites name="installed-workspace-proof" tests="{len(FAMILIES)}" failures="{failures}">',
        f'  <testsuite name="families" tests="{len(FAMILIES)}" failures="{failures}">',
    ]
    for family in FAMILIES:
        entry = scenarios[family]
        outcome = entry["outcome"]
        lines.append(f'    <testcase name="{esc(family)}" classname="prove.installed_workspace">')
        if outcome != PASS:
            detail = entry.get("reason") or "; ".join(
                f"{sub['name']}: {sub['detail'] or sub['outcome']}"
                for sub in entry["subchecks"]
                if sub["outcome"] != PASS
            )
            lines.append(
                f'      <failure message="{esc(outcome)}" type="ScenarioNotPassed">{esc(detail[:2000])}</failure>'
            )
        lines.append("    </testcase>")
    lines.append("  </testsuite>")
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"


def write_bundle(
    output: Path,
    results: dict[str, Any],
    family_payloads: dict[str, dict[str, Any]],
    manifest_bytes: bytes,
    profile_bytes: bytes | None,
) -> Path:
    """Write payloads, results, junit, then the hashing index manifest.json."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "reviewed-manifest.json").write_bytes(manifest_bytes)
    if profile_bytes is not None:
        (output / "profile.json").write_bytes(profile_bytes)
    for family, payload in family_payloads.items():
        (output / payload_name(family)).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    (output / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "junit.xml").write_text(build_junit(results), encoding="utf-8")

    files: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(output).as_posix()
        if name in EXCLUDED_FROM_HASH:
            continue
        files[name] = f"sha256:{_sha256_bytes(path.read_bytes())}"
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        raise ProofError(f"bundle is missing required file(s): {missing}")
    index = {
        "schema": INDEX_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "input_manifest_sha256": f"sha256:{_sha256_bytes(manifest_bytes)}",
        "profile_sha256": (
            f"sha256:{_sha256_bytes(profile_bytes)}" if profile_bytes is not None else None
        ),
        "hash_exclusions": list(EXCLUDED_FROM_HASH),
        "files": files,
        "bundle_digest": _canonical_digest(files),
    }
    (output / "manifest.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output / "manifest.json"


def payload_name(family: str) -> str:
    return {
        "INSTALL": "effective-config.json",
        "EXECUTE": "execution.json",
        "RESTART": "restart.json",
        "ISOLATE": "isolation.json",
        "FAIL_CLOSED": "fail-closed.json",
    }[family]


# ---------------------------------------------------------------------------
# Bundle verification (--verify): structure and integrity only.
# ---------------------------------------------------------------------------


def verify_bundle(bundle: Path) -> list[str]:  # noqa: C901 - one branch per bundle invariant
    problems: list[str] = []
    index_path = bundle / "manifest.json"
    if not index_path.is_file():
        return [f"{bundle}: missing manifest.json index"]
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"manifest.json index is not valid JSON: {exc}"]
    if not isinstance(index, dict) or index.get("schema") != INDEX_SCHEMA_VERSION:
        return ["manifest.json index has an unsupported schema"]
    files = index.get("files")
    if not isinstance(files, dict):
        return ["manifest.json index has no files map"]

    for name in REQUIRED_FILES:
        if name not in files:
            problems.append(f"index does not list required file {name}")
    for name in EXCLUDED_FROM_HASH:
        if name in files:
            problems.append(f"index lists excluded file {name} in the recursive hash list")

    for name, digest in sorted(files.items()):
        path = bundle / name
        if not path.is_file():
            problems.append(f"listed file {name} is missing")
            continue
        actual = f"sha256:{_sha256_bytes(path.read_bytes())}"
        if actual != digest:
            problems.append(f"{name}: hash mismatch (index {digest}, actual {actual})")
    if index.get("bundle_digest") != _canonical_digest(files):
        problems.append("bundle_digest does not match the files map")

    results_path = bundle / "results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"results.json unreadable: {exc}")
        return problems
    if not isinstance(results, dict) or results.get("schema") != RESULTS_SCHEMA_VERSION:
        problems.append("results.json has an unsupported schema")
        return problems
    scenarios = results.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(FAMILIES):
        problems.append(f"results.json scenarios must be exactly {list(FAMILIES)}")
        return problems
    headless = (
        isinstance(results.get("profile_echo"), dict)
        and isinstance(results["profile_echo"].get("headless_review"), dict)
        and results["profile_echo"]["headless_review"].get("independently_reviewed") is True
    )
    for family in FAMILIES:
        entry = scenarios[family]
        if not isinstance(entry, dict):
            problems.append(f"{family}: scenario entry must be an object")
            continue
        if entry.get("outcome") not in (PASS, FAIL, BLOCKED, NOT_RUN):
            problems.append(f"{family}: invalid outcome {entry.get('outcome')!r}")
        for ref in entry.get("evidence", []) or []:
            _check_evidence_ref(ref, files, family, problems)
        for sub in entry.get("subchecks", []) or []:
            if not isinstance(sub, dict):
                problems.append(f"{family}: subcheck must be an object")
                continue
            if sub.get("outcome") not in SUBCHECK_OUTCOMES:
                problems.append(
                    f"{family}/{sub.get('name')}: invalid outcome {sub.get('outcome')!r}"
                )
            if sub.get("outcome") == NOT_APPLICABLE and (
                sub.get("name") != "BROWSER_LOGIN" or not headless
            ):
                problems.append(
                    f"{family}/{sub.get('name')}: NOT_APPLICABLE is only valid for BROWSER_LOGIN "
                    "on an independently reviewed headless profile"
                )
            for ref in sub.get("evidence", []) or []:
                _check_evidence_ref(ref, files, f"{family}/{sub.get('name')}", problems)
    try:
        junit = ET.parse(bundle / "junit.xml")
        cases = {case.get("name") for case in junit.iter("testcase")}
        if cases != set(FAMILIES):
            problems.append(f"junit.xml testcases {sorted(cases)} != families {list(FAMILIES)}")
    except (OSError, ET.ParseError) as exc:
        problems.append(f"junit.xml unreadable: {exc}")
    return problems


def _check_evidence_ref(
    ref: object, files: dict[str, str], where: str, problems: list[str]
) -> None:
    if not isinstance(ref, str):
        problems.append(f"{where}: evidence reference must be a string")
        return
    name = ref.split("#", 1)[0]
    if name in EXCLUDED_FROM_HASH or name == "results.json":
        problems.append(f"{where}: evidence reference {ref!r} must point at a listed payload")
    elif name not in files:
        problems.append(f"{where}: evidence reference {ref!r} names an unlisted file")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_manifest(path: Path, schema: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProofError(f"cannot read manifest {path}: {exc}") from exc
    check_no_secret_literals(raw.decode("utf-8", errors="replace"))
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProofError(f"manifest {path} is not valid JSON: {exc}") from exc
    validate_manifest(manifest, schema)
    check_cross_rules(manifest)
    check_no_checkout_artifacts(manifest)
    return manifest, raw


def read_profile(manifest: dict[str, Any]) -> bytes | None:
    declared = _at(manifest, "support_row", "profile_path")
    if declared is None:
        return None
    path = Path(str(declared))
    if not path.is_file():
        raise ProofError(f"support_row.profile_path {declared} does not exist")
    return path.read_bytes()


def cmd_prove(args: argparse.Namespace) -> int:
    schema = load_contract()
    manifest_path = Path(args.manifest)
    manifest, raw = load_manifest(manifest_path, schema)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise ProofError(f"output directory {output} is not empty")
    # The bundle directory must exist before the first log line is written to
    # it; the sanitized install log is created eagerly by ProofRun.
    output.mkdir(parents=True, exist_ok=True)

    profile = read_profile(manifest)
    run = ProofRun(manifest, manifest_path, output)
    results = run.run_all()
    family_payloads = {
        family: run.results[family].to_payload(results["generated_at"]) for family in FAMILIES
    }
    write_bundle(output, results, family_payloads, raw, profile)

    problems = verify_bundle(output)
    results["closeout"]["bundle_verified"] = not problems
    if problems:
        print("bundle self-verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    # results.json hash inside the index covers the pre-verification copy;
    # rewrite both so the recorded closeout is part of the hashed evidence.
    (output / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    index = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    files = {
        name: f"sha256:{_sha256_bytes((output / name).read_bytes())}" for name in index["files"]
    }
    index["files"] = files
    index["bundle_digest"] = _canonical_digest(files)
    (output / "manifest.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # The rewritten bundle is the one a reader receives, so it is the one that
    # has to verify. A failure here is recorded in the closeout and fails the
    # run rather than being reported as a verified bundle.
    final_problems = verify_bundle(output)
    if final_problems:
        results["closeout"]["bundle_verified"] = False
        (output / "results.json").write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        index = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        files = {
            name: f"sha256:{_sha256_bytes((output / name).read_bytes())}" for name in index["files"]
        }
        index["files"] = files
        index["bundle_digest"] = _canonical_digest(files)
        (output / "manifest.json").write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("final bundle self-verification failed:", file=sys.stderr)
        for problem in final_problems:
            print(f"  - {problem}", file=sys.stderr)

    exit_code = results["closeout"]["exit_code"]
    if problems or final_problems:
        exit_code = EXIT_EVIDENCE
    print(json.dumps(results["closeout"], sort_keys=True))
    print(f"bundle: {output.resolve()}")
    for family in FAMILIES:
        print(f"  {family}: {results['scenarios'][family]['outcome']}")
    if exit_code == EXIT_OK:
        print("all five families passed on observed evidence")
    return exit_code


def cmd_validate(args: argparse.Namespace) -> int:
    schema = load_contract()
    load_manifest(Path(args.manifest), schema)
    print(f"manifest {args.manifest} is structurally valid")
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    bundle = Path(args.verify)
    if not bundle.is_dir():
        print(f"bundle directory {bundle} does not exist", file=sys.stderr)
        return EXIT_MISUSE
    problems = verify_bundle(bundle)
    print(
        "structural verification only: a valid bundle proves structure and integrity, "
        "never run occurrence or authenticity"
    )
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    if problems:
        return EXIT_EVIDENCE
    print(f"bundle {bundle} is structurally valid")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-manifest", action="store_true", help="validate and exit")
    modes.add_argument("--verify", metavar="BUNDLE", help="verify an existing evidence bundle")
    parser.add_argument("--manifest", help="reviewed manifest path (prove/validate)")
    parser.add_argument("--output", help="evidence bundle directory (prove)")
    args = parser.parse_args(argv)

    if args.verify:
        return cmd_verify(args)
    if args.validate_manifest:
        if not args.manifest:
            parser.error("--validate-manifest requires --manifest")
        return cmd_validate(args)
    if not (args.manifest and args.output):
        parser.error(
            "prove mode requires --manifest and --output (or use --verify/--validate-manifest)"
        )
    return cmd_prove(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(EXIT_MISUSE)
