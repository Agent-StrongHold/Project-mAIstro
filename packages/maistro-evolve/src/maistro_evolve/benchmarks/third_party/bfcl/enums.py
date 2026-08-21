"""Vendored from bfcl-eval 2026.3.23 (Berkeley Function Calling Leaderboard) — DO NOT EDIT.

Regenerate with ``python3 scripts/vendor_bfcl.py``; verify with ``--check``.
Upstream wheel: https://files.pythonhosted.org/packages/ba/41/ed458527c770c50225b60bae3b0c3444b26804ee455fa2d8f187018d2cb2/bfcl_eval-2026.3.23-py3-none-any.whl
Upstream member sha256: 2182becfa2a1d071ee1db30db593b4758c6bf866aa12d2d4b8daf09175ea518a
Apache License 2.0 — see the NOTICE file in this directory.

The only changes from upstream are the rewrites documented in
scripts/vendor_bfcl.py (``_REWRITES``); the ``_model_config_shim`` substitution
is the sole semantic one and is strictly harsher than upstream (no function-name
accommodation for any model). Hand-editing this file will fail
``vendor_bfcl.py --check`` in CI — the grader must not drift from the published
grader without that being visible.
"""

from enum import Enum


class ModelStyle(Enum):
    """
    ModelStyle controls how the function doc should be formatted.
    """
    GORILLA = "gorilla"
    OPENAI_COMPLETIONS = "openai-completions"
    OPENAI_RESPONSES = "openai-responses"
    ANTHROPIC = "claude"
    MISTRAL = "mistral"
    GOOGLE = "google"
    AMAZON = "amazon"
    FIREWORK_AI = "firework_ai"
    NEXUS = "nexus"
    OSSMODEL = "ossmodel"
    COHERE = "cohere"
    WRITER = "writer"
    NOVITA_AI = "novita_ai"


class Language(Enum):
    """
    Language controls the type checking for AST checker.
    """
    PYTHON = "python"
    JAVA = "java"
    JAVASCRIPT = "javascript"


class ReturnFormat(Enum):
    """
    ReturnFormat controls the decode_ast logic.
    """
    PYTHON = "python"
    JAVA = "java"
    JAVASCRIPT = "javascript"
    JSON = "json"
    VERBOSE_XML = "verbose_xml"
    CONCISE_XML = "concise_xml"
