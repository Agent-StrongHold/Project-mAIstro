"""`pdf_path` is a caller-supplied filesystem path, so the route decides what
it may name before anything opens it.

The preflight root defaults to the platform temp directory, which is
world-writable: anyone with a shell on the host can plant a symlink there.
That makes a lexical prefix check the wrong instrument — every component of
``<tmp>/innocent.pdf`` reads as legal and its target need not be. Containment
is decided on the *resolved* path, and the resolved path is what is handed to
the reader, so the file opened is the file the check approved.

Kept apart from ``test_preflight.py``, which builds fixture PDFs and therefore
needs reportlab; these need nothing but the module.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from server.lulu import service


def test_a_path_inside_the_root_is_accepted(tmp_path: Path) -> None:
    with patch.object(service, "PREFLIGHT_ROOT", str(tmp_path.resolve())):
        pdf = tmp_path / "interior.pdf"
        assert service._preflight_path(str(pdf)) == str(pdf.resolve())


def test_the_root_itself_is_accepted(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    with patch.object(service, "PREFLIGHT_ROOT", root):
        assert service._preflight_path(root) == root


def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with (
        patch.object(service, "PREFLIGHT_ROOT", str(root.resolve())),
        pytest.raises(HTTPException) as excinfo,
    ):
        service._preflight_path(str(tmp_path / "elsewhere.pdf"))
    assert excinfo.value.status_code == 400


def test_a_traversal_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with (
        patch.object(service, "PREFLIGHT_ROOT", str(root.resolve())),
        pytest.raises(HTTPException),
    ):
        service._preflight_path(str(root / ".." / "secret.pdf"))


def test_a_sibling_whose_name_merely_starts_with_the_root_is_refused(tmp_path: Path) -> None:
    """`startswith(root)` without the separator would accept `<root>-evil`."""
    root = tmp_path / "root"
    root.mkdir()
    with (
        patch.object(service, "PREFLIGHT_ROOT", str(root.resolve())),
        pytest.raises(HTTPException),
    ):
        service._preflight_path(f"{root}-evil/interior.pdf")


def test_a_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    """The escape a lexical check passes. Nothing in the requested string says
    `..`; the link says it."""
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4\n")
    link = root / "innocent.pdf"
    link.symlink_to(secret)

    with (
        patch.object(service, "PREFLIGHT_ROOT", str(root.resolve())),
        pytest.raises(HTTPException) as excinfo,
    ):
        service._preflight_path(str(link))
    assert "preflight directory" in excinfo.value.detail


def test_a_root_that_is_itself_a_symlink_accepts_its_own_files(tmp_path: Path) -> None:
    """The default root is the platform temp directory, which is a symlink on
    some platforms (macOS `/tmp` -> `/private/tmp`). Holding the root
    unresolved while resolving the candidate would refuse every real export."""
    real = tmp_path / "real"
    real.mkdir()
    configured = tmp_path / "configured"
    configured.symlink_to(real, target_is_directory=True)

    with patch.object(service, "PREFLIGHT_ROOT", os.path.realpath(str(configured))):
        resolved = service._preflight_path(str(configured / "interior.pdf"))
    assert resolved == str((real / "interior.pdf").resolve())
