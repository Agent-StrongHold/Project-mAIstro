"""Domain-owned serialization for durable Evolve snapshots (#1064).

The Conductor persists ``EvolveDomainSnapshot`` rows through its own durable
domain store, but the export/restore choreography belongs to the package that
owns the stores: genomes, cycle markers and tournament state are serialized
and rebuilt here, so every consumer (the Conductor's capture/restore seams,
plus any future replica) shares one versioned contract instead of reaching
into ``PopulationStore``/``EloTournament`` internals directly.

These functions are deliberate public API (``__all__``): their production
callers live in the downstream Conductor, outside this package's own source
scan, which is why the underlying store methods are port-style surfaces whose
use is indirect rather than dead code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament

__all__ = ["EvolveDomainExport", "export_domain_state", "restore_domain_state"]


@dataclass(frozen=True)
class EvolveDomainExport:
    """The plain payload for one durable snapshot boundary (#1064).

    Carries exactly what the Conductor's persisted ``EvolveDomainSnapshot``
    needs from the in-process domain; the Conductor folds these fields into
    its own store model and hands them back on restart.
    """

    genomes: list[str]
    tournament_state: dict[str, Any]
    cycle_markers: dict[str, dict[str, Any]]


def export_domain_state(
    population: PopulationStore, tournament: EloTournament
) -> EvolveDomainExport:
    """Serialize the full in-process domain at a publication boundary (#1064).

    Genomes export sorted and byte-identical for the same population; the
    tournament export is the versioned serialization (ratings, full battle
    history with canonical NodeRun/Attempt publication identity, next id).
    A store without the cycle-marker ledger (a partial double) contributes
    no markers rather than failing the capture, matching the Conductor's
    historical tolerance at this boundary.
    """
    markers: dict[str, dict[str, Any]] = {}
    if hasattr(population, "export_cycle_markers"):
        markers = population.export_cycle_markers()
    return EvolveDomainExport(
        genomes=population.export_genomes_snapshot(),
        tournament_state=tournament.export_snapshot(),
        cycle_markers=markers,
    )


def restore_domain_state(
    population: PopulationStore,
    tournament: EloTournament,
    export: EvolveDomainExport,
) -> None:
    """Rebuild ``population`` and ``tournament`` in place from ``export`` (#1064).

    Replaces prior state (never merges) so a recovered process holds exactly
    the population the exporting process held. Malformed payloads raise
    (``ValueError``) rather than silently half-restoring; the caller owns
    the fail-closed disposition for a raise after partial restore.
    """
    population.restore_genomes_snapshot(export.genomes)
    population.restore_cycle_markers(export.cycle_markers)
    tournament.restore_snapshot(export.tournament_state)
