"""Unified live evolution (ADR-070126-6386 v2, "the run IS the gym"): the genome
population is the tournament roster, real work folds back as scores, transient
provider errors bench a model (it sits out — no sample, no death), and model
reliability multiplies into fitness. Stub apply, no LLM/network."""

from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

import pytest

from maistro_rsi.local_loop import (
    LocalRsiConfig,
    LocalRsiLoop,
    _is_transient_provider_error,
    _parse_retry_after_seconds,
)
from maistro_rsi.protocols import MicroVmSandbox


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} rc={proc.returncode}: {proc.stderr.strip()}")


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "rsi@test.local")
    _git(path, "config", "user.name", "RSI Test")
    (path / "value.txt").write_text("0\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _live_config(tmp_path: Path, **overrides) -> LocalRsiConfig:
    defaults = {
        "repo_path": str(_make_repo(tmp_path / "src")),
        "test_command": "exit 0",
        "work_root": str(tmp_path / "work"),
        "max_cycles": 2,
        "model": "testmodel",
        "genome_db": str(tmp_path / "pop.db"),
        "roster_size": 3,
    }
    defaults.update(overrides)
    return LocalRsiConfig(**defaults)


def _make_apply(writer) -> object:
    async def apply(sandbox: MicroVmSandbox, workspace: str, model: str | None = None) -> None:
        writer(Path(workspace))

    return apply


def _bump(ws: Path) -> None:
    f = ws / "value.txt"
    f.write_text(f.read_text() + "x\n", encoding="utf-8")


def test_transient_error_classifier() -> None:
    assert _is_transient_provider_error("LiteLLM gateway 429: RateLimitError ...")
    assert _is_transient_provider_error("You exceeded your current quota, check billing")
    assert _is_transient_provider_error("503 service overloaded")
    # A dead endpoint is capacity, not fitness — the live string from a local
    # model whose serving process died mid-run (gateway 500 wrapping it).
    assert _is_transient_provider_error(
        'LiteLLM gateway 500: {"error":{"message":"litellm.InternalServerError: '
        'InternalServerError: OpenAIException - Connection error."}}'
    )
    assert _is_transient_provider_error("APIConnectionError: connection refused")
    assert _is_transient_provider_error("502 Bad Gateway")
    assert not _is_transient_provider_error("list index out of range")
    assert not _is_transient_provider_error("SyntaxError: invalid syntax")


@pytest.mark.ac("SPEC-070126-9d37/AC-15")
def test_reliability_ema_decays_and_recovers(tmp_path: Path) -> None:
    random.seed(7)
    loop = LocalRsiLoop(_live_config(tmp_path), apply_patch=_make_apply(_bump))
    assert loop._observe_reliability("m", ok=False) == 0.7
    assert loop._observe_reliability("m", ok=False) == 0.49
    assert loop._observe_reliability("m", ok=True) > 0.49  # recovers on success


@pytest.mark.ac("SPEC-070126-9d37/AC-13")
def test_real_work_scores_the_population_and_it_evolves(tmp_path: Path) -> None:
    random.seed(11)
    config = _live_config(tmp_path)
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    result = loop.run()

    # Work was KEPT (promotions ratcheted) — no separate training evals exist.
    assert result.promotions == 2
    genomes = loop._population.list_all()
    # Real composites folded into the authoring genomes (samples counted).
    sampled = [g for g in genomes if g.harness_params.get("eval_samples", {}).get("code_rsi")]
    assert sampled, "cycle work should have scored the genomes that authored it"
    # Fitness computed with the model-reliability multiplier recorded.
    assert any(g.fitness_score is not None for g in genomes)
    assert any("model_reliability" in g.harness_params for g in genomes)
    # The population persisted (lineage survives runs).
    assert (tmp_path / "pop.db").exists()


@pytest.mark.ac("SPEC-070126-9d37/AC-14")
def test_transient_provider_error_benches_model_and_folds_nothing(tmp_path: Path) -> None:
    random.seed(13)

    async def rate_limited(
        sandbox: MicroVmSandbox, workspace: str, model: str | None = None
    ) -> None:
        raise RuntimeError("LiteLLM gateway 429: RateLimitError - quota exceeded")

    config = _live_config(tmp_path)
    loop = LocalRsiLoop(config, apply_patch=rate_limited)
    result = loop.run()

    # The run survived and completed every cycle.
    assert len(result.cycles) == 2
    # The model got benched (wall-clock deadline in the future) instead of the
    # genomes dying.
    assert loop._benched("testmodel")
    # Sitting out is NEUTRAL: no samples were folded into any genome.
    for g in loop._population.list_all():
        assert not g.eval_scores, "a benched cycle must not score the genome"
    # But reliability remembers: the model's score decayed below 1.0.
    assert loop._reliability.get("testmodel", 1.0) < 1.0


def test_non_transient_variant_error_is_surfaced_not_hidden_as_no_change(
    tmp_path: Path,
) -> None:
    random.seed(17)

    async def boom(sandbox: MicroVmSandbox, workspace: str, model: str | None = None) -> None:
        # A real fault (not a 429) — a bad apply, disk error, git failure, etc.
        raise RuntimeError("apply exploded: something broke")

    config = _live_config(tmp_path)
    loop = LocalRsiLoop(config, apply_patch=boom)
    result = loop.run()

    # The run survives, but a crashed variant must NEVER be reported as the
    # agent quietly declining to change anything — the fault has to be visible.
    assert result.promotions == 0
    notes = [c.note for c in result.cycles]
    assert all("no change" not in n for n in notes), notes
    assert all(("failed" in n or "errored" in n) for n in notes), notes


def test_parse_retry_after_all_documented_formats() -> None:
    # Formats catalogued in C:\maistro\MODEL-LIMITS.md.
    assert _parse_retry_after_seconds("Please try again in 7.664s") == 7.664
    assert _parse_retry_after_seconds('"retryDelay": "58s"') == 58.0
    assert _parse_retry_after_seconds("retry-after: 30") == 30.0
    assert _parse_retry_after_seconds("no wait stated here") is None


@pytest.mark.ac("SPEC-070126-9d37/AC-14")
def test_bench_honors_provider_stated_retry_after(tmp_path: Path) -> None:
    """A stated 7s RPM blip must not cost minutes; a stated 58s must be waited."""
    loop = LocalRsiLoop(_live_config(tmp_path), apply_patch=_make_apply(_bump))

    loop._bench_model("groqmodel", index=1, error_text="Please try again in 7.664s")
    remaining = loop._bench["groqmodel"] - time.monotonic()
    assert 6 < remaining <= 31  # honored, floored at the 30s minimum

    loop._bench_model("geminimodel", index=1, error_text='"retryDelay": "58s"')
    remaining = loop._bench["geminimodel"] - time.monotonic()
    assert 50 < remaining < 65


@pytest.mark.ac("SPEC-070126-9d37/AC-14")
def test_bench_default_backs_off_geometrically_and_resets_on_success(tmp_path: Path) -> None:
    loop = LocalRsiLoop(_live_config(tmp_path, bench_cycles=1), apply_patch=_make_apply(_bump))

    loop._bench_model("m", index=1, error_text="429 no stated wait")
    first = loop._bench["m"] - time.monotonic()
    loop._bench_model("m", index=2, error_text="429 no stated wait")
    second = loop._bench["m"] - time.monotonic()
    # Consecutive benches double the default sit-out (capped at the ceiling).
    assert second > first * 1.5
    # Real scored work ends the streak: the next bench is short again.
    loop._observe_reliability("m", ok=True)
    loop._bench_model("m", index=3, error_text="429 no stated wait")
    third = loop._bench["m"] - time.monotonic()
    assert third < second


def test_genome_models_seeds_population_across_models(tmp_path: Path) -> None:
    config = _live_config(tmp_path, genome_models=["model-a", "model-b", "model-c"], roster_size=3)
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    from maistro_rsi.local_loop import _entry_model

    models = {_entry_model(g) for g in loop._population.list_all()}
    assert models == {"model-a", "model-b", "model-c"}


def test_empty_genome_models_falls_back_to_model(tmp_path: Path) -> None:
    loop = LocalRsiLoop(_live_config(tmp_path), apply_patch=_make_apply(_bump))
    from maistro_rsi.local_loop import _entry_model

    assert {_entry_model(g) for g in loop._population.list_all()} == {"testmodel"}


def test_never_idle_spawns_when_whole_roster_benched(tmp_path: Path) -> None:
    # Whole roster benched (its provider fully rate-limited) → the loop must NOT
    # no-op the cycle: it spawns a fresh genome onto a servable cross-provider
    # emergency model and fields it (the "we MUST run some models" guarantee).
    from maistro_rsi.local_loop import _entry_model

    config = _live_config(
        tmp_path,
        genome_models=["model-a", "model-b"],
        roster_size=2,
        emergency_models=["rescue-model"],
    )
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    for g in loop._population.list_all():
        loop._bench[_entry_model(g)] = time.monotonic() + 999  # bench every roster model
    before = len(loop._population.list_all())

    roster = loop._genome_roster(index=1)

    assert roster, "loop must not idle when the whole roster is benched"
    assert roster[0].model == "rescue-model"  # spawned onto the servable emergency model
    assert len(loop._population.list_all()) == before + 1  # a new lineage joined the population


def test_emergency_prefers_servable_then_soonest_unbench(tmp_path: Path) -> None:
    config = _live_config(tmp_path, emergency_models=["down-a", "up-b", "down-c"])
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    now = time.monotonic()
    loop._bench["down-a"] = now + 500
    loop._bench["down-c"] = now + 50  # benched but expires soonest
    # up-b is not benched → it wins
    assert loop._emergency_model(index=1) == "up-b"
    # with everything benched, the soonest-to-recover is chosen (least-bad probe)
    loop._bench["up-b"] = now + 999
    assert loop._emergency_model(index=1) == "down-c"


def test_emergency_pool_defaults_when_unset(tmp_path: Path) -> None:
    from maistro_rsi.local_loop import _DEFAULT_EMERGENCY_MODELS

    loop = LocalRsiLoop(_live_config(tmp_path), apply_patch=_make_apply(_bump))
    assert loop._emergency_pool() == list(_DEFAULT_EMERGENCY_MODELS)


def test_never_idle_probes_without_persisting_when_all_benched(tmp_path: Path) -> None:
    # Codex P2 (#250): when roster AND emergency pool are ALL benched, field a
    # least-bad transient probe WITHOUT persisting a new lineage — else a long
    # outage floods population.db and evicts proven genomes.
    from maistro_rsi.local_loop import _entry_model

    config = _live_config(
        tmp_path, genome_models=["model-a"], roster_size=1, emergency_models=["down-x"]
    )
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    now = time.monotonic()
    for g in loop._population.list_all():
        loop._bench[_entry_model(g)] = now + 999
    loop._bench["down-x"] = now + 999  # the emergency pool is benched too
    before = len(loop._population.list_all())

    roster = loop._genome_roster(index=1)

    assert roster, "must still field a probe rather than idle"
    assert roster[0].model == "down-x"  # least-bad probe
    assert len(loop._population.list_all()) == before  # NOT persisted
    assert roster[0].label not in loop._label_to_genome  # folds back to no genome


def test_local_fallback_used_when_entire_pool_benched(tmp_path: Path) -> None:
    # The never-idle FLOOR: roster AND the cross-provider emergency pool are all
    # rate-limited, but local hardware has no rate limit to hit — so the cycle
    # runs on the local tier instead of degrading to a benched probe.
    from maistro_rsi.local_loop import _entry_model

    config = _live_config(
        tmp_path,
        genome_models=["model-a"],
        roster_size=1,
        emergency_models=["down-x"],
        local_fallback_model="local-gpu",
    )
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    now = time.monotonic()
    for g in loop._population.list_all():
        loop._bench[_entry_model(g)] = now + 999
    loop._bench["down-x"] = now + 999  # the cloud pool is benched too
    before = len(loop._population.list_all())

    roster = loop._genome_roster(index=1)

    assert roster[0].model == "local-gpu"  # the floor caught it
    # Local work is REAL work: unlike a transient probe, it persists and evolves.
    assert len(loop._population.list_all()) == before + 1


def test_local_fallback_never_pre_empts_a_servable_cloud_model(tmp_path: Path) -> None:
    # THE ordering guarantee. Pool selection ranks by reliability, defaulting to
    # 1.0 for an unseen model, and a local model never benches — so a local tier
    # placed INSIDE emergency_models would out-rank every proven cloud model and
    # silently become primary. It must stay a last resort even when the only
    # servable cloud model is measurably worse than a fresh local one.
    config = _live_config(tmp_path, emergency_models=["up-b"], local_fallback_model="local-gpu")
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    loop._reliability["up-b"] = 0.2  # far below local's implicit 1.0

    assert loop._emergency_model(index=1) == "up-b"

    # ...and only once the cloud model is benched does the floor engage.
    loop._bench["up-b"] = time.monotonic() + 999
    assert loop._emergency_model(index=1) == "local-gpu"


def test_local_fallback_unset_keeps_probe_behaviour(tmp_path: Path) -> None:
    # No local tier configured ⇒ the pre-existing least-bad-probe path, unchanged.
    config = _live_config(tmp_path, emergency_models=["down-x"])
    loop = LocalRsiLoop(config, apply_patch=_make_apply(_bump))
    loop._bench["down-x"] = time.monotonic() + 999

    assert loop._emergency_model(index=1) == "down-x"
