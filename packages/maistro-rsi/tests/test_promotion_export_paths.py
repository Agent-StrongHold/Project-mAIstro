"""Promotion exports must stay in the operator-selected export directory."""

from pathlib import Path

import pytest

from maistro_rsi.promotion_review import _export_patch


@pytest.mark.parametrize("stem", ["/../../x", "../evil", "x\\..\\x", ""])
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


def test_export_refuses_leaf_symlink_created_at_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "exports"
    outside = tmp_path / "outside.patch"
    outside.write_text("private patch")
    original_open = Path.open

    def plant_link(path: Path, *args: object, **kwargs: object):
        if path.name == "0001-approved-abc12345.patch":
            path.symlink_to(outside)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", plant_link)
    with pytest.raises(FileExistsError):
        _export_patch(export, "abc123456789", "candidate")
    assert outside.read_text() == "private patch"
