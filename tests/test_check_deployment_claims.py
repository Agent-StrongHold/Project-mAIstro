"""Deployment docs may not name a service or backend that does not exist (#81).

`DEPLOYMENT-STANCE.md` listed a `maistro-sandbox-worker` in all four supported
profiles, assigned sandbox execution to it, and claimed the installer verifies
it is "configured and reachable". There is no such package, no such compose
service, and no such check — and it survived because nothing compared the prose
to the tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-deployment-claims.py"

PROFILE_HEADER = "| Profile | Components | Use case |\n|---|---|---|\n"
TIER_HEADER = "| Tier | Backend | Ships? |\n|---|---|---|\n"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_deployment_claims", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- the committed state -----------------------------------------------------


def test_the_shipped_document_passes(gate) -> None:
    assert gate.main([]) == 0


# --- rule 1: profile components ----------------------------------------------


def test_the_defect_this_gate_was_written_for(gate) -> None:
    """The literal row that shipped for months. If this ever stops failing, the
    gate has stopped doing the one thing it exists to do."""
    row = "| `full-ui` | maistro-server + sandbox-worker + Hive + persistence | Full |"

    failures = gate.profile_claims(row, {"maistro-server"}, set())

    assert [failure.name for failure in failures] == ["sandbox-worker"]


def test_a_component_that_is_a_package_resolves(gate) -> None:
    row = "| `full-headless` | maistro-server + persistence | API-only |"

    assert gate.profile_claims(row, {"maistro-server"}, set()) == []


def test_a_component_that_is_a_compose_service_resolves(gate) -> None:
    """A deployable unit does not have to be a package in this repo — the
    database is a service and nothing else."""
    row = "| `full-ui` | postgres-primary | Full |"

    assert gate.profile_claims(row, set(), {"postgres-primary"}) == []


def test_a_capability_word_is_not_treated_as_a_service(gate) -> None:
    """`persistence` and `Hive` name capabilities, not units. The exemption
    list is explicit so adding to it is a decision rather than a silent hole."""
    row = "| `full-ui` | Hive + persistence + UI | Full |"

    assert gate.profile_claims(row, set(), set()) == []


def test_compose_services_are_read_from_the_real_files(gate, tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "version: '3'\nservices:\n  api:\n    image: x\n  worker:\n    image: y\nvolumes:\n  data:\n"
    )

    found = gate.compose_services((compose,))

    # `data` is a volume, not a service: the parser has to leave the services
    # block when the indent returns to column zero.
    assert found == {"api", "worker"}


# --- rule 2: shipping backends ------------------------------------------------


def test_a_tier_that_claims_to_ship_must_name_a_real_module(gate, tmp_path: Path) -> None:
    (tmp_path / "bubblewrap.py").write_text("")
    row = TIER_HEADER + "| 2 — gVisor | `maistro.sandbox.backends.gvisor` | **Yes.** |\n"

    failures = gate.backend_claims(row, tmp_path)

    assert len(failures) == 1
    assert "gvisor" in failures[0].name


def test_a_tier_that_ships_and_names_a_real_module_passes(gate, tmp_path: Path) -> None:
    (tmp_path / "bubblewrap.py").write_text("")
    row = TIER_HEADER + "| 3 — namespace | `maistro.sandbox.backends.bubblewrap` | **Yes.** |\n"

    assert gate.backend_claims(row, tmp_path) == []


def test_a_tier_that_does_not_claim_to_ship_is_not_checked(gate, tmp_path: Path) -> None:
    """Naming Firecracker as a tier with no backend is the honest state, and
    the point of the Ships? column. Only a `Yes` is a claim."""
    row = TIER_HEADER + "| 1 — VM | microVM (Firecracker) | **No backend.** Probed only. |\n"

    assert gate.backend_claims(row, tmp_path) == []


def test_claiming_to_ship_without_naming_anything_fails(gate, tmp_path: Path) -> None:
    row = TIER_HEADER + "| 3 — namespace | some backend | **Yes.** |\n"

    failures = gate.backend_claims(row, tmp_path)

    assert "names no module" in failures[0].message


def test_main_reports_each_claim_and_fails(gate, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        gate, "audit", lambda: [gate.Claim("profile `x`", "ghost", "names 'ghost'")]
    )

    exit_code = gate.main([])
    printed = capsys.readouterr().out

    assert exit_code == 1
    assert "profile `x`: names 'ghost'" in printed
    assert "mark what is planned as planned" in printed


def test_main_fails_when_the_document_is_missing(gate, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gate, "STANCE", tmp_path / "gone.md")

    assert gate.main([]) == 1
