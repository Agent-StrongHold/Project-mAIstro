"""Publication proofs for the root-admission identity vocabulary (#1859).

``maistro.runs`` is the published surface of the canonical execution model
(``Goal -> Graph -> Run -> NodeRun -> Attempt``). The root-admission identity
vocabulary of #1851 is published from it, so a downstream product imports the
identity types from the package instead of reaching into the submodule.

These tests pin two properties of that publication:

- the published names are the module's own objects (a re-export, not a copy
  or a shadowing definition), and they are declared in the package's
  ``__all__``;
- the leaf is still a leaf. Exactly two production edges import the module:
  the package's own ``__init__`` (the publication) and the inactive #1852
  classifier (``tasks/admission_generation.py``), which reads the identity
  types without anything consuming it in turn. The live claim loop imports
  neither, so the reachability the import graph now reports is a published
  library surface plus an unconsumed contract leaf — not a runtime consumer
  that quietly consumes the types.

Nothing here grants authority: constructing a DTO is not admission, and these
tests assert no admission decision.
"""

from __future__ import annotations

import ast
from pathlib import Path

import maistro.runs as runs_package
import maistro.runs.admission_identity as admission_identity
from maistro.runs import (
    AdmissionBinding,
    AdmissionRecordV2,
    CanonicalJsonObject,
    LegacyAdmissionRecord,
    RootAdmissionEnvelope,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_INIT = REPO_ROOT / "packages" / "maistro-core" / "src" / "maistro" / "runs" / "__init__.py"

PUBLISHED_NAMES = (
    "AdmissionBinding",
    "AdmissionRecordV2",
    "CanonicalJsonObject",
    "LegacyAdmissionRecord",
    "RootAdmissionEnvelope",
)


def _imports_admission_identity(tree: ast.AST) -> bool:
    """True when the module imports the admission identity leaf."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "maistro.runs.admission_identity":
                return True
            if node.module == "maistro.runs" and any(
                alias.name == "admission_identity" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == "maistro.runs.admission_identity" for alias in node.names):
                return True
    return False


def _production_importers() -> list[Path]:
    """Every production module that imports the admission identity leaf."""
    importers: list[Path] = []
    for src_root in sorted(REPO_ROOT.glob("packages/*/src")):
        for path in sorted(src_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _imports_admission_identity(tree):
                importers.append(path)
    return importers


def test_runs_package_publishes_the_admission_identity_names() -> None:
    """The identity vocabulary is importable from the package surface."""
    for name in PUBLISHED_NAMES:
        published = getattr(runs_package, name)
        assert published is getattr(admission_identity, name), (
            f"maistro.runs.{name} must be the module's own object, not a copy"
        )
        assert name in runs_package.__all__, f"maistro.runs.__all__ must declare {name}"


def test_published_names_are_importable_with_a_from_import() -> None:
    """A downstream product can `from maistro.runs import ...` the vocabulary."""
    imported = {
        "AdmissionBinding": AdmissionBinding,
        "AdmissionRecordV2": AdmissionRecordV2,
        "CanonicalJsonObject": CanonicalJsonObject,
        "LegacyAdmissionRecord": LegacyAdmissionRecord,
        "RootAdmissionEnvelope": RootAdmissionEnvelope,
    }
    for name, value in imported.items():
        assert value is getattr(admission_identity, name)
        assert value is getattr(runs_package, name)


def test_the_package_publication_is_the_only_production_edge() -> None:
    """The leaf stays a contract leaf: publishing it wires no runtime consumer.

    The reachability gate now sees this module through the package's own
    ``__init__``. Exactly two production importers are sanctioned, both
    contract leaves and neither a runtime consumer:

    - the package publication itself (``maistro/runs/__init__.py``), and
    - the #1852 replay-generation classifier (``tasks/admission_generation.py``),
      whose issue-specified API imports the identity types while staying
      inactive — nothing imports the classifier, so no admission decision
      path reads these names.

    Any importer beyond exactly those two — above all the live claim loop in
    ``tasks/idempotency.py`` or the queue — means the leaf has grown a runtime
    consumer and its reachability disposition has to be revisited (the #1845
    admission-backend integration) — that is a contract change, not a
    refactor, and this test is where it surfaces.
    """
    classifier = (
        REPO_ROOT
        / "packages"
        / "maistro-core"
        / "src"
        / "maistro"
        / "tasks"
        / "admission_generation.py"
    )
    importers = _production_importers()
    assert importers == [PACKAGE_INIT, classifier], (
        "the admission identity leaf must keep exactly two production edges — "
        f"the package publication in {PACKAGE_INIT} and the inactive #1852 "
        f"classifier {classifier}; got "
        + ", ".join(str(path.relative_to(REPO_ROOT)) for path in importers)
    )
