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

#1879 extends this module (no parallel helper) with the selected-call
half: :func:`validate_model_call`, the pure internal-consistency validator
for exactly one selected completed model Invocation and its original
physical dispatch, reusing the same parser, pointer builder, error-code
vocabulary and :class:`Report` below.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

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

    def __init__(self, mode: str, codes: frozenset[str] | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        self.mode = mode
        # ``codes`` is the (#1879) extension hook: the envelope vocabulary
        # stays exactly ``ERROR_CODES`` (its closed-vocabulary pin still
        # holds), while another document kind validated by this same Report
        # can bring its own closed vocabulary.
        self._codes = ERROR_CODES if codes is None else codes
        self._errors: list[dict[str, str]] = []

    def add(self, code: str, path: str) -> None:
        if code not in self._codes:
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


# ---------------------------------------------------------------------------
# selected completed model Invocation, v1 (#1879)
#
# The pure internal-consistency validator for exactly one selected completed
# model Invocation and its original physical dispatch. Reuses this module's
# duplicate-key parser, pointer builder, error-code vocabulary and Report —
# no parallel helper. It is consistency proof only: not provider
# authenticity, not complete Agent-turn accounting (valid tool calls
# elsewhere in the turn may use unrelated providers), not Warden/Sentinel
# enforcement (matching opaque IDs cannot establish authorization), not
# restart proof, and not #87 closure.
#
# First-error discipline: after schema validation, semantic invariants run
# in a fixed order (invocation state; request->Run identity; Run
# scope/actor; NodeRun; Attempt; Invocation; Binding; dispatch;
# provider/model; response; usage) and the report carries exactly the first
# failure, at its JSON pointer (RFC 6901). Provider/model and
# usage-provenance mismatches are always reported against the /dispatch
# side: the dispatch is the record under test; invocation.binding and
# expected_model are its references.
# ---------------------------------------------------------------------------

#: Selected-call error codes (#1879): one per ordered join/state/response/
#: usage invariant. UNSUPPORTED_INVOCATION_STATE covers the *known*
#: non-completed canonical states; a misspelled or mistyped status fails
#: SCHEMA_INVALID instead, and text that does not parse fails INVALID_JSON.
UNSUPPORTED_INVOCATION_STATE = "UNSUPPORTED_INVOCATION_STATE"
REQUEST_RUN_MISMATCH = "REQUEST_RUN_MISMATCH"
RUN_SCOPE_MISMATCH = "RUN_SCOPE_MISMATCH"
ACTOR_MISMATCH = "ACTOR_MISMATCH"
NODE_RUN_LINK_MISMATCH = "NODE_RUN_LINK_MISMATCH"
ATTEMPT_LINK_MISMATCH = "ATTEMPT_LINK_MISMATCH"
INVOCATION_LINK_MISMATCH = "INVOCATION_LINK_MISMATCH"
BINDING_SCOPE_MISMATCH = "BINDING_SCOPE_MISMATCH"
DISPATCH_LINK_MISMATCH = "DISPATCH_LINK_MISMATCH"
PROVIDER_MISMATCH = "PROVIDER_MISMATCH"
MODEL_MISMATCH = "MODEL_MISMATCH"
STUB_RESPONSE = "STUB_RESPONSE"
RESULT_MISSING = "RESULT_MISSING"
USAGE_PROVENANCE_MISSING = "USAGE_PROVENANCE_MISSING"

#: The selected-call vocabulary (#1879) — closed like the envelope's, but
#: separate: #1878's ``test_error_code_vocabulary_is_closed`` pins
#: ``ERROR_CODES`` to the envelope's 13 codes, so the selected-call codes
#: live in their own set passed to :class:`Report`. INVALID_JSON and
#: SCHEMA_INVALID are shared: parsing and schema layers mean the same thing
#: in both document kinds.
MODEL_CALL_ERROR_CODES = frozenset(
    {
        INVALID_JSON,
        SCHEMA_INVALID,
        UNSUPPORTED_INVOCATION_STATE,
        REQUEST_RUN_MISMATCH,
        RUN_SCOPE_MISMATCH,
        ACTOR_MISMATCH,
        NODE_RUN_LINK_MISMATCH,
        ATTEMPT_LINK_MISMATCH,
        INVOCATION_LINK_MISMATCH,
        BINDING_SCOPE_MISMATCH,
        DISPATCH_LINK_MISMATCH,
        PROVIDER_MISMATCH,
        MODEL_MISMATCH,
        STUB_RESPONSE,
        RESULT_MISSING,
        USAGE_PROVENANCE_MISSING,
    }
)

#: The exact v1 schema for the selected-call evidence object.
MODEL_CALL_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "testing"
    / "installed-workspace-model-call.schema.json"
)

#: The only Invocation state this successful-call validator supports. Every
#: other canonical InvocationStatus value is a known state reported as
#: UNSUPPORTED_INVOCATION_STATE; anything outside the canonical set fails
#: schema validation as SCHEMA_INVALID instead.
SUPPORTED_INVOCATION_STATE = "completed"

_MODEL_CALL_SCHEMA_CACHE: dict[str, Any] = {}


def _model_call_schema() -> dict[str, Any]:
    """Load (and cache) the checked-in v1 selected-call schema."""
    if not _MODEL_CALL_SCHEMA_CACHE:
        _MODEL_CALL_SCHEMA_CACHE.update(
            json.loads(MODEL_CALL_SCHEMA_PATH.read_text(encoding="utf-8"))
        )
    return _MODEL_CALL_SCHEMA_CACHE


def _schema_failure(document: Any) -> tuple[str, str] | None:
    """First structural failure under the v1 schema, deterministic by pointer."""
    validator = Draft202012Validator(_model_call_schema())
    errors = sorted(
        validator.iter_errors(document),
        key=lambda err: pointer(*err.absolute_path),
    )
    if not errors:
        return None
    first = errors[0]
    return (SCHEMA_INVALID, pointer(*first.absolute_path))


def _cost_finite_failure(document: Mapping[str, Any]) -> tuple[str, str] | None:
    """Reject non-finite cost_cents that schema ``minimum`` cannot see.

    ``float("nan")`` compares False against every bound, so a document handed
    over as a Python object (no parser pass) could carry NaN cost through
    schema validation. Finiteness is a stated v1 requirement, so it is
    enforced directly.
    """
    usage = document["invocation"]["usage"]
    if usage is None:
        return None
    cost = usage["cost_cents"]
    if cost is not None and not math.isfinite(cost):
        return (SCHEMA_INVALID, "/invocation/usage/cost_cents")
    return None


def _model_call_report() -> Report:
    """A structural Report validated against the selected-call vocabulary."""
    return Report("structural", codes=MODEL_CALL_ERROR_CODES)


def _invalid_json() -> dict[str, Any]:
    report = _model_call_report()
    report.add(INVALID_JSON, "/")
    return report.as_dict()


def _check_invocation_state(invocation: Mapping[str, Any]) -> tuple[str, str] | None:
    status = invocation["status"]
    if status != SUPPORTED_INVOCATION_STATE:
        return (UNSUPPORTED_INVOCATION_STATE, "/invocation/status")
    return None


def _check_request_run(
    request: Mapping[str, Any], run: Mapping[str, Any]
) -> tuple[str, str] | None:
    if request["run_id"] != run["run_id"]:
        return (REQUEST_RUN_MISMATCH, "/request/run_id")
    for field in ("workspace_id", "project_id"):
        if request[field] != run[field]:
            return (RUN_SCOPE_MISMATCH, f"/request/{field}")
    if request["actor_principal_id"] != run["actor_principal_id"]:
        # Actor is provenance, not authorization: a mismatch is reported as a
        # join failure, and no security field is part of this evidence.
        return (ACTOR_MISMATCH, "/request/actor_principal_id")
    return None


def _check_node_run_link(
    node_run: Mapping[str, Any], run: Mapping[str, Any]
) -> tuple[str, str] | None:
    if node_run["run_id"] != run["run_id"]:
        return (NODE_RUN_LINK_MISMATCH, "/node_run/run_id")
    return None


def _check_attempt_link(
    attempt: Mapping[str, Any], node_run: Mapping[str, Any]
) -> tuple[str, str] | None:
    if attempt["node_run_id"] != node_run["node_run_id"]:
        return (ATTEMPT_LINK_MISMATCH, "/attempt/node_run_id")
    return None


def _check_invocation_link(
    invocation: Mapping[str, Any],
    run: Mapping[str, Any],
    node_run: Mapping[str, Any],
    attempt: Mapping[str, Any],
) -> tuple[str, str] | None:
    joins = (
        ("run_id", run["run_id"]),
        ("node_run_id", node_run["node_run_id"]),
        ("attempt_id", attempt["attempt_id"]),
        ("workspace_id", run["workspace_id"]),
        ("project_id", run["project_id"]),
    )
    for field, expected in joins:
        if invocation[field] != expected:
            return (INVOCATION_LINK_MISMATCH, f"/invocation/{field}")
    return None


def _check_binding_scope(invocation: Mapping[str, Any]) -> tuple[str, str] | None:
    binding = invocation["binding"]
    for field in ("workspace_id", "project_id"):
        if binding[field] != invocation[field]:
            return (BINDING_SCOPE_MISMATCH, f"/invocation/binding/{field}")
    return None


def _check_dispatch_link(
    dispatch: Mapping[str, Any], invocation: Mapping[str, Any]
) -> tuple[str, str] | None:
    if dispatch["invocation_id"] != invocation["invocation_id"]:
        return (DISPATCH_LINK_MISMATCH, "/dispatch/invocation_id")
    return None


def _check_provider_model(
    dispatch: Mapping[str, Any],
    binding: Mapping[str, Any],
    expected_model: Mapping[str, Any],
) -> tuple[str, str] | None:
    if dispatch["provider_name"] != binding["provider_name"]:
        return (PROVIDER_MISMATCH, "/dispatch/provider_name")
    if dispatch["provider_name"] != expected_model["provider_name"]:
        return (PROVIDER_MISMATCH, "/dispatch/provider_name")
    if dispatch["requested_model"] != expected_model["requested_model"]:
        return (MODEL_MISMATCH, "/dispatch/requested_model")
    return None


def _check_response(dispatch: Mapping[str, Any]) -> tuple[str, str] | None:
    if dispatch["response_kind"] != "provider":
        return (STUB_RESPONSE, "/dispatch/response_kind")
    if dispatch["result_present"] is not True:
        return (RESULT_MISSING, "/dispatch/result_present")
    return None


def _check_usage(
    dispatch: Mapping[str, Any], invocation: Mapping[str, Any]
) -> tuple[str, str] | None:
    """usage is null iff usage_provenance.source is unavailable.

    With a reported/estimated source the canonical usage must be present and
    the evidence_ref nonblank. No cost is fabricated either way: canonical
    cost_cents staying null is exactly the unmeasured-cost case.
    """
    usage = invocation["usage"]
    provenance = dispatch["usage_provenance"]
    unavailable = provenance["source"] == "unavailable"
    if (usage is None) != unavailable:
        if usage is None:
            return (USAGE_PROVENANCE_MISSING, "/invocation/usage")
        return (USAGE_PROVENANCE_MISSING, "/dispatch/usage_provenance/source")
    if usage is not None:
        evidence_ref = provenance["evidence_ref"]
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            return (USAGE_PROVENANCE_MISSING, "/dispatch/usage_provenance/evidence_ref")
    return None


def _first_invariant_failure(document: Mapping[str, Any]) -> tuple[str, str] | None:
    """Apply the stable invariant order; return the first failure, if any."""
    ordered_checks = (
        lambda: _check_invocation_state(document["invocation"]),
        lambda: _check_request_run(document["request"], document["run"]),
        lambda: _check_node_run_link(document["node_run"], document["run"]),
        lambda: _check_attempt_link(document["attempt"], document["node_run"]),
        lambda: _check_invocation_link(
            document["invocation"],
            document["run"],
            document["node_run"],
            document["attempt"],
        ),
        lambda: _check_binding_scope(document["invocation"]),
        lambda: _check_dispatch_link(document["dispatch"], document["invocation"]),
        lambda: _check_provider_model(
            document["dispatch"],
            document["invocation"]["binding"],
            document["expected_model"],
        ),
        lambda: _check_response(document["dispatch"]),
        lambda: _check_usage(document["dispatch"], document["invocation"]),
    )
    for check in ordered_checks:
        failure = check()
        if failure is not None:
            return failure
    return None


def validate_model_call(
    document: Mapping[str, Any] | str | bytes | bytearray,
) -> dict[str, Any]:
    """Validate one selected completed model Invocation (pure helper, #1879).

    Accepts the evidence object itself or its JSON text (parsed with this
    module's duplicate-key parser). Returns the shared versioned Report in
    structural mode: ``{schema_version, valid, mode, errors}`` with at most
    the first failure. The input document is never mutated, completed, or
    rewritten to fit the join shape; a retry reusing an already completed
    Invocation re-proves the same joins against the same original dispatch
    and Attempt evidence -- no new dispatch or Invocation is required or
    invented here.
    """
    report = _model_call_report()
    if isinstance(document, (str, bytes, bytearray)):
        text = document.decode("utf-8") if not isinstance(document, str) else document
        try:
            document = parse_json_object(text)
        except DuplicateKeyError:
            return _invalid_json()
        except ValueError:
            # json.JSONDecodeError and the parser's non-JSON-constant refusal.
            return _invalid_json()
    if not isinstance(document, Mapping):
        report = _model_call_report()
        report.add(SCHEMA_INVALID, "/")
        return report.as_dict()
    # Deliberately lazy: no semantic rule may run unless the schema pass
    # already succeeded (and the finite-cost guard needs the schema's shape
    # too), so each candidate failure is computed only when reached.
    failure = _schema_failure(document)
    if failure is None:
        failure = _cost_finite_failure(document)
    if failure is None:
        failure = _first_invariant_failure(document)
    if failure is not None:
        report.add(*failure)
    return report.as_dict()
