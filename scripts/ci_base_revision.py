#!/usr/bin/env python3
"""Resolve the immutable base revision for a GitHub CI event.

Pull-request and merge-queue checks must answer the same question: which exact
revision is this candidate replacing?  Keeping that answer in workflow
expressions made the semantics drift between checks.  This module is the one
fail-closed resolver for that decision.

Supported events:

- ``pull_request`` -> ``pull_request.base.sha``
- ``merge_group`` -> ``merge_group.base_sha``
- ``push`` -> ``before``

A missing, null, or malformed SHA is an error.  Callers that do not have a
meaningful base should not call this resolver rather than silently substituting
another ref.
"""

from __future__ import annotations

import json
import os
import string
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_HEX = frozenset(string.hexdigits)
_VALID_SHA_LENGTHS = {40, 64}


class BaseRevisionError(RuntimeError):
    """The current CI event does not provide one trustworthy base revision."""


def _read_mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BaseRevisionError(f"GitHub event field {field!r} is missing or is not an object")
    return value


def _read_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise BaseRevisionError(f"GitHub event field {field!r} is missing or is not a SHA")
    sha = value.strip()
    if len(sha) not in _VALID_SHA_LENGTHS or any(ch not in _HEX for ch in sha):
        raise BaseRevisionError(
            f"GitHub event field {field!r} is not a valid commit SHA: {value!r}"
        )
    if set(sha) == {"0"}:
        raise BaseRevisionError(
            f"GitHub event field {field!r} is git's null SHA, not a base revision"
        )
    return sha.lower()


def resolve_base_revision(event_name: str, payload: Mapping[str, Any]) -> str:
    """Return the event's immutable base SHA or raise ``BaseRevisionError``."""
    if event_name == "pull_request":
        pull_request = _read_mapping(payload.get("pull_request"), field="pull_request")
        base = _read_mapping(pull_request.get("base"), field="pull_request.base")
        return _read_sha(base.get("sha"), field="pull_request.base.sha")

    if event_name == "merge_group":
        merge_group = _read_mapping(payload.get("merge_group"), field="merge_group")
        return _read_sha(merge_group.get("base_sha"), field="merge_group.base_sha")

    if event_name == "push":
        return _read_sha(payload.get("before"), field="before")

    raise BaseRevisionError(
        f"GitHub event {event_name!r} has no defined base-revision contract; "
        "supported events are pull_request, merge_group, and push"
    )


def load_event_payload(path: Path) -> Mapping[str, Any]:
    """Read one GitHub event payload and require a JSON object at the root."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BaseRevisionError(f"could not read GitHub event payload {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BaseRevisionError(f"GitHub event payload {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise BaseRevisionError(f"GitHub event payload {path} is not a JSON object")
    return payload


def resolve_base_revision_from_env() -> str:
    """Resolve from ``GITHUB_EVENT_NAME`` and ``GITHUB_EVENT_PATH``."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_name:
        raise BaseRevisionError("GITHUB_EVENT_NAME is not set")
    if not event_path:
        raise BaseRevisionError("GITHUB_EVENT_PATH is not set")
    return resolve_base_revision(event_name, load_event_payload(Path(event_path)))


def main() -> int:
    try:
        print(resolve_base_revision_from_env())
    except BaseRevisionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
