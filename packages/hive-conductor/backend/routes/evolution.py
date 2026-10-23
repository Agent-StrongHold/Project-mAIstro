"""Evolution API routes -- population, fitness, tournament, cycle control."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from services.request_principal import optional_actor_id

router = APIRouter(tags=["evolution"])
logger = logging.getLogger("hive.evolution.routes")


def _actor_principal_id(request: Request) -> str | None:
    explicit = getattr(request.state, "user_id", None)
    if explicit:
        return str(explicit)
    actor = optional_actor_id(request)
    return actor or None


@router.get("/status")
def evolution_status() -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        status = dict(svc.status())
        # Stored diagnostics can contain provider credentials and local paths.
        if status.get("last_error"):
            status["last_error"] = "evolution cycle failed; see server logs"
        if status.get("availability_reason"):
            status["availability_reason"] = "evolution execution unavailable; see server logs"
        return status
    except RuntimeError:
        return {
            "running": False,
            "execution_available": False,
            "availability": "unavailable",
            "availability_reason": "evolution service not started",
            "domain_state_only": True,
            "cycle_count": 0,
            "population_size": 0,
            "last_error": None,
            "last_run_id": None,
            "last_run_status": None,
            "tournament": {},
        }


@router.get("/population")
def list_population() -> list[dict]:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.population is None:
            return []
        return [g.model_dump(mode="json") for g in svc.population.list_all()]
    except RuntimeError:
        return []


@router.get("/population/{genome_id}")
def get_genome(genome_id: str) -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.population is None:
            raise HTTPException(status_code=404, detail="population not initialized")
        genome = svc.population.get(genome_id)
        if genome is None:
            raise HTTPException(status_code=404, detail="genome not found")
        return genome.model_dump(mode="json")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="evolution service not started") from None


@router.get("/champion")
def get_champion() -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.population is None:
            return {"genome": None, "fitness": None}
        champ = svc.population.get_champion()
        if champ is None:
            return {"genome": None, "fitness": None}
        return {"genome": champ.model_dump(mode="json"), "fitness": champ.fitness_score}
    except RuntimeError:
        return {"genome": None, "fitness": None}


@router.get("/lineage/{genome_id}")
def get_lineage(genome_id: str) -> list[dict]:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.population is None:
            return []
        lineage = svc.population.get_lineage(genome_id)
        return [g.model_dump(mode="json") for g in lineage]
    except RuntimeError:
        return []


@router.get("/tournament/leaderboard")
def tournament_leaderboard(benchmark: str | None = None) -> list[dict]:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.tournament is None:
            return []
        return svc.tournament.get_leaderboard(benchmark)
    except RuntimeError:
        return []


@router.get("/tournament/battles")
def tournament_battles(
    genome_id: str | None = None,
    benchmark: str | None = None,
    limit: int = 50,
) -> list[dict]:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.tournament is None:
            return []
        return svc.tournament.get_battle_history(genome_id, benchmark, limit)
    except RuntimeError:
        return []


@router.get("/tournament/stats")
def tournament_stats() -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        if svc.tournament is None:
            return {}
        return svc.tournament.get_stats()
    except RuntimeError:
        return {}


class SeedPopulationBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int = 10
    base_name: str = "evolved"


@router.post("/seed")
async def seed_population(body: SeedPopulationBody) -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        seeded, population_size = await svc.seed_population(body.count)
        return {"seeded": seeded, "population_size": population_size}
    except RuntimeError:
        raise HTTPException(status_code=503, detail="evolution service not started") from None


@router.post("/cycle")
async def trigger_cycle(request: Request) -> dict:
    from services.evolution import (
        CanonicalEvolutionRunError,
        EvolutionServiceNotStarted,
        EvolutionUnavailableError,
        get_evolution_service,
    )

    try:
        svc = get_evolution_service()
        run_id = await svc._run_one_cycle(actor_principal_id=_actor_principal_id(request))
        return {"status": "completed", "cycle_count": svc.cycle_count, "run_id": run_id}
    except EvolutionServiceNotStarted:
        logger.warning("Evolution service is not started", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "evolution_unavailable",
                "availability": "unavailable",
                "message": "evolution execution unavailable; see server logs",
            },
        ) from None
    except EvolutionUnavailableError as exc:
        logger.warning("Evolution execution unavailable", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "evolution_unavailable",
                "availability": exc.availability,
                "message": "evolution execution unavailable; see server logs",
            },
        ) from None
    except CanonicalEvolutionRunError as exc:
        # The Run was admitted and durably terminalized; this is execution
        # failure, not service availability failure. Preserve its identity.
        logger.warning("Canonical evolution Run failed: run_id=%s", exc.run_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "canonical_run_failed",
                "run_id": exc.run_id,
                "status": exc.status.value,
                "diagnostic": "evolution cycle failed; see server logs",
                "message": "evolution cycle failed; see server logs",
            },
        ) from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Evolution cycle failed before completion")
        raise HTTPException(
            status_code=500, detail="evolution cycle failed; see server logs"
        ) from None
