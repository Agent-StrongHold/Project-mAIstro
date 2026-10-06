"""Contract-compatibility policy (M9-C1, issue #955) — behavior and structure.

Each test names the acceptance criterion it pins:

* the host decides compatibility from manifest/SDK metadata before any code
  import (proven structurally: negotiation runs with ``__import__`` banned);
* optional features degrade explicitly — withheld from the granted feature
  set, never silently pretended;
* unsupported major/minor contract combinations fail with actionable reasons
  that name the versions and the missed policy boundary;
* deprecations carry machine-readable status and a documented removal target,
  and the support window (removal only at a future contract major) is
  enforced by construction;
* compatibility is independent of the application patch version and of
  private module paths (no such field exists; no import path can enter the
  decision).
"""

from __future__ import annotations

import builtins
import json
from typing import Any

import pytest

from maistro.extensions.compat import (
    CONTRACT_VERSION,
    FEATURE_DEPRECATED,
    FEATURE_REMOVED,
    FEATURE_STATUSES,
    FEATURE_SUPPORTED,
    HOST_FEATURES,
    SUPPORTED_CONTRACT_MAJORS,
    CompatError,
    CompatibilityReport,
    CompatMetadataError,
    ContractVersion,
    Degradation,
    DeprecationNotice,
    ExtensionCompatMetadata,
    FeatureStatus,
    FeatureSupport,
    HostContractMetadata,
    IncompatibleContract,
    Verdict,
    ensure_compatible,
    negotiate,
    parse_compat_metadata,
    parse_contract_range,
    parse_contract_version,
    parse_feature_status,
)

# ADR-100526-9c55 declares this module the behavioral-contract evidence for
# the extension compatibility policy (ADR-032's cross-check): every test here
# pins behavior the contract vocabulary promises, so the whole module carries
# the kind's marker.
pytestmark = pytest.mark.contract("behavioral")


def make_host(
    *,
    version: str = "1.4.0",
    majors: tuple[int, ...] = (1,),
    features: tuple[FeatureSupport, ...] = HOST_FEATURES,
) -> HostContractMetadata:
    return HostContractMetadata(
        contract_version=parse_contract_version(version),
        supported_majors=majors,
        features=features,
    )


def make_extension(
    contract: str = ">=1.0.0,<2.0.0",
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
) -> ExtensionCompatMetadata:
    return ExtensionCompatMetadata(
        contract=parse_contract_range(contract),
        required_features=required,
        optional_features=optional,
    )


# ---------------------------------------------------------------------------
# contract version policy
# ---------------------------------------------------------------------------


@pytest.mark.ac("ADR-100526-9c55/AC-5")
def test_host_contract_version_is_independent_of_any_package_or_app_version() -> None:
    """The contract version is a literal policy constant, not derived."""
    assert CONTRACT_VERSION.count(".") == 2
    assert CONTRACT_VERSION == "1.0.0"
    host = HostContractMetadata.current()
    assert host.contract_version == parse_contract_version(CONTRACT_VERSION)
    assert host.supported_majors == SUPPORTED_CONTRACT_MAJORS
    assert host.features == HOST_FEATURES


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.0.0", ContractVersion(1, 0, 0)),
        ("0.2.14", ContractVersion(0, 2, 14)),
        ("10.20.30", ContractVersion(10, 20, 30)),
    ],
)
def test_contract_version_parses(value: str, expected: ContractVersion) -> None:
    assert parse_contract_version(value) == expected


@pytest.mark.parametrize(
    "value",
    ["1.0", "1", "1.0.0.0", "01.0.0", "1.00.0", "1.0.0-beta", "v1.0.0", "", "one.0.0"],
)
def test_contract_version_rejects_malformed_explicitly(value: str) -> None:
    with pytest.raises(CompatMetadataError, match=r"MAJOR\.MINOR\.PATCH"):
        parse_contract_version(value)


def test_contract_version_orders_lexicographically() -> None:
    assert ContractVersion(1, 4, 0) < ContractVersion(1, 10, 0)
    assert ContractVersion(1, 4, 9) < ContractVersion(1, 5, 0)
    assert ContractVersion(2, 0, 0) > ContractVersion(1, 99, 99)


# ---------------------------------------------------------------------------
# contract ranges
# ---------------------------------------------------------------------------


def test_range_satisfied_by_honors_every_operator() -> None:
    low = ContractVersion(1, 0, 0)
    mid = ContractVersion(1, 4, 2)
    high = ContractVersion(2, 0, 0)
    below = ContractVersion(0, 9, 0)
    assert parse_contract_range(">=1.0.0,<2.0.0").satisfied_by(mid)
    assert parse_contract_range(">=1.0.0,<2.0.0").satisfied_by(low)  # >= is inclusive
    assert not parse_contract_range(">1.0.0,<2.0.0").satisfied_by(low)
    assert not parse_contract_range(">=1.0.0,<2.0.0").satisfied_by(high)
    assert not parse_contract_range(">=1.0.0,<2.0.0").satisfied_by(below)
    assert parse_contract_range(">1.0.0").satisfied_by(mid)
    assert parse_contract_range("<=1.4.2").satisfied_by(mid)
    assert parse_contract_range("==1.4.2").satisfied_by(mid)
    assert parse_contract_range("<1.5.0").satisfied_by(mid)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        ">=1.0",
        "1.0.0",
        "~1.0.0",
        "^1.0.0",
        ">=1.0.0;",
        "=1.0.0",
        ">=01.0.0",
        ">=1.0.0,",
    ],
)
def test_range_rejects_unsupported_specifiers(text: str) -> None:
    with pytest.raises(CompatMetadataError):
        parse_contract_range(text)


def test_range_explain_names_major_break_as_unbridgeable() -> None:
    """A contract-major miss is named as the breaking boundary it is."""
    host = make_host(version="1.4.0")
    extension = make_extension(contract=">=2.0.0,<3.0.0")
    reason = extension.contract.explain(
        host.contract_version, supported_majors=host.supported_majors
    )
    assert ">=2.0.0,<3.0.0" in reason
    assert "1.4.0" in reason
    assert "breaking boundary" in reason
    assert "2.0.0" in reason


def test_range_explain_names_same_major_window() -> None:
    """A same-major floor above the host is a window miss, not a major break."""
    host = make_host(version="1.4.0")
    extension = make_extension(contract=">=1.9.0,<2.0.0")
    reason = extension.contract.explain(
        host.contract_version, supported_majors=host.supported_majors
    )
    assert "same-major contract floor" in reason
    assert "1.9.0" in reason and "1.4.0" in reason


def test_range_explain_names_ended_range_when_host_is_ahead() -> None:
    """A range capped below the host says the extension predates the host."""
    host = make_host(version="2.1.0", majors=(1, 2))
    extension = make_extension(contract=">=1.0.0,<2.0.0")
    reason = extension.contract.explain(
        host.contract_version, supported_majors=host.supported_majors
    )
    assert "ended before this host's contract version" in reason


# ---------------------------------------------------------------------------
# extension metadata parsing (strict, no import-path field)
# ---------------------------------------------------------------------------


def test_parse_metadata_minimal() -> None:
    metadata = parse_compat_metadata({"contract": ">=1.0.0,<2.0.0"})
    assert metadata.contract.satisfied_by(ContractVersion(1, 0, 0))
    assert metadata.required_features == ()
    assert metadata.optional_features == ()


def test_parse_metadata_features() -> None:
    metadata = parse_compat_metadata(
        {
            "contract": ">=1.0.0",
            "required_features": ["streaming"],
            "optional_features": ["scheduled", "background"],
        }
    )
    assert metadata.required_features == ("streaming",)
    assert metadata.optional_features == ("scheduled", "background")


def test_parse_metadata_rejects_unknown_keys_by_name() -> None:
    with pytest.raises(CompatMetadataError, match="entry_point"):
        parse_compat_metadata({"contract": ">=1.0.0", "entry_point": "evil:impl"})


def test_parse_metadata_requires_contract() -> None:
    with pytest.raises(CompatMetadataError, match="'contract'"):
        parse_compat_metadata({"required_features": ["streaming"]})


def test_parse_metadata_rejects_non_string_contract() -> None:
    with pytest.raises(CompatMetadataError, match="'contract'"):
        parse_compat_metadata({"contract": 2})


def test_parse_metadata_rejects_bad_feature_names() -> None:
    for bad in ("maistro._private", "Streaming", "with_underscore", ""):
        with pytest.raises(CompatMetadataError, match="lowercase-slug"):
            parse_compat_metadata({"contract": ">=1.0.0", "required_features": [bad]})


def test_parse_metadata_rejects_duplicate_features() -> None:
    with pytest.raises(CompatMetadataError, match="duplicate"):
        parse_compat_metadata({"contract": ">=1.0.0", "required_features": ["a", "a"]})
    with pytest.raises(CompatMetadataError, match="one or the other"):
        parse_compat_metadata(
            {"contract": ">=1.0.0", "required_features": ["a"], "optional_features": ["a"]}
        )


def test_parse_metadata_rejects_wrong_list_types() -> None:
    with pytest.raises(CompatMetadataError, match="required_features"):
        parse_compat_metadata({"contract": ">=1.0.0", "required_features": "streaming"})


def test_parse_metadata_rejects_non_mapping() -> None:
    with pytest.raises(CompatMetadataError, match="JSON object"):
        parse_compat_metadata(["contract", ">=1.0.0"])  # type: ignore[arg-type]


def test_compat_metadata_model_has_no_importable_name_field() -> None:
    """Structural guarantee: nothing in the metadata can name code to import.

    Acceptance: compatibility is decided from metadata before code import —
    so the metadata itself must not carry an entrypoint/module field.
    """
    metadata = parse_compat_metadata({"contract": ">=1.0.0"})
    data = metadata.__dict__
    assert set(data) == {"contract", "required_features", "optional_features"}
    assert not any("module" in key or "entry" in key or "path" in key for key in data)


# ---------------------------------------------------------------------------
# host metadata construction invariants (machine-readable deprecation status)
# ---------------------------------------------------------------------------


def feature(
    name: str,
    status: FeatureStatus,
    *,
    since: str = "1.0.0",
    removal_target: str | None = None,
    removed_in: str | None = None,
    migration: str = "",
) -> FeatureSupport:
    return FeatureSupport(
        name=name,
        status=status,
        since=parse_contract_version(since),
        removal_target=None if removal_target is None else parse_contract_version(removal_target),
        removed_in=None if removed_in is None else parse_contract_version(removed_in),
        migration=migration,
    )


def test_host_rejects_impossible_supported_majors() -> None:
    with pytest.raises(CompatError, match="at least one contract major"):
        HostContractMetadata(
            contract_version=ContractVersion(1, 0, 0), supported_majors=(), features=()
        )
    with pytest.raises(CompatError, match="strictly increasing"):
        make_host(majors=(2, 1))
    with pytest.raises(CompatError, match="supported majors"):
        make_host(version="2.0.0", majors=(1,))


def test_host_rejects_duplicate_features() -> None:
    with pytest.raises(CompatError, match="duplicate feature 'background'"):
        make_host(features=(HOST_FEATURES[0], HOST_FEATURES[0]))


def test_host_may_implement_a_feature_the_contract_formalizes_later() -> None:
    """A backport/preview is declarable; the *grant* is still contract-gated.

    The host table records when the contract introduced each feature; a host
    speaking an older contract may implement it early. Negotiation (not
    construction) refuses to grant it, because extensions may assume only
    semantics their contract version defines — that rule is tested below.
    """
    host = make_host(
        version="1.4.0",
        features=(*HOST_FEATURES, feature("widgets", FEATURE_SUPPORTED, since="1.9.0")),
    )
    assert host.feature("widgets") is not None  # declared
    report = negotiate(host, make_extension(optional=("widgets",)))
    assert report.verdict is Verdict.DEGRADED  # not granted
    assert "1.9.0" in report.degradations[0].reason and "1.4.0" in report.degradations[0].reason


@pytest.mark.ac("ADR-100526-9c55/AC-4")
def test_deprecated_feature_requires_removal_target_and_migration() -> None:
    with pytest.raises(CompatError, match="documented removal target"):
        feature("old", FEATURE_DEPRECATED, migration="use 'new'")
    with pytest.raises(CompatError, match="document a migration path"):
        feature("old", FEATURE_DEPRECATED, removal_target="2.0.0")


def test_deprecated_feature_removal_target_must_be_a_future_major() -> None:
    """The support window is enforced, not promised: removal at a future major."""
    with pytest.raises(CompatError, match="future major"):
        make_host(
            version="1.4.0",
            features=(feature("old", FEATURE_DEPRECATED, removal_target="1.5.0", migration="m"),),
        )
    # A target inside the *current* major is equally impossible.
    with pytest.raises(CompatError, match="future major"):
        make_host(
            version="1.4.0",
            features=(feature("old", FEATURE_DEPRECATED, removal_target="1.0.0", migration="m"),),
        )


def test_removed_feature_requires_record_and_migration() -> None:
    with pytest.raises(CompatError, match="must record removed_in"):
        feature("gone", FEATURE_REMOVED, migration="m")
    with pytest.raises(CompatError, match="document a migration path"):
        feature("gone", FEATURE_REMOVED, removed_in="1.0.0")
    with pytest.raises(CompatError, match="newer than the contract"):
        make_host(
            version="1.4.0",
            features=(feature("gone", FEATURE_REMOVED, removed_in="1.9.0", migration="m"),),
        )


def test_supported_feature_cannot_carry_lifecycle_evidence() -> None:
    with pytest.raises(CompatError, match="supported"):
        feature("fine", FEATURE_SUPPORTED, removal_target="3.0.0")
    with pytest.raises(CompatError, match="supported"):
        feature("fine", FEATURE_SUPPORTED, migration="m")
    with pytest.raises(CompatError, match="supported"):
        feature("fine", FEATURE_SUPPORTED, removed_in="1.0.0")


def test_host_feature_lookup() -> None:
    host = make_host()
    assert host.feature("streaming") is not None
    assert host.feature("teleport") is None


# ---------------------------------------------------------------------------
# negotiation
# ---------------------------------------------------------------------------


def test_negotiate_compatible_happy_path() -> None:
    host = make_host()
    report = negotiate(
        host,
        make_extension(required=("streaming",), optional=("scheduled",)),
    )
    assert report.verdict is Verdict.COMPATIBLE
    assert report.reasons == ()
    assert report.degradations == ()
    assert report.deprecations == ()
    assert report.supported_features == ("streaming", "scheduled")


@pytest.mark.ac("ADR-100526-9c55/AC-3")
def test_negotiate_major_mismatch_is_incompatible_with_actionable_reason() -> None:
    host = make_host()
    report = negotiate(host, make_extension(contract=">=2.0.0,<3.0.0", required=("streaming",)))
    assert report.verdict is Verdict.INCOMPATIBLE
    assert len(report.reasons) == 1
    reason = report.reasons[0]
    assert ">=2.0.0,<3.0.0" in reason and "1.4.0" in reason
    assert "breaking boundary" in reason
    # The contract gate short-circuits: a manifest written against an
    # unsupported major is not interpreted against this host's feature
    # vocabulary at all, so nothing is granted.
    assert report.supported_features == ()
    assert report.degradations == ()


@pytest.mark.ac("ADR-100526-9c55/AC-3")
def test_negotiate_same_major_window_miss_is_incompatible_and_actionable() -> None:
    host = make_host(version="1.4.0")
    report = negotiate(host, make_extension(contract=">=1.9.0,<2.0.0"))
    assert report.verdict is Verdict.INCOMPATIBLE
    assert "same-major contract floor" in report.reasons[0]
    assert "1.9.0" in report.reasons[0] and "1.4.0" in report.reasons[0]


def test_negotiate_uncapped_range_within_supported_major_is_compatible() -> None:
    host = make_host(version="1.4.0")
    report = negotiate(host, make_extension(contract=">=1.0.0"))
    assert report.verdict is Verdict.COMPATIBLE


def test_negotiate_unknown_required_feature_is_incompatible_and_names_alternatives() -> None:
    host = make_host()
    report = negotiate(host, make_extension(required=("teleport",)))
    assert report.verdict is Verdict.INCOMPATIBLE
    reason = report.reasons[0]
    assert "'teleport'" in reason
    assert "does not implement" in reason
    assert "streaming" in reason  # names what the host *does* implement


def test_negotiate_required_feature_removed_is_incompatible_with_migration() -> None:
    host = make_host(
        version="2.1.0",
        majors=(1, 2),
        features=(
            feature("legacy", FEATURE_REMOVED, removed_in="2.0.0", migration="use 'modern'"),
        ),
    )
    report = negotiate(host, make_extension(contract=">=2.0.0,<3.0.0", required=("legacy",)))
    assert report.verdict is Verdict.INCOMPATIBLE
    reason = report.reasons[0]
    assert "'legacy'" in reason
    assert "removed in contract 2.0.0" in reason
    assert "use 'modern'" in reason


def test_negotiate_required_feature_newer_than_host_is_incompatible() -> None:
    host = make_host(
        version="1.4.0",
        features=(
            *HOST_FEATURES,
            feature("widgets", FEATURE_SUPPORTED, since="1.9.0"),
        ),
    )
    report = negotiate(host, make_extension(required=("widgets",)))
    assert report.verdict is Verdict.INCOMPATIBLE
    reason = report.reasons[0]
    assert "'widgets'" in reason and "1.9.0" in reason and "1.4.0" in reason


@pytest.mark.ac("ADR-100526-9c55/AC-2")
def test_negotiate_optional_feature_unknown_degrades_explicitly() -> None:
    host = make_host()
    report = negotiate(host, make_extension(optional=("teleport",)))
    assert report.verdict is Verdict.DEGRADED
    assert report.reasons == ()
    assert report.degradations == (
        Degradation(
            feature="teleport",
            reason=report.degradations[0].reason,
        ),
    )
    # Explicit degradation, in both directions: named, and absent from the
    # granted set — no pretending support.
    assert "teleport" in report.degradations[0].reason
    assert "teleport" not in report.supported_features


@pytest.mark.ac("ADR-100526-9c55/AC-2")
def test_negotiate_optional_feature_removed_degrades_with_record() -> None:
    host = make_host(
        version="2.1.0",
        majors=(1, 2),
        features=(
            feature("legacy", FEATURE_REMOVED, removed_in="2.0.0", migration="use 'modern'"),
        ),
    )
    report = negotiate(host, make_extension(contract=">=2.0.0,<3.0.0", optional=("legacy",)))
    assert report.verdict is Verdict.DEGRADED
    assert "removed in contract 2.0.0" in report.degradations[0].reason
    assert report.supported_features == ()


@pytest.mark.ac("ADR-100526-9c55/AC-4")
def test_negotiate_deprecated_feature_negotiates_with_notice_and_removal_target() -> None:
    host = make_host(
        features=(
            feature("old", FEATURE_DEPRECATED, removal_target="2.0.0", migration="use 'new'"),
        )
    )
    report = negotiate(host, make_extension(required=("old",)))
    assert report.verdict is Verdict.COMPATIBLE
    assert report.deprecations == (
        DeprecationNotice(
            feature="old",
            status=FEATURE_DEPRECATED,
            removal_target=ContractVersion(2, 0, 0),
            migration="use 'new'",
        ),
    )
    assert report.supported_features == ("old",)


def test_negotiate_deprecated_optional_feature_also_carries_notice() -> None:
    host = make_host(
        features=(
            feature("old", FEATURE_DEPRECATED, removal_target="2.0.0", migration="use 'new'"),
        )
    )
    report = negotiate(host, make_extension(optional=("old",)))
    assert report.verdict is Verdict.COMPATIBLE
    assert report.deprecations[0].feature == "old"
    assert report.supported_features == ("old",)


def test_negotiate_accumulates_reasons_across_the_feature_gate() -> None:
    """One negotiation reports everything wrong with the feature set."""
    host = make_host()
    report = negotiate(
        host,
        make_extension(
            contract=">=1.0.0,<2.0.0",
            required=("teleport", "time-travel"),
        ),
    )
    assert report.verdict is Verdict.INCOMPATIBLE
    assert len(report.reasons) == 2
    assert any("'teleport'" in reason for reason in report.reasons)
    assert any("'time-travel'" in reason for reason in report.reasons)


def test_incompatible_verdict_beats_degraded() -> None:
    """A required-feature failure is fatal even alongside degradations."""
    host = make_host()
    report = negotiate(
        host,
        make_extension(required=("teleport",), optional=("time-travel",)),
    )
    assert report.verdict is Verdict.INCOMPATIBLE
    assert report.degradations  # still recorded, for the report's completeness
    assert report.supported_features == ()


# ---------------------------------------------------------------------------
# structural acceptance: no imports, no app version, no private paths
# ---------------------------------------------------------------------------


@pytest.mark.ac("ADR-100526-9c55/AC-1")
def test_negotiation_never_imports_anything() -> None:
    """Compatibility is decidable with the import machinery disabled.

    Acceptance: the host determines compatibility from metadata *before code
    import*. Banning ``__import__`` makes any import a hard failure — the
    negotiation completes anyway, because its inputs are plain data.
    """
    host = make_host(
        features=(feature("old", FEATURE_DEPRECATED, removal_target="2.0.0", migration="m"),)
    )
    extension = make_extension(contract=">=1.0.0,<3.0.0", required=("old",), optional=("teleport",))
    real_import = builtins.__import__

    def banned(*args: object, **kwargs: object) -> object:
        raise AssertionError("negotiation must not import anything")

    builtins.__import__ = banned  # type: ignore[assignment]
    try:
        report = negotiate(host, extension)
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
    assert report.verdict is Verdict.DEGRADED
    assert report.deprecations[0].feature == "old"


@pytest.mark.ac("ADR-100526-9c55/AC-5")
def test_compatibility_is_independent_of_application_patch_version() -> None:
    """Two hosts on the same contract decide identically.

    Acceptance: compatibility does not depend on the application patch
    version. The only version in the model is the contract version — there is
    no application-version field to differ. The *decision* (verdict, granted
    set, degradations) is identical across patch versions; an incompatible
    range's reason text names each host's own version, which is actionability,
    not dependence.
    """
    host_a = make_host(version="1.4.0")
    host_b = make_host(version="1.4.9")
    extensions = [
        make_extension(contract=">=1.0.0,<2.0.0", required=("streaming",)),
        make_extension(contract=">=1.9.0,<2.0.0"),
        make_extension(required=("teleport",), optional=("scheduled",)),
    ]
    for extension in extensions:
        report_a = negotiate(host_a, extension)
        report_b = negotiate(host_b, extension)
        assert report_a.verdict is report_b.verdict
        assert report_a.supported_features == report_b.supported_features
        assert report_a.degradations == report_b.degradations
        assert report_a.deprecations == report_b.deprecations


@pytest.mark.ac("ADR-100526-9c55/AC-5")
def test_host_metadata_has_no_application_version_field() -> None:
    field_names = {f.name for f in HostContractMetadata.__dataclass_fields__.values()}
    assert field_names == {"contract_version", "supported_majors", "features"}


@pytest.mark.ac("ADR-100526-9c55/AC-5")
def test_reports_never_leak_private_module_paths() -> None:
    """Reasons and notices name versions and features, never module paths."""
    host = make_host(
        features=(feature("old", FEATURE_DEPRECATED, removal_target="2.0.0", migration="m"),)
    )
    cases = [
        make_extension(contract=">=2.0.0", required=("teleport",)),
        make_extension(contract=">=1.0.0,<2.0.0", required=("old",), optional=("missing",)),
    ]
    for extension in cases:
        report = negotiate(host, extension)
        text = json.dumps(report.to_dict())
        assert "maistro." not in text
        assert ".py" not in text
        assert "import" not in text


# ---------------------------------------------------------------------------
# machine-readable surfaces and fail-fast form
# ---------------------------------------------------------------------------


def test_feature_status_parses_the_closed_vocabulary() -> None:
    """The only string→status path rejects anything the policy does not define."""
    assert parse_feature_status("supported") is FEATURE_SUPPORTED
    assert parse_feature_status("deprecated") is FEATURE_DEPRECATED
    assert parse_feature_status("removed") is FEATURE_REMOVED
    with pytest.raises(CompatError, match="unknown feature status"):
        parse_feature_status("sunset")


def test_report_to_dict_is_json_safe_and_closed_vocabulary() -> None:
    host = make_host(
        features=(
            feature("old", FEATURE_DEPRECATED, removal_target="2.0.0", migration="use 'new'"),
        )
    )
    report = negotiate(
        host,
        make_extension(required=("old",), optional=("teleport",)),
    )
    payload: dict[str, Any] = report.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["verdict"] == "degraded"
    assert round_tripped["supported_features"] == ["old"]
    assert round_tripped["degradations"][0]["feature"] == "teleport"
    assert round_tripped["deprecations"][0] == {
        "feature": "old",
        "status": "deprecated",
        "removal_target": "2.0.0",
        "migration": "use 'new'",
    }
    assert {v.value for v in Verdict} == {"compatible", "degraded", "incompatible"}
    assert {s.value for s in FEATURE_STATUSES} == {"supported", "deprecated", "removed"}


def test_ensure_compatible_passes_compatible_and_degraded_reports_through() -> None:
    host = make_host()
    extension = make_extension(optional=("teleport",))
    report = ensure_compatible(host, extension)
    assert isinstance(report, CompatibilityReport)
    assert report.verdict is Verdict.DEGRADED


def test_ensure_compatible_raises_incompatible_with_actionable_message() -> None:
    host = make_host()
    with pytest.raises(IncompatibleContract) as excinfo:
        ensure_compatible(host, make_extension(contract=">=1.0.0,<2.0.0", required=("teleport",)))
    message = str(excinfo.value)
    assert "'teleport'" in message
    # The exception carries exactly the report's reasons, nothing less.
    report = negotiate(host, make_extension(contract=">=1.0.0,<2.0.0", required=("teleport",)))
    for reason in report.reasons:
        assert reason in message
