"""`maistro-rsi-campaign` console script — bounded frontier-model RSI campaigns.

A deliberate companion entry point to `maistro-rsi` (and, like it, a thin CLI
over `maistro_rsi.campaign`): it runs a ceilinged frontier-vs-baseline
experiment over an objective pool through the canonical gateway and writes a
campaign report.

    maistro-rsi-campaign --objective-pool pool.json \\
        --frontier-model anthropic/claude-opus-4 \\
        --baseline-model openrouter/free \\
        --max-spend-usd 5.0 --max-model-calls 40 --max-seconds 3600 \\
        --allowed-path src/ --report campaign.json

This surface is deliberately **not** a subcommand of `maistro_rsi.cli`: the
promotion-surface gate (scripts/check-promotion-surface.py) walks the
first-party import closure of the promotion-path roots — of which
`maistro_rsi.cli` is one — and requires everything reached there to be
protected or reviewed, because anything the promotion machinery can reach can
be self-modified onto the promotion path. The campaign harness is an
evaluation surface, not promotion machinery: it dispatches benchmark-style
objective pools through the gateway and records Invocations; it promotes
nothing. Giving it its own entry module keeps the promotion-path closure
exactly as reviewed — and if a reviewer judges this surface
promotion-adjacent, adding `maistro_rsi.campaign_cli` to PROMOTION_ROOTS is
the explicit, reviewable step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime

from maistro.observability.logging import configure_logging
from maistro.providers.types import ModelMetadata
from maistro_rsi.campaign import (
    ArmPolicy,
    CampaignCeilings,
    CampaignReport,
    ObjectivePool,
    ensure_bounded,
    ensure_unique_objectives,
    gateway_model_call,
    run_campaign,
)
from maistro_rsi.cli import normalize_litellm_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maistro-rsi-campaign",
        description="Run a bounded frontier-vs-baseline RSI campaign (M5-B, #114)",
    )
    parser.add_argument(
        "--objective-pool",
        required=True,
        help=(
            'JSON file: {"objectives": [{objective_id, task, keywords?, paths?}]}'
            " — both arms walk it verbatim"
        ),
    )
    parser.add_argument(
        "--frontier-model",
        required=True,
        help="Model alias the experimental arm routes through the gateway",
    )
    parser.add_argument(
        "--baseline-model",
        default=None,
        help="Cheaper-router baseline arm (omit for a single-arm campaign)",
    )
    parser.add_argument("--max-spend-usd", type=float, default=None)
    parser.add_argument("--max-total-tokens", type=int, default=None)
    parser.add_argument("--max-model-calls", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--max-objectives", type=int, default=None)
    parser.add_argument(
        "--allowed-path",
        action="append",
        default=None,
        help="Work-scope ceiling: path prefixes objectives may reference (repeatable)",
    )
    parser.add_argument(
        "--pricing",
        default=None,
        help=(
            "Optional JSON file mapping model alias -> {cost_per_1k_input, "
            "cost_per_1k_output, provider, latency_p50_ms}; without it cost "
            "evidence stays absent (None), never zero"
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--report", default=None, help="Write the campaign report JSON here (default: stdout)"
    )
    parser.add_argument("--run-id", default=None, help="Campaign run id (default: generated)")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary")
    return parser


def _campaign_ceilings(args: argparse.Namespace) -> CampaignCeilings:
    """Build the ceilings from CLI flags; ``ensure_bounded`` refuses an
    unbounded campaign before any dispatch exists."""
    ceilings = CampaignCeilings(
        max_spend_usd=args.max_spend_usd,
        max_total_tokens=args.max_total_tokens,
        max_model_calls=args.max_model_calls,
        max_wall_clock_s=args.max_seconds,
        max_objectives=args.max_objectives,
        allowed_paths=tuple(args.allowed_path) if args.allowed_path else (),
    )
    ensure_bounded(ceilings)
    return ceilings


def _load_pricing(path: str) -> dict[str, ModelMetadata]:
    """Model pricing table for cost attribution, from an operator-supplied
    file. Absent metadata means absent cost evidence, never zero."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    table: dict[str, ModelMetadata] = {}
    for alias, entry in raw.items():
        table[alias] = ModelMetadata(
            name=alias,
            provider=str(entry.get("provider", alias.split("/")[0])),
            cost_per_1k_input=float(entry["cost_per_1k_input"]),
            cost_per_1k_output=float(entry["cost_per_1k_output"]),
            latency_p50_ms=int(entry.get("latency_p50_ms", 0)),
        )
    return table


def _print_campaign_report(
    report: CampaignReport, *, payload: str, wrote_file: bool, as_json: bool
) -> None:
    """Render the campaign report for an operator: per-arm progress, cost,
    attempts, regressions and intervention rates, then the comparison."""
    if as_json:
        print(payload)
        return
    for arm in report.arms:
        stop = arm.stop_reason.ceiling if arm.stop_reason else "pool exhausted"
        print(
            f"{arm.arm_id} ({arm.model}): attempts={arm.attempts} "
            f"progress={arm.verified_progress} regressions={arm.regressions} "
            f"interventions={arm.interventions} "
            f"(rate {arm.intervention_rate:.2f}) "
            f"cost_usd={arm.cost_usd:.4f} "
            f"stop={stop}"
        )
        for rec in arm.attempts_log:
            if rec.intervention:
                print(f"  [{arm.arm_id}] {rec.objective_id}: {rec.intervention_reason}")
    if report.comparison:
        c = report.comparison
        multiple = c.cost_multiple if c.cost_multiple is not None else "n/a"
        print(
            f"comparison {c.frontier_arm} vs {c.baseline_arm} "
            f"over {c.objectives_compared} objective(s): "
            f"frontier {c.frontier_wins} / baseline {c.baseline_wins} "
            f"/ ties {c.ties} (mean delta {c.mean_score_delta:+.3f}; "
            f"cost ${c.frontier_cost_usd:.4f} vs ${c.baseline_cost_usd:.4f}, "
            f"multiple {multiple})"
        )
    if not wrote_file:
        print(payload)


async def _run_campaign(args: argparse.Namespace) -> int:
    base_url, api_key = normalize_litellm_env()
    if not (base_url and api_key):
        print(
            "error: a campaign dispatches real gateway calls — set LITELLM_BASE_URL and "
            "one of LITELLM_MASTER_KEY/LITELLM_API_KEY/LITELLM_VIRTUAL_KEY",
            file=sys.stderr,
        )
        return 2

    try:
        with open(args.objective_pool, encoding="utf-8") as fh:
            pool = ObjectivePool.model_validate(json.load(fh))
        ensure_unique_objectives(pool)
        ceilings = _campaign_ceilings(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: invalid campaign configuration: {exc}", file=sys.stderr)
        return 2

    arms = [
        ArmPolicy(
            arm_id="frontier",
            model=args.frontier_model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    ]
    if args.baseline_model:
        arms.append(
            ArmPolicy(
                arm_id="baseline",
                model=args.baseline_model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
        )

    pricing_table = _load_pricing(args.pricing) if args.pricing else {}
    run_id = args.run_id or f"campaign-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}"
    report = await run_campaign(
        run_id=run_id,
        pool=pool,
        arms=arms,
        ceilings=ceilings,
        make_model_call=lambda arm: gateway_model_call(arm.model, timeout=args.timeout),
        pricing=lambda arm: pricing_table.get(arm.model),
        workspace_id="rsi-campaign",
        project_id=run_id,
    )

    payload = report.to_json()
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")

    _print_campaign_report(report, payload=payload, wrote_file=bool(args.report), as_json=args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    return asyncio.run(_run_campaign(args))


if __name__ == "__main__":
    sys.exit(main())
