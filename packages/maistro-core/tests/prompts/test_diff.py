"""Tests for the prompt diff engine."""

from __future__ import annotations

from maistro.prompts.diff import DiffLine, compute_diff


def _ops(lines: list[DiffLine]) -> list[tuple[str, str]]:
    return [(dl.op, dl.content) for dl in lines]


def test_removed_dashdashdash_line_is_remove_not_header() -> None:
    """A removed content line '---' must be op='remove', marker stripped."""
    old = "alpha\n---\nbeta\n"
    new = "alpha\nbeta\n"

    lines = compute_diff(old, new)

    # The '---' line was removed; it must be classified as a remove with the
    # leading diff marker stripped, NOT as a file header.
    removes = [dl for dl in lines if dl.op == "remove"]
    assert any(dl.content == "---" for dl in removes), _ops(lines)
    # It must NOT show up as a header carrying the un-stripped marker.
    assert not any(dl.op == "header" and dl.content == "----" for dl in lines), _ops(lines)


def test_added_plusplusplus_line_is_add_not_header() -> None:
    """An added content line '+++' must be op='add', marker stripped."""
    old = "alpha\nbeta\n"
    new = "alpha\n+++\nbeta\n"

    lines = compute_diff(old, new)

    adds = [dl for dl in lines if dl.op == "add"]
    assert any(dl.content == "+++" for dl in adds), _ops(lines)
    assert not any(dl.op == "header" and dl.content == "++++" for dl in lines), _ops(lines)


def test_line_numbers_do_not_drift_after_dashdashdash_removal() -> None:
    """Line numbers must keep advancing through a removed '---' content line."""
    old = "alpha\n---\nbeta\ngamma\n"
    new = "alpha\nbeta\ngamma\n"

    lines = compute_diff(old, new)

    # Find the removed '---' line and the surviving context/added lines after it.
    remove_dashes = next(dl for dl in lines if dl.op == "remove" and dl.content == "---")
    assert remove_dashes.old_lineno is not None

    # The removed '---' is the 2nd old line, so old_lineno == 2.
    assert remove_dashes.old_lineno == 2, _ops(lines)

    # 'gamma' is a context line; with the removal accounted for, its old_lineno
    # must be 4 (alpha=1, ---=2, beta=3, gamma=4) and new_lineno 3.
    gamma = next(dl for dl in lines if dl.content == "gamma")
    assert gamma.old_lineno == 4, _ops(lines)
    assert gamma.new_lineno == 3, _ops(lines)


def test_real_file_headers_still_classified_as_header() -> None:
    """Genuine '--- '/'+++ ' file headers must remain op='header'."""
    old = "alpha\n"
    new = "beta\n"

    lines = compute_diff(old, new, old_label="previous", new_label="current")

    headers = [dl for dl in lines if dl.op == "header"]
    # difflib emits '--- previous' and '+++ current' file headers.
    assert any(dl.content.startswith("--- ") for dl in headers), _ops(lines)
    assert any(dl.content.startswith("+++ ") for dl in headers), _ops(lines)
    # And the @@ hunk header.
    assert any(dl.content.startswith("@@") for dl in headers), _ops(lines)
