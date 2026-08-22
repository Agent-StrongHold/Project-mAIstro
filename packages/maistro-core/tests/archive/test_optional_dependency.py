"""maistro-core imports with no cloud SDK installed (ADR-082226-f436 decision 4).

Stated as a rule rather than a preference because `maistro-core` is a library
other products import (ADR-019): a transitive boto3 is a large, opinionated
dependency to inflict on a consumer that wanted a router.

The subprocess is the point. Within one interpreter boto3 is already in
`sys.modules` — this suite installs it — so an accidental module-scope import
would be invisible here and would only appear on a consumer's clean install.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import maistro

_SRC = str(pathlib.Path(maistro.__file__).resolve().parent.parent)


def _run(statement: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


#: Makes boto3 unimportable for the child, whatever is installed.
_BLOCK_BOTO3 = (
    "import sys\n"
    "class _Blocked:\n"
    "    def find_module(self, name, path=None):\n"
    "        return self if name.split('.')[0] in ('boto3', 'botocore') else None\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name.split('.')[0] in ('boto3', 'botocore'):\n"
    "            raise ImportError(f'blocked: {name}')\n"
    "        return None\n"
    "sys.meta_path.insert(0, _Blocked())\n"
)


def test_the_package_imports_without_boto3() -> None:
    result = _run(_BLOCK_BOTO3 + "import maistro.archive as a; assert a.FilesystemArchiveStore")

    assert result.returncode == 0, result.stderr


def test_the_filesystem_backend_works_without_boto3() -> None:
    statement = _BLOCK_BOTO3 + (
        "import asyncio, tempfile\n"
        "from maistro.archive import FilesystemArchiveStore\n"
        "async def main():\n"
        "    with tempfile.TemporaryDirectory() as root:\n"
        "        store = FilesystemArchiveStore(root)\n"
        "        key = await store.put(b'payload', scope='learnings')\n"
        "        assert await store.get(key) == b'payload'\n"
        "asyncio.run(main())\n"
    )

    result = _run(statement)

    assert result.returncode == 0, result.stderr


def test_importing_the_package_does_not_import_boto3() -> None:
    """The lazy re-export must stay lazy: a module-scope import in
    `archive/__init__.py` would satisfy the test above and still pull boto3 into
    every consumer that touches `maistro.archive`."""
    result = _run("import sys, maistro.archive; assert 'boto3' not in sys.modules")

    assert result.returncode == 0, result.stderr


def test_asking_for_the_s3_backend_without_boto3_says_what_to_install() -> None:
    statement = _BLOCK_BOTO3 + (
        "from maistro.archive import S3ArchiveStore\n"
        "from maistro.archive.types import ArchiveError\n"
        "try:\n"
        "    S3ArchiveStore('bucket')\n"
        "except ArchiveError as exc:\n"
        '    assert "maistro-core[s3]" in str(exc), str(exc)\n'
        "else:\n"
        "    raise AssertionError('expected ArchiveError')\n"
    )

    result = _run(statement)

    assert result.returncode == 0, result.stderr


def test_an_unknown_attribute_still_raises_attribute_error() -> None:
    """The lazy `__getattr__` must not swallow typos into ImportErrors."""
    statement = (
        "import maistro.archive as a\n"
        "try:\n"
        "    a.NoSuchThing\n"
        "except AttributeError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('expected AttributeError')\n"
    )

    result = _run(statement)

    assert result.returncode == 0, result.stderr
