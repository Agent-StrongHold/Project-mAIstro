"""Vendored from bfcl-eval 2026.3.23 (Berkeley Function Calling Leaderboard) — DO NOT EDIT.

Regenerate with ``python3 scripts/vendor_bfcl.py``; verify with ``--check``.
Upstream wheel: https://files.pythonhosted.org/packages/ba/41/ed458527c770c50225b60bae3b0c3444b26804ee455fa2d8f187018d2cb2/bfcl_eval-2026.3.23-py3-none-any.whl
Upstream member sha256: 1702fb67afbe2c492608e58e2b7d02e46381f50166b47f3c952f76e34c7cd3bd
Apache License 2.0 — see the NOTICE file in this directory.

The only changes from upstream are the rewrites documented in
scripts/vendor_bfcl.py (``_REWRITES``); the ``_model_config_shim`` substitution
is the sole semantic one and is strictly harsher than upstream (no function-name
accommodation for any model). Hand-editing this file will fail
``vendor_bfcl.py --check`` in CI — the grader must not drift from the published
grader without that being visible.
"""

GORILLA_TO_OPENAPI = {
    "integer": "integer",
    "number": "number",
    "float": "number",
    "string": "string",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "list": "array",
    "dict": "object",
    "object": "object",
    "tuple": "array",
    "any": "string",
    "byte": "integer",
    "short": "integer",
    "long": "integer",
    "double": "number",
    "char": "string",
    "ArrayList": "array",
    "Array": "array",
    "HashMap": "object",
    "Hashtable": "object",
    "Queue": "array",
    "Stack": "array",
    "Any": "string",
    "String": "string",
    "Bigint": "integer",
}

GORILLA_TO_PYTHON = {
    "integer": "int",
    "number": "float",
    "float": "float",
    "string": "str",
    "boolean": "bool",
    "bool": "bool",
    "array": "list",
    "list": "list",
    "dict": "dict",
    "object": "dict",
    "tuple": "tuple",
    "any": "str",
    "byte": "int",
    "short": "int",
    "long": "int",
    "double": "float",
    "char": "str",
    "ArrayList": "list",
    "Array": "list",
    "HashMap": "dict",
    "Hashtable": "dict",
    "Queue": "list",
    "Stack": "list",
    "Any": "str",
    "String": "str",
    "Bigint": "int",
}


JAVA_TYPE_CONVERSION = {
    "byte": int,
    "short": int,
    "integer": int,
    "float": float,
    "double": float,
    "long": int,
    "boolean": bool,
    "char": str,
    "Array": list,
    "ArrayList": list,
    "Set": set,
    "HashMap": dict,
    "Hashtable": dict,
    "Queue": list,  # this can be `queue.Queue` as well, for simplicity we check with list
    "Stack": list,
    "String": str,
    "any": str,
}

JS_TYPE_CONVERSION = {
    "String": str,
    "integer": int,
    "float": float,
    "Bigint": int,
    "Boolean": bool,
    "dict": dict,
    "array": list,
    "any": str,
}
