"""Shared corpus builder for the retrieval test suite.

Exposed as the `make_doc` fixture (not an importable helper — the root
conftest.py owns the `conftest` module name, so tests must not import
from this file): retrieval behavior has to be testable against a corpus
whose content *we* control (a ubiquitous term, a title-only term, a
KNOWN-GAPS layout), so each test states the corpus that makes its
assertion meaningful.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest

_FM_TEMPLATE = """---
id: {doc_id}
title: "{title}"
repo: maistro-engine
kind: {kind}
status: {status}
created: 2026-01-01
accepted: 2026-01-02
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: {layer}
owners: []
history: []
---

# {doc_id}: {title}

{body}
"""


class MakeDoc(Protocol):
    """Signature of the corpus writer handed to tests."""

    def __call__(
        self,
        root: Path,
        directory: str,
        filename: str,
        doc_id: str,
        title: str,
        *,
        kind: str = "adr",
        status: str = "Accepted",
        layer: str = "Foundation",
        body: str = "",
    ) -> Path: ...


def _write_doc(
    root: Path,
    directory: str,
    filename: str,
    doc_id: str,
    title: str,
    *,
    kind: str = "adr",
    status: str = "Accepted",
    layer: str = "Foundation",
    body: str = "",
) -> Path:
    """Write one valid front-matter document into a synthetic repo tree."""
    directory_path = root / directory
    directory_path.mkdir(parents=True, exist_ok=True)
    path = directory_path / filename
    path.write_text(
        _FM_TEMPLATE.format(
            doc_id=doc_id,
            title=title,
            kind=kind,
            status=status,
            layer=layer,
            body=body,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def make_doc() -> Callable[..., Path]:
    return _write_doc
