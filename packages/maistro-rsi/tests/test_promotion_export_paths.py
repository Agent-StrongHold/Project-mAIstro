"""Promotion exports must stay in the operator-selected export directory."""

import builtins
import os
from pathlib import Path

import pytest

from maistro_rsi.promotion_review import _authorized_export_roots, _export_patch


@pytest.mark.parametrize(
    "stem",
    ["/../../x", "../evil", "x\\..\\x", "", "has space", "semi;colon", "a" * 65],
)
def test_export_rejects_path_components(tmp_path: Path, stem: str) -> None:
    export = tmp_path / "exports"
    export.mkdir()
    # Make a traversal payload viable rather than merely hitting a missing parent.
    (export / "0001-approved-").mkdir()
    with pytest.raises(ValueError, match="stem"):
        _export_patch(export, stem, "untrusted patch")
    assert not (tmp_path / "x.patch").exists()


def test_export_rejects_existing_patch_symlink_escape(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    export.mkdir()
    outside = tmp_path / "outside.patch"
    outside.write_text("private patch")
    (export / "0001-approved-abc12345.patch").symlink_to(outside)
    with pytest.raises(ValueError, match="export directory"):
        _export_patch(export, "abc123456789", "candidate")
    assert outside.read_text() == "private patch"


def test_export_preserves_symlinked_root_and_idempotence(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    export = tmp_path / "exports"
    export.symlink_to(real, target_is_directory=True)
    result = _export_patch(export, "abc123456789", "candidate")
    assert result.resolve().parent == real
    assert result.read_text() == "candidate"
    assert _export_patch(export, "abc123456789", "second") == result
    assert result.read_text() == "candidate"


def test_authorized_export_roots_honor_env_pathsep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RSI_WORK_ROOT / RSI_EXPORT_ROOTS entries are realpath'd into the allowlist."""
    work = tmp_path / "work"
    a = tmp_path / "a"
    b = tmp_path / "b"
    for path in (work, a, b):
        path.mkdir()
    monkeypatch.setenv("RSI_WORK_ROOT", str(work))
    monkeypatch.setenv("RSI_EXPORT_ROOTS", f"{a}{os.pathsep}{b}{os.pathsep}")
    roots = _authorized_export_roots()
    assert os.path.realpath(str(work)) in roots
    assert os.path.realpath(str(a)) in roots
    assert os.path.realpath(str(b)) in roots


def test_export_rejects_directory_outside_authorized_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Export roots are the platform temp dir plus RSI_* env allowlists."""
    monkeypatch.delenv("RSI_WORK_ROOT", raising=False)
    monkeypatch.delenv("RSI_EXPORT_ROOTS", raising=False)
    # A private directory that is not under gettempdir() — simulate by
    # shrinking the authorized set to an empty sibling allowlist.
    outside = tmp_path / "outside-exports"
    outside.mkdir()
    allow = tmp_path / "only-here"
    allow.mkdir()
    monkeypatch.setenv("RSI_EXPORT_ROOTS", str(allow))
    # Also override tempdir root so tmp_path itself is not implicitly trusted
    # when it happens to live under the real platform temp directory.
    monkeypatch.setenv("RSI_WORK_ROOT", str(allow))
    monkeypatch.setattr(
        "maistro_rsi.promotion_review._authorized_export_roots",
        lambda: (os.path.realpath(str(allow)),),
    )
    with pytest.raises(ValueError, match="authorized export root"):
        _export_patch(outside, "abc123456789", "candidate")
    assert list(outside.glob("*.patch")) == []


def test_export_refuses_leaf_symlink_created_at_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "exports"
    outside = tmp_path / "outside.patch"
    outside.write_text("private patch")
    original_open = builtins.open

    def plant_link(path: object, *args: object, **kwargs: object):
        path_str = os.fspath(path)
        if str(path_str).endswith("0001-approved-abc12345.patch"):
            Path(path_str).symlink_to(outside)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", plant_link)
    with pytest.raises(FileExistsError):
        _export_patch(export, "abc123456789", "candidate")
    assert outside.read_text() == "private patch"
