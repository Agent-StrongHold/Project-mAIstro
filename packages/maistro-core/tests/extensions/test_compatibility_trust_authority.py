"""Compatibility, trust and authority evaluation (#953, M9-B2).

The three pure evaluators behind the inspection phase. Every ambiguity must
resolve to "no": an unknown dependency range is unsatisfiable, an empty
publisher allowlist trusts nobody, and an authority delta only names what is
genuinely new.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from maistro.extensions.authority import (
    AuthorityBaseline,
    compute_authority_delta,
    normalize_permission,
)
from maistro.extensions.compatibility import CompatibilityPolicy, evaluate_compatibility
from maistro.extensions.trust import TrustPolicy, evaluate_trust
from maistro.extensions.types import ExtensionScope, TrustClaim


def _manifest_bytes(**overrides: object) -> bytes:
    payload = b"payload"
    document: dict[str, object] = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": "1.4.0",
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "m", "attribute": "a"}],
        "artifact": {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
    }
    document.update(overrides)  # type: ignore[arg-type]
    return json.dumps(document).encode()


def _manifest(**overrides: object):
    from maistro.extensions.manifest import inspect_manifest

    return inspect_manifest(_manifest_bytes(**overrides))


class TestCompatibility:
    def test_same_major_is_compatible(self) -> None:
        report = evaluate_compatibility(
            _manifest(api_version="1.9.3"),
            CompatibilityPolicy(platform_api_version="1.0.0", installed_versions={}),
        )
        assert report.compatible and report.failures == ()

    def test_different_major_is_incompatible(self) -> None:
        report = evaluate_compatibility(
            _manifest(api_version="2.0.0"),
            CompatibilityPolicy(platform_api_version="1.0.0", installed_versions={}),
        )
        assert not report.compatible
        assert any("major mismatch" in f for f in report.failures)

    def test_missing_dependency_is_incompatible(self) -> None:
        manifest = _manifest(dependencies=[{"id": "acme.ui_kit", "range": "^1.0.0"}])
        report = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(platform_api_version="1.0.0", installed_versions={}),
        )
        assert not report.compatible
        assert any("missing dependency" in f for f in report.failures)

    def test_caret_range_accepts_same_major_at_or_above_floor(self) -> None:
        manifest = _manifest(dependencies=[{"id": "acme.ui_kit", "range": "^1.2.0"}])
        for installed in ("1.2.0", "1.9.0"):
            report = evaluate_compatibility(
                manifest,
                CompatibilityPolicy(
                    platform_api_version="1.0.0",
                    installed_versions={"acme.ui_kit": installed},
                ),
            )
            assert report.compatible, installed
        report = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.ui_kit": "2.1.0"}
            ),
        )
        assert not report.compatible
        report = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.ui_kit": "1.1.9"}
            ),
        )
        assert not report.compatible

    def test_exact_range_requires_the_exact_version(self) -> None:
        manifest = _manifest(dependencies=[{"id": "acme.core", "range": "2.0.0"}])
        ok = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.core": "2.0.0"}
            ),
        )
        assert ok.compatible
        near = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.core": "2.0.1"}
            ),
        )
        assert not near.compatible

    def test_unknown_range_grammar_fails_closed(self) -> None:
        manifest = _manifest(dependencies=[{"id": "acme.core", "range": ">=1.0,<2.0"}])
        report = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.core": "1.5.0"}
            ),
        )
        assert not report.compatible
        assert any("does not satisfy" in f for f in report.failures)

    def test_star_range_matches_any_installed_version(self) -> None:
        manifest = _manifest(dependencies=[{"id": "acme.core", "range": "*"}])
        report = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version="1.0.0", installed_versions={"acme.core": "0.0.1"}
            ),
        )
        assert report.compatible


class TestTrust:
    EVIDENCE = TrustClaim(publisher_id="acme", signature_present=True, signer_key_id="k1")
    POLICY = TrustPolicy(
        trusted_publishers=frozenset({"acme"}),
        require_signature=True,
        allowed_signer_keys=frozenset({"k1"}),
    )

    def test_trusted_publisher_with_signature_passes(self) -> None:
        report = evaluate_trust(_manifest(), self.EVIDENCE, self.POLICY)
        assert report.trusted

    def test_unsigned_package_fails_when_signature_required(self) -> None:
        evidence = TrustClaim(publisher_id="acme", signature_present=False)
        report = evaluate_trust(_manifest(), evidence, self.POLICY)
        assert not report.trusted
        assert any("no signature" in f for f in report.failures)

    def test_empty_allowlist_trusts_nobody(self) -> None:
        report = evaluate_trust(_manifest(), self.EVIDENCE, TrustPolicy())
        assert not report.trusted
        assert any("allowlist" in f for f in report.failures)

    def test_unlisted_publisher_is_refused(self) -> None:
        report = evaluate_trust(
            _manifest(publisher="shady"),
            TrustClaim(publisher_id="shady", signature_present=True, signer_key_id="k1"),
            self.POLICY,
        )
        assert not report.trusted
        assert any("allowlist" in f for f in report.failures)

    def test_evidence_naming_a_different_publisher_is_a_tamper_signal(self) -> None:
        report = evaluate_trust(
            _manifest(publisher="acme"),
            TrustClaim(publisher_id="someone-else", signature_present=True),
            self.POLICY,
        )
        assert not report.trusted
        assert any("publisher mismatch" in f for f in report.failures)

    def test_unknown_signer_key_is_refused_when_keys_are_pinned(self) -> None:
        evidence = TrustClaim(publisher_id="acme", signature_present=True, signer_key_id="rogue")
        report = evaluate_trust(_manifest(), evidence, self.POLICY)
        assert not report.trusted
        assert any("signing key" in f for f in report.failures)

    def test_missing_signer_key_is_refused_when_keys_are_pinned(self) -> None:
        evidence = TrustClaim(publisher_id="acme", signature_present=True)
        report = evaluate_trust(_manifest(), evidence, self.POLICY)
        assert not report.trusted

    def test_signature_not_required_allows_unsigned(self) -> None:
        policy = TrustPolicy(trusted_publishers=frozenset({"acme"}), require_signature=False)
        report = evaluate_trust(_manifest(), TrustClaim(publisher_id="acme"), policy)
        assert report.trusted

    def test_evidence_digest_must_match_the_manifest_claim(self) -> None:
        evidence = TrustClaim(
            publisher_id="acme",
            signature_present=True,
            signer_key_id="k1",
            package_sha256="0" * 64,
        )
        report = evaluate_trust(_manifest(), evidence, self.POLICY)
        assert not report.trusted
        assert any("does not match" in f for f in report.failures)


class TestAuthority:
    SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-1")

    def test_normalize_accepts_grammar_conformant_tokens(self) -> None:
        assert normalize_permission("network.http") == "network.http"
        assert normalize_permission("a") == "a"
        assert normalize_permission("storage.workspace_rows") == "storage.workspace_rows"

    @pytest.mark.parametrize("bad", ["", "UPPER", "1net", "net..work", "net work", "a.B"])
    def test_normalize_refuses_malformed_tokens(self, bad: str) -> None:
        with pytest.raises(ValueError, match="malformed permission"):
            normalize_permission(bad)

    def test_delta_first_install_requests_everything(self) -> None:
        delta = compute_authority_delta(("network.http", "clipboard.read"), AuthorityBaseline())
        assert delta.new == ("clipboard.read", "network.http")
        assert delta.retained == ()
        assert delta.requires_authorization

    def test_delta_names_only_what_is_new(self) -> None:
        baseline = AuthorityBaseline(
            previously_granted=frozenset({"network.http"}),
            pre_approved=frozenset({"storage.workspace"}),
        )
        delta = compute_authority_delta(
            ("network.http", "storage.workspace", "clipboard.read"), baseline
        )
        assert delta.new == ("clipboard.read",)
        assert delta.retained == ("network.http", "storage.workspace")
        assert delta.requires_authorization

    def test_delta_without_new_authority_does_not_require_a_decision(self) -> None:
        baseline = AuthorityBaseline(previously_granted=frozenset({"a.b", "c.d"}))
        delta = compute_authority_delta(("c.d", "a.b"), baseline)
        assert delta.new == ()
        assert not delta.requires_authorization

    def test_dropped_reports_baseline_permissions_not_requested(self) -> None:
        baseline = AuthorityBaseline(previously_granted=frozenset({"a.b", "c.d"}))
        delta = compute_authority_delta(("a.b",), baseline)
        assert delta.dropped == ("c.d",)

    def test_requested_set_is_a_set_not_a_multiset(self) -> None:
        delta = compute_authority_delta(("a.b", "a.b"), AuthorityBaseline())
        assert delta.new == ("a.b",)
