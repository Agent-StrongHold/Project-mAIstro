"""A module that declares a feature and implements none of it is not architecture (#618).

`quality/reachability-baseline.json` is the repository's claim about how much of
its own code is wired. Fourteen modules under `maistro/agents/` were counted in
it while containing a docstring and nothing else — `maistro/agents/cache.py` in
full was:

    \"\"\"Prompt LRU cache.\"\"\"

— or, for five package markers, not even that. Nothing imported them, and
nothing could have: there was no name to import. They were dispositioned
CONNECT, which #34 defines as terminating at a verified product entry point,
and no entry point can reach an empty file. So the baseline was overstating the
amount of real-but-unwired architecture by fourteen, in the flattering
direction.

The names made it worse than a miscount. The Conductor backend has a real
`agents/cache.py` and a real `agents/registry.py`; the empty ones sat exactly
where a reader looking for those would look, so "the prompt cache lives in
maistro/agents/cache.py" was a reasonable and wrong conclusion to draw.

This derives the set rather than listing them, so the check is about the
property and not about the files that happened to have it. That mattered twice:
the derived set was larger than the one found by reading, both times.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "packages" / "maistro-core" / "src" / "maistro" / "agents"


def _is_inert(node: ast.stmt) -> bool:
    """True when this statement defines nothing and does nothing.

    A docstring, a `pass`, a bare `...`, or `from __future__ import ...` — the
    conventions people reach for when a file has to exist and has nothing in it.
    Matching only string expressions would have let a placeholder through for
    the price of one future import, which is a gate that can be satisfied by
    typing (Codex, #618).
    """
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return isinstance(node.value.value, str) or node.value.value is Ellipsis
    if isinstance(node, ast.Pass):
        return True
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _is_placeholder(path: Path) -> bool:
    """True when nothing in the file defines anything.

    An `__init__.py` is exempt **only while the package holds something else**.
    An empty one beside real modules means "this directory is a package" and
    carries that meaning by existing; an empty one alone in an empty directory
    means nothing at all, and exempting it unconditionally would leave the
    baseline overstated in exactly the direction this check exists to prevent
    (Codex, #618).
    """
    if path.name == "__init__.py" and any(
        sibling.suffix == ".py" and sibling.name != "__init__.py"
        for sibling in path.parent.iterdir()
    ):
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return all(_is_inert(node) for node in tree.body)


def test_no_agent_module_is_a_docstring_and_nothing_else() -> None:
    placeholders = sorted(
        path.relative_to(ROOT).as_posix() for path in AGENTS.rglob("*.py") if _is_placeholder(path)
    )

    assert placeholders == [], (
        "these modules declare a feature and implement none of it; a name with no "
        "code behind it reads as architecture to every reader and every gate that "
        "counts modules:\n  " + "\n  ".join(placeholders)
    )


def test_a_no_op_statement_does_not_buy_a_pass(tmp_path: Path) -> None:
    """The gate must not be satisfiable by typing.

    Matching only string expressions meant one conventional
    `from __future__ import annotations` — or a `pass`, or a bare `...` — turned
    a placeholder into something the check waved through, while the module still
    defined nothing (Codex, #618).
    """
    for body in (
        '"""Prompt LRU cache."""\n\nfrom __future__ import annotations\n',
        '"""Prompt LRU cache."""\n\npass\n',
        '"""Prompt LRU cache."""\n\n...\n',
        "from __future__ import annotations\n",
    ):
        module = tmp_path / "cache.py"
        module.write_text(body, encoding="utf-8")

        assert _is_placeholder(module) is True, body


def test_an_empty_package_marker_is_a_placeholder_when_it_stands_over_nothing(
    tmp_path: Path,
) -> None:
    """An `__init__.py` earns its exemption from the package it marks.

    Beside real modules it means "this directory is a package" and carries that
    meaning by existing. Alone in an empty directory it means nothing at all,
    and exempting it unconditionally left the baseline overstated in exactly the
    direction this check exists to prevent (Codex, #618).
    """
    populated = tmp_path / "populated"
    populated.mkdir()
    (populated / "__init__.py").write_text("", encoding="utf-8")
    (populated / "real.py").write_text("VALUE = 1\n", encoding="utf-8")

    hollow = tmp_path / "hollow"
    hollow.mkdir()
    (hollow / "__init__.py").write_text("", encoding="utf-8")

    assert _is_placeholder(populated / "__init__.py") is False
    assert _is_placeholder(hollow / "__init__.py") is True


def test_the_detector_would_notice_one_coming_back(tmp_path: Path) -> None:
    """The control. Without it, a detector that found nothing anywhere would
    satisfy the test above while proving nothing."""
    placeholder = tmp_path / "cache.py"
    placeholder.write_text('"""Prompt LRU cache."""\n', encoding="utf-8")
    real = tmp_path / "real.py"
    real.write_text('"""Docstring, then code."""\n\nVALUE = 1\n', encoding="utf-8")
    marker = tmp_path / "__init__.py"
    marker.write_text("", encoding="utf-8")

    assert _is_placeholder(placeholder) is True
    assert _is_placeholder(real) is False
    # An empty `__init__.py` beside a real module means "this directory is a
    # package"; it is not a placeholder, and deleting it would break the package
    # below it. `real.py` above is that sibling — the exemption is earned, not
    # granted by the file name.
    assert _is_placeholder(marker) is False
