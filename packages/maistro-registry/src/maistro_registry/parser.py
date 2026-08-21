"""Markdown front-matter parser.

No external deps beyond `pyyaml` (already in `pyproject.toml`).
Format:

    ---
    key: value
    ---
    # body content

Returns:

- `front_matter=None` if the file has no opening `---` delimiter or if
  the opening has no closing match (treated as no front-matter).
- `front_matter={}` if the front-matter block is present but empty.
- A populated dict otherwise.

Raises `ValueError` on YAML errors or non-mapping front-matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_DELIM = "---\n"
_CLOSE = "\n---\n"


@dataclass(frozen=True)
class ParsedFile:
    path: Path
    front_matter: dict[str, Any] | None
    body: str


def parse_file(path: Path | str) -> ParsedFile:
    """Parse a markdown file with optional YAML front-matter."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    if not text.startswith(_DELIM):
        return ParsedFile(path=p, front_matter=None, body=text)

    rest = text[len(_DELIM) :]

    # Empty front-matter: opening "---\n" immediately followed by closing
    # "---\n" (no content between). Returns front_matter={} per the
    # docstring contract, not None.
    if rest.startswith(_DELIM):
        return ParsedFile(path=p, front_matter={}, body=rest[len(_DELIM) :])

    closing = rest.find(_CLOSE)
    if closing == -1:
        # opening but no closing delimiter — treat as no front-matter
        return ParsedFile(path=p, front_matter=None, body=text)

    fm_text = rest[:closing]
    body = rest[closing + len(_CLOSE) :]

    try:
        data = yaml.safe_load(fm_text) if fm_text.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{p}: invalid YAML in front-matter: {exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{p}: front-matter must be a YAML mapping, got {type(data).__name__}")

    return ParsedFile(path=p, front_matter=data, body=body)
