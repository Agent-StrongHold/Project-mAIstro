"""Copier command resolution for the updateable monorepo dispatcher."""

from __future__ import annotations

import pytest

from maistro_bootstrap.resolver import copier_command

pytestmark = [
    pytest.mark.contract("behavioral"),
    pytest.mark.scope("unit"),
]


def test_product_uses_root_dispatcher_without_blanket_trust() -> None:
    command = copier_command("autonoetic", "../my product")

    assert command == ("uv run copier copy --data product_template=autonoetic . '../my product'")
    assert "--trust" not in command


def test_destination_is_shell_quoted_even_though_command_is_print_only() -> None:
    command = copier_command(
        "single-tenant-multi-user",
        "$(touch /tmp/copier-command-injection)",
    )

    assert command is not None
    assert command.endswith(" '$(touch /tmp/copier-command-injection)'")


def test_incomplete_multi_tenant_seed_stays_outside_root_dispatcher() -> None:
    command = copier_command("multi-tenant", "../stronghold-seed")

    assert command == "uv run copier copy templates/multi-tenant ../stronghold-seed"
    assert "product_template" not in command


def test_unknown_product_has_no_command() -> None:
    assert copier_command("not-a-product", "../output") is None
