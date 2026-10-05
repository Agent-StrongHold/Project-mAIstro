"""Host-upgrade compatibility preflight (#957, M9-C3).

Every test names the acceptance criterion it pins:

- the target upgrade is evaluated from data alone — no target code is
  imported, no extension is activated, nothing is written (the CLI leg opens
  the store read-only, so a successful preflight *is* the no-write proof);
- incompatible extensions are named with the exact contract or dependency
  conflict;
- a strict policy refuses the upgrade while blocking extensions remain
  enabled, and enabled-ness is the operator's lever;
- warnings and hard blockers are distinct collections and distinct verdicts;
- the preflight reads only public contract metadata (the module's imports are
  checked structurally);
- the report is reproducible: byte-identical canonical JSON across repeated
  evaluations, across independently built equal lock states, and across a
  SQLite restart.

The parametrized "representative version transitions" matrix is the CI
fixture the issue asks for: minor bumps, major boundaries, capability
deprecations/removals, dependency drift.
"""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from extensions.extension_fixtures import install_bundle
from maistro.cli._extensions import app
from maistro.extensions import preflight
from maistro.extensions.preflight import (
    ExtensionStatus,
    ManifestContractError,
    PreflightPolicy,
    TargetHostContract,
    current_lock_state,
    parse_semantic_version,
    parse_version_range,
    run_preflight,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import InMemoryExtensionInstallStore
from maistro.extensions.types import (
    InstallRecord,
    PackageIdentity,
    PublisherIdentity,
    RegistryProvenance,
    TrustEvidence,
    manifest_snapshot,
    sha256_hex,
)

runner = CliRunner()

REGISTERED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 9, 2, 8, 30, 0, tzinfo=UTC)
INSTALLED_AT = datetime(2026, 9, 3, 9, 0, 0, tzinfo=UTC)


def manifest_json(
    *,
    contract: str = ">=2.0.0,<3.0.0",
    capabilities: tuple[str, ...] = (),
    dependencies: tuple[tuple[str, str], ...] = (),
    with_entrypoint: bool = True,
) -> str:
    """A representative public manifest document for the given metadata.

    The default contract range includes the default target's contract
    version (2.0.0), so a plain record evaluates compatible and each test
    names only the deviation it studies.
    """
    document: dict[str, Any] = {
        "id": "pub.ext",
        "publisher": "pub",
        "version": "1.0.0",
        "title": "Ext",
        "description": "A governed extension.",
        "contract": contract,
        "family": "tool",
        "capabilities": list(capabilities),
        "effects": ["read-only"],
        "data": {"scopes": []},
        "dependencies": [{"id": dep, "range": rng} for dep, rng in dependencies],
    }
    if with_entrypoint:
        document["entrypoint"] = {"module": "ext.plugin", "object": "PLUGIN"}
    return json.dumps(document, sort_keys=True)


def make_record(
    name: str = "ext-a",
    version: str = "1.0.0",
    manifest_body: str | None = None,
    *,
    installed_at: datetime = INSTALLED_AT,
    install_id: str = "install-1",
) -> InstallRecord:
    """A fabricated install record: identity, manifest snapshot, evidence."""
    body = manifest_body if manifest_body is not None else manifest_json()
    return InstallRecord(
        install_id=install_id,
        identity=PackageIdentity(
            extension_name=name,
            semantic_version=version,
            package_sha256=sha256_hex(f"{name}@{version}".encode()),
            manifest_sha256=manifest_snapshot(body).sha256,
        ),
        publisher=PublisherIdentity(
            publisher_id="pub",
            display_name="Publisher",
            signing_key_fingerprint="f" * 64,
            signing_public_key="a" * 64,
            registered_at=REGISTERED_AT,
        ),
        signature="signature",
        manifest=manifest_snapshot(body),
        provenance=RegistryProvenance(
            catalog_url="https://catalog.example/extensions.json",
            catalog_snapshot_sha256="b" * 64,
            retrieved_at=RETRIEVED_AT,
        ),
        evidence=TrustEvidence(
            verified=True,
            verifier_key_fingerprint="f" * 64,
            policy="ed25519-canonical-install:v1",
            subject_sha256=sha256_hex(f"{name}@{version}".encode()),
            verified_at=RETRIEVED_AT,
        ),
        installed_at=installed_at,
    )


def base_target(**overrides: Any) -> TargetHostContract:
    """The representative target contract the transition matrix runs against."""
    metadata: dict[str, Any] = {
        "host_version": "2.0.0",
        "contract_version": "2.0.0",
        "capabilities": frozenset({"workspace.read", "tool.invoke", "run.read"}),
        "deprecated": {"memory.read": "read workspace projections instead"},
        "removed": {"secrets.read": "removed in contract 2.0.0; use host secret refs"},
    }
    metadata.update(overrides)
    return TargetHostContract(**metadata)


# ---------------------------------------------------------------------------
# AC: preflight uses public contract metadata, not target-private internals.
# ---------------------------------------------------------------------------


def test_preflight_module_imports_only_public_contract_metadata() -> None:
    """The module's maistro-imports stop at the public record model.

    Structural proof of the acceptance criterion: the preflight evaluates a
    target release it never imports. If someone wires a target-private
    import in, the module source names it and this fails.
    """
    module_file = preflight.__file__
    assert module_file is not None and module_file.endswith("preflight.py")
    tree = ast.parse(Path(module_file).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    maistro_imports = [
        name for name in imported if name == "maistro" or name.startswith("maistro.")
    ]
    assert maistro_imports == ["maistro.extensions.types"], (
        f"preflight must import only the public record model, saw {maistro_imports}"
    )


def test_preflight_never_imports_the_extension_entrypoint() -> None:
    """AC: evaluation never activates extension code.

    The manifest names an entrypoint module that cannot exist; if the
    preflight tried to resolve or import it, the evaluation would fail. It
    must succeed on metadata alone.
    """
    record = make_record(
        manifest_body=manifest_json(with_entrypoint=True).replace(
            '"ext.plugin"', '"no.such.module.exists"'
        )
    )
    report = run_preflight([record], base_target())
    assert report.rows[0].status is ExtensionStatus.COMPATIBLE


# ---------------------------------------------------------------------------
# AC: target upgrade evaluated without activating the new host version.
# ---------------------------------------------------------------------------


def test_evaluation_never_touches_the_target_release() -> None:
    """The target contract is plain data; evaluating imports no new module."""
    import sys

    target = base_target()
    record = make_record(name="ext-a", manifest_body=manifest_json())
    before = set(sys.modules)
    report = run_preflight([record], target)
    new_modules = set(sys.modules) - before
    assert report.can_proceed is True
    assert not any(name.startswith(("ext_a", "no.such")) for name in new_modules)


# ---------------------------------------------------------------------------
# Representative version transitions (the CI fixture).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "contract", "target_kwargs", "expected"),
    [
        ("patch", ">=1.0.0,<2.0.0", {"contract_version": "1.0.1"}, ExtensionStatus.COMPATIBLE),
        ("minor", ">=1.0.0,<2.0.0", {"contract_version": "1.4.0"}, ExtensionStatus.COMPATIBLE),
        (
            "major-repin-required",
            ">=1.0.0,<2.0.0",
            {"contract_version": "2.0.0"},
            ExtensionStatus.BLOCKING,
        ),
        (
            "major-older-pin",
            ">=1.0.0,<2.0.0",
            {"contract_version": "3.0.0"},
            ExtensionStatus.BLOCKING,
        ),
        (
            "spanning-range-migrates",
            ">=1.0.0,<3.0.0",
            {"contract_version": "2.0.0"},
            ExtensionStatus.MIGRATION_REQUIRED,
        ),
        (
            "unbounded-range-migrates",
            ">=1.0.0",
            {"contract_version": "1.5.0"},
            ExtensionStatus.MIGRATION_REQUIRED,
        ),
        (
            "exact-pin-compatible",
            "==1.2.0",
            {"contract_version": "1.2.0"},
            ExtensionStatus.COMPATIBLE,
        ),
        (
            "exact-pin-blocks",
            "==1.2.0",
            {"contract_version": "1.3.0"},
            ExtensionStatus.BLOCKING,
        ),
    ],
)
def test_contract_transition_matrix(
    label: str,
    contract: str,
    target_kwargs: dict[str, Any],
    expected: ExtensionStatus,
) -> None:
    """Representative host/contract transitions evaluate to the pinned verdict."""
    record = make_record(name="ext-a", manifest_body=manifest_json(contract=contract))
    report = run_preflight([record], base_target(**target_kwargs))
    row = report.rows[0]
    assert row.status is expected, f"transition {label}: {row.conflicts}"
    # The default policy is permissive: blockers are reported, never refused.
    assert report.can_proceed is True
    assert row.conflicts == () or expected is ExtensionStatus.BLOCKING


def test_capability_removal_transition_blocks_with_the_exact_name() -> None:
    """AC: exact conflict — removed capability named with its removal note."""
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(capabilities=("workspace.read", "secrets.read")),
    )
    report = run_preflight([record], base_target())
    row = report.rows[0]
    assert row.status is ExtensionStatus.BLOCKING
    assert any(
        "'secrets.read'" in conflict
        and "removed in the target host contract 2.0.0" in conflict
        and "host secret refs" in conflict
        for conflict in row.conflicts
    )
    assert row.warnings == ()


def test_capability_deprecation_transition_warns_with_replacement() -> None:
    """Deprecated capability: distinct warning verdict, replacement metadata."""
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(capabilities=("memory.read", "workspace.read")),
    )
    report = run_preflight([record], base_target())
    row = report.rows[0]
    assert row.status is ExtensionStatus.DEPRECATION
    assert any(
        "'memory.read'" in warning and "workspace projections" in warning
        for warning in row.warnings
    )
    assert row.conflicts == ()


def test_unknown_capability_blocks_only_against_a_declared_vocabulary() -> None:
    """No declared vocabulary = no opinion; a declared one is enforced."""
    record = make_record(name="ext-a", manifest_body=manifest_json(capabilities=("brand.new.cap",)))
    with_vocabulary = run_preflight([record], base_target())
    assert with_vocabulary.rows[0].status is ExtensionStatus.BLOCKING
    assert any("'brand.new.cap'" in c for c in with_vocabulary.rows[0].conflicts)

    bare = TargetHostContract(host_version="2.0.0", contract_version="2.0.0")
    without_vocabulary = run_preflight([record], bare)
    assert without_vocabulary.rows[0].status is ExtensionStatus.COMPATIBLE


# ---------------------------------------------------------------------------
# AC: incompatible extensions named with the exact dependency conflict.
# ---------------------------------------------------------------------------


def test_missing_dependency_blocks_with_id_and_range() -> None:
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(dependencies=(("ext-b", ">=1.0.0,<2.0.0"),)),
    )
    report = run_preflight([record], base_target())
    conflicts = report.rows[0].conflicts
    assert report.rows[0].status is ExtensionStatus.BLOCKING
    assert any("'ext-b'" in c and "not installed" in c and ">=1.0.0,<2.0.0" in c for c in conflicts)


def test_dependency_version_mismatch_names_the_installed_version() -> None:
    records = [
        make_record(
            name="ext-a",
            manifest_body=manifest_json(dependencies=(("ext-b", ">=2.0.0"),)),
        ),
        make_record(name="ext-b", version="1.5.0"),
    ]
    report = run_preflight(records, base_target())
    row = report.rows[0]
    assert row.extension_name == "ext-a"
    assert row.status is ExtensionStatus.BLOCKING
    assert any(
        "'ext-b'" in c and "'>=2.0.0'" in c and "1.5.0 is installed" in c for c in row.conflicts
    )
    # The dependency itself is fine against the target; only the edge conflicts.
    dependency_row = report.rows[1]
    assert dependency_row.status is ExtensionStatus.COMPATIBLE


def test_satisfied_dependency_does_not_conflict() -> None:
    records = [
        make_record(
            name="ext-a",
            manifest_body=manifest_json(dependencies=(("ext-b", ">=1.0.0,<2.0.0"),)),
        ),
        make_record(name="ext-b", version="1.5.0"),
    ]
    report = run_preflight(records, base_target())
    assert all(row.status is ExtensionStatus.COMPATIBLE for row in report.rows)


def test_transitive_blocking_dependency_names_the_chain() -> None:
    """A dependency that cannot survive the upgrade blocks its dependents."""
    records = [
        make_record(
            name="ext-a",
            manifest_body=manifest_json(dependencies=(("ext-b", ">=1.0.0"),)),
        ),
        make_record(name="ext-b", manifest_body=manifest_json(contract=">=1.0.0,<2.0.0")),
    ]
    report = run_preflight(records, base_target())  # target contract 2.0.0
    dependent = report.rows[0]
    assert dependent.extension_name == "ext-a"
    assert dependent.status is ExtensionStatus.BLOCKING
    assert any(
        "'ext-b'" in c and "blocking on the target host" in c and "'>=1.0.0'" in c
        for c in dependent.conflicts
    )


def test_transitive_migration_dependency_is_inherited() -> None:
    records = [
        make_record(
            name="ext-a",
            manifest_body=manifest_json(dependencies=(("ext-b", ">=1.0.0"),)),
        ),
        make_record(name="ext-b", manifest_body=manifest_json(contract=">=1.0.0,<3.0.0")),
    ]
    report = run_preflight(records, base_target(contract_version="2.0.0"))
    dependent = report.rows[0]
    assert dependent.status is ExtensionStatus.MIGRATION_REQUIRED
    assert any(
        "'ext-b'" in note and "inherits the migration" in note for note in dependent.migration_notes
    )


def test_self_dependency_is_a_conflict() -> None:
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(dependencies=(("ext-a", ">=1.0.0"),)),
    )
    report = run_preflight([record], base_target())
    assert any("itself" in c for c in report.rows[0].conflicts)


def test_unreadable_manifest_blocks_with_the_exact_reason() -> None:
    for body in ("{not json", json.dumps(["a", "list"]), json.dumps({"version": "1.0.0"})):
        record = make_record(name="ext-a", manifest_body=body)
        report = run_preflight([record], base_target())
        row = report.rows[0]
        assert row.status is ExtensionStatus.BLOCKING, body
        assert row.conflicts, body
        assert row.contract_range == ""  # nothing readable to display


# ---------------------------------------------------------------------------
# AC: strict policy refuses the upgrade while blocking extensions are enabled.
# ---------------------------------------------------------------------------


def test_strict_policy_cannot_proceed_with_enabled_blocker() -> None:
    blocker = make_record(name="ext-a", manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"))
    report = run_preflight([blocker], base_target(), policy=PreflightPolicy.STRICT)
    assert report.can_proceed is False
    assert len(report.blockers) == 1


def test_strict_policy_proceeds_when_the_blocker_is_disabled() -> None:
    """Enabled-ness is the operator's lever: disabled extensions cannot block."""
    blocker = make_record(name="ext-a", manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"))
    report = run_preflight(
        [blocker],
        base_target(),
        policy=PreflightPolicy.STRICT,
        enabled=frozenset({"something-else"}),
    )
    row = report.rows[0]
    assert row.status is ExtensionStatus.BLOCKING  # still incompatible…
    assert row.enabled is False
    assert report.blockers == ()  # …but it cannot block the upgrade
    assert report.can_proceed is True


def test_permissive_policy_reports_blockers_but_can_proceed() -> None:
    blocker = make_record(name="ext-a", manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"))
    report = run_preflight([blocker], base_target(), policy=PreflightPolicy.PERMISSIVE)
    assert report.can_proceed is True
    assert len(report.blockers) == 1


def test_policy_from_name_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="unknown preflight policy"):
        PreflightPolicy.from_name("yolo")
    assert PreflightPolicy.from_name(" STRICT ") is PreflightPolicy.STRICT


# ---------------------------------------------------------------------------
# AC: warnings and hard blockers are distinct.
# ---------------------------------------------------------------------------


def test_warnings_and_blockers_land_in_distinct_collections() -> None:
    deprecated = make_record(
        name="ext-dep",
        manifest_body=manifest_json(capabilities=("memory.read",)),
    )
    blocker = make_record(name="ext-block", manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"))
    clean = make_record(name="ext-ok")
    report = run_preflight([deprecated, blocker, clean], base_target())
    assert [row.extension_name for row in report.blockers] == ["ext-block"]
    assert [row.extension_name for row in report.warning_rows] == ["ext-dep"]
    blocker_row = next(row for row in report.rows if row.extension_name == "ext-block")
    assert blocker_row.warnings == ()  # a blocker is not also counted as a warning


def test_migration_required_outranks_deprecated() -> None:
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(contract=">=1.0.0,<3.0.0", capabilities=("memory.read",)),
    )
    report = run_preflight([record], base_target(contract_version="2.0.0"))
    row = report.rows[0]
    assert row.status is ExtensionStatus.MIGRATION_REQUIRED
    assert row.warnings  # the deprecation is still reported…
    assert row.migration_notes  # …and so is the required migration


# ---------------------------------------------------------------------------
# AC: the report is reproducible from installed lock state.
# ---------------------------------------------------------------------------


def test_report_is_byte_identical_across_repeated_evaluations() -> None:
    records = [
        make_record(name="ext-a", manifest_body=manifest_json(capabilities=("memory.read",))),
        make_record(name="ext-b", version="1.1.0"),
    ]
    first = run_preflight(records, base_target(), policy=PreflightPolicy.STRICT)
    second = run_preflight(records, base_target(), policy=PreflightPolicy.STRICT)
    assert first.canonical_json() == second.canonical_json()


def test_report_is_identical_for_equal_but_independently_built_lock_states() -> None:
    def build() -> list[InstallRecord]:
        return [
            make_record(name="ext-a", install_id="install-a"),
            make_record(name="ext-b", version="1.1.0", install_id="install-b"),
        ]

    first = run_preflight(build(), base_target())
    second = run_preflight(build(), base_target())
    assert first.canonical_json() == second.canonical_json()


def test_report_carries_no_wall_clock() -> None:
    """Only lock-state timestamps appear; evaluation time does not."""
    records = [make_record(name="ext-a")]
    report = run_preflight(records, base_target())
    payload = json.loads(report.canonical_json())
    assert set(payload) == {
        "target_host_version",
        "target_contract_version",
        "policy",
        "can_proceed",
        "rows",
    }
    assert all("evaluated_at" not in row for row in payload["rows"])


# ---------------------------------------------------------------------------
# Lock state: one row per extension, the current install.
# ---------------------------------------------------------------------------


def test_current_lock_state_picks_the_latest_install_per_extension() -> None:
    records = [
        make_record(name="ext-a", version="1.0.0", installed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        make_record(
            name="ext-a",
            version="1.1.0",
            installed_at=datetime(2026, 2, 1, tzinfo=UTC),
            install_id="install-2",
        ),
        make_record(name="ext-b", version="2.0.0"),
    ]
    lock = current_lock_state(records)
    assert [(r.identity.extension_name, r.identity.semantic_version) for r in lock] == [
        ("ext-a", "1.1.0"),
        ("ext-b", "2.0.0"),
    ]


def test_preflight_matrix_has_one_row_per_extension() -> None:
    records = [
        make_record(name="ext-a", version="1.0.0", installed_at=datetime(2026, 1, 1, tzinfo=UTC)),
        make_record(
            name="ext-a",
            version="1.1.0",
            installed_at=datetime(2026, 2, 1, tzinfo=UTC),
            install_id="install-2",
            manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"),
        ),
    ]
    report = run_preflight(records, base_target(contract_version="1.1.0"))
    assert len(report.rows) == 1
    assert report.rows[0].semantic_version == "1.1.0"
    assert report.rows[0].status is ExtensionStatus.COMPATIBLE


def test_empty_lock_state_proceeds_under_strict() -> None:
    report = run_preflight([], base_target(), policy=PreflightPolicy.STRICT)
    assert report.rows == ()
    assert report.can_proceed is True


# ---------------------------------------------------------------------------
# Version/range grammar: malformed metadata blocks with exact text, never guesses.
# ---------------------------------------------------------------------------


def test_malformed_contract_range_blocks_with_exact_text() -> None:
    record = make_record(name="ext-a", manifest_body=manifest_json(contract=">=1.0"))
    report = run_preflight([record], base_target())
    assert any("'>=1.0'" in c and "comparator" in c for c in report.rows[0].conflicts)


def test_version_range_parser_errors_name_the_offender() -> None:
    for bad in ("", "1.0.0", ">=1.0.0;", "~=1.0.0", ">=1.0.0,<2"):
        with pytest.raises(ManifestContractError, match="malformed version range"):
            parse_version_range(bad)


def test_version_range_admits_is_exact_comparator_math() -> None:
    """Boundary semantics: closed floors, open ceilings, exact pins."""
    rng = parse_version_range(">=1.0.0,<2.0.0")
    assert rng.admits(parse_semantic_version("1.0.0"))
    assert rng.admits(parse_semantic_version("1.9.9"))
    assert not rng.admits(parse_semantic_version("2.0.0"))
    assert not rng.admits(parse_semantic_version("0.9.9"))

    closed = parse_version_range(">=1.0.0,<=2.0.0")
    assert closed.admits(parse_semantic_version("2.0.0"))

    exact = parse_version_range("==1.2.0")
    assert exact.admits(parse_semantic_version("1.2.0"))
    assert not exact.admits(parse_semantic_version("1.2.1"))

    excluded = parse_version_range(">=1.0.0,!=1.5.0")
    assert not excluded.admits(parse_semantic_version("1.5.0"))
    assert excluded.admits(parse_semantic_version("1.5.1"))


def test_version_range_span_detection_matches_the_authoring_rule() -> None:
    """Pin-one-major is the rule; crossing a boundary is the violation."""
    assert not parse_version_range(">=1.0.0,<2.0.0").spans_multiple_majors()
    assert not parse_version_range("==1.2.0").spans_multiple_majors()
    assert not parse_version_range(">=0.1.0,<1.0.0").spans_multiple_majors()
    assert parse_version_range(">=1.0.0,<3.0.0").spans_multiple_majors()
    assert parse_version_range(">=1.0.0,<2.1.0").spans_multiple_majors()
    assert parse_version_range(">=1.0.0,<=2.0.0").spans_multiple_majors()
    assert parse_version_range(">=1.0.0").spans_multiple_majors()


def test_semantic_version_parser_rejects_non_semver() -> None:
    for bad in ("1.0", "v1.0.0", "1.0.0-beta", "01.0.0"):
        with pytest.raises(ManifestContractError, match="malformed semantic version"):
            parse_semantic_version(bad)


def test_target_contract_metadata_is_validated_eagerly() -> None:
    with pytest.raises(ManifestContractError, match="malformed semantic version"):
        base_target(host_version="two")
    with pytest.raises(ManifestContractError, match="both deprecated and removed"):
        base_target(
            deprecated={"x.cap": "replacement"},
            removed={"x.cap": "note"},
        )


def test_malformed_dependency_range_blocks() -> None:
    record = make_record(
        name="ext-a",
        manifest_body=manifest_json(dependencies=(("ext-b", "latest"),)),
    )
    report = run_preflight([record], base_target())
    assert any("'ext-b'" in c and "malformed version range" in c for c in report.rows[0].conflicts)


# ---------------------------------------------------------------------------
# The lock-state read seam, over both store legs (#957 all_installs).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_all_installs_returns_every_record_across_extensions(
    store_kind: str, tmp_path: Path
) -> None:
    """One read returns the whole installed set, ordered by extension name."""
    shared_key = Ed25519PrivateKey.generate()
    bundles = [
        install_bundle(
            name="ext-b", version="1.0.0", manifest_body=manifest_json(), signer=shared_key
        ),
        install_bundle(
            name="ext-a", version="2.0.0", manifest_body=manifest_json(), signer=shared_key
        ),
    ]
    conn: aiosqlite.Connection | None = None

    async def scenario() -> list[InstallRecord]:
        nonlocal conn
        store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore
        if store_kind == "memory":
            store = InMemoryExtensionInstallStore()
        else:
            conn = await aiosqlite.connect(tmp_path / "installs.db")
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
        try:
            for bundle in bundles:
                await store.register_publisher(bundle["publisher"])
                await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
            return await store.all_installs()
        finally:
            if conn is not None:
                await conn.close()

    records = asyncio.run(scenario())
    assert [r.identity.extension_name for r in records] == ["ext-a", "ext-b"]


def test_report_is_reproducible_across_a_sqlite_restart(tmp_path: Path) -> None:
    """AC: reproducible from installed lock state — the restart leg.

    Records are written through the real store with real signatures; each
    evaluation reads the file back over its own fresh connection, so the
    identical reports prove the report is a function of the durable lock
    state, not of any process state.
    """
    db_path = tmp_path / "installs.db"
    bundle = install_bundle(
        name="ext-a",
        version="1.0.0",
        manifest_body=manifest_json(capabilities=("memory.read",)),
    )

    async def seed() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
            await store.register_publisher(bundle["publisher"])
            await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
        finally:
            await conn.close()

    asyncio.run(seed())
    first = run_preflight(_read_back(db_path), base_target())
    second = run_preflight(_read_back(db_path), base_target())
    assert first.canonical_json() == second.canonical_json()


def _read_back(db_path: Path) -> list[InstallRecord]:
    """Fresh read-only connection over the seeded file (the restart leg)."""

    async def read() -> list[InstallRecord]:
        conn = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            return await SqliteExtensionInstallStore(conn).all_installs()
        finally:
            await conn.close()

    records = asyncio.run(read())
    assert records, "the restart must read the seeded records back"
    return records


# ---------------------------------------------------------------------------
# The operator surface: distinct sections, strict exits non-zero, read-only.
# ---------------------------------------------------------------------------


def _seed_db(db_path: Path, *bundles: dict[str, Any]) -> None:
    async def seed() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
            for bundle in bundles:
                await store.register_publisher(bundle["publisher"])
                await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
        finally:
            await conn.close()

    asyncio.run(seed())


def _blocking_bundle(signer: Ed25519PrivateKey | None = None) -> dict[str, Any]:
    return install_bundle(
        name="ext-block",
        version="1.0.0",
        manifest_body=manifest_json(contract=">=1.0.0,<2.0.0"),
        signer=signer,
    )


def test_cli_preflight_names_blockers_and_exits_nonzero_under_strict(tmp_path: Path) -> None:
    """AC: strict policy + enabled blocker = non-zero exit; blocker named."""
    db_path = tmp_path / "installs.db"
    bundle = _blocking_bundle()
    _seed_db(db_path, bundle)

    result = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--policy",
            "strict",
        ],
    )
    assert result.exit_code == 1
    assert "ext-block@1.0.0" in result.output
    assert "Blocking extensions" in result.output
    assert ">=1.0.0,<2.0.0" in result.output
    assert "refuses the upgrade" in result.output


def test_cli_preflight_permissive_reports_and_exits_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "installs.db"
    _seed_db(db_path, _blocking_bundle())

    result = runner.invoke(
        app,
        ["preflight", str(db_path), "2.0.0", "--contract-version", "2.0.0"],
    )
    assert result.exit_code == 0
    assert "Blocking extensions" in result.output
    assert "can proceed" in result.output


def test_cli_preflight_disabled_blocker_proceeds_under_strict(tmp_path: Path) -> None:
    """AC: the upgrade cannot be refused by an extension the host disabled."""
    db_path = tmp_path / "installs.db"
    _seed_db(db_path, _blocking_bundle())

    result = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--policy",
            "strict",
            "--enabled",
            "other.extension",
        ],
    )
    assert result.exit_code == 0
    assert "ext-block" in result.output  # still reported, as disabled
    assert "the upgrade can proceed" in result.output


def test_cli_preflight_reproducible_json_output(tmp_path: Path) -> None:
    db_path = tmp_path / "installs.db"
    _seed_db(db_path, _blocking_bundle())
    argv = ["preflight", str(db_path), "2.0.0", "--contract-version", "2.0.0", "--json"]

    first = runner.invoke(app, argv)
    second = runner.invoke(app, argv)
    assert first.exit_code == 0 and second.exit_code == 0
    assert first.output == second.output
    payload = json.loads(first.output)
    assert payload["target_host_version"] == "2.0.0"
    assert payload["rows"][0]["status"] == "blocking"


def test_cli_preflight_warns_distinctly_from_blockers(tmp_path: Path) -> None:
    """AC: warnings and hard blockers render as separate sections."""
    db_path = tmp_path / "installs.db"
    shared_key = Ed25519PrivateKey.generate()
    _seed_db(
        db_path,
        _blocking_bundle(shared_key),
        install_bundle(
            name="ext-warn",
            version="1.0.0",
            manifest_body=manifest_json(capabilities=("memory.read",)),
            signer=shared_key,
        ),
    )
    result = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--deprecated-capability",
            "memory.read=read workspace projections instead",
        ],
    )
    assert result.exit_code == 0
    blockers_at = result.output.index("Blocking extensions")
    warnings_at = result.output.index("Warnings")
    assert blockers_at < warnings_at
    assert "ext-block@1.0.0" in result.output[blockers_at:warnings_at]
    assert "ext-warn@1.0.0" in result.output[warnings_at:]
    assert "deprecated" in result.output


def test_cli_preflight_over_a_read_only_store_writes_nothing(tmp_path: Path) -> None:
    """AC: evaluation without activation — the store is opened mode=ro."""
    db_path = tmp_path / "installs.db"
    _seed_db(db_path, install_bundle(name="ext-ok", manifest_body=manifest_json()))
    before = db_path.read_bytes()

    result = runner.invoke(app, ["preflight", str(db_path), "2.0.0", "--contract-version", "2.0.0"])

    assert result.exit_code == 0
    assert db_path.read_bytes() == before


def test_cli_preflight_missing_database_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["preflight", str(tmp_path / "nope.db"), "2.0.0", "--contract-version", "2.0.0"],
    )
    assert result.exit_code == 1


def test_cli_preflight_invalid_policy_and_metadata_exit_nonzero(tmp_path: Path) -> None:
    db_path = tmp_path / "installs.db"
    _seed_db(db_path, install_bundle(name="ext-ok", manifest_body=manifest_json()))

    bad_policy = runner.invoke(
        app,
        ["preflight", str(db_path), "2.0.0", "--contract-version", "2.0.0", "--policy", "yolo"],
    )
    assert bad_policy.exit_code == 1
    assert "unknown preflight policy" in bad_policy.output

    bad_meta = runner.invoke(
        app,
        ["preflight", str(db_path), "not-a-version", "--contract-version", "2.0.0"],
    )
    assert bad_meta.exit_code == 1
    assert "Invalid target contract metadata" in bad_meta.output

    bad_capability_meta = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--removed-capability",
            "secrets.read",
        ],
    )
    assert bad_capability_meta.exit_code == 1
    assert "expects NAME=note" in bad_capability_meta.output


def test_cli_preflight_empty_store_proceeds(tmp_path: Path) -> None:
    db_path = tmp_path / "installs.db"

    async def make_schema() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            await SqliteExtensionInstallStore(conn).ensure_schema()
        finally:
            await conn.close()

    asyncio.run(make_schema())
    result = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--policy",
            "strict",
        ],
    )
    assert result.exit_code == 0
    assert "No installed extensions" in result.output


def test_cli_preflight_removed_capability_flag_enforced(tmp_path: Path) -> None:
    """The CLI target metadata drives the verdict: removal blocks, exit 1."""
    db_path = tmp_path / "installs.db"
    _seed_db(
        db_path,
        install_bundle(
            name="ext-ok",
            manifest_body=manifest_json(capabilities=("secrets.read",)),
        ),
    )
    result = runner.invoke(
        app,
        [
            "preflight",
            str(db_path),
            "2.0.0",
            "--contract-version",
            "2.0.0",
            "--removed-capability",
            "secrets.read=removed in 2.0.0",
            "--policy",
            "strict",
        ],
    )
    assert result.exit_code == 1
    assert "'secrets.read'" in result.output
