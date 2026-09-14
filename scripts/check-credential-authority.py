#!/usr/bin/env python3
"""Enforce the classified credential authority against production reachability.

The credential ledger is deliberately joined to the same import graph used by
``check-reachability.py``.  A new reachable credential-shaped implementation
therefore fails closed until it is either removed or explicitly classified as
an adapter to an existing authority.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "quality" / "credential-authority.json"
REACHABILITY = ROOT / "scripts" / "check-reachability.py"

_OPERATION_NAMES = frozenset(
    {
        "acquire",
        "add",
        "create",
        "delete",
        "fetch",
        "get",
        "list",
        "read",
        "release",
        "remove",
        "resolve",
        "retrieve",
        "rotate",
        "save",
        "select",
        "set",
        "update",
        "use",
    }
)
_SENSITIVE_TERMS = frozenset(
    {"credential", "credentials", "secret", "secrets", "api_key", "apikey", "token"}
)
_CRYPTO_OR_TRANSPORT_TERMS = frozenset(
    {"encrypt", "encrypted", "decrypt", "fernet", "httpx", "postgrest", "ciphertext"}
)
_ALLOWED_KINDS = frozenset(
    {
        "product_crud",
        "encrypted_store",
        "runtime_selection",
        "deployment_secret_vault",
        "protocol_adapter",
    }
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _reachable_production_modules() -> tuple[dict[str, Path], set[str]]:
    checker = _load(REACHABILITY, "_credential_authority_reachability")
    return checker._reachability(
        checker.ROOT, checker.FLAT_APPS, checker.STATIC_ROOTS, checker.DYNAMIC_ROOTS
    )


def _names(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            values.add(node.id.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.add(node.name.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.update(node.value.lower().replace("-", "_").split())
    return values


def _operation_name(name: str) -> bool:
    normalized = name.lower().lstrip("_")
    return normalized in _OPERATION_NAMES or any(
        normalized.startswith(f"{operation}_") for operation in _OPERATION_NAMES
    )


def _is_protocol(node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id == "Protocol")
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in node.bases
    )


def is_credential_surface(path: Path) -> bool:
    """Return whether a production module implements credential-like CRUD.

    This is intentionally behavior-shaped rather than filename-shaped.  A
    module called ``token_cache.py`` or a class called ``Repository`` cannot
    evade the guard merely by avoiding ``credential_store`` in its name.
    Protocols are contracts, not authorities, and are classified separately.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return False

    names = _names(tree)
    sensitive = names & _SENSITIVE_TERMS
    if not sensitive:
        return False
    operations = {
        node.name.lower().lstrip("_")
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _operation_name(node.name)
    }
    if not operations:
        return False

    path_signal = any(
        term in part.lower() for part in path.parts for term in ("credential", "secret", "vault")
    )
    crypto_or_transport = bool(names & _CRYPTO_OR_TRANSPORT_TERMS)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or _is_protocol(node):
            continue
        class_names = {
            node.name.lower(),
            *(base.id.lower() for base in node.bases if isinstance(base, ast.Name)),
        }
        class_words = _names(node)
        class_sensitive = bool(class_names & _SENSITIVE_TERMS) or any(
            term in node.name.lower() for term in ("credential", "secret", "vault")
        )
        class_secret_data = any(
            term in word for word in class_words for term in ("credential", "secret")
        )
        methods = {
            child.name.lower().lstrip("_")
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _operation_name(child.name)
        }
        # A real implementation exposes several state-changing/read operations.
        # Requiring three keeps two-method protocols and incidental token helpers
        # out of the authority census while still catching a renamed CRUD store.
        mutation_methods = {"delete", "remove", "rotate", "update"}
        if len(methods) >= 3 and (
            class_sensitive
            or (crypto_or_transport and class_secret_data and methods & mutation_methods)
        ):
            return True

    # Route/service adapters often expose functions rather than a store class.
    # Require both a credential-shaped path and CRUD-like functions so generic
    # token resolvers are not mistaken for a storage authority.
    return path_signal and len(operations) >= 2


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _surface_entries(ledger: dict[str, object]) -> list[dict[str, object]]:
    entries = ledger.get("reachable")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def audit(  # noqa: C901 -- this is the closed-world ledger gate
    ledger: dict[str, object] | None = None,
    *,
    modules: dict[str, Path] | None = None,
    reachable: set[str] | None = None,
) -> list[str]:
    """Return ledger/reachability violations, with no repository mutation."""
    ledger = _ledger() if ledger is None else ledger
    if modules is None or reachable is None:
        modules, reachable = _reachable_production_modules()

    failures: list[str] = []
    entries = _surface_entries(ledger)
    by_path = {str(entry.get("path")): entry for entry in entries}
    if len(by_path) != len(entries):
        failures.append("reachable credential ledger contains duplicate or missing paths")

    path_to_key = {path.resolve(): key for key, path in modules.items()}
    for entry in entries:
        path_text = str(entry.get("path", ""))
        path = ROOT / path_text
        if not path.is_file():
            failures.append(f"{path_text}: classified reachable surface is missing")
            continue
        key = path_to_key.get(path.resolve())
        if key is None:
            failures.append(f"{path_text}: surface is outside the reachability module graph")
        elif key not in reachable:
            failures.append(f"{path_text}: classified credential surface is unreachable")
        kind = entry.get("kind")
        if kind not in _ALLOWED_KINDS:
            failures.append(f"{path_text}: unsupported credential surface kind {kind!r}")
        scope = str(entry.get("scope", "")).strip().lower()
        authority = str(entry.get("authority", "")).strip().lower()
        if not scope:
            failures.append(f"{path_text}: credential surface must declare scope")
        if not authority:
            failures.append(f"{path_text}: credential surface must name its authority")
        required_contract = {
            "product_crud": ("canonical", ("user", "principal")),
            "encrypted_store": ("canonical", ("user", "principal")),
            "runtime_selection": ("canonical", ("authorized", "binding")),
            "deployment_secret_vault": ("spec-011", ("deployment", "admin")),
            "protocol_adapter": ("canonical", ()),
        }.get(kind)
        if required_contract is not None:
            authority_term, scope_terms = required_contract
            if authority_term not in authority:
                failures.append(f"{path_text}: authority must name {authority_term}")
            if scope_terms and not any(term in scope for term in scope_terms):
                failures.append(f"{path_text}: scope does not satisfy the {kind} contract")

    detected: dict[str, str] = {}
    for key in reachable:
        path = modules[key]
        if not path.is_relative_to(ROOT / "packages") or not is_credential_surface(path):
            continue
        relative = _relative(path)
        detected[relative] = key
        entry = by_path.get(relative)
        if entry is None:
            failures.append(
                f"{relative}: reachable credential implementation is not classified in "
                "quality/credential-authority.json"
            )
        elif (
            entry.get("kind") == "protocol_adapter"
            and "canonical" not in str(entry.get("authority", "")).lower()
        ):
            # Adapters may expose an interface, but must not become a second
            # storage authority. The ledger's explicit kind makes that reviewable.
            failures.append(f"{relative}: protocol adapter does not name canonical authority")

    retired = ledger.get("retired")
    if not isinstance(retired, list) or not retired:
        failures.append("credential authority ledger must record at least one retired decision")
    else:
        for record in retired:
            if not isinstance(record, dict):
                failures.append("credential authority retired record is not an object")
                continue
            path_text = str(record.get("path", ""))
            if (ROOT / path_text).exists():
                failures.append(f"{path_text}: retired credential implementation still exists")
            if path_text in detected:
                failures.append(f"{path_text}: retired credential implementation is reachable")

    return sorted(set(failures))


def main() -> int:
    failures = audit()
    if failures:
        print("FAIL: credential authority classification is not closed", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("OK: reachable credential surfaces are classified and authority-scoped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
