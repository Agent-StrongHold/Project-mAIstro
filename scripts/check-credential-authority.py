#!/usr/bin/env python3
"""Enforce the classified credential authority against production reachability.

The credential ledger is joined to the production import graph. Classification
is not authorization: a candidate cannot approve a second implementation by
adding scope claims to its own ledger. Only the trusted-base census (or the
fixed initial census when the base predates this gate) can approve surfaces.
Ownership behavior is exercised by the canonical store/API isolation tests,
not inferred from the presence of owner-shaped identifiers.
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
# Bootstrap only: an absent trusted ledger must not let the candidate invent
# authorities. These are the existing production surfaces at introduction of
# #1186, not a waiver for future stores/adapters. Once present, the base ledger
# is the policy. Changing that policy requires independent governance review.
_INITIAL_SURFACES = {
    "packages/hive-conductor/backend/routes/credentials.py": "product_crud",
    "packages/hive-conductor/backend/services/user_credentials.py": "product_crud",
    "packages/maistro-core/src/maistro/credentials/pool.py": "runtime_selection",
    "packages/maistro-core/src/maistro/credentials/router.py": "runtime_selection",
    "packages/maistro-core/src/maistro/credentials/store.py": "encrypted_store",
    "packages/maistro-core/src/maistro/vault.py": "deployment_secret_vault",
}
_INITIAL_CANONICAL = {
    "product_crud": "packages/hive-conductor/backend/services/user_credentials.py",
    "encrypted_store": (
        "packages/maistro-core/src/maistro/credentials/store.py::UserCredentialStore"
    ),
    "runtime_selection": (
        "packages/maistro-core/src/maistro/credentials/router.py::CredentialRouter"
    ),
    "scope": (
        "request principal user id for product CRUD; authorized binding scope for runtime selection"
    ),
    "guard": "tests/test_credential_authority.py",
}
_RETIRED_STORE = "packages/hive-conductor/backend/services/credential_store_v2.py"
_OWNER_SCOPE_TERMS = frozenset({"user", "principal", "owner", "uid"})
_CODE_SCOPED_KINDS = frozenset({"product_crud", "encrypted_store"})
# Exact non-record catalog helpers, not a blanket exemption for list operations.
_CATALOG_LISTS = {
    ("packages/hive-conductor/backend/routes/credentials.py", "list_providers"),
    ("packages/hive-conductor/backend/services/user_credentials.py", "list_provider_catalog"),
}
_STORE_OPERATIONS = frozenset(
    {"list_providers_for_user", "set_secret", "delete_secret", "has_secret", "use_secret"}
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
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    if not isinstance(ledger, dict):
        raise ValueError("credential authority ledger must be an object")
    return ledger


def _trusted_ledger() -> dict[str, object] | None:
    provenance = _load(ROOT / "scripts" / "ratchet_provenance.py", "_credential_provenance")
    baseline = provenance.resolve_baseline(LEDGER, root=ROOT)
    # The resolver's local worktree fallback is not independent authorization.
    # Use the closed initial census in that case too.
    if baseline.origin == "worktree" or baseline.absent_at_base:
        return None
    trusted = baseline.loads()
    if not isinstance(trusted, dict):
        raise ValueError("trusted credential authority ledger must be an object")
    return trusted


def _policy_failures(ledger: dict[str, object], trusted: dict[str, object] | None) -> list[str]:
    if trusted is not None:
        # No candidate-authored grants or silent reclassification. Descriptive
        # contracts are security policy too; compare every policy section.
        return [
            f"{section}: candidate credential policy differs from trusted base"
            for section in ("canonical", "reachable", "retired")
            if ledger.get(section) != trusted.get(section)
        ]

    entries = _surface_entries(ledger)
    census = {str(entry.get("path")): entry.get("kind") for entry in entries}
    failures = []
    if ledger.get("canonical") != _INITIAL_CANONICAL:
        failures.append("canonical credential authority differs from the fixed initial policy")
    if census != _INITIAL_SURFACES:
        failures.append(
            "credential authority census differs from the fixed initial census; "
            "candidate classification cannot authorize a new credential implementation"
        )
    retired = ledger.get("retired")
    if not isinstance(retired, list) or not any(
        isinstance(record, dict)
        and record.get("path") == _RETIRED_STORE
        and record.get("disposition") == "RETIRE"
        for record in retired
    ):
        failures.append("credential authority policy must preserve credential_store_v2 retirement")
    return failures


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


def _owner_name(name: str) -> bool:
    return bool(set(name.lower().strip("_").split("_")) & _OWNER_SCOPE_TERMS)


def _call_name(node: ast.AST) -> str:
    return ast.unparse(node) if isinstance(node, (ast.Name, ast.Attribute)) else ""


def _scope_sources(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], set[str], set[str]]:
    """Collect required owner inputs and the canonical storage delegates."""
    positional = [*node.args.posonlyargs, *node.args.args]
    required = positional[: len(positional) - len(node.args.defaults)]
    required += [
        arg
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if default is None
    ]
    owners = {arg.arg for arg in required if _owner_name(arg.arg)}
    data_names: set[str] = set()
    store_names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Assign) or len(child.targets) != 1:
            continue
        target = child.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(child.value, ast.Call):
            continue
        call = child.value
        name = _call_name(call.func)
        if name == "_user_id" and len(call.args) == 1 and ast.unparse(call.args[0]) == "request":
            owners.add(target.id)
        elif name == "self._load":
            data_names.add(target.id)
        elif name == "cred_svc.require_store":
            store_names.add(target.id)

    return owners, data_names, store_names


def _scope_sink_evidence(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Conservative lint, not an authorization proof.

    Required owner inputs must reach an owned bucket or canonical delegate,
    rather than merely occur in a name, string, log, or unused parameter.
    """
    owners, data_names, store_names = _scope_sources(node)

    def is_owner(expr: ast.AST) -> bool:
        return isinstance(expr, ast.Name) and expr.id in owners

    scoped = False
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in data_names:
                if func.attr not in {"get", "setdefault", "pop"}:
                    return False
            elif func.value.id not in store_names or func.attr not in _STORE_OPERATIONS:
                continue
        elif _call_name(func) not in {"_read_config", "_config_key"}:
            continue
        # Reject even a second, unscoped access alongside a scoped one.
        if not child.args or not is_owner(child.args[0]):
            return False
        scoped = True
    return scoped


def _owner_scope_failures(relative: str, path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return [f"{relative}: cannot parse owner-scoped credential surface"]
    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _operation_name(node.name):
            continue
        params = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        selects_record = any(
            set(arg.arg.split("_")) & {"id", "ids", "record", "records"} for arg in params
        )
        lists_records = node.name.lstrip("_").split("_")[0] == "list"
        if (relative, node.name) in _CATALOG_LISTS:
            continue
        # Key-material administration is not per-user record CRUD. Lists need
        # scope even with no selector; this was missing in the old heuristic.
        if (selects_record or lists_records) and not _scope_sink_evidence(node):
            failures.append(
                f"{relative}: {node.name} lacks owner/principal scope at a canonical storage sink"
            )
    return failures


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


def _imports_module_stem(path: Path, stem: str) -> bool:
    """Return whether a production module imports a retired module stem."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = (alias.name.rsplit(".", 1)[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = [alias.name for alias in node.names]
            if node.module:
                imported.append(node.module.rsplit(".", 1)[-1])
        else:
            continue
        if stem in imported:
            return True
    return False


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
    trusted: dict[str, object] | None = None,
) -> list[str]:
    """Return ledger/reachability violations, with no repository mutation.

    Injected ledgers default to the fixed bootstrap policy, never to trusting
    themselves. Tests may supply an independent trusted policy explicitly.
    """
    if ledger is None:
        ledger = _ledger()
        trusted = _trusted_ledger()
    if modules is None or reachable is None:
        modules, reachable = _reachable_production_modules()

    failures = _policy_failures(ledger, trusted)
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
        if kind in _CODE_SCOPED_KINDS and path.suffix == ".py":
            failures.extend(_owner_scope_failures(path_text, path))

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

            stem = Path(path_text).stem
            for module_path in modules.values():
                if not module_path.is_file() or not _imports_module_stem(module_path, stem):
                    continue
                failures.append(
                    f"{_relative(module_path)}: imports retired credential module {stem}"
                )

    return sorted(set(failures))


def main() -> int:
    try:
        failures = audit()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL: credential authority policy could not be resolved: {exc}", file=sys.stderr)
        return 1
    if failures:
        print("FAIL: credential authority classification is not closed", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("OK: reachable credential surfaces match the approved authority census")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
