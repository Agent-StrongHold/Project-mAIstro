"""`maistro.identity`'s missing-extra guard must fire, and must be actionable.

`maistro.identity` needs secp256k1 (it derives BTC/ETH paths via
`Bip32Slip10Secp256k1`), which means `bip-utils`, which means `coincurve` — a C
extension whose wheels stop at cp313, while the API image's base ships a later
Python. So the dependency is declared by the `identity` extra rather than as a
base dependency, and both identity modules guard their imports to say so.

Those guards carried `# pragma: no cover - install-shape guard`: the branch that
turns a bare `ModuleNotFoundError` into an actionable message was never
executed by any test. That is the half of the contract worth pinning, because
the wheel-import gate cannot cover it — `bare` mode deliberately omits
`maistro.identity` from its surface (importing it there *should* fail), and
`all` mode installs the extra, so the failure path exists in neither tier.

These tests simulate the bare install by blocking the import at the finder
level, which is the closest in-process equivalent of `pip install maistro-core`
with no extras.
"""

from __future__ import annotations

import importlib
import sys

import pytest

_GUARDED_ROOTS = ("bip_utils", "nacl")
_GUARDED_MODULES = (
    "maistro.identity",
    "maistro.identity.lifecycle",
)


class _BlockRoot:
    """A meta-path finder that makes one top-level package un-importable.

    Raises from `find_spec` rather than returning None so the failure is a
    `ModuleNotFoundError` naming the module, exactly as a genuinely absent
    distribution produces.
    """

    def __init__(self, blocked: str) -> None:
        self._blocked = blocked

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname.split(".")[0] == self._blocked:
            raise ModuleNotFoundError(f"No module named {self._blocked!r}", name=self._blocked)
        return None


@pytest.fixture
def bare_install(monkeypatch):
    """Yield a callable that blocks `root` and re-imports `module` from scratch.

    Uses monkeypatch's delitem/setattr for every mutation so `sys.modules` and
    `sys.meta_path` are restored even on failure. Popping entries by hand and
    restoring them at the end of the test body is how a previous fixture in this
    repo silently corrupted every later test in the session.
    """

    def _attempt(module: str, root: str):
        for name in list(sys.modules):
            if name.split(".")[0] in _GUARDED_ROOTS or name in _GUARDED_MODULES:
                monkeypatch.delitem(sys.modules, name, raising=False)
        monkeypatch.setattr(sys, "meta_path", [_BlockRoot(root), *sys.meta_path])
        return importlib.import_module(module)

    return _attempt


@pytest.mark.parametrize("module", _GUARDED_MODULES)
@pytest.mark.parametrize("root", _GUARDED_ROOTS)
def test_import_without_extra_names_the_extra(bare_install, module, root):
    with pytest.raises(ImportError) as exc:
        bare_install(module, root)

    message = str(exc.value)
    # ModuleNotFoundError subclasses ImportError, so `raises(ImportError)` alone
    # would also pass on the unguarded failure this test exists to rule out.
    # Asserting the install command is what distinguishes guarded from bare.
    assert "maistro-core[identity]" in message, (
        f"{module} raised an unguarded import error for {root!r}; the guard that "
        "names the 'identity' extra did not fire"
    )
    assert root in message, f"{module}'s guard did not report which module was missing"


@pytest.mark.parametrize("module", _GUARDED_MODULES)
def test_import_succeeds_when_extra_is_installed(module):
    """Control: the guard is not tripping in this environment.

    Without this, the tests above would still pass if `maistro.identity` were
    broken for some entirely unrelated reason.
    """
    assert importlib.import_module(module) is not None
