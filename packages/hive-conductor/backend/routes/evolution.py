"""Evolution API routes -- population, fitness, tournament, cycle control."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["evolution"])


def _actor_principal_id(request: Request) -> str | None:
    explicit = getattr(request.state, "user_id", None)
    if explicit:
        return str(explicit)
    user = getattr(request.state, "user", None) or {}
    if isinstance(user, dict):
        value = user.get("id") or user.get("username")
        if value:
            return str(value)
    return None


@router.get("/status")
def evolution_status() -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        return svc.status()
    except RuntimeError:
        return {
            "running": False,
            "cycle_count": 0,
            "population_size": 0,
            "last_error": None,
            "last_run_id": None,
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

        from maistro_evolve.diversity import emergency_spawn

        svc = get_evolution_service()
        if svc.population is None:
            raise HTTPException(status_code=503, detail="population not initialized")
        existing = svc.population.list_all()
        spawned = emergency_spawn(existing, body.count)
        for g in spawned:
            svc.population.add(g)
        return {"seeded": len(spawned), "population_size": len(svc.population.list_all())}
    except RuntimeError:
        raise HTTPException(status_code=503, detail="evolution service not started") from None


@router.post("/cycle")
async def trigger_cycle(request: Request) -> dict:
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
        run_id = await svc._run_one_cycle(actor_principal_id=_actor_principal_id(request))
        return {"status": "completed", "cycle_count": svc.cycle_count, "run_id": run_id}
    except RuntimeError:
        raise HTTPException(status_code=503, detail="evolution service not started") from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
