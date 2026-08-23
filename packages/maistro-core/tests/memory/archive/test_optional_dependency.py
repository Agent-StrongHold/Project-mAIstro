"""`maistro-core` must import with the `[s3]` extra absent (#133, ADR §6).

This is the acceptance criterion that cannot be checked by reading the code: a
lazy import is only lazy until someone adds a convenience re-export at package
level, and the failure lands on every deployment that does not archive — which
is the default one, and the one least likely to be running this suite.

The tests hide `aioboto3` from `sys.modules` and the import system rather than
uninstalling it, so they assert the real property in an environment where the
extra happens to be installed. Without that, a suite running *with* the extra
proves nothing about a base install, which is exactly the gap this closes.
"""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest


@pytest.fixture
def without_aioboto3(monkeypatch):
    """Make `import aioboto3` (and botocore) fail, as on a base install."""
    hidden = ("aioboto3", "botocore", "boto3", "aiobotocore")
    for name in list(sys.modules):
        if name.split(".")[0] in hidden:
            monkeypatch.delitem(sys.modules, name, raising=False)
    # The S3 module is cached from an earlier test in the same session; drop it
    # so the next import genuinely re-executes and hits the blocked dependency.
    monkeypatch.delitem(sys.modules, "maistro.memory.archive.s3", raising=False)

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split(".")[0] in hidden:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


class TestBaseInstall:
    def test_the_archive_package_imports_without_the_extra(self, without_aioboto3):
        """The headline claim. A package-level `from .s3 import S3ArchiveStore`
        would fail here, which is the regression this exists to catch."""
        module = importlib.import_module("maistro.memory.archive")
        importlib.reload(module)
        assert module.FilesystemArchiveStore is not None

    def test_the_filesystem_store_works_without_the_extra(self, without_aioboto3, tmp_path):
        """Importing is not enough — the homelab path has to actually run."""
        module = importlib.reload(importlib.import_module("maistro.memory.archive"))
        store = module.FilesystemArchiveStore(tmp_path)
        assert store.root == tmp_path.resolve()

    def test_the_protocol_module_imports_without_the_extra(self, without_aioboto3):
        module = importlib.import_module("maistro.protocols.archive")
        importlib.reload(module)
        assert module.ArchiveStore is not None

    def test_asking_for_the_s3_store_names_the_extra(self, without_aioboto3):
        """An ImportError naming `aioboto3` sends the reader looking for a
        module they have never heard of. Naming the extra tells them what to
        install."""
        module = importlib.reload(importlib.import_module("maistro.memory.archive"))
        with pytest.raises(ImportError, match=r"maistro-core\[s3\]"):
            module.s3_archive_store(bucket="b")


class TestWithTheExtra:
    def test_the_s3_store_is_constructible_when_the_extra_is_present(self):
        """The other half: the lazy path must actually work when installed, or
        the extra is decoration."""
        pytest.importorskip("aioboto3")
        from maistro.memory.archive import s3_archive_store

        store = s3_archive_store(bucket="b", endpoint_url="http://example.invalid")
        assert store is not None

    def test_the_s3_module_is_not_imported_by_the_package(self):
        """`import maistro.memory.archive` must not pull the SDK in even when it
        is available — otherwise the laziness is untested in the environment
        where it is easiest to break."""
        for name in ("maistro.memory.archive", "maistro.memory.archive.s3", "aioboto3"):
            sys.modules.pop(name, None)
        importlib.import_module("maistro.memory.archive")
        assert "maistro.memory.archive.s3" not in sys.modules
        assert "aioboto3" not in sys.modules
