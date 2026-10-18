"""The installed-workspace release-proof envelope validates fail-closed (#1878).

`scripts/validate-installed-workspace-proof.py` is the single offline
validator that separates structurally valid evidence from a complete observed
release-proof envelope. Everything here exists to pin its exact v1 contract:
the closed error-code vocabulary, the stage order (stop at the first failing
stage, diagnostics sorted by ``(path, code)``), the five mandatory scenario
families, and the byte-level file checks.

Two properties get the deepest coverage because the validator's value is
fail-closed behavior, not happy paths:

1. **Structurally convenient evidence never reaches closeout.** FAIL/BLOCKED/
   NOT_RUN rows are legitimate *structural* evidence and must pass
   ``--mode structural`` — and must fail closeout by name. A synthetic
   all-PASS bundle is likewise structurally valid and rejected at closeout by
   SYNTHETIC_NOT_CLOSEOUT. Neither rejection may leak into structural mode.
2. **The reviewed profile cannot waive a family.** The profile schema defines
   exactly three properties (so there is no waiver switch), the validator
   derives nothing about the profile from the bundle, and all five families
   are required in both modes.

Envelope validation never asserts that a run occurred, that evidence is
authentic, or that live security/provider behavior passed; the observed
all-PASS bundle below is *correctly hashed*, which is all the envelope check
claims about it.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "validate-installed-workspace-proof.py"
CONTRACT = REPO / "scripts" / "installed_workspace_proof_contract.py"
SCHEMA_PATH = REPO / "docs" / "testing" / "installed-workspace-proof.schema.json"

CANDIDATE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
ARTIFACT_SHA256 = "f" * 64
PROFILE_ID = "reviewed-profile-2026-09"
PROFILE_NAME = "reviewed-profile.json"

#: Deterministic payload bytes; hashes in a fixture bundle are computed over
#: exactly these bytes, never over decoded/reformatted JSON.
PAYLOAD_BYTES: dict[str, bytes] = {
    "install.log": b"step: install ok\n",
    "effective-config.json": b'{"auth": "required"}\n',
    "execution.json": b'{"scenario": "execute", "ok": true}\n',
    "restart.json": b'{"scenario": "restart", "ok": true}\n',
    "isolation.json": b'{"scenario": "isolate", "ok": true}\n',
    "junit.xml": b'<testsuites failures="0"/>\n',
}

FAMILY_EVIDENCE = {
    "INSTALL": ["install.log", "effective-config.json"],
    "EXECUTE": ["execution.json"],
    "RESTART": ["restart.json"],
    "ISOLATE": ["isolation.json"],
    "FAIL-CLOSED": ["junit.xml"],
}

STRUCTURAL = "structural"
CLOSEOUT = "closeout"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(doc: dict[str, Any]) -> bytes:
    return (json.dumps(doc, indent=2) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# fixture documents
# ---------------------------------------------------------------------------


def profile_doc(applicable: bool = True, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": 1,
        "profile_id": PROFILE_ID,
        "browser_login_applicable": applicable,
    }
    return {**doc, **overrides}


def scenario_row(family: str, outcome: str = "PASS") -> dict[str, Any]:
    if outcome == "PASS":
        return {
            "id": family,
            "outcome": outcome,
            "reason_code": None,
            "evidence_paths": list(FAMILY_EVIDENCE[family]),
        }
    return {
        "id": family,
        "outcome": outcome,
        "reason_code": f"{family.lower()}-did-not-pass",
        "evidence_paths": [],
    }


def subcheck_row(applicable: bool, outcome: str | None = None) -> dict[str, Any]:
    if outcome is None:
        outcome = "PASS" if applicable else "NOT_APPLICABLE"
    return {
        "id": "BROWSER_LOGIN",
        "outcome": outcome,
        "reason_code": None if outcome == "PASS" else "browser-login-not-passed",
        "evidence_paths": ["install.log"] if outcome == "PASS" else [],
    }


def results_doc(
    applicable: bool = True,
    outcomes: dict[str, str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    outcomes = outcomes or {}
    doc: dict[str, Any] = {
        "schema_version": 1,
        "candidate_sha256": ARTIFACT_SHA256,
        "profile_id": PROFILE_ID,
        "scenarios": [
            scenario_row(family, outcomes.get(family, "PASS"))
            for family in ("INSTALL", "EXECUTE", "RESTART", "ISOLATE", "FAIL-CLOSED")
        ],
        "subchecks": [subcheck_row(applicable)],
    }
    return {**doc, **overrides}


# ---------------------------------------------------------------------------
# bundle writer
# ---------------------------------------------------------------------------


def write_bundle(
    tmp_path: Path,
    *,
    applicable: bool = True,
    evidence_kind: str = "observed",
    outcomes: dict[str, str] | None = None,
    subcheck_outcome: str | None = None,
    mutate_profile: Callable[[dict[str, Any]], None] | None = None,
    mutate_manifest: Callable[[dict[str, Any]], None] | None = None,
    mutate_results: Callable[[dict[str, Any]], None] | None = None,
    extra_payloads: dict[str, bytes] | None = None,
    drop_from_listing: set[str] | None = None,
    append_listed: list[dict[str, str]] | None = None,
    hash_overrides: dict[str, str] | None = None,
    omit_writing: set[str] | None = None,
    write_instead: dict[str, bytes] | None = None,
) -> tuple[Path, Path]:
    """Write a complete, correctly-hashed bundle; return ``(bundle, profile)``.

    The manifest's hashes are computed over the exact bytes that end up on
    disk, so the default bundle is valid in both modes and every mutator
    breaks exactly one contract rule:

    - ``hash_overrides``: list a wrong digest (EVIDENCE_HASH_MISMATCH);
    - ``write_instead``: put different bytes on disk than were hashed
      (EVIDENCE_HASH_MISMATCH — bytes, not decoded JSON);
    - ``omit_writing``: list a file that is absent (EVIDENCE_MISSING);
    - ``drop_from_listing``: leave a required file unlisted
      (EVIDENCE_UNLISTED);
    - ``append_listed``: add manifest entries (duplicates, control inputs,
      unsafe paths).
    """
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    profile_path = tmp_path / PROFILE_NAME
    profile = profile_doc(applicable)
    if mutate_profile:
        mutate_profile(profile)
    profile_path.write_bytes(_dump(profile))

    overrides: dict[str, Any] = {}
    if subcheck_outcome is not None:
        overrides["subchecks"] = [subcheck_row(applicable, subcheck_outcome)]
    results = results_doc(applicable, outcomes, **overrides)
    if mutate_results:
        mutate_results(results)
    on_disk: dict[str, bytes] = {
        **PAYLOAD_BYTES,
        **(extra_payloads or {}),
        "results.json": _dump(results),
    }

    listed = [contract_mod().RESULTS_NAME, *PAYLOAD_BYTES]
    listed += [p for p in on_disk if p not in listed]
    listing = []
    for path in listed:
        if drop_from_listing and path in drop_from_listing:
            continue
        digest = sha256(on_disk[path])
        if hash_overrides and path in hash_overrides:
            digest = hash_overrides[path]
        listing.append({"path": path, "sha256": digest})
    listing += append_listed or []

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "evidence_kind": evidence_kind,
        "candidate": {"commit": CANDIDATE_COMMIT, "artifact_sha256": ARTIFACT_SHA256},
        "profile_id": PROFILE_ID,
        "files": listing,
    }
    if mutate_manifest:
        mutate_manifest(manifest)
    (root / "manifest.json").write_bytes(_dump(manifest))

    omit = omit_writing or set()
    final_bytes = {**on_disk, **(write_instead or {})}
    for path, data in final_bytes.items():
        if path not in omit:
            (root / path).write_bytes(data)
    return root, profile_path


# ---------------------------------------------------------------------------
# module loading and the in-process CLI driver
# ---------------------------------------------------------------------------

_LOADED: dict[str, Any] = {}


def _load(name: str, path: Path) -> Any:
    if name not in _LOADED:
        spec = importlib.util.spec_from_file_location(f"_proof_{name}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _LOADED[name] = module
    return _LOADED[name]


def validator_mod() -> Any:
    return _load("validator", SCRIPT)


def contract_mod() -> Any:
    return _load("contract", CONTRACT)


@pytest.fixture(scope="module")
def contract() -> Any:
    return contract_mod()


@pytest.fixture(scope="module")
def validator() -> Any:
    return validator_mod()


def validate(bundle: Path, profile: Path, mode: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = validator_mod().run(
            ["--bundle", str(bundle), "--profile", str(profile), "--mode", mode]
        )
    return code, json.loads(out.getvalue())


def errors_of(report: dict[str, Any]) -> list[tuple[str, str]]:
    return [(e["code"], e["path"]) for e in report["errors"]]


def with_duplicate_key(doc: dict[str, Any], key: str, extra: Any) -> bytes:
    """Serialize *doc* with *key* defined twice — INVALID_JSON, not last-wins."""
    text = json.dumps(doc)
    injection = json.dumps({key: extra})[1:-1]
    at = text.index(f'"{key}":')
    return (text[:at] + injection + ", " + text[at:]).encode("utf-8")


# ---------------------------------------------------------------------------
# closeout semantics: the five families, synthetic, and the headless profile
# ---------------------------------------------------------------------------


class TestCloseoutSemantics:
    def test_observed_all_pass_bundle_passes_closeout(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path)
        code, report = validate(bundle, profile, CLOSEOUT)
        assert (code, report["valid"], report["errors"]) == (0, True, [])

    def test_observed_all_pass_bundle_passes_structural(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path)
        code, report = validate(bundle, profile, STRUCTURAL)
        assert (code, report["valid"]) == (0, True)

    @pytest.mark.parametrize(
        ("family", "index"),
        [("INSTALL", 0), ("EXECUTE", 1), ("RESTART", 2), ("ISOLATE", 3), ("FAIL-CLOSED", 4)],
    )
    def test_nonpass_family_is_valid_evidence_but_fails_closeout(
        self, tmp_path: Path, family: str, index: int
    ) -> None:
        """FAIL/BLOCKED/NOT_RUN rows are real evidence: structural accepts
        them; closeout names the exact row that did not pass."""
        for outcome in ("FAIL", "BLOCKED", "NOT_RUN"):
            bundle, profile = write_bundle(tmp_path, outcomes={family: outcome})
            code, report = validate(bundle, profile, STRUCTURAL)
            assert (code, report["valid"]) == (0, True), report
            code, report = validate(bundle, profile, CLOSEOUT)
            assert code == 1
            assert errors_of(report) == [
                ("REQUIRED_SCENARIO_NOT_PASS", f"results.json#/scenarios/{index}")
            ]

    def test_synthetic_all_pass_is_structural_but_never_closeout(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, evidence_kind="synthetic")
        code, report = validate(bundle, profile, STRUCTURAL)
        assert (code, report["valid"]) == (0, True)
        code, report = validate(bundle, profile, CLOSEOUT)
        assert code == 1
        assert errors_of(report) == [("SYNTHETIC_NOT_CLOSEOUT", "manifest.json#/evidence_kind")]

    def test_no_family_may_be_not_applicable(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, outcomes={"ISOLATE": "NOT_APPLICABLE"})
        for mode in (STRUCTURAL, CLOSEOUT):
            code, report = validate(bundle, profile, mode)
            assert code == 1
            assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/3/outcome")]

    def test_missing_family_fails_in_both_modes(self, tmp_path: Path) -> None:
        def drop_isolate(results: dict[str, Any]) -> None:
            results["scenarios"] = [row for row in results["scenarios"] if row["id"] != "ISOLATE"]

        bundle, profile = write_bundle(tmp_path, mutate_results=drop_isolate)
        for mode in (STRUCTURAL, CLOSEOUT):
            code, report = validate(bundle, profile, mode)
            assert code == 1
            assert errors_of(report) == [("REQUIRED_SCENARIO_NOT_PASS", "results.json#/scenarios")]

    def test_unknown_family_is_schema_invalid(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"].append(scenario_row("UPGRADE", "FAIL")),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/5/id")]

    def test_headless_profile_passes_closeout_with_not_applicable_subcheck(
        self, tmp_path: Path
    ) -> None:
        bundle, profile = write_bundle(tmp_path, applicable=False)
        code, report = validate(bundle, profile, CLOSEOUT)
        assert (code, report["valid"]) == (0, True)

    def test_profile_schema_defines_no_family_waiver(self) -> None:
        """The reviewed profile has exactly three properties and forbids the
        rest: there is no switch that can drop one of the five families."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        profile_def = schema["$defs"]["reviewedProfile"]
        assert profile_def["additionalProperties"] is False
        assert set(profile_def["required"]) == {
            "schema_version",
            "profile_id",
            "browser_login_applicable",
        }
        assert set(profile_def["properties"]) == set(profile_def["required"])

    def test_shipped_schema_is_valid_draft_2020_12(self) -> None:
        """The schema file is the shape authority; a malformed one would
        silently weaken every SCHEMA_INVALID diagnostic above."""
        from jsonschema import Draft202012Validator

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"].endswith("draft/2020-12/schema")

    def test_waiver_switch_in_profile_is_rejected(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path, mutate_profile=lambda p: p.update(waive_families=True)
        )
        code, report = validate(bundle, profile, CLOSEOUT)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "profile#/waive_families")]


# ---------------------------------------------------------------------------
# browser-login applicability joins against the independently supplied profile
# ---------------------------------------------------------------------------


class TestBrowserApplicability:
    def test_applicable_fail_subcheck_structural_ok_closeout_rejected(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, applicable=True, subcheck_outcome="FAIL")
        code, report = validate(bundle, profile, STRUCTURAL)
        assert (code, report["valid"]) == (0, True)
        code, report = validate(bundle, profile, CLOSEOUT)
        assert code == 1
        assert errors_of(report) == [("REQUIRED_SCENARIO_NOT_PASS", "results.json#/subchecks/0")]

    def test_not_applicable_when_applicable_is_inconsistent_even_structurally(
        self, tmp_path: Path
    ) -> None:
        bundle, profile = write_bundle(tmp_path, applicable=True, subcheck_outcome="NOT_APPLICABLE")
        for mode in (STRUCTURAL, CLOSEOUT):
            code, report = validate(bundle, profile, mode)
            assert code == 1
            assert errors_of(report) == [("INVALID_APPLICABILITY", "results.json#/subchecks/0")]

    def test_outcome_when_not_applicable_is_inconsistent(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, applicable=False, subcheck_outcome="PASS")
        for mode in (STRUCTURAL, CLOSEOUT):
            code, report = validate(bundle, profile, mode)
            assert code == 1
            assert errors_of(report) == [("INVALID_APPLICABILITY", "results.json#/subchecks/0")]

    def test_missing_subcheck_row_fails_both_modes(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, mutate_results=lambda r: r.update(subchecks=[]))
        for mode in (STRUCTURAL, CLOSEOUT):
            code, report = validate(bundle, profile, mode)
            assert code == 1
            assert errors_of(report) == [("REQUIRED_SCENARIO_NOT_PASS", "results.json#/subchecks")]

    def test_duplicate_subcheck_row_is_a_duplicate_scenario(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["subchecks"].append(subcheck_row(True)),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("DUPLICATE_SCENARIO", "results.json#/subchecks/1")]


# ---------------------------------------------------------------------------
# schema rejections: shapes, hex, blanks, outcome rules, duplicate JSON keys
# ---------------------------------------------------------------------------


def _mutated_bundle(tmp_path: Path, mutate: Callable[..., Any]) -> tuple[Path, Path]:
    """Apply a one-line lambda to the document its parameter names.

    The lambda's parameter name selects the document (``p`` profile, ``m``
    manifest, ``r`` results); this keeps each schema case a single readable
    expression while routing it to the right file.
    """
    parameter = next(iter(inspect.signature(mutate).parameters))
    if parameter == "p":
        return write_bundle(tmp_path, mutate_profile=mutate)
    if parameter == "m":
        return write_bundle(tmp_path, mutate_manifest=mutate)
    return write_bundle(tmp_path, mutate_results=mutate)


def _mutated_pointer(mutate: Callable[..., Any]) -> str:
    parameter = next(iter(inspect.signature(mutate).parameters))
    source = inspect.getsource(mutate)
    if parameter == "p":
        key = source.split("p.update(")[1].split("=")[0].strip()
        return f"profile#/{key}"
    if parameter == "m":
        key = source.split(".update(")[1].split("=")[0].strip()
        prefix = "manifest.json#/candidate/" if "candidate" in source else "manifest.json#/"
        return f"{prefix}{key}"
    if "[" in source:
        field = source.split('r["')[1].split('"')[0]
        index = source.split("]")[1].lstrip("[").split("]")[0].strip()
        key = source.split(".update(")[1].split("=")[0].strip()
        return f"results.json#/{field}/{index}/{key}"
    key = source.split("r.update(")[1].split("=")[0].strip()
    return f"results.json#/{key}"


class TestSchemaRejections:
    @pytest.mark.parametrize("doc", ["profile", "manifest.json", "results.json"], ids=str)
    def test_duplicate_json_keys_are_invalid_json(self, tmp_path: Path, doc: str) -> None:
        bundle, profile = write_bundle(tmp_path)
        if doc == "profile":
            profile.write_bytes(with_duplicate_key(profile_doc(), "profile_id", "x"))
        elif doc == "manifest.json":
            path = bundle / doc
            parsed = json.loads(path.read_text(encoding="utf-8"))
            path.write_bytes(with_duplicate_key(parsed, "evidence_kind", "observed"))
        else:
            path = bundle / doc
            parsed = json.loads(path.read_text(encoding="utf-8"))
            path.write_bytes(with_duplicate_key(parsed, "scenarios", []))
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("INVALID_JSON", doc)]

    def test_profile_nan_literal_is_invalid_json(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path)
        profile.write_bytes(profile.read_bytes().replace(b'"reviewed-profile-2026-09"', b"NaN"))
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("INVALID_JSON", "profile")]

    @pytest.mark.parametrize(
        "mutate,expected",
        [
            (lambda p: p.update(waive_families=True), "profile#/waive_families"),
            (lambda m: m.update(generated_by="fixture"), "manifest.json#/generated_by"),
            (lambda r: r.update(notes="extra"), "results.json#/notes"),
        ],
        ids=["profile-extra", "manifest-extra", "results-extra"],
    )
    def test_additional_properties_rejected(
        self, tmp_path: Path, mutate: Callable[..., Any], expected: str
    ) -> None:
        bundle, profile = _mutated_bundle(tmp_path, mutate)
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", expected)]

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.update(schema_version="1"),
            lambda p: p.update(browser_login_applicable="yes"),
            lambda m: m.update(evidence_kind="live"),
            lambda r: r.update(candidate_sha256="short"),
            lambda r: r["scenarios"][0].update(evidence_paths="install.log"),
        ],
        ids=[
            "profile-version-type",
            "profile-flag-type",
            "manifest-kind",
            "results-sha-type",
            "scenario-evidence-type",
        ],
    )
    def test_wrong_types_rejected(self, tmp_path: Path, mutate: Callable[..., Any]) -> None:
        bundle, profile = _mutated_bundle(tmp_path, mutate)
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report)[0][0] == "SCHEMA_INVALID"

    @pytest.mark.parametrize(
        "mutate,expected",
        [
            (lambda p: p.update(profile_id="  "), "profile#/profile_id"),
            (
                lambda m: m["candidate"].update(commit="0123456789ABCDEF0123456789abcdef01234567"),
                "manifest.json#/candidate/commit",
            ),
            (
                lambda m: m["candidate"].update(artifact_sha256="f" * 63),
                "manifest.json#/candidate/artifact_sha256",
            ),
            (
                lambda r: r.update(candidate_sha256="0x" + "f" * 62),
                "results.json#/candidate_sha256",
            ),
            (lambda r: r.update(profile_id=""), "results.json#/profile_id"),
        ],
        ids=[
            "blank-profile-id",
            "uppercase-commit",
            "short-sha",
            "hex-prefix",
            "blank-results-profile-id",
        ],
    )
    def test_blank_ids_and_bad_hex_rejected(
        self, tmp_path: Path, mutate: Callable[..., Any], expected: str
    ) -> None:
        bundle, profile = _mutated_bundle(tmp_path, mutate)
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", expected)]

    def test_pass_row_requires_null_reason_code(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"][0].update(reason_code="why"),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/0/reason_code")]

    def test_pass_row_requires_nonempty_evidence_paths(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"][0].update(evidence_paths=[]),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/0/evidence_paths")]

    def test_nonpass_row_requires_reason_code(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            outcomes={"EXECUTE": "FAIL"},
            mutate_results=lambda r: r["scenarios"][1].update(reason_code=None),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/1/reason_code")]

    def test_blank_reason_code_on_nonpass_row_rejected(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            outcomes={"EXECUTE": "FAIL"},
            mutate_results=lambda r: r["scenarios"][1].update(reason_code=""),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("SCHEMA_INVALID", "results.json#/scenarios/1/reason_code")]

    def test_duplicate_scenario_row(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"].append(scenario_row("INSTALL")),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("DUPLICATE_SCENARIO", "results.json#/scenarios/5")]


# ---------------------------------------------------------------------------
# joins: profile identity and candidate binding
# ---------------------------------------------------------------------------


class TestJoins:
    def test_manifest_profile_id_mismatch(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path, mutate_manifest=lambda m: m.update(profile_id="other-profile")
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("PROFILE_MISMATCH", "manifest.json#/profile_id")]

    def test_results_profile_id_mismatch(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path, mutate_results=lambda r: r.update(profile_id="other-profile")
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("PROFILE_MISMATCH", "results.json#/profile_id")]

    def test_candidate_sha_mismatch(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path, mutate_results=lambda r: r.update(candidate_sha256="a" * 64)
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("CANDIDATE_MISMATCH", "results.json#/candidate_sha256")]


# ---------------------------------------------------------------------------
# evidence files: hashes, presence, listing boundary, path safety
# ---------------------------------------------------------------------------


class TestEvidenceFiles:
    def test_modified_digest_is_hash_mismatch(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, hash_overrides={"install.log": "a" * 64})
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("EVIDENCE_HASH_MISMATCH", "manifest.json#/files/1")]

    def test_different_bytes_still_mismatch_even_with_same_json(self, tmp_path: Path) -> None:
        """Hash bytes, not decoded/reformatted JSON: the same JSON meaning
        with different bytes fails the listing."""
        bundle, profile = write_bundle(
            tmp_path,
            write_instead={"effective-config.json": b'{"auth":"required"}'},
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("EVIDENCE_HASH_MISMATCH", "manifest.json#/files/2")]

    def test_listed_but_absent_file_is_missing(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, omit_writing={"restart.json"})
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("EVIDENCE_MISSING", "manifest.json#/files/4")]

    def test_unlisted_evidence_reference(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"][0]["evidence_paths"].append("extra.log"),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [
            ("EVIDENCE_UNLISTED", "results.json#/scenarios/0/evidence_paths/2")
        ]

    def test_evidence_may_never_name_results_json(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"][0].update(evidence_paths=["results.json"]),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [
            ("EVIDENCE_UNLISTED", "results.json#/scenarios/0/evidence_paths/0")
        ]

    def test_results_json_must_be_listed(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, drop_from_listing={"results.json"})
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("EVIDENCE_UNLISTED", "results.json")]

    @pytest.mark.parametrize(
        "payload",
        [
            "install.log",
            "effective-config.json",
            "execution.json",
            "restart.json",
            "isolation.json",
            "junit.xml",
        ],
    )
    def test_required_payload_must_be_listed(self, tmp_path: Path, payload: str) -> None:
        bundle, profile = write_bundle(tmp_path, drop_from_listing={payload})
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        # Stage 5 reports every listing violation at once: the dropped payload
        # is unlisted, and any family citing it gets a companion diagnostic.
        assert ("EVIDENCE_UNLISTED", payload) in errors_of(report)
        assert {code for code, _ in errors_of(report)} == {"EVIDENCE_UNLISTED"}

    def test_manifest_json_must_not_be_listed(self, tmp_path: Path) -> None:
        """Listing manifest.json breaks the boundary — and its hash cannot be
        made self-consistent, which is the recursive self-hashing the boundary
        exists to prevent, so stage 5 reports both facts."""
        bundle, profile = write_bundle(
            tmp_path, append_listed=[{"path": "manifest.json", "sha256": "b" * 64}]
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert ("EVIDENCE_UNLISTED", "manifest.json#/files/7") in errors_of(report)

    def test_reviewed_profile_must_not_be_listed(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path, append_listed=[{"path": PROFILE_NAME, "sha256": "c" * 64}]
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert ("EVIDENCE_UNLISTED", "manifest.json#/files/7") in errors_of(report)

    def test_duplicate_listed_file(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            append_listed=[{"path": "install.log", "sha256": sha256(PAYLOAD_BYTES["install.log"])}],
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("DUPLICATE_FILE", "manifest.json#/files/7")]

    @pytest.mark.parametrize(
        "bad_path",
        [
            "../escape.log",
            "/etc/passwd",
            "C:/temp/x.log",
            "back\\slash.log",
            "./install.log",
            "a/./b.log",
            "a/../b.log",
            "trailing/",
        ],
    )
    def test_unsafe_listed_paths_rejected(self, tmp_path: Path, bad_path: str) -> None:
        bundle, profile = write_bundle(
            tmp_path, append_listed=[{"path": bad_path, "sha256": "e" * 64}]
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("EVIDENCE_PATH_UNSAFE", "manifest.json#/files/7/path")]

    def test_symlink_escape_is_unsafe_and_never_read(self, tmp_path: Path) -> None:
        """A listed path that resolves outside the bundle is unsafe — and the
        outside file must never be hashed (no read, hence no mismatch)."""
        outside = tmp_path / "outside-secret.log"
        outside.write_bytes(b"not bundle evidence\n")
        bundle, profile = write_bundle(
            tmp_path, hash_overrides={"install.log": sha256(outside.read_bytes())}
        )
        (bundle / "install.log").unlink()
        os.symlink(outside, bundle / "install.log")
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        # The listing entry is unsafe; INSTALL cites the same path, so its
        # evidence reference is unsafe too. Nothing outside the bundle is read:
        # no EVIDENCE_MISSING and no EVIDENCE_HASH_MISMATCH appears.
        assert ("EVIDENCE_PATH_UNSAFE", "manifest.json#/files/1/path") in errors_of(report)
        assert {code for code, _ in errors_of(report)} == {"EVIDENCE_PATH_UNSAFE"}

    def test_unsafe_evidence_reference(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            mutate_results=lambda r: r["scenarios"][0].update(evidence_paths=["../install.log"]),
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [
            ("EVIDENCE_PATH_UNSAFE", "results.json#/scenarios/0/evidence_paths/0")
        ]


# ---------------------------------------------------------------------------
# deterministic report: stage order, sorting, shape
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_stops_at_first_failing_stage(self, tmp_path: Path) -> None:
        """A results.json that is INVALID_JSON alongside a manifest whose
        schema is broken must report only the parse stage."""
        bundle, profile = write_bundle(
            tmp_path, mutate_manifest=lambda m: m.update(evidence_kind="bogus")
        )
        results_path = bundle / "results.json"
        parsed = json.loads(results_path.read_text(encoding="utf-8"))
        results_path.write_bytes(with_duplicate_key(parsed, "scenarios", []))
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("INVALID_JSON", "results.json")]

    def test_closeout_diagnostics_sorted_by_path_then_code(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(
            tmp_path,
            evidence_kind="synthetic",
            outcomes={"EXECUTE": "FAIL"},
            applicable=True,
            subcheck_outcome="BLOCKED",
        )
        code, report = validate(bundle, profile, CLOSEOUT)
        assert code == 1
        expected = [
            ("SYNTHETIC_NOT_CLOSEOUT", "manifest.json#/evidence_kind"),
            ("REQUIRED_SCENARIO_NOT_PASS", "results.json#/scenarios/1"),
            ("REQUIRED_SCENARIO_NOT_PASS", "results.json#/subchecks/0"),
        ]
        assert errors_of(report) == expected
        assert sorted(expected, key=lambda e: (e[1], e[0])) == expected

    def test_identical_stage_diagnostics_deduplicate(self, tmp_path: Path) -> None:
        """Two missing families share one path; the report collapses them to
        a single diagnostic rather than repeating an identical line."""
        bundle, profile = write_bundle(tmp_path, mutate_results=lambda r: r.update(scenarios=[]))
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert errors_of(report) == [("REQUIRED_SCENARIO_NOT_PASS", "results.json#/scenarios")]

    def test_report_shape_is_exact(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, hash_overrides={"install.log": "a" * 64})
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert set(report) == {"schema_version", "valid", "mode", "errors"}
        assert report["schema_version"] == 1
        assert report["mode"] == STRUCTURAL
        assert all(set(e) == {"code", "path"} for e in report["errors"])

    def test_diagnostics_never_quote_file_contents(self, tmp_path: Path) -> None:
        secret = "provider-key-SUPER-SECRET-123"
        bundle, profile = write_bundle(
            tmp_path,
            hash_overrides={"install.log": "a" * 64},
            write_instead={"install.log": f"token={secret}\n".encode()},
        )
        code, report = validate(bundle, profile, STRUCTURAL)
        assert code == 1
        assert secret not in json.dumps(report)


# ---------------------------------------------------------------------------
# the shared contract module
# ---------------------------------------------------------------------------


class TestContractHelpers:
    def test_duplicate_key_rejected(self, contract: Any) -> None:
        with pytest.raises(contract.DuplicateKeyError):
            contract.parse_json_object('{"a": 1, "b": {"a": 1, "a": 2}}')

    def test_nan_rejected(self, contract: Any) -> None:
        with pytest.raises(ValueError):
            contract.parse_json_object('{"a": NaN}')

    @pytest.mark.parametrize(
        ("path", "ok"),
        [
            ("install.log", True),
            ("a/b/c.log", True),
            ("", False),
            ("/etc/passwd", False),
            ("C:/x", False),
            ("back\\slash", False),
            ("a//b", False),
            ("./a", False),
            ("a/.", False),
            ("..", False),
            ("a/../b", False),
            ("trailing/", False),
        ],
    )
    def test_safe_relative_posix_paths(self, contract: Any, path: str, ok: bool) -> None:
        assert contract.is_safe_relative_posix_path(path) is ok

    def test_report_sorts_by_path_then_code(self, contract: Any) -> None:
        report = contract.Report(STRUCTURAL)
        report.add("EVIDENCE_MISSING", "b.log")
        report.add("EVIDENCE_UNLISTED", "a.log")
        report.add("DUPLICATE_FILE", "manifest.json#/files/9")
        doc = report.as_dict()
        assert [(e["code"], e["path"]) for e in doc["errors"]] == [
            ("EVIDENCE_UNLISTED", "a.log"),
            ("EVIDENCE_MISSING", "b.log"),
            ("DUPLICATE_FILE", "manifest.json#/files/9"),
        ]

    def test_report_rejects_unknown_mode_and_code(self, contract: Any) -> None:
        with pytest.raises(ValueError):
            contract.Report("enforce")
        report = contract.Report(CLOSEOUT)
        with pytest.raises(ValueError):
            report.add("NOT_A_CODE", "x")

    def test_error_code_vocabulary_is_closed(self, contract: Any) -> None:
        assert {
            "INVALID_JSON",
            "SCHEMA_INVALID",
            "DUPLICATE_SCENARIO",
            "DUPLICATE_FILE",
            "PROFILE_MISMATCH",
            "CANDIDATE_MISMATCH",
            "INVALID_APPLICABILITY",
            "EVIDENCE_PATH_UNSAFE",
            "EVIDENCE_MISSING",
            "EVIDENCE_UNLISTED",
            "EVIDENCE_HASH_MISMATCH",
            "REQUIRED_SCENARIO_NOT_PASS",
            "SYNTHETIC_NOT_CLOSEOUT",
        } == contract.ERROR_CODES


# ---------------------------------------------------------------------------
# the real CLI process: exit codes 0 / 1 / 2
# ---------------------------------------------------------------------------


class TestCli:
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            timeout=120,
            check=False,
        )

    def test_valid_closeout_exits_zero(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path)
        done = self.run_cli("--bundle", str(bundle), "--profile", str(profile), "--mode", CLOSEOUT)
        assert done.returncode == 0
        report = json.loads(done.stdout)
        assert report["valid"] is True and report["errors"] == []

    def test_invalid_bundle_exits_one(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path, evidence_kind="synthetic")
        done = self.run_cli("--bundle", str(bundle), "--profile", str(profile), "--mode", CLOSEOUT)
        assert done.returncode == 1
        report = json.loads(done.stdout)
        assert report["valid"] is False

    def test_usage_misuse_exits_two_with_empty_stdout(self, tmp_path: Path) -> None:
        bundle, profile = write_bundle(tmp_path)
        cases: list[list[str]] = [
            [],
            ["--bundle", str(bundle), "--profile", str(profile), "--mode", "enforce"],
            [
                "--bundle",
                str(tmp_path / "absent"),
                "--profile",
                str(profile),
                "--mode",
                CLOSEOUT,
            ],
            [
                "--bundle",
                str(bundle),
                "--profile",
                str(tmp_path / "absent.json"),
                "--mode",
                CLOSEOUT,
            ],
        ]
        for argv in cases:
            done = self.run_cli(*argv)
            assert done.returncode == 2, argv
            assert done.stdout == b"", argv
            assert done.stderr, argv

    def test_missing_schema_is_reported_as_misuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(validator_mod(), "SCHEMA_PATH", tmp_path / "absent.schema.json")
        bundle, profile = write_bundle(tmp_path)
        assert (
            validator_mod().run(
                ["--bundle", str(bundle), "--profile", str(profile), "--mode", CLOSEOUT]
            )
            == 2
        )
