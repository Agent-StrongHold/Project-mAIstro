"""Shared conformance and the operator CLI (issue #963, AC6 + AC1).

The suite that proves "reference built-in/external connectors pass shared
conformance": the same ``run_connector_conformance`` runs against an in-tree
reference implementation and an external-style connector, and deliberately
broken connectors fail with named violations instead of passing vacuously.
``maistro connectors verify`` drives the same function from the CLI.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from connectors.connector_fixtures import (
    ExternalStyleConnector,
    Page,
    ScriptedConnector,
)
from maistro.cli._connectors import app
from maistro.connectors import (
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorUnavailableError,
    SecretRef,
    SourceItem,
    StaticSecretAuthority,
    SyncPage,
    run_connector_conformance,
)

runner = CliRunner()

_DECLARED_WORKSPACES = ("ws-primary",)
_SECRET_NAME = "api_token"


def _item(external_id: str) -> SourceItem:
    return SourceItem(source_id="repo", external_id=external_id, content="content", version="v1")


def _conformant_connector(**overrides) -> ScriptedConnector:
    """A reference implementation of the full contract (LIST/QUERY/FETCH)."""
    kwargs = {
        "connector_id": "builtin.reference",
        "secret_refs": (SecretRef(name=_SECRET_NAME, description="Upstream API token"),),
    }
    kwargs.update(overrides)
    return ScriptedConnector(
        {None: Page(items=(_item("doc-1"), _item("doc-2")), next_cursor=None)},
        **kwargs,
    )


def _authority() -> StaticSecretAuthority:
    return StaticSecretAuthority({("ws-primary", _SECRET_NAME): "hunter2"})


async def test_reference_builtin_connector_passes_shared_conformance():
    """AC6: the in-tree reference implementation passes the shared suite."""
    violations = await run_connector_conformance(
        _conformant_connector(),
        workspace_ids=_DECLARED_WORKSPACES,
        secrets=_authority(),
    )

    assert violations == ()


async def test_external_style_connector_passes_the_same_suite():
    """AC6+AC1: a public-SDK-only implementation passes the identical suite."""
    violations = await run_connector_conformance(
        ExternalStyleConnector(
            {None: Page(items=(_item("ext-1"),), next_cursor=None)},
            connector_id="vendor.external",
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert violations == ()


async def test_multi_page_connector_passes_conformance():
    """Paged streams conform too: the cursor walk and dedup checks hold."""
    violations = await run_connector_conformance(
        ScriptedConnector(
            {
                None: Page(items=(_item("doc-1"),), next_cursor="cursor-2"),
                "cursor-2": Page(items=(_item("doc-2"),), next_cursor=None),
            },
            connector_id="builtin.paged",
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert violations == ()


async def test_bare_connector_id_fails_the_descriptor_check():
    violations = await run_connector_conformance(
        _conformant_connector(connector_id="nonamespaced"),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert any("namespaced" in violation for violation in violations)


async def test_undescribed_secret_fails_the_descriptor_check():
    violations = await run_connector_conformance(
        _conformant_connector(
            secret_refs=(SecretRef(name="api_token", description=""),),
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert any("needs a description" in violation for violation in violations)


async def test_duplicate_identity_within_one_listing_fails_conformance():
    """A listing that repeats an identity is a named violation, not a silent loss."""

    class DuplicateFeeder(ScriptedConnector):
        async def list_items(self, ctx):
            page = await super().list_items(ctx)
            return SyncPage(items=page.items + page.items[:1], next_cursor=None)

    violations = await run_connector_conformance(
        DuplicateFeeder(
            {None: Page(items=(_item("doc-1"), _item("doc-2")), next_cursor=None)},
            connector_id="builtin.duplicating",
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert any("same source identity twice" in violation for violation in violations)


async def test_empty_listing_fails_conformance():
    """A connector that yields nothing cannot be verified as working."""
    violations = await run_connector_conformance(
        ScriptedConnector(
            {None: Page(items=(), next_cursor=None)},
            connector_id="builtin.empty",
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert any("no outcomes" in violation for violation in violations)


async def test_scope_escaping_connector_is_reported_not_fatal():
    """A connector raising mid-check produces a violation, not a crashed suite."""

    class ScopeLeakConnector(ScriptedConnector):
        async def list_items(self, ctx):
            raise ConnectorUnavailableError("connector exploded mid-listing")

    violations = await run_connector_conformance(
        ScopeLeakConnector(
            {None: Page(items=(_item("doc-1"),), next_cursor=None)},
            connector_id="builtin.leaky",
        ),
        workspace_ids=_DECLARED_WORKSPACES,
    )

    assert violations, "an exploding connector must not pass silently"


async def test_harness_refuses_to_declare_the_probe_workspace():
    violations = await run_connector_conformance(
        _conformant_connector(),
        workspace_ids=("__conformance_undeclared_workspace__",),
    )

    assert violations, "declaring the probe workspace is a harness misconfiguration"
    assert "misconfigured" in violations[0]


class BrokenCliConnector:
    """Constructible, but violates the descriptor contract (bare id, no items)."""

    @property
    def descriptor(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_id="brokencli",  # not namespaced: a real contract violation
            version="1.0.0",
            capabilities=frozenset({ConnectorCapability.LIST}),
        )

    async def list_items(self, ctx: object) -> SyncPage:
        return SyncPage(items=(), next_cursor=None)

    async def query_items(self, ctx: object) -> SyncPage:
        return SyncPage(items=(), next_cursor=None)

    async def fetch_item(self, ctx: object, external_id: str) -> SourceItem:
        raise ConnectorUnavailableError(f"no item {external_id!r}")


def test_cli_verify_passes_a_conformant_connector():
    """The operator command loads an out-of-tree connector by dotted path."""
    result = runner.invoke(
        app,
        [
            "verify",
            "connectors.connector_fixtures:ExternalStyleConnector",
            "--workspace",
            "ws-primary",
        ],
    )

    assert result.exit_code == 0
    assert "conformant" in result.output


def test_cli_describe_prints_the_declaration():
    """The installer view names id, version, capabilities, and secrets."""
    result = runner.invoke(
        app, ["describe", "connectors.connector_fixtures:ExternalStyleConnector"]
    )

    assert result.exit_code == 0
    assert "tests.scripted @ 1.0.0" in result.output
    assert "fetch, list, query" in result.output


def test_cli_describe_prints_declared_secrets_with_descriptions():
    result = runner.invoke(
        app, ["describe", "connectors.connector_fixtures:DeclaringSecretsConnector"]
    )

    assert result.exit_code == 0
    assert "vendor.secrets" in result.output
    assert "api_token" in result.output
    assert "Upstream API token" in result.output


def test_cli_verify_accepts_the_dotted_class_spelling_without_a_colon():
    """Both module:Class and module.Class reference spellings load."""
    result = runner.invoke(
        app,
        ["verify", "connectors.connector_fixtures.ExternalStyleConnector"],
    )

    assert result.exit_code == 0
    assert "conformant" in result.output


def test_cli_verify_fails_a_broken_connector_with_named_violations():
    result = runner.invoke(app, ["verify", f"{__name__}:BrokenCliConnector"])

    assert result.exit_code == 1
    assert "namespaced" in result.output
    assert "no outcomes" in result.output


def test_cli_verify_reports_an_unloadable_reference():
    result = runner.invoke(app, ["verify", "no.such.module:Missing"])

    assert result.exit_code == 1
    assert "Cannot load connector" in result.output


def test_cli_verify_rejects_a_non_connector_class():
    result = runner.invoke(app, ["verify", "builtins:object"])

    assert result.exit_code == 1
    assert "ConnectorSource protocol" in result.output


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["verify"], id="missing-source-ref"),
    ],
)
def test_cli_verify_requires_the_source_reference(argv: list[str]) -> None:
    result = runner.invoke(app, argv)

    assert result.exit_code != 0


def test_cli_verify_provisions_declared_secrets_for_secret_using_connectors():
    """A connector that resolves its declared secret during listing verifies.

    Pins the operator-surface repair: verify binds a secret authority for the
    run, so a conformant secret-using connector passes once the operator
    provisions the declared names, instead of failing with an unsatisfiable
    'check raised LookupError: ... no secret authority is bound'.
    """
    result = runner.invoke(
        app,
        [
            "verify",
            "connectors.connector_fixtures:SecretUsingConnector",
            "--workspace",
            "ws-primary",
            "--secret",
            "api_token=hunter2",
        ],
    )

    assert result.exit_code == 0
    assert "conformant" in result.output


def test_cli_verify_reports_an_unprovisioned_declared_secret_as_the_operator_gap():
    """Without provisioning, the canonical LookupError names the missing pair.

    The failure is honest — the sync cannot run without the token — but it
    says exactly which (Workspace, secret) pair lacks a value rather than
    blaming the connector or reporting a bare exception type.
    """
    result = runner.invoke(
        app,
        [
            "verify",
            "connectors.connector_fixtures:SecretUsingConnector",
            "--workspace",
            "ws-primary",
        ],
    )

    assert result.exit_code == 1
    assert "no secret provisioned for 'api_token' in workspace 'ws-primary'" in result.output


def test_cli_verify_refuses_a_secret_the_descriptor_never_declared():
    """Provisioning an undeclared name is refused, not silently provisioned."""
    result = runner.invoke(
        app,
        [
            "verify",
            "connectors.connector_fixtures:SecretUsingConnector",
            "--workspace",
            "ws-primary",
            "--secret",
            "admin_password=hunter2",
        ],
    )

    assert result.exit_code == 1
    assert "not declared" in result.output
    assert "api_token" in result.output


def test_cli_verify_rejects_a_malformed_secret_provision():
    result = runner.invoke(
        app,
        [
            "verify",
            "connectors.connector_fixtures:SecretUsingConnector",
            "--secret",
            "api-token-without-a-value",
        ],
    )

    assert result.exit_code == 1
    assert "NAME=VALUE" in result.output
