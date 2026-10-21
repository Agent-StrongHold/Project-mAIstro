"""The runs package root publishes the admission-identity vocabulary.

`maistro.runs` is the published surface of the canonical execution spine
(`Run` -> `NodeRun` -> `Attempt`): the package root re-exports the model,
lifecycle, store and service vocabulary so a consumer imports one front door
instead of reaching into private submodules. The root-admission identity
types (#1851) are part of that vocabulary, so the root re-exports them too.

The re-export is not only convenience — it is the module's *reachability*.
`scripts/check-reachability.py` walks the import graph from the published
entry points, and a module no published path imports is unwired debt that has
to be banked as a row in `quality/reachability-baseline.json`. Banking it
needs a grant that only a previously merged base can carry (`ratchet
_provenance.load_authorizations` reads the grant from the merge base), so
the reachable form is the maintainable one.

The gate is `scripts/check-reachability.py`; this file is the local, named
failure. If the re-export is pruned, the `exact-debt-ledger` job's
`check-ratchet-provenance.py` step reds on an unrelated PR with "NEW
unreachable module absent from trusted base", and nothing inside this package
says which import disappeared. These pins say it here, next to the surface
they protect.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import maistro
import maistro.runs as runs

#: The identity vocabulary the package root publishes.
ADMISSION_IDENTITY_NAMES = (
    "AdmissionBinding",
    "AdmissionRecordV2",
    "CanonicalJsonObject",
    "LegacyAdmissionRecord",
    "RootAdmissionEnvelope",
)

_SRC = str(pathlib.Path(maistro.__file__).resolve().parent.parent)


def _run(statement: str) -> subprocess.CompletedProcess[str]:
    """Run a statement in a cold interpreter.

    Within one interpreter the first test to touch a package populates
    ``sys.modules``, so an import that only works because something else
    imported it first looks fine. The question the ratchet asks is "does the
    published path import it", which is a question about a cold start.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_admission_identity_vocabulary_is_importable_from_the_package_root() -> None:
    """The published names are the module's own objects, not copies."""
    from maistro.runs import admission_identity

    published = {name: getattr(runs, name) for name in ADMISSION_IDENTITY_NAMES}
    assert published == {
        name: getattr(admission_identity, name) for name in ADMISSION_IDENTITY_NAMES
    }


def test_all_publishes_the_admission_identity_names() -> None:
    """Importable is not published: `__all__` is the surface contract."""
    for name in ADMISSION_IDENTITY_NAMES:
        assert name in runs.__all__, f"{name} imports from the root but is not in __all__"
        assert getattr(runs, name) is not None


def test_the_admission_identity_module_is_reachable_through_the_package_root() -> None:
    """A cold interpreter that imports the front door reaches the module.

    Without the root re-export, `import maistro.runs` leaves the submodule
    unimported and `runs.admission_identity` raises `AttributeError` — the
    module is then reachable only from its own test, which is exactly the
    unwired shape the reachability ratchet reports.
    """
    result = _run(
        "import maistro.runs as runs;"
        "assert runs.admission_identity.__name__ == 'maistro.runs.admission_identity',"
        " runs.admission_identity;"
        "assert runs.RootAdmissionEnvelope"
        " is runs.admission_identity.RootAdmissionEnvelope"
    )

    assert result.returncode == 0, result.stderr
