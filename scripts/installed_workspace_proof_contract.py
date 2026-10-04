"""Shared contract for the installed-workspace release-proof envelope (#1878).

Owned by this envelope leaf: the CLI validator
(``validate-installed-workspace-proof.py``) and its tests
(``tests/release/test_installed_workspace_proof_schema.py``) both import this
module, so the duplicate-key parser, the error-code vocabulary and the report
assembly cannot drift between the gate and the evidence that pins it.

The envelope distinguishes structurally valid evidence from a complete
observed release-proof envelope. Passing it never asserts that a run
occurred, that evidence is authentic, or that live security or provider
behavior passed — only that the envelope is well-formed (``structural``) and,
in ``closeout`` mode, that every mandatory family passed and the evidence is
not synthetic.
"""

from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = 1

#: The two validation modes. ``structural`` accepts non-PASS scenario rows as
#: evidence; ``closeout`` additionally requires every family to PASS, the
#: browser subcheck to agree with the reviewed profile, and the evidence to be
#: observed rather than synthetic.
MODES = ("structural", "closeout")

#: The five mandatory scenario families, in canonical stage order. Exactly one
#: row per family is required, and no reviewed-profile option can waive one:
#: the profile schema (``docs/testing/installed-workspace-proof.schema.json``)
#: defines no such property, and the validator derives nothing from the bundle
#: being validated.
SCENARIO_IDS = ("INSTALL", "EXECUTE", "RESTART", "ISOLATE", "FAIL-CLOSED")

#: The single mandatory subcheck.
SUBCHECK_IDS = ("BROWSER_LOGIN",)

#: Payload files every manifest must list (additional listed payloads are
#: allowed). ``results.json`` itself is required in the listing too, but it is
#: never admissible as an ``evidence_paths`` entry.
REQUIRED_PAYLOADS = (
    "install.log",
    "effective-config.json",
    "execution.json",
    "restart.json",
    "isolation.json",
    "junit.xml",
)

#: Bundle control documents by their diagnostics label. The external profile
#: is a control input like the manifest, not bundle evidence.
MANIFEST_NAME = "manifest.json"
RESULTS_NAME = "results.json"
PROFILE_LABEL = "profile"

#: Bundle control inputs that are never admissible ``evidence_paths``
#: entries. ``manifest.json`` is not listed in ``files`` at all;
#: ``results.json`` is listed but is the document under validation, so citing
#: it as its own evidence would let a bundle approve itself. The external
#: reviewed profile is likewise inadmissible; the validator adds the supplied
#: profile path and its basename to this pair, since only it knows that path.
INADMISSIBLE_EVIDENCE = (MANIFEST_NAME, RESULTS_NAME)

# The report's closed error-code vocabulary.
INVALID_JSON = "INVALID_JSON"
SCHEMA_INVALID = "SCHEMA_INVALID"
DUPLICATE_SCENARIO = "DUPLICATE_SCENARIO"
DUPLICATE_FILE = "DUPLICATE_FILE"
PROFILE_MISMATCH = "PROFILE_MISMATCH"
CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"
INVALID_APPLICABILITY = "INVALID_APPLICABILITY"
EVIDENCE_PATH_UNSAFE = "EVIDENCE_PATH_UNSAFE"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
EVIDENCE_UNLISTED = "EVIDENCE_UNLISTED"
EVIDENCE_HASH_MISMATCH = "EVIDENCE_HASH_MISMATCH"
REQUIRED_SCENARIO_NOT_PASS = "REQUIRED_SCENARIO_NOT_PASS"
SYNTHETIC_NOT_CLOSEOUT = "SYNTHETIC_NOT_CLOSEOUT"

ERROR_CODES = frozenset(
    {
        INVALID_JSON,
        SCHEMA_INVALID,
        DUPLICATE_SCENARIO,
        DUPLICATE_FILE,
        PROFILE_MISMATCH,
        CANDIDATE_MISMATCH,
        INVALID_APPLICABILITY,
        EVIDENCE_PATH_UNSAFE,
        EVIDENCE_MISSING,
        EVIDENCE_UNLISTED,
        EVIDENCE_HASH_MISMATCH,
        REQUIRED_SCENARIO_NOT_PASS,
        SYNTHETIC_NOT_CLOSEOUT,
    }
)


class DuplicateKeyError(ValueError):
    """A JSON object defined the same key twice — invalid, not last-wins."""


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        seen[key] = value
    return seen


def _reject_non_json_constants(value: str) -> None:
    """Reject ``NaN``/``Infinity`` literals the stdlib parser would accept."""
    raise ValueError(f"not a JSON constant: {value}")


def parse_json_object(text: str) -> Any:
    """Parse JSON text, rejecting duplicate keys and non-JSON constants.

    Duplicate keys are INVALID_JSON rather than last-wins: a results document
    that defines ``scenarios`` twice must not have its second half silently
    taken as the whole truth.
    """
    return json.loads(
        text,
        object_pairs_hook=_object_pairs_no_duplicates,
        parse_constant=_reject_non_json_constants,
    )


def is_safe_relative_posix_path(path: str) -> bool:
    """Whether *path* is a normalized, nonempty, relative POSIX path.

    Rejects absolute paths, drive prefixes (``C:``/``c:`` — a no-op check on
    POSIX path APIs, so it is spelled out), backslashes, and empty, ``.`` or
    ``..`` components. Symlink/realpath escape is checked separately by the
    caller against the real bundle root, before any read or hash.
    """
    if not path or path.startswith("/") or "\\" in path:
        return False
    if _DRIVE_PREFIX.match(path):
        return False
    parts = path.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def pointer(*parts: Any) -> str:
    """A JSON pointer (RFC 6901) into one document, e.g. ``/scenarios/0/id``."""
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped)


def doc_path(label: str, *pointer_parts: Any) -> str:
    """A diagnostics path: the document label plus an optional JSON pointer.

    With no pointer parts the label alone names the whole document (used for
    file-level errors such as INVALID_JSON). The ``#`` joins them the way a
    URI-fragment pointer would, so every diagnostic names the file it
    belongs to without ambiguity across the three documents.
    """
    if not pointer_parts:
        return label
    return f"{label}#{pointer(*pointer_parts)}"


class Report:
    """Accumulates diagnostics for one validation run.

    The driver validates in the contract's stage order and stops at the first
    failing stage, so a finished report only ever carries diagnostics from a
    single stage — sorted by ``(path, code)`` and deduplicated, so the report
    is byte-identical for identical inputs regardless of dict iteration or
    filesystem enumeration order.
    """

    def __init__(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        self.mode = mode
        self._errors: list[dict[str, str]] = []

    def add(self, code: str, path: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {code!r}")
        self._errors.append({"code": code, "path": path})

    @property
    def failed(self) -> bool:
        return bool(self._errors)

    def as_dict(self) -> dict[str, Any]:
        unique = {(e["code"], e["path"]): e for e in self._errors}
        errors = sorted(unique.values(), key=lambda e: (e["path"], e["code"]))
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": not errors,
            "mode": self.mode,
            "errors": errors,
        }
