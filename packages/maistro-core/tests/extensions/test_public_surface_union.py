"""The ``maistro.extensions`` package root re-exports everything it imports.

The package root is a union surface assembled from many lanes (runtime
contract #950, registry/install #952/#953, compat #955, resolution #956,
preflight #957, effective authority #969, sandbox #970, certification #975).
Develop-sync merges extend it by hand, and the merge that assembled the
certification lane with develop's compat lane did in fact drop the nine
``Certification*`` names from ``__all__`` (caught only by ruff's F401 — a
name that is not re-exported anywhere else would vanish silently). These
tests pin the structural invariant directly: every name the root imports
from its own submodules is published in ``__all__``, and everything
``__all__`` names resolves.
"""

from __future__ import annotations

import ast
from pathlib import Path

import maistro.extensions

#: The package root module and its on-disk source.
_INIT = maistro.extensions.__file__
assert _INIT is not None
_SOURCE = Path(_INIT).read_text(encoding="utf-8")


def _imported_names() -> set[str]:
    """Names bound by the root's ``from maistro.extensions.* import (...)`` blocks."""
    tree = ast.parse(_SOURCE)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not (node.module or "").startswith("maistro.extensions."):
            continue
        for alias in node.names:
            if alias.name == "*":
                raise AssertionError("star import in the package root hides the surface")
            names.add(alias.asname or alias.name)
    return names


def test_every_submodule_import_is_published_in_all() -> None:
    """A root import missing from ``__all__`` is a silently regressed export."""
    missing = _imported_names() - set(maistro.extensions.__all__)
    assert not missing, (
        "maistro.extensions imports these names without re-exporting them "
        f"(add them to __all__): {sorted(missing)}"
    )


def test_every_published_name_resolves() -> None:
    """``from maistro.extensions import <name>`` works for the whole surface."""
    module = maistro.extensions
    unresolvable = [name for name in module.__all__ if not hasattr(module, name)]
    assert not unresolvable, f"__all__ names that do not resolve: {unresolvable}"


def test_both_merged_halves_are_exported() -> None:
    """The certification (#975) and compat (#955) halves both ride in ``__all__``."""
    exported = set(maistro.extensions.__all__)
    for name in (
        "CertificationReport",
        "CertificationSeal",
        "CertificationProfile",
        "certify",
        "verify_certification",
        "verify_certified_package",
        "certification_as_trust_claim",
    ):
        assert name in exported, f"certification surface missing from __all__: {name}"
    for name in (
        "Verdict",
        "HostContractMetadata",
        "ExtensionCompatMetadata",
        "negotiate",
        "parse_compat_metadata",
        "ensure_compatible",
    ):
        assert name in exported, f"compat surface missing from __all__: {name}"
