"""The ``maistro.personas`` scorer tier loads lazily (#552 canonical convergence).

The RSI promotion path reaches this package through the Workspace persona
store, so the facade keeps its static import graph to the data/store tier:
importing ``maistro.personas`` must not drag the judge/scorer tier in, and
the scorer module loads only when one of its names is used. Same contract
as ``maistro.identity`` and ``maistro.extensions``: the names stay
importable from the package root, the module loads on first access.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import maistro.personas

_CLEAN_IMPORT = (
    "import sys\n"
    "import maistro.personas\n"
    "loaded = [m for m in sorted(sys.modules) if m == 'maistro.personas.scorer']\n"
    "assert not loaded, f'facade import loaded the scorer tier: {loaded}'\n"
)


def test_importing_the_facade_does_not_load_the_scorer_tier() -> None:
    """Importing ``maistro.personas`` must not import ``personas.scorer``.

    Runs in a fresh interpreter so this process's other imports cannot have
    loaded the scorer first and false-passed the property.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _CLEAN_IMPORT],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_scorer_name_resolves_from_the_root_on_first_access() -> None:
    """The lazily-tiered names still import from the package root."""
    from maistro.personas import scorer

    assert maistro.personas.RubricScorer is scorer.RubricScorer
    assert maistro.personas.create_judge_scorer is scorer.create_judge_scorer


def test_unknown_name_raises_attribute_error() -> None:
    """A name outside the scorer tier fails the way a missing attribute does."""

    unknown = "NotAPersonaName"
    with pytest.raises(AttributeError, match="NotAPersonaName"):
        getattr(maistro.personas, unknown)
