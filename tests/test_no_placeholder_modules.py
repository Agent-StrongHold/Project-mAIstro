"""A module that declares a feature and implements none of it is not architecture (#618).

`quality/reachability-baseline.json` is the repository's claim about how much of
its own code is wired. Six modules under `maistro/agents/` were counted in it
while containing a docstring and nothing else — `maistro/agents/cache.py` in
full was:

    \"\"\"Prompt LRU cache.\"\"\"

Nothing imported them, and nothing could have: there was no name to import. They
were dispositioned CONNECT, which #34 defines as terminating at a verified
product entry point, and no entry point can reach an empty file. So the baseline
was overstating the amount of real-but-unwired architecture by six, in the
flattering direction.

The names made it worse than a miscount. The Conductor backend has a real
`agents/cache.py` and a real `agents/registry.py`; the empty ones sat exactly
where a reader looking for those would look, so "the prompt cache lives in
maistro/agents/cache.py" was a reasonable and wrong conclusion to draw.

This derives the set rather than listing the six, so the check is about the
property and not about the files that happened to have it.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "packages" / "maistro-core" / "src" / "maistro" / "agents"


def _is_placeholder(path: Path) -> bool:
    """True when the file's whole body is bare string expressions.

    A docstring and nothing else. `__init__.py` is exempt: an empty one is how
    Python is told a directory is a package, so it carries meaning by existing —
    which is exactly what the deleted modules did not.
    """
    if path.name == "__init__.py":
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )


def test_no_agent_module_is_a_docstring_and_nothing_else() -> None:
    placeholders = sorted(
        path.relative_to(ROOT).as_posix() for path in AGENTS.rglob("*.py") if _is_placeholder(path)
    )

    assert placeholders == [], (
        "these modules declare a feature and implement none of it; a name with no "
        "code behind it reads as architecture to every reader and every gate that "
        "counts modules:\n  " + "\n  ".join(placeholders)
    )


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
    # An empty `__init__.py` means "this directory is a package"; it is not a
    # placeholder, and deleting one would break the package below it.
    assert _is_placeholder(marker) is False
