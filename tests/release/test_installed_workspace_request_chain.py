"""Request-chain proof for one selected completed model Invocation (#1879).

The validator under test (``validate_model_call`` in
``scripts/installed_workspace_proof_contract.py``) checks the internal
consistency of exactly one selected completed model Invocation, its original
physical dispatch, and the originating request/Run/NodeRun/Attempt records.
It is consistency proof only -- not provider authenticity, not complete turn
accounting, not Warden/Sentinel enforcement, not restart proof, and not the
#87 closure. It reuses the #1878 proof-envelope module's shared primitives
(duplicate-key parser, pointer builder, error-code vocabulary, ``Report``)
and returns that module's versioned report in structural mode:
``{schema_version, valid, mode, errors}`` with at most the first failure at
its JSON-pointer ``path``.

Completed-effect reuse: the test in :class:`TestCompletedEffectReuse` uses one
valid selected completed-call object for the original physical dispatch and
then validates the *unchanged* object again, standing in for a later admission
that reuses that completed effect. Both must pass without the validator
creating or inventing a new Invocation or provider dispatch. Note that
``logical_effect`` deduplication may span NodeRuns: this object's NodeRun and
Attempt are the original effect's provenance, not a claim that every reusing
consumer owns the effect. Exporting reuse-consumer relationships, all-call
accounting, authorization, and the complete installed same-request release
proof remain #87's broader integration contract.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "installed_workspace_proof_contract.py"
SCHEMA_PATH = ROOT / "docs" / "testing" / "installed-workspace-model-call.schema.json"

CANONICAL_INVOCATION_STATES = ("created", "running", "completed", "failed", "unknown")


@pytest.fixture(scope="module")
def contract():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("installed_workspace_proof_contract", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# fixtures and helpers
# ---------------------------------------------------------------------------


def valid_document() -> dict[str, Any]:
    """The exact v1 selected-model-call evidence object, fully consistent."""
    return {
        "schema_version": 1,
        "evidence_kind": "observed",
        "request": {
            "request_id": "req-01",
            "run_id": "run-01",
            "workspace_id": "ws-01",
            "project_id": "proj-01",
            "actor_principal_id": "principal-01",
            "agent_id": "agent-01",
        },
        "run": {
            "run_id": "run-01",
            "workspace_id": "ws-01",
            "project_id": "proj-01",
            "actor_principal_id": "principal-01",
        },
        "node_run": {
            "node_run_id": "nr-01",
            "run_id": "run-01",
            "node_id": "node-answer",
        },
        "attempt": {
            "attempt_id": "att-01",
            "node_run_id": "nr-01",
            "ordinal": 1,
        },
        "invocation": {
            "invocation_id": "inv-01",
            "run_id": "run-01",
            "node_run_id": "nr-01",
            "attempt_id": "att-01",
            "workspace_id": "ws-01",
            "project_id": "proj-01",
            "effect_key": "answer:primary",
            "logical_effect": True,
            "status": "completed",
            "binding": {
                "binding_id": "bind-01",
                "workspace_id": "ws-01",
                "project_id": "proj-01",
                "capability": "model.inference",
                "provider_name": "openai",
            },
            "usage": {
                "units": "tokens",
                "input_units": 120,
                "output_units": 45,
                "cost_cents": 0.25,
                "model": "gpt-5.3",
                "model_version": "gpt-5.3-2026-01-15",
                "provider": "openai",
            },
        },
        "dispatch": {
            "dispatch_id": "disp-01",
            "invocation_id": "inv-01",
            "provider_name": "openai",
            "requested_model": "gpt-5.3",
            "provider_request_id": "chatcmpl-123",
            "response_kind": "provider",
            "result_present": True,
            "usage_provenance": {
                "source": "reported",
                "evidence_ref": "provider:chatcmpl-123#usage",
            },
        },
        "expected_model": {
            "provider_name": "openai",
            "requested_model": "gpt-5.3",
        },
    }


def changed(dotted: str, value: Any) -> dict[str, Any]:
    """A valid document with exactly one existing field replaced."""
    document = valid_document()
    parent: Any = document
    *parents, leaf = dotted.split(".")
    for key in parents:
        parent = parent[key]
    assert leaf in parent, f"test bug: {dotted} does not exist in the fixture"
    parent[leaf] = value
    return document


def with_extra(dotted: str, value: Any) -> dict[str, Any]:
    """A valid document with exactly one extra field added."""
    document = valid_document()
    parent: Any = document
    *parents, leaf = dotted.split(".")
    for key in parents:
        parent = parent[key]
    assert leaf not in parent, f"test bug: {dotted} already exists in the fixture"
    parent[leaf] = value
    return document


def assert_valid(contract, document: Any) -> None:
    """Validate and require the empty-errors valid report."""
    report = contract.validate_model_call(document)
    assert report["valid"] is True, f"expected valid, got: {report}"
    assert report["errors"] == [], "first-error discipline: at most one entry"


def first_error(contract, document: Any) -> dict[str, Any]:
    """Validate and return the single first-error entry of the Report."""
    report = contract.validate_model_call(document)
    assert report["valid"] is False, f"expected failure, got: {report}"
    assert len(report["errors"]) == 1, "first-error discipline: at most one entry"
    return report["errors"][0]


def assert_code_and_pointer(contract, document: Any, code: str, pointer: str) -> None:
    error = first_error(contract, document)
    assert error["code"] == code, f"wrong code: {error}"
    assert error["path"] == pointer, f"wrong pointer: {error}"


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


class TestValidSelectedCall:
    def test_observed_call_with_reported_usage_validates(self, contract) -> None:
        report = contract.validate_model_call(valid_document())
        assert report == {
            "schema_version": 1,
            "mode": "structural",
            "valid": True,
            "errors": [],
        }

    def test_synthetic_evidence_kind_validates(self, contract) -> None:
        assert_valid(contract, changed("evidence_kind", "synthetic"))

    def test_usage_null_with_unavailable_source_validates(self, contract) -> None:
        document = changed("invocation.usage", None)
        document["dispatch"]["usage_provenance"] = {
            "source": "unavailable",
            "evidence_ref": None,
        }
        assert_valid(contract, document)

    def test_null_cost_with_reported_source_stays_valid(self, contract) -> None:
        # An unmeasured cost is absent, not zero: no required cost is
        # fabricated when canonical cost_cents is null.
        document = changed("invocation.usage.cost_cents", None)
        assert_valid(contract, document)

    def test_absent_provider_request_id_validates(self, contract) -> None:
        # Provider request IDs may be absent.
        assert_valid(contract, changed("dispatch.provider_request_id", None))

    def test_model_version_may_differ_from_requested_alias(self, contract) -> None:
        # usage.model_version is the concrete version the provider reported;
        # it must never be assumed equal to the requested alias, and neither
        # usage.model nor usage.model_version is a join key here.
        document = changed("invocation.usage.model_version", "snapshot-2026-02-01")
        document["invocation"]["usage"]["model"] = "gpt-5.3-real"
        assert_valid(contract, document)

    def test_ordinal_beyond_one_validates(self, contract) -> None:
        # Nothing here requires one Invocation per Attempt or ordinal == 1.
        assert_valid(contract, changed("attempt.ordinal", 3))

    def test_json_text_input_uses_the_envelope_parser(self, contract) -> None:
        assert_valid(contract, json.dumps(valid_document()))

    def test_estimated_usage_with_evidence_ref_validates(self, contract) -> None:
        document = changed("dispatch.usage_provenance.source", "estimated")
        assert_valid(contract, document)


# ---------------------------------------------------------------------------
# the shared versioned Report and purity
# ---------------------------------------------------------------------------


class TestReportShapeAndPurity:
    def test_report_is_versioned_and_structural(self, contract) -> None:
        report = contract.validate_model_call(valid_document())
        assert set(report) == {"schema_version", "mode", "valid", "errors"}
        assert report["schema_version"] == 1
        assert report["mode"] == "structural"

    def test_validation_does_not_mutate_or_complete_the_document(self, contract) -> None:
        document = valid_document()
        snapshot = copy.deepcopy(document)
        contract.validate_model_call(document)
        assert document == snapshot, "the validator must stay pure"

    def test_repeated_validation_is_deterministic(self, contract) -> None:
        document = valid_document()
        assert contract.validate_model_call(document) == contract.validate_model_call(document)

    def test_selected_call_codes_live_outside_the_envelope_vocabulary(self, contract) -> None:
        # #1878 pins ERROR_CODES to exactly the envelope's 13 codes, so the
        # selected-call codes live in their own closed set passed to Report.
        # The default Report must still enforce the envelope vocabulary, and
        # the selected-call Report must accept every selected-call code.
        envelope = set(contract.ERROR_CODES)
        selected = set(contract.MODEL_CALL_ERROR_CODES)
        assert {"INVALID_JSON", "SCHEMA_INVALID"} <= selected
        assert envelope.isdisjoint(selected - {"INVALID_JSON", "SCHEMA_INVALID"})
        for code in ("REQUEST_RUN_MISMATCH", "STUB_RESPONSE", "USAGE_PROVENANCE_MISSING"):
            assert code not in envelope
            with pytest.raises(ValueError, match="unknown error code"):
                contract.Report("structural").add(code, "/")
            contract.Report("structural", codes=selected).add(code, "/")

    def test_non_object_document_is_schema_invalid(self, contract) -> None:
        # Parseable JSON, but not an object: the schema's root type rejects it
        # at the document root.
        assert_code_and_pointer(contract, [valid_document()], "SCHEMA_INVALID", "/")

    def test_envelope_parser_rejects_duplicate_keys(self, contract) -> None:
        with pytest.raises(contract.DuplicateKeyError):
            contract.parse_json_object('{"a": 1, "a": 2}')

    def test_duplicate_key_document_is_invalid_json(self, contract) -> None:
        # The envelope's duplicate-key parser, not the dict, must see both
        # copies of a doubled key: a duplicated key is INVALID_JSON before any
        # schema or join rule runs.
        text = json.dumps(valid_document())
        doubled = text.replace(
            '"evidence_kind": "observed",',
            '"evidence_kind": "observed", "evidence_kind": "observed",',
            1,
        )
        assert doubled != text
        with pytest.raises(contract.DuplicateKeyError):
            contract.parse_json_object(doubled)
        error = first_error(contract, doubled)
        assert error == {"code": contract.INVALID_JSON, "path": "/"}

    def test_non_finite_constant_in_text_is_invalid_json(self, contract) -> None:
        text = json.dumps(valid_document()).replace('"cost_cents": 0.25', '"cost_cents": NaN')
        error = first_error(contract, text)
        assert error == {"code": contract.INVALID_JSON, "path": "/"}


# ---------------------------------------------------------------------------
# schema strictness (SCHEMA_INVALID, not semantic codes)
# ---------------------------------------------------------------------------


class TestSchemaStrictness:
    def test_extra_top_level_field_rejected(self, contract) -> None:
        assert_code_and_pointer(contract, with_extra("extra", 1), "SCHEMA_INVALID", "/")

    def test_extra_nested_field_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract, with_extra("invocation.extra", 1), "SCHEMA_INVALID", "/invocation"
        )

    def test_missing_object_rejected(self, contract) -> None:
        document = valid_document()
        del document["dispatch"]
        assert_code_and_pointer(contract, document, "SCHEMA_INVALID", "/")

    def test_blank_structural_id_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract, changed("run.run_id", "   "), "SCHEMA_INVALID", "/run/run_id"
        )

    def test_whitespace_only_request_id_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("request.request_id", "\t"),
            "SCHEMA_INVALID",
            "/request/request_id",
        )

    @pytest.mark.parametrize("bad", [0, -1, 1.5, True, "1"])
    def test_attempt_ordinal_must_be_a_positive_integer(self, contract, bad) -> None:
        assert_code_and_pointer(
            contract, changed("attempt.ordinal", bad), "SCHEMA_INVALID", "/attempt/ordinal"
        )

    def test_schema_version_must_be_literal_one(self, contract) -> None:
        assert_code_and_pointer(
            contract, changed("schema_version", "1"), "SCHEMA_INVALID", "/schema_version"
        )

    def test_schema_version_true_is_not_one(self, contract) -> None:
        # Python's True == 1; the schema's integer type guard must not let it pass.
        assert_code_and_pointer(
            contract, changed("schema_version", True), "SCHEMA_INVALID", "/schema_version"
        )

    def test_misspelled_status_is_schema_invalid_not_unsupported(self, contract) -> None:
        # A misspelling/type error is SCHEMA_INVALID; only *known canonical*
        # non-completed states are UNSUPPORTED_INVOCATION_STATE.
        assert_code_and_pointer(
            contract,
            changed("invocation.status", "complete"),
            "SCHEMA_INVALID",
            "/invocation/status",
        )

    def test_negative_cost_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("invocation.usage.cost_cents", -0.01),
            "SCHEMA_INVALID",
            "/invocation/usage/cost_cents",
        )

    def test_non_finite_cost_in_python_object_is_schema_invalid(self, contract) -> None:
        # NaN compares False against every JSON Schema bound, so finiteness is
        # enforced directly for documents handed over as Python objects.
        document = changed("invocation.usage.cost_cents", float("nan"))
        assert_code_and_pointer(
            contract,
            document,
            "SCHEMA_INVALID",
            "/invocation/usage/cost_cents",
        )
        assert not math.isfinite(
            document["invocation"]["usage"]["cost_cents"]
        )  # the fixture really carried NaN

    def test_usage_units_blank_rejected(self, contract) -> None:
        # Canonical InvocationUsage rejects blank units; the evidence object
        # mirrors that.
        assert_code_and_pointer(
            contract,
            changed("invocation.usage.units", ""),
            "SCHEMA_INVALID",
            "/invocation/usage/units",
        )

    def test_negative_input_units_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("invocation.usage.input_units", -1),
            "SCHEMA_INVALID",
            "/invocation/usage/input_units",
        )

    def test_stub_response_kind_still_schema_valid(self, contract) -> None:
        # "stub" is a known response_kind: it must fail the *semantic*
        # STUB_RESPONSE invariant, never schema validation.
        assert_code_and_pointer(
            contract,
            changed("dispatch.response_kind", "stub"),
            "STUB_RESPONSE",
            "/dispatch/response_kind",
        )


# ---------------------------------------------------------------------------
# supported Invocation state
# ---------------------------------------------------------------------------


class TestInvocationState:
    @pytest.mark.parametrize("state", ["created", "running", "failed", "unknown"])
    def test_known_non_completed_states_are_unsupported(self, contract, state) -> None:
        assert_code_and_pointer(
            contract,
            changed("invocation.status", state),
            "UNSUPPORTED_INVOCATION_STATE",
            "/invocation/status",
        )

    def test_state_is_the_first_invariant(self, contract) -> None:
        # No synthesized counters or joins turn an incomplete effect into a
        # completed one: state failure wins even when other joins are broken.
        document = changed("invocation.status", "running")
        document["request"]["run_id"] = "run-other"
        document["dispatch"]["response_kind"] = "stub"
        assert_code_and_pointer(
            contract, document, "UNSUPPORTED_INVOCATION_STATE", "/invocation/status"
        )


# ---------------------------------------------------------------------------
# ordered joins, one mutation assertion per rule
# ---------------------------------------------------------------------------


class TestOrderedJoins:
    def test_request_run_identity(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("request.run_id", "run-other"),
            "REQUEST_RUN_MISMATCH",
            "/request/run_id",
        )

    def test_request_scope_workspace(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("request.workspace_id", "ws-other"),
            "RUN_SCOPE_MISMATCH",
            "/request/workspace_id",
        )

    def test_request_scope_project(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("request.project_id", "proj-other"),
            "RUN_SCOPE_MISMATCH",
            "/request/project_id",
        )

    def test_scope_is_checked_before_actor(self, contract) -> None:
        document = changed("request.workspace_id", "ws-other")
        document["request"]["actor_principal_id"] = "principal-other"
        assert_code_and_pointer(contract, document, "RUN_SCOPE_MISMATCH", "/request/workspace_id")

    def test_actor_mismatch_is_provenance_not_authorization(self, contract) -> None:
        # Matching opaque IDs cannot establish Warden/Sentinel enforcement; a
        # mismatch is reported, and no security field is emitted either way.
        error = first_error(contract, changed("request.actor_principal_id", "principal-other"))
        assert error == {"code": "ACTOR_MISMATCH", "path": "/request/actor_principal_id"}

    def test_node_run_link(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("node_run.run_id", "run-other"),
            "NODE_RUN_LINK_MISMATCH",
            "/node_run/run_id",
        )

    def test_node_run_link_precedes_attempt_link(self, contract) -> None:
        document = changed("node_run.run_id", "run-other")
        document["attempt"]["node_run_id"] = "nr-other"
        assert_code_and_pointer(contract, document, "NODE_RUN_LINK_MISMATCH", "/node_run/run_id")

    def test_attempt_link(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("attempt.node_run_id", "nr-other"),
            "ATTEMPT_LINK_MISMATCH",
            "/attempt/node_run_id",
        )

    def test_attempt_link_precedes_invocation_link(self, contract) -> None:
        document = changed("attempt.node_run_id", "nr-other")
        document["invocation"]["run_id"] = "run-other"
        assert_code_and_pointer(contract, document, "ATTEMPT_LINK_MISMATCH", "/attempt/node_run_id")

    @pytest.mark.parametrize(
        ("field", "other"),
        [
            ("run_id", "run-other"),
            ("node_run_id", "nr-other"),
            ("attempt_id", "att-other"),
            ("workspace_id", "ws-other"),
            ("project_id", "proj-other"),
        ],
    )
    def test_invocation_link(self, contract, field, other) -> None:
        assert_code_and_pointer(
            contract,
            changed(f"invocation.{field}", other),
            "INVOCATION_LINK_MISMATCH",
            f"/invocation/{field}",
        )

    def test_invocation_link_precedes_binding_scope(self, contract) -> None:
        document = changed("invocation.run_id", "run-other")
        document["invocation"]["binding"]["workspace_id"] = "ws-other"
        assert_code_and_pointer(
            contract, document, "INVOCATION_LINK_MISMATCH", "/invocation/run_id"
        )

    @pytest.mark.parametrize("field", ["workspace_id", "project_id"])
    def test_binding_scope(self, contract, field) -> None:
        assert_code_and_pointer(
            contract,
            changed(f"invocation.binding.{field}", f"{field}-other"),
            "BINDING_SCOPE_MISMATCH",
            f"/invocation/binding/{field}",
        )

    def test_binding_scope_precedes_dispatch_link(self, contract) -> None:
        document = changed("invocation.binding.workspace_id", "ws-other")
        document["dispatch"]["invocation_id"] = "inv-other"
        assert_code_and_pointer(
            contract, document, "BINDING_SCOPE_MISMATCH", "/invocation/binding/workspace_id"
        )

    def test_dispatch_link(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("dispatch.invocation_id", "inv-other"),
            "DISPATCH_LINK_MISMATCH",
            "/dispatch/invocation_id",
        )

    def test_dispatch_link_precedes_provider_check(self, contract) -> None:
        document = changed("dispatch.invocation_id", "inv-other")
        document["dispatch"]["provider_name"] = "anthropic"
        assert_code_and_pointer(
            contract, document, "DISPATCH_LINK_MISMATCH", "/dispatch/invocation_id"
        )

    def test_provider_mismatch_against_binding(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("dispatch.provider_name", "anthropic"),
            "PROVIDER_MISMATCH",
            "/dispatch/provider_name",
        )

    def test_provider_mismatch_against_expected_model(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("expected_model.provider_name", "anthropic"),
            "PROVIDER_MISMATCH",
            "/dispatch/provider_name",
        )

    def test_provider_is_checked_before_model(self, contract) -> None:
        document = changed("dispatch.provider_name", "anthropic")
        document["dispatch"]["requested_model"] = "claude-x"
        assert_code_and_pointer(contract, document, "PROVIDER_MISMATCH", "/dispatch/provider_name")

    def test_model_mismatch(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("dispatch.requested_model", "gpt-4o"),
            "MODEL_MISMATCH",
            "/dispatch/requested_model",
        )

    def test_model_is_checked_before_response(self, contract) -> None:
        document = changed("dispatch.requested_model", "gpt-4o")
        document["dispatch"]["response_kind"] = "stub"
        assert_code_and_pointer(contract, document, "MODEL_MISMATCH", "/dispatch/requested_model")

    def test_stub_response_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("dispatch.response_kind", "stub"),
            "STUB_RESPONSE",
            "/dispatch/response_kind",
        )

    def test_stub_is_checked_before_result(self, contract) -> None:
        document = changed("dispatch.response_kind", "stub")
        document["dispatch"]["result_present"] = False
        assert_code_and_pointer(contract, document, "STUB_RESPONSE", "/dispatch/response_kind")

    def test_result_missing_rejected(self, contract) -> None:
        assert_code_and_pointer(
            contract,
            changed("dispatch.result_present", False),
            "RESULT_MISSING",
            "/dispatch/result_present",
        )

    def test_result_is_checked_before_usage(self, contract) -> None:
        document = changed("dispatch.result_present", False)
        document["invocation"]["usage"] = None
        assert_code_and_pointer(contract, document, "RESULT_MISSING", "/dispatch/result_present")


# ---------------------------------------------------------------------------
# usage provenance iff-rule
# ---------------------------------------------------------------------------


class TestUsageProvenance:
    @pytest.mark.parametrize("source", ["reported", "estimated"])
    def test_null_usage_with_available_source_rejected(self, contract, source) -> None:
        document = changed("invocation.usage", None)
        document["dispatch"]["usage_provenance"]["source"] = source
        assert_code_and_pointer(contract, document, "USAGE_PROVENANCE_MISSING", "/invocation/usage")

    def test_present_usage_with_unavailable_source_rejected(self, contract) -> None:
        document = changed("dispatch.usage_provenance.source", "unavailable")
        assert_code_and_pointer(
            contract,
            document,
            "USAGE_PROVENANCE_MISSING",
            "/dispatch/usage_provenance/source",
        )

    def test_null_evidence_ref_with_reported_source_rejected(self, contract) -> None:
        document = changed("dispatch.usage_provenance.evidence_ref", None)
        assert_code_and_pointer(
            contract,
            document,
            "USAGE_PROVENANCE_MISSING",
            "/dispatch/usage_provenance/evidence_ref",
        )

    def test_blank_evidence_ref_with_estimated_source_rejected(self, contract) -> None:
        document = changed("dispatch.usage_provenance.evidence_ref", "   ")
        document["dispatch"]["usage_provenance"]["source"] = "estimated"
        assert_code_and_pointer(
            contract,
            document,
            "USAGE_PROVENANCE_MISSING",
            "/dispatch/usage_provenance/evidence_ref",
        )

    def test_unavailable_source_allows_null_evidence_ref(self, contract) -> None:
        document = changed("invocation.usage", None)
        document["dispatch"]["usage_provenance"] = {
            "source": "unavailable",
            "evidence_ref": None,
        }
        assert_valid(contract, document)


# ---------------------------------------------------------------------------
# completed-effect reuse
# ---------------------------------------------------------------------------


class TestCompletedEffectReuse:
    def test_reuse_validates_the_unchanged_object_without_new_dispatch(self, contract) -> None:
        """A later admission reusing a completed effect re-proves the same joins.

        The first validation stands for the original physical dispatch; the
        second uses the byte-identical object, standing for a retry that
        reuses the already completed Invocation. Both must pass, and the
        validator must not create or invent a new Invocation, dispatch, or
        counters -- the object's NodeRun/Attempt remain the original effect's
        provenance (logical_effect dedup may span NodeRuns; see module
        docstring). No new dispatch evidence is fabricated for the retry.
        """
        document = valid_document()
        snapshot = copy.deepcopy(document)

        original = contract.validate_model_call(document)
        reuse = contract.validate_model_call(document)

        assert original["valid"] and reuse["valid"]
        assert original == reuse, "reuse must not invent new evidence"
        assert document == snapshot, "reuse must not rewrite the record to fit"

    def test_reuse_via_json_text_is_equally_valid(self, contract) -> None:
        text = json.dumps(valid_document())
        assert contract.validate_model_call(text)["valid"]
        assert contract.validate_model_call(text)["valid"]


# ---------------------------------------------------------------------------
# the checked-in schema file is authoritative, not decorative
# ---------------------------------------------------------------------------


class TestSchemaFileContract:
    def test_module_loads_the_docs_testing_schema(self, contract) -> None:
        assert contract.MODEL_CALL_SCHEMA_PATH == SCHEMA_PATH
        assert SCHEMA_PATH.is_file()

    def test_schema_file_accepts_the_valid_document(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.validators.validator_for(schema)(schema)
        jsonschema.Draft202012Validator.check_schema(schema)
        assert list(validator.iter_errors(valid_document())) == []

    def test_schema_file_rejects_an_extra_field_independently(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.validators.validator_for(schema)(schema)
        errors = list(validator.iter_errors(with_extra("extra", 1)))
        assert errors, "the schema file itself must reject extra fields"

    def test_schema_admits_every_canonical_state(self) -> None:
        # The completed-only rule is semantic (UNSUPPORTED_INVOCATION_STATE);
        # the schema must keep misspellings (SCHEMA_INVALID) distinguishable.
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        status = schema["properties"]["invocation"]["$ref"]
        assert status == "#/$defs/invocation"
        enum = schema["$defs"]["invocation"]["properties"]["status"]["enum"]
        assert tuple(enum) == CANONICAL_INVOCATION_STATES
