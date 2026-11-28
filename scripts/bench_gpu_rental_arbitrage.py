#!/usr/bin/env python3
"""Opportunistic GPU-rental arbitrage bench (issue #2121, epic #905 M8-F).

Offline/replay evaluator for the opportunistic-GPU-rental research question:
can a 22-24 h/day autonomous software factory buy inference capacity on
marketplace GPU rentals (Vast/Salad/Prime-Intellect-class hosts) at a lower
expected accepted-task cost than the alternatives, without ever letting a
marketplace discovery path grant model egress authority or provision anything?

What is real
------------
Nothing leaves this process. The harness performs no network I/O, reads no
quality ledger, provisions no machine, and spends no money. The GPU hardware
facts (VRAM, compute capability, tensor-path support) are published constants;
every price is an authored, clearly-labeled simulated lead modeled on the
public marketplace shape. Selection semantics are pure functions over a
versioned offer schema and a capability registry, which is exactly the part a
future operator can reuse against a live feed after human approval.

What is simulated (and said so loudly)
--------------------------------------
- Every offer in the feed is synthetic. Advertised prices — including the
  anomalous $0.02/h RTX 3060 and $0.06/h A40 leads the issue names — are
  modeled as UNVERIFIED LEADS: schema-valid but carrying a low
  availability probability, so ranking on *expected* cost risk-adjusts them
  instead of trusting them as availability guarantees.
- Capability records are synthetic fixtures keyed by
  (GPU, quantization, serving stack/version, context bucket, concurrency,
  task class). Unknown compatibility is INELIGIBLE, never guessed; the
  registry intentionally leaves most (SKU, quant, stack) combinations unknown
  so the ineligibility rule is exercised, and no record carries
  hardware-measured provenance.
- Task outcomes come from the same authored acceptance model as #934/#914:
  acceptance probability and decode throughput are registry fields, not
  observations. Magnitudes below are simulator-dependent.

Failure-injection replay
------------------------
The replay executor validates the schema at ingestion, re-validates freshness
at execution time, pre-flights VRAM and capability before renting anything,
bills idempotently per task key (checkpoint/resume on preemption — a resumed
task is never double-billed), and refuses to exceed an explicit billing cap.
Injected failure modes: preemption, stale offer, unavailable host, OOM, model
mismatch, invalid price, billing cap.

Routes compared
---------------
- fixed-gpu         : the operator pins one SKU (RTX 3090) and rents it
                      regardless of the rest of the feed.
- cheapest-listed   : the naive operator — minimum listed $/h across all
                      schema-valid offers, eligibility be damned. This is the
                      trap the issue warns about: it selects the cheapest
                      unverified lead and pays for it in availability risk.
- cheapest-eligible : minimum expected accepted-task cost over offers that
                      pass every eligibility rule (fresh, valid price,
                      approved host, capability-verified, VRAM-fit).
- quality-adjusted  : cheapest-eligible constrained to a quality floor, so
                      warmup/preemption/acceptance penalties are paid where
                      they actually land instead of being priced away.

Annual sensitivity: always-rented, owned-16GB-plus-cloud, and
heavy-model-on-demand strategies at 22 and 24 h/day over 365 days, under
lead/mid/high price bases (the lead base exists only to show what the
anomalous prices would be WORTH IF TRUE — it is not a prediction).

Deterministic and offline: every draw is a blake2b hash of stable ids. No
network, no database, no wall clock in the report (two runs are
byte-identical). Run it after changing the offer schema, the capability
registry, or the cost model; results are comparable run-to-run.

Usage:
    uv run python scripts/bench_gpu_rental_arbitrage.py [--tasks-per-class 40]
        [--seed gpu-arb-v1] [--hours 22|24|both] [--output results.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# --------------------------------------------------------------------------
# Stated modeling constants. Every magnitude below is an authored choice, not
# a measurement; the report labels its own data class "simulation".
# --------------------------------------------------------------------------

OFFER_SCHEMA_VERSION = "1"

#: Availability probability modeled for a schema-valid offer whose price is
#: only advertised (an unverified lead). The issue's rule: advertised prices
#: are leads, never availability guarantees.
LEAD_AVAILABILITY = 0.10

#: Availability probability modeled for a verified-basis offer.
VERIFIED_AVAILABILITY = 0.95

#: Offers below this historic-uptime claim are ineligible regardless of price.
MIN_RELIABILITY = 0.90

#: Acceptance floor for the quality-adjusted route.
QUALITY_FLOOR = 0.85

#: Fraction of preemptible attempts that actually get preempted (model).
PREEMPTION_RATE = 0.20

#: GPU-hours over which monthly storage is amortized into a steady-state
#: session's hourly rate.
STORAGE_AMORTIZATION_HOURS = 24.0

#: Steady-state tasks per provisioning (start-up) window; start time is
#: amortized over this many tasks.
SESSION_TASKS = 200

#: Hosts an operator has explicitly approved for rental (trust control: no
#: sensitive repo data and no credentials on unapproved hosts).
APPROVED_HOSTS = frozenset({"vast", "salad", "prime"})

#: Owned-GPU TCO constants (16GB-class card, e.g. a 4060 Ti 16GB).
OWNED_GPU_CAPEX_USD = 550.0
OWNED_AMORT_YEARS = 3.0
OWNED_WATTS = 160.0
OWNED_ELECTRICITY_USD_PER_KWH = 0.12
OWNED_UTILIZATION_SHARE = 0.60  # share of factory hours the owned GPU covers
CLOUD_OVERFLOW_SHARE = 1.0 - OWNED_UTILIZATION_SHARE
HEAVY_TASK_SHARE = 0.25  # share of tasks needing the large rented GPU
HEAVY_RATE_PREMIUM = 2.0  # 70B-class rental premium over the light rate

#: Annual price bases in USD per GPU-hour. "lead" exists only to show what
#: the anomalous prices would be worth IF TRUE; it is not a prediction.
PRICE_BASES: dict[str, float] = {
    "lead": 0.35,
    "mid": 0.55,
    "high": 1.10,
}


def _hash_float(*parts: object) -> float:
    """Deterministic uniform draw in [0, 1) from stable string parts."""
    digest = hashlib.blake2b("|".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


# --------------------------------------------------------------------------
# GPU hardware facts (published constants, not prices).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuSpec:
    """Published hardware facts for one GPU SKU."""

    sku: str
    vram_gb: int
    compute_capability: str  # CUDA compute capability, e.g. "8.6"
    fp16_tensor: bool  # fast fp16 tensor-core path
    bf16: bool  # native bfloat16 support
    int4_weight_only: bool  # supported weight-only int4 fast path
    watts: float


GPU_SPECS: dict[str, GpuSpec] = {
    "RTX_3060_12GB": GpuSpec("RTX_3060_12GB", 12, "8.6", True, False, True, 170),
    "TESLA_P40_24GB": GpuSpec("TESLA_P40_24GB", 24, "6.1", False, False, False, 250),
    "TESLA_V100_32GB": GpuSpec("TESLA_V100_32GB", 32, "7.0", True, False, False, 300),
    "RTX_3090_24GB": GpuSpec("RTX_3090_24GB", 24, "8.6", True, True, True, 350),
    "A40_48GB": GpuSpec("A40_48GB", 48, "8.6", True, True, True, 300),
    "RTX_4090_24GB": GpuSpec("RTX_4090_24GB", 24, "8.9", True, True, True, 450),
    "RTX_5090_32GB": GpuSpec("RTX_5090_32GB", 32, "12.0", True, True, True, 575),
    "B200_192GB": GpuSpec("B200_192GB", 192, "10.0", True, True, True, 1000),
}


# --------------------------------------------------------------------------
# Model-capability registry (design item 2). Keyed by GPU, quantization,
# serving stack + version, context bucket, concurrency and task class.
# Unknown compatibility is INELIGIBLE, never guessed.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityKey:
    """One compatibility cell of the capability registry."""

    gpu_sku: str
    quantization: str  # "fp16" | "int8" | "int4"
    serving_stack: str  # "vllm" | "llamacpp"
    stack_version: str
    context_bucket: str  # "4k" | "32k" | "64k"
    concurrency: int
    task_class: str


@dataclass(frozen=True)
class CapabilityRecord:
    """A recorded compatibility cell — synthetic fixture provenance only.

    ``provenance`` is what separates evidence from guesswork: no record in
    this fixture is hardware-measured, and the report says so. A record whose
    compatibility was never benchmarked is simply ABSENT (unknown), and an
    absent record makes the combination ineligible.
    """

    compatible: bool
    decode_tokens_per_s: float
    acceptance: float  # modeled acceptance probability for the task class
    warmup_seconds: float
    provenance: str = "synthetic-fixture"


def capability_registry() -> dict[CapabilityKey, CapabilityRecord]:
    """The fixture registry. Deliberately sparse: most cells are unknown."""
    entries: dict[CapabilityKey, CapabilityRecord] = {}
    # 3090 + vllm + int4: verified fixture for light classes at 4k context.
    for task_class, tps, acc in (
        ("chat", 55.0, 0.97),
        ("classification", 70.0, 0.99),
        ("extraction", 45.0, 0.93),
        ("summarization", 40.0, 0.90),
    ):
        entries[CapabilityKey("RTX_3090_24GB", "int4", "vllm", "0.6.4", "4k", 1, task_class)] = (
            CapabilityRecord(True, tps, acc, 90.0)
        )
    # 3090 + fp16 at 32k context: recorded INCOMPATIBLE (VRAM) — pinned negative.
    entries[CapabilityKey("RTX_3090_24GB", "fp16", "vllm", "0.6.4", "32k", 1, "summarization")] = (
        CapabilityRecord(False, 0.0, 0.0, 0.0)
    )
    # A40 + vllm + int4: the 70B-class heavy cells (planning/code_repair).
    for task_class, tps, acc in (("code_repair", 14.0, 0.88), ("planning", 12.0, 0.86)):
        entries[CapabilityKey("A40_48GB", "int4", "vllm", "0.6.4", "32k", 1, task_class)] = (
            CapabilityRecord(True, tps, acc, 240.0)
        )
    # A40 + llamacpp: recorded INCOMPATIBLE for the pinned stack version.
    entries[CapabilityKey("A40_48GB", "int4", "llamacpp", "b4200", "32k", 1, "planning")] = (
        CapabilityRecord(False, 0.0, 0.0, 0.0)
    )
    # 4090 + vllm + int4: the fastest light-class cells.
    for task_class, tps, acc in (
        ("chat", 110.0, 0.97),
        ("classification", 130.0, 0.99),
        ("extraction", 90.0, 0.94),
        ("summarization", 80.0, 0.91),
    ):
        entries[CapabilityKey("RTX_4090_24GB", "int4", "vllm", "0.6.4", "4k", 1, task_class)] = (
            CapabilityRecord(True, tps, acc, 75.0)
        )
    return entries


#: VRAM requirement per pinned model class (int4 weights + KV at the class's
#: context bucket). Authored, conservative.
MODEL_VRAM_GB = {"7b-int4": 6, "13b-int4": 10, "70b-int4": 42}


# --------------------------------------------------------------------------
# Workload classes (same six capability classes as #914/#934).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkloadClass:
    """One pinned workload class routed to GPU rentals."""

    name: str
    model_class: str
    context_bucket: str
    reasoning: bool
    tasks_per_class: int  # per replay batch


WORKLOAD_CLASSES: tuple[WorkloadClass, ...] = (
    WorkloadClass("chat", "7b-int4", "4k", False, 40),
    WorkloadClass("classification", "7b-int4", "4k", False, 40),
    WorkloadClass("extraction", "13b-int4", "4k", False, 40),
    WorkloadClass("summarization", "13b-int4", "4k", False, 40),
    WorkloadClass("code_repair", "70b-int4", "32k", True, 40),
    WorkloadClass("planning", "70b-int4", "32k", True, 40),
)

#: Deterministic per-class output size bands (tokens), mirroring #914.
OUTPUT_BANDS: dict[str, tuple[int, int]] = {
    "chat": (80, 400),
    "classification": (5, 40),
    "extraction": (100, 800),
    "summarization": (200, 1200),
    "code_repair": (100, 900),
    "planning": (300, 1500),
}


def output_tokens_per_task(workload: WorkloadClass) -> float:
    """Deterministic per-class output size (tokens) in the class band."""
    lo, hi = OUTPUT_BANDS[workload.name]
    mid = workload.tasks_per_class // 2
    return lo + (hi - lo) * _hash_float("out", workload.name, mid)


# --------------------------------------------------------------------------
# Marketplace-offer schema (design item 1): versioned, with freshness and
# eligibility rules. Missing/stale/false offers are rejected, never ranked.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketplaceOffer:
    """One marketplace offer. All prices USD; all times seconds."""

    schema_version: str
    offer_id: str
    host: str  # marketplace host id, NOT a model provider
    gpu_sku: str
    region: str
    price_usd_per_hour: float
    cpu_usd_per_hour: float
    storage_usd_per_month: float
    egress_usd_per_gb: float
    reliability: float  # historic uptime claim in [0, 1]
    min_duration_hours: float
    preemptible: bool
    start_time_seconds: float
    capacity_gpus: int
    price_basis: Literal["advertised", "verified"]
    captured_at: float
    ttl_seconds: float

    def hourly_cost(self) -> float:
        """Recurring GPU-hour cost: rental + attached CPU."""
        return self.price_usd_per_hour + self.cpu_usd_per_hour

    def availability_probability(self) -> float:
        """Modeled availability: leads are leads, verified basis is history."""
        if self.price_basis == "advertised":
            return LEAD_AVAILABILITY
        return VERIFIED_AVAILABILITY


@dataclass(frozen=True)
class OfferDecision:
    """Schema-level eligibility verdict (offer-wide, workload-independent)."""

    offer_id: str
    eligible: bool
    reason: str  # "" when eligible; otherwise a stable rejection category


def evaluate_offer(
    offer: MarketplaceOffer,
    now: float,
    approved_hosts: frozenset[str] = APPROVED_HOSTS,
    min_reliability: float = MIN_RELIABILITY,
) -> OfferDecision:
    """Apply the documented freshness/eligibility rules to one offer.

    Order matters and is part of the contract: schema, price validity,
    freshness, host trust, reliability floor, capacity, known GPU. The first
    failing rule names the rejection; a rejected offer is never ranked.
    """
    if offer.schema_version != OFFER_SCHEMA_VERSION:
        return OfferDecision(offer.offer_id, False, "schema_version")
    if not _valid_price(offer.price_usd_per_hour) or not _valid_rate(offer.cpu_usd_per_hour):
        return OfferDecision(offer.offer_id, False, "invalid_price")
    if offer.captured_at + offer.ttl_seconds <= now:
        return OfferDecision(offer.offer_id, False, "stale")
    if offer.host not in approved_hosts:
        return OfferDecision(offer.offer_id, False, "host_unapproved")
    if not math.isfinite(offer.reliability) or offer.reliability < min_reliability:
        return OfferDecision(offer.offer_id, False, "unreliable")
    if offer.capacity_gpus <= 0:
        return OfferDecision(offer.offer_id, False, "no_capacity")
    if offer.gpu_sku not in GPU_SPECS:
        return OfferDecision(offer.offer_id, False, "unknown_gpu")
    return OfferDecision(offer.offer_id, True, "")


def _valid_price(price: float) -> bool:
    """A price must be finite and strictly positive to be trustworthy."""
    return math.isfinite(price) and price > 0.0


def _valid_rate(rate: float) -> bool:
    """An attached rate (CPU) must be finite and non-negative."""
    return math.isfinite(rate) and rate >= 0.0


def vram_fit(offer: MarketplaceOffer, workload: WorkloadClass) -> bool:
    """Pre-flight VRAM check: OOM is a pre-rental rejection, not a runtime."""
    return GPU_SPECS[offer.gpu_sku].vram_gb >= MODEL_VRAM_GB[workload.model_class]


def capability_for(offer: MarketplaceOffer, workload: WorkloadClass) -> CapabilityRecord | None:
    """Registry lookup for (offer GPU, workload class). None means unknown.

    Unknown compatibility is ineligible rather than guessed, and a recorded
    INCOMPATIBLE cell is equally ineligible.
    """
    key = CapabilityKey(
        gpu_sku=offer.gpu_sku,
        quantization="int4",
        serving_stack="vllm",
        stack_version="0.6.4",
        context_bucket=workload.context_bucket,
        concurrency=1,
        task_class=workload.name,
    )
    return capability_registry().get(key)


def workload_eligible(
    offer: MarketplaceOffer, workload: WorkloadClass, now: float
) -> tuple[bool, str, CapabilityRecord | None]:
    """Full eligibility: schema rules first, then hardware, capability, VRAM."""
    schema = evaluate_offer(offer, now)
    if not schema.eligible:
        return False, schema.reason, None
    spec = GPU_SPECS[offer.gpu_sku]
    if workload.model_class.endswith("int4") and not spec.int4_weight_only:
        # The SKU's published hardware facts say this quantization path is
        # not supported — a hardware fact, not a guess.
        return False, "model_mismatch", None
    record = capability_for(offer, workload)
    if record is None or not record.compatible:
        return False, "model_mismatch", record
    if not vram_fit(offer, workload):
        return False, "oom", record
    return True, "", record


# --------------------------------------------------------------------------
# Expected accepted-task cost (design item 3). Ranking on expected cost per
# ACCEPTED task, including queue time, retries, preemption redo, warmup, and
# modeled availability; $/GPU-hour and $/Mtok are secondary diagnostics.
# --------------------------------------------------------------------------


def redo_multiplier(offer: MarketplaceOffer) -> float:
    """Cost multiplier for preemption redo on checkpointed work.

    A preempted attempt resumes from its checkpoint, so only the post-
    checkpoint half of a task repeats. The replay executor retries until
    completion with a fresh preemption draw per attempt, so the expected
    number of preemptions before completion is p / (1 - p), each costing
    half a task: multiplier = 1 + 0.5 * p / (1 - p).
    """
    if not offer.preemptible:
        return 1.0
    p = PREEMPTION_RATE
    return 1.0 + 0.5 * p / (1.0 - p)


def risk_adjusted_hourly_cost(offer: MarketplaceOffer) -> float:
    """GPU-hour cost divided by modeled availability.

    A cheap lead that exists 10% of the time costs 10x its sticker once you
    need it to be there — this is how "unverified lead" becomes arithmetic
    instead of a warning label.
    """
    hourly = offer.hourly_cost()
    hourly += offer.storage_usd_per_month / (30.0 * STORAGE_AMORTIZATION_HOURS)
    hourly += offer.egress_usd_per_gb * 0.5  # modeled egress GB per GPU-hour
    return hourly / offer.availability_probability()


def expected_accepted_task_cost(
    offer: MarketplaceOffer, record: CapabilityRecord, workload: WorkloadClass
) -> float:
    """USD per ACCEPTED task on this offer, or math.inf when never viable.

    Decomposition (all authored model, documented here on purpose):
    - per-attempt cost = risk-adjusted GPU-hour * max(modeled session
      seconds, offer.min_duration_hours) amortized over SESSION_TASKS — the
      rental minimum is honored at session level before amortization, so a
      short session still pays for the whole minimum billable window;
    - acceptance = record.acceptance * offer.reliability — retries are priced
      as 1/acceptance (the expected number of attempts per accepted task);
    - preemption redo adds redo_multiplier on preemptible offers.
    """
    out_tokens = output_tokens_per_task(workload)
    gpu_seconds = out_tokens / record.decode_tokens_per_s
    session_seconds = record.warmup_seconds + offer.start_time_seconds + SESSION_TASKS * gpu_seconds
    billable_seconds = max(session_seconds, offer.min_duration_hours * 3600.0)
    acceptance = record.acceptance * offer.reliability
    if acceptance <= 0.0 or gpu_seconds <= 0.0:
        return math.inf
    per_task = risk_adjusted_hourly_cost(offer) * billable_seconds / 3600.0 / SESSION_TASKS
    per_task = per_task / acceptance
    return per_task * redo_multiplier(offer)


def dollars_per_mtok_accepted(
    offer: MarketplaceOffer, record: CapabilityRecord, workload: WorkloadClass
) -> float:
    """Secondary diagnostic: USD per million ACCEPTED output tokens."""
    out_tokens = output_tokens_per_task(workload)
    cost = expected_accepted_task_cost(offer, record, workload)
    if cost == math.inf or out_tokens <= 0:
        return math.inf
    return cost / (out_tokens / 1e6)


def dollars_per_gpu_hour(offer: MarketplaceOffer) -> float:
    """Secondary diagnostic: risk-adjusted recurring USD per GPU-hour."""
    return round(risk_adjusted_hourly_cost(offer), 4)


# --------------------------------------------------------------------------
# Routing policies (the routes AC2 requires).
# --------------------------------------------------------------------------


def select_fixed_gpu(
    offers: list[MarketplaceOffer], workload: WorkloadClass, now: float, pinned_sku: str
) -> tuple[MarketplaceOffer | None, str]:
    """Pin one SKU and rent its cheapest ELIGIBLE listed offer.

    The operator's commitment is the SKU, not the listing: schema-invalid or
    stale listings for that SKU fall through, and if no listing for the SKU
    can serve the workload the route fails closed for it.
    """
    pinned = sorted(
        (
            o
            for o in offers
            if o.gpu_sku == pinned_sku
            and o.schema_version == OFFER_SCHEMA_VERSION
            and _valid_price(o.price_usd_per_hour)
        ),
        key=lambda o: o.hourly_cost(),
    )
    if not pinned:
        return None, "no_offer_for_sku"
    reason = "no_eligible_offer"
    for offer in pinned:
        eligible, why, _ = workload_eligible(offer, workload, now)
        if eligible:
            return offer, ""
        reason = why
    return None, reason


def select_cheapest_listed(offers: list[MarketplaceOffer]) -> tuple[MarketplaceOffer | None, str]:
    """The naive route: minimum listed $/h across schema-valid offers.

    Deliberately ignores trust, capability, and availability modeling: this
    is what sorting a marketplace by price gets an operator. The feed's
    cheapest listed offer is an unverified lead — the trap the issue warns
    about.
    """
    valid = [
        o
        for o in offers
        if o.schema_version == OFFER_SCHEMA_VERSION and _valid_price(o.price_usd_per_hour)
    ]
    if not valid:
        return None, "no_valid_offer"
    return min(valid, key=lambda o: o.price_usd_per_hour), ""


def select_cheapest_eligible(
    offers: list[MarketplaceOffer], workload: WorkloadClass, now: float
) -> tuple[MarketplaceOffer | None, str, float]:
    """Minimum expected accepted-task cost over fully eligible offers."""
    best: MarketplaceOffer | None = None
    best_cost = math.inf
    for offer in offers:
        eligible, _reason, record = workload_eligible(offer, workload, now)
        if not eligible:
            continue
        cost = expected_accepted_task_cost(offer, record, workload)
        if cost < best_cost or (
            cost == best_cost and best is not None and offer.offer_id < best.offer_id
        ):
            best, best_cost = offer, cost
    if best is None:
        return None, "no_eligible_offer", math.inf
    return best, "", best_cost


def select_quality_adjusted(
    offers: list[MarketplaceOffer], workload: WorkloadClass, now: float
) -> tuple[MarketplaceOffer | None, str, float]:
    """Cheapest-eligible constrained to the quality floor."""
    best: MarketplaceOffer | None = None
    best_cost = math.inf
    for offer in offers:
        eligible, _, record = workload_eligible(offer, workload, now)
        if not eligible or record.acceptance < QUALITY_FLOOR:
            continue
        cost = expected_accepted_task_cost(offer, record, workload)
        if cost < best_cost:
            best, best_cost = offer, cost
    if best is None:
        return None, "no_offer_above_quality_floor", math.inf
    return best, "", best_cost


# --------------------------------------------------------------------------
# Synthetic offer feed. Every offer is simulated; hosts and prices are
# modeled on public marketplace shapes. The anomalous $0.02/h 3060 and
# $0.06/h A40 leads from the issue are present, explicitly unverified.
# --------------------------------------------------------------------------


def _make_offer(now: float, **kwargs: object) -> MarketplaceOffer:
    """One feed entry with the feed's defaults made explicit."""
    params: dict[str, object] = {
        "schema_version": OFFER_SCHEMA_VERSION,
        "host": "vast",
        "region": "us-central",
        "cpu_usd_per_hour": 0.02,
        "storage_usd_per_month": 5.0,
        "egress_usd_per_gb": 0.02,
        "reliability": 0.97,
        "min_duration_hours": 1.0,
        "preemptible": True,
        "start_time_seconds": 120.0,
        "capacity_gpus": 8,
        "price_basis": "verified",
        "captured_at": now,
        "ttl_seconds": 300.0,
    }
    params.update(kwargs)
    return MarketplaceOffer(**params)  # type: ignore[arg-type]


def offer_feed(now: float) -> list[MarketplaceOffer]:
    """The synthetic marketplace feed for one evaluation instant."""
    return [
        # The anomalous leads (issue body): advertised, never verified. The
        # 3060 lead sits on an APPROVED host to prove risk-adjustment alone
        # dislodges it; the A40 lead sits on an unapproved host to prove the
        # trust gate.
        _make_offer(
            now,
            offer_id="lead-3060-002",
            gpu_sku="RTX_3060_12GB",
            price_usd_per_hour=0.02,
            price_basis="advertised",
        ),
        _make_offer(
            now,
            offer_id="lead-a40-006",
            host="cheapcloud",
            gpu_sku="A40_48GB",
            price_usd_per_hour=0.06,
            price_basis="advertised",
        ),
        # An advertised 4090 lead on an approved host WITH a capability cell:
        # cheapest-listed picks it; expected-cost ranking does not.
        _make_offer(
            now,
            offer_id="lead-4090-005",
            gpu_sku="RTX_4090_24GB",
            price_usd_per_hour=0.05,
            price_basis="advertised",
        ),
        # Verified-basis offers on approved hosts (the ranking's fuel).
        _make_offer(
            now, offer_id="vast-3090-021", gpu_sku="RTX_3090_24GB", price_usd_per_hour=0.21
        ),
        _make_offer(
            now, offer_id="vast-4090-034", gpu_sku="RTX_4090_24GB", price_usd_per_hour=0.34
        ),
        _make_offer(now, offer_id="vast-a40-048", gpu_sku="A40_48GB", price_usd_per_hour=0.48),
        _make_offer(
            now,
            offer_id="salad-4090-032",
            host="salad",
            gpu_sku="RTX_4090_24GB",
            price_usd_per_hour=0.32,
            preemptible=False,
        ),
        _make_offer(
            now,
            offer_id="prime-3090-023",
            host="prime",
            gpu_sku="RTX_3090_24GB",
            price_usd_per_hour=0.23,
            reliability=0.95,
        ),
        # A stale copy of the 3090 offer: cheaper, but captured long ago and
        # already past its TTL — rejected on freshness before ranking.
        _make_offer(
            now,
            offer_id="vast-3090-stale",
            gpu_sku="RTX_3090_24GB",
            price_usd_per_hour=0.19,
            captured_at=now - 600.0,
            ttl_seconds=60.0,
        ),
        # Trust-control fixtures.
        _make_offer(
            now,
            offer_id="hostify-3060-018",
            host="hostify",
            gpu_sku="RTX_3060_12GB",
            price_usd_per_hour=0.18,
        ),
        _make_offer(
            now,
            offer_id="vast-lowrel-4090",
            gpu_sku="RTX_4090_24GB",
            price_usd_per_hour=0.12,
            reliability=0.55,
        ),
        # False/failed fixtures.
        _make_offer(
            now,
            offer_id="vast-3090-cap0",
            gpu_sku="RTX_3090_24GB",
            price_usd_per_hour=0.20,
            capacity_gpus=0,
        ),
        _make_offer(
            now, offer_id="bad-3090-nan", gpu_sku="RTX_3090_24GB", price_usd_per_hour=math.nan
        ),  # false offer: non-finite price
        _make_offer(
            now, offer_id="bad-3090-neg", gpu_sku="RTX_3090_24GB", price_usd_per_hour=-0.10
        ),  # false offer: negative price
        _make_offer(
            now,
            offer_id="bad-4090-oldschema",
            gpu_sku="RTX_4090_24GB",
            price_usd_per_hour=0.30,
            schema_version="0",
        ),
    ]


# --------------------------------------------------------------------------
# Failure-injection replay executor (AC4, design item 4). Durable, idempotent
# execution: every task carries an idempotency key; a preempted attempt
# checkpoints and resumes under the SAME key, so a key completes exactly once
# and no accepted task is ever billed twice. The billing cap fails closed.
# --------------------------------------------------------------------------

FailureMode = Literal[
    "benign",
    "preemption",
    "stale_offer",
    "host_unavailable",
    "oom",
    "model_mismatch",
    "invalid_price",
    "billing_cap",
]


@dataclass
class ReplayLedger:
    """Durable execution ledger: idempotency keys -> completion count."""

    completed: dict[str, int] = field(default_factory=dict)
    billed_usd: float = 0.0
    events: list[str] = field(default_factory=list)

    def is_complete(self, task_id: str) -> bool:
        return self.completed.get(task_id, 0) > 0

    def attempt(self, task_id: str, run: Callable[[], tuple[float, bool]]) -> tuple[float, bool]:
        """One attempt of a task's body under its idempotency key.

        The first completion of a key executes, bills, and records; a
        re-submission of an already-completed key (a retry storm, a duplicate
        publish, a replayed requeue) is a no-op that bills nothing — no
        duplicate work, no double billing. An attempt that ends in a
        checkpoint (preemption) bills only its post-checkpoint tail and does
        NOT complete the key: the requeue resumes it under the same key.
        """
        if self.is_complete(task_id):
            self.events.append(f"idempotent-skip:{task_id}")
            return 0.0, True
        billed, completed = run()
        # Work actually performed is billed even when it ends in a
        # checkpoint: the post-preemption tail is real spend, and it is what
        # makes redo_multiplier visible in the replay's billed_usd. Only a
        # COMPLETION advances the idempotency key, so a key never bills its
        # full body twice and a checkpointed key never completes twice.
        self.billed_usd += billed
        if completed:
            self.completed[task_id] = self.completed.get(task_id, 0) + 1
        else:
            self.events.append(f"checkpoint-requeue:{task_id}")
        return billed, completed


def _task_body(
    mode: FailureMode, seed: str, task_id: str, attempt_no: int, rate_per_task: float
) -> tuple[float, bool]:
    """One deterministic attempt: preemption checkpoints half a task's work.

    The preemption draw includes the attempt number, so a requeue is a fresh
    draw against the same idempotency key — resumed work repeats only its
    post-checkpoint tail, and the key still completes exactly once.
    """
    if mode == "preemption" and _hash_float(seed, "preempt", task_id, attempt_no) < PREEMPTION_RATE:
        return rate_per_task * 0.5, False
    return rate_per_task, True


def _replay_invalid_price(offers: list[MarketplaceOffer], now: float) -> dict[str, object]:
    """Invalid prices are caught at ingestion, before any ranking."""
    decisions = [evaluate_offer(o, now) for o in offers]
    bad = sorted(d.offer_id for d in decisions if d.reason == "invalid_price")
    return {
        "mode": "invalid_price",
        "rejected_at_ingestion": bad,
        "accepted": 0,
        "billed_usd": 0.0,
        "route_failures": 0,
        "idempotent_skips": 0,
        "note": "invalid prices never enter ranking; ledger untouched",
    }


def _replay_stale(pick: MarketplaceOffer, tasks: int) -> dict[str, object]:
    """Freshness is re-checked at execution time, not just at selection."""
    exec_now = pick.captured_at + pick.ttl_seconds + 1.0
    verdict = evaluate_offer(pick, exec_now)
    return {
        "mode": "stale_offer",
        "rejected_at_ingestion": [],
        "accepted": 0,
        "billed_usd": 0.0,
        "route_failures": tasks if not verdict.eligible else 0,
        "idempotent_skips": 0,
        "note": f"execution-time re-validation verdict: {verdict.reason or 'eligible'}",
    }


def _replay_preflight(mode: FailureMode, pick: MarketplaceOffer, tasks: int) -> dict[str, object]:
    """OOM and model-mismatch are pre-rental rejections: zero billing."""
    if mode == "oom":
        # The cell for (3090/4090, int4, vllm, 4k, summarization) is verified
        # compatible — but a 70B model does not fit 24GB. OOM is caught at
        # pre-flight, before any rental, with zero billing.
        heavy = WorkloadClass("summarization", "70b-int4", "4k", False, tasks)
        ok, why, _ = workload_eligible(pick, heavy, pick.captured_at)
        note = f"70B class on {pick.gpu_sku} pre-flight: {why or 'eligible'}"
    else:
        # A workload whose (gpu, quant, stack, context, class) cell is absent
        # from the registry: unknown compatibility is ineligible, not guessed.
        unknown = WorkloadClass("summarization", "13b-int4", "32k", False, tasks)
        ok, why, _ = workload_eligible(pick, unknown, pick.captured_at)
        note = f"unregistered cell pre-flight: {why or 'eligible'}"
    return {
        "mode": mode,
        "rejected_at_ingestion": [],
        "accepted": 0,
        "billed_usd": 0.0,
        "route_failures": tasks if not ok else 0,
        "idempotent_skips": 0,
        "note": note,
    }


def _replay_failover(
    pick: MarketplaceOffer,
    offers: list[MarketplaceOffer],
    now: float,
    workload: WorkloadClass,
    tasks: int,
) -> dict[str, object]:
    """A drained host re-enters the SAME selection path, narrowed — no new
    authority, no second mechanism: the exhausted offer is dropped from the
    candidate set and the ranking runs again over the rest."""
    drained = [o for o in offers if o.capacity_gpus > 0 and o.offer_id != pick.offer_id]
    second, reason, _ = select_cheapest_eligible(drained, workload, now)
    return {
        "mode": "host_unavailable",
        "rejected_at_ingestion": [],
        "accepted": 0,
        "billed_usd": 0.0,
        "route_failures": 0 if second is not None else tasks,
        "idempotent_skips": 0,
        "note": f"failover target after draining {pick.offer_id}: "
        f"{second.offer_id if second else f'none ({reason})'}",
    }


def _replay_execute(
    mode: FailureMode,
    pick: MarketplaceOffer,
    seed: str,
    rate_per_task: float,
    tasks: int,
) -> dict[str, object]:
    """Execution-path modes: benign, preemption, billing cap."""
    ledger = ReplayLedger()
    cap = math.inf if mode != "billing_cap" else rate_per_task * 3.0
    accepted = 0
    for i in range(tasks):
        task_id = f"chat-{i:04d}"
        if ledger.billed_usd >= cap:
            ledger.events.append(f"billing-cap-refusal:{task_id}")
            break
        done = False
        attempt_no = 0
        while not done:
            attempt_no += 1
            _, done = ledger.attempt(
                task_id,
                lambda a=attempt_no, t=task_id: _task_body(mode, seed, t, a, rate_per_task),
            )
        if done:
            accepted += 1
    return {
        "mode": mode,
        "rejected_at_ingestion": [],
        "accepted": accepted,
        "billed_usd": round(ledger.billed_usd, 6),
        "route_failures": max(0, tasks - accepted),
        "idempotent_skips": sum(1 for e in ledger.events if e.startswith("idempotent-skip")),
        "events": ledger.events[:64],
        "distinct_keys_completed": len(ledger.completed),
        "note": "each idempotency key completed at most once; cap refused the rest",
    }


def run_replay(
    mode: FailureMode,
    seed: str = "gpu-arb-v1",
    now: float = 1_000_000.0,
    tasks_per_class: int = 6,
) -> dict[str, object]:
    """Replay one workload batch under one injected failure mode.

    Selection uses the cheapest-eligible route; the executor never widens
    authority: nothing is provisioned, no credential is read, and the
    billing cap refuses further spend instead of exceeding it.
    """
    workload = WORKLOAD_CLASSES[0]  # chat
    offers = offer_feed(now)
    if mode == "invalid_price":
        return _replay_invalid_price(offers, now)
    pick, reason, expected = select_cheapest_eligible(offers, workload, now)
    if pick is None:
        return {
            "mode": mode,
            "rejected_at_ingestion": [],
            "accepted": 0,
            "billed_usd": 0.0,
            "route_failures": tasks_per_class,
            "idempotent_skips": 0,
            "note": f"selection failed: {reason}",
        }
    if mode == "stale_offer":
        return _replay_stale(pick, tasks_per_class)
    if mode in ("oom", "model_mismatch"):
        return _replay_preflight(mode, pick, tasks_per_class)
    if mode == "host_unavailable":
        return _replay_failover(pick, offers, now, workload, tasks_per_class)
    rate_per_task = (expected if expected != math.inf else 0.001) * 0.1
    return _replay_execute(mode, pick, seed, rate_per_task, tasks_per_class)


# --------------------------------------------------------------------------
# Route comparison (AC2) — deterministic offline replay.
# --------------------------------------------------------------------------


def _describe_route(
    pick: MarketplaceOffer | None, why: str, cost: float, workload: WorkloadClass
) -> dict[str, object]:
    """One route's selection, priced on the expected-cost model.

    Any serviceable pick (compatible capability record, VRAM fit) gets a
    finite expected accepted-task cost; null is reserved for picks that
    genuinely cannot serve the workload.
    """
    if pick is None:
        return {"offer": None, "reason": why, "expected_cost_per_task_usd": None}
    record = capability_for(pick, workload)
    if cost == math.inf and record is not None and record.compatible and vram_fit(pick, workload):
        cost = expected_accepted_task_cost(pick, record, workload)
    mtok = math.inf if record is None else dollars_per_mtok_accepted(pick, record, workload)
    return {
        "offer": pick.offer_id,
        "gpu": pick.gpu_sku,
        "host": pick.host,
        "listed_usd_per_hour": pick.price_usd_per_hour,
        "price_basis": pick.price_basis,
        "availability_probability": pick.availability_probability(),
        "risk_adjusted_usd_per_gpu_hour": dollars_per_gpu_hour(pick),
        "expected_cost_per_task_usd": None if cost == math.inf else round(cost, 8),
        "usd_per_mtok_accepted": None if mtok == math.inf else round(mtok, 4),
        "reason": why,
    }


def route_comparison(seed: str, tasks_per_class: int, now: float) -> dict[str, object]:
    """Replay every route over the pinned corpus and score each."""
    offers = offer_feed(now)
    routes: dict[str, object] = {}
    for workload in WORKLOAD_CLASSES:
        fixed, fixed_why = select_fixed_gpu(offers, workload, now, "RTX_3090_24GB")
        listed, listed_why = select_cheapest_listed(offers)
        eligible, elig_why, elig_cost = select_cheapest_eligible(offers, workload, now)
        quality, qual_why, qual_cost = select_quality_adjusted(offers, workload, now)
        routes[workload.name] = {
            "fixed-gpu": _describe_route(fixed, fixed_why, math.inf, workload),
            "cheapest-listed": _describe_route(listed, listed_why, math.inf, workload),
            "cheapest-eligible": _describe_route(eligible, elig_why, elig_cost, workload),
            "quality-adjusted": _describe_route(quality, qual_why, qual_cost, workload),
        }
    return {
        "routes": routes,
        "seed": seed,
        "tasks_per_class": tasks_per_class,
        "data_class": "simulation",
        "note": (
            "cheapest-listed is the documented trap: it selects the cheapest "
            "unverified lead, whose risk-adjusted expected cost exceeds every "
            "verified offer's. expected_cost_per_task_usd is authored-model "
            "output, not a measurement."
        ),
    }


# --------------------------------------------------------------------------
# Annual sensitivity (design item 6): 22 vs 24 h/day, 365 days, three
# strategies. All outputs are simulation under each price basis.
# --------------------------------------------------------------------------


def _owned_annual_usd(hours_per_day: int) -> dict[str, float]:
    """Owned-GPU annual cost: capex amortized over OWNED_AMORT_YEARS + power."""
    hours = hours_per_day * 365.0
    capex = OWNED_GPU_CAPEX_USD / OWNED_AMORT_YEARS
    power = OWNED_WATTS / 1000.0 * hours * OWNED_ELECTRICITY_USD_PER_KWH
    return {"capex_amortized_usd": round(capex, 2), "power_usd": round(power, 2)}


def annual_tco(hours_per_day: int) -> dict[str, object]:
    """Annual TCO per strategy per price basis. Simulation, not prediction."""
    year_hours = hours_per_day * 365.0
    owned = _owned_annual_usd(hours_per_day)
    owned_base = owned["capex_amortized_usd"] + owned["power_usd"]
    strategies: dict[str, object] = {}
    for basis, rate in PRICE_BASES.items():
        strategies[basis] = {
            "always-rented": round(year_hours * rate, 2),
            "owned-16gb-plus-cloud": round(
                owned_base + year_hours * CLOUD_OVERFLOW_SHARE * rate, 2
            ),
            "heavy-model-on-demand": round(
                owned_base + year_hours * HEAVY_TASK_SHARE * rate * HEAVY_RATE_PREMIUM, 2
            ),
            "price_basis_note": (
                "unverified lead basis: what the anomalous prices would be "
                "worth IF TRUE; not an availability guarantee"
                if basis == "lead"
                else "verified-basis modeled rate"
            ),
        }
    return {
        "hours_per_day": hours_per_day,
        "days_per_year": 365,
        "owned_gpu": owned,
        "strategies_usd_per_year": strategies,
        "data_class": "simulation",
    }


# --------------------------------------------------------------------------
# Disposition (AC7): explicit go/no-go and the #934 assessment.
# --------------------------------------------------------------------------


def disposition() -> dict[str, object]:
    """The research disposition this bench exists to support."""
    return {
        "go_no_go": "no-go",
        "go_no_go_detail": (
            "No rental, deposit, or spending is authorized or recommended: "
            "every price in scope is an unverified lead, no capability cell "
            "is hardware-measured, and the operator-approval gate has not "
            "been exercised against a live feed. The next step is evidence, "
            "not adoption."
        ),
        "issue_934_disposition": "WATCH (unchanged)",
        "issue_934_incubate_now": False,
        "issue_934_incubate_preconditions": [
            "a real-hardware benchmark of >=3 distinct GPU classes under the "
            "pinned workload rubric (AC3) — not attempted here: no rental "
            "budget or hardware access was authorized for this round",
            "a replayed-Invocation run on real infrastructure per the #934 "
            "benchmark procedure, with hardware-utilization numbers",
            "a verified-basis offer feed (audited price/billing history) from "
            "at least one approved host",
        ],
        "production_adoption": (
            "none; any future adoption routes through the canonical routing "
            "seam (ADR-038/ADR-079) and its owners"
        ),
    }


# --------------------------------------------------------------------------
# Benchmark driver.
# --------------------------------------------------------------------------


def _schema_section() -> dict[str, object]:
    """The versioned schema contract the bench enforces (AC1)."""
    return {
        "offer_schema_version": OFFER_SCHEMA_VERSION,
        "freshness_rule": "captured_at + ttl_seconds > now, re-checked at execution time",
        "eligibility_rules": [
            "schema_version must match",
            "price and cpu rate finite; price > 0, cpu >= 0",
            "not stale at evaluation AND at execution time",
            "host in APPROVED_HOSTS (operator trust list)",
            "reliability >= MIN_RELIABILITY",
            "capacity_gpus > 0",
            "gpu_sku known",
            "(gpu, quantization, stack/version, context, concurrency, task) "
            "cell present AND compatible AND VRAM fits — unknown is ineligible",
        ],
    }


def _offer_feed_section(
    offers: list[MarketplaceOffer], decisions: list[OfferDecision]
) -> dict[str, object]:
    """The feed inventory: eligible count, rejections, unverified leads."""
    rejected = sorted(f"{d.offer_id}:{d.reason}" for d in decisions if not d.eligible)
    return {
        "data_class": "simulation",
        "offers": len(offers),
        "schema_eligible": sum(1 for d in decisions if d.eligible),
        "rejected": rejected,
        "unverified_leads": sorted(o.offer_id for o in offers if o.price_basis == "advertised"),
        "note": "advertised prices are leads with modeled low availability, never guarantees",
    }


def _registry_section(registry: dict[CapabilityKey, CapabilityRecord]) -> dict[str, object]:
    """The capability registry's honest inventory: nothing hardware-measured."""
    return {
        "cells": len(registry),
        "compatible_cells": sum(1 for r in registry.values() if r.compatible),
        "hardware_measured_cells": 0,
        "provenance": "synthetic-fixture",
        "note": "unknown cells are ineligible by rule; nothing is guessed",
    }


def _gpu_catalog_section() -> list[dict[str, object]]:
    """The research matrix's GPU classes with published hardware facts only."""
    return [
        {
            "sku": s.sku,
            "vram_gb": s.vram_gb,
            "compute_capability": s.compute_capability,
            "fp16_tensor": s.fp16_tensor,
            "bf16": s.bf16,
            "int4_weight_only": s.int4_weight_only,
            "watts": s.watts,
        }
        for s in GPU_SPECS.values()
    ]


def run_benchmark(
    seed: str = "gpu-arb-v1",
    tasks_per_class: int = 40,
    hours: str = "both",
) -> dict[str, object]:
    """Assemble the full report. Byte-identical for identical arguments."""
    now = 1_000_000.0  # fixed evaluation instant; no wall clock in the report
    offers = offer_feed(now)
    decisions = [evaluate_offer(o, now) for o in offers]
    registry = capability_registry()
    failure_modes: list[FailureMode] = [
        "benign",
        "preemption",
        "stale_offer",
        "host_unavailable",
        "oom",
        "model_mismatch",
        "invalid_price",
        "billing_cap",
    ]
    hours_values = [22, 24] if hours == "both" else [int(hours)]
    return {
        "benchmark": "gpu-rental-arbitrage",
        "issue": "2121",
        "epic": "905",
        "schema": _schema_section(),
        "offer_feed": _offer_feed_section(offers, decisions),
        "capability_registry": _registry_section(registry),
        "gpu_catalog": _gpu_catalog_section(),
        "routes": route_comparison(seed, tasks_per_class, now),
        "failure_injection": {
            mode: run_replay(mode, seed, now, tasks_per_class) for mode in failure_modes
        },
        "annual_sensitivity_usd": {str(h): annual_tco(h) for h in hours_values},
        "trust_controls": {
            "network_io": "none; the harness imports no network module (asserted by tests)",
            "operator_approval": "host allow-list (APPROVED_HOSTS) gates every rental decision",
            "credentials": "none read, none embedded",
            "unattended_deposit": "billing cap fails closed in every replay",
            "egress_authority": "marketplace discovery grants no model egress; "
            "inference-model selection stays behind the shipped CostAwareRouter "
            "seam, untouched by this bench",
        },
        "disposition": disposition(),
        "provenance": {
            "seed": seed,
            "deterministic": "blake2b draws over stable ids; byte-identical reruns",
            "observed_data": "none — every number in this report is simulated",
            "gpu_facts_source": "published hardware specifications (VRAM, "
            "compute capability); no measured throughput",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks-per-class", type=int, default=40)
    parser.add_argument("--seed", type=str, default="gpu-arb-v1")
    parser.add_argument("--hours", type=str, default="both", choices=["22", "24", "both"])
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args(argv)
    report = run_benchmark(args.seed, args.tasks_per_class, args.hours)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    picks = [v["cheapest-eligible"]["offer"] for v in report["routes"]["routes"].values()]
    print(f"cheapest-eligible picks: {picks}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
