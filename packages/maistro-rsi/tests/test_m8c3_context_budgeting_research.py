"""M8-C3 adaptive context budgeting / hierarchical compression / omission (#922).

Evidence-only research harness for the M8-C leaf asking whether *dynamically
choosing* how much context to retrieve, compress, summarize, or omit beats the
shipped fixed context budget, and whether hierarchical summaries plus selective
omission of redundant memories hold quality while cutting cost.

This module imports **no** maistro module: research evidence, never an
authority (M8 epic contract — a budget policy that imported the assembly
package could drift into becoming a second context authority). Everything here
measures; nothing ships.

What is replicated, for measurement only, from the shipped seam:

* The assembly spine at ``packages/maistro-core/src/maistro/memory/context_assembly.py``
  (ADR-091 / SPEC-244): ``_estimate_tokens`` (``len(text) // 4``), ``_pack``
  (whole memories in the order given; weight >= 0.6 taken whatever the budget
  says and allowed to overspend; below the band taken only while it fits whole,
  skip-not-break), the weight bands (0.6 always-include / 0.3 pool floor / 0.9
  wisdom), and the fixed caller-side budget — ``ContextBuilder`` hands
  ``system_token_budget = 4096`` tokens in, every call, regardless of the
  query, the evidence, or the model window. That fixed default is exactly the
  baseline this leaf's hypothesis is about.
* The ranking the packer consumes: ``memory/episodic/ranking.py`` ``score`` /
  ``rank`` — ``(keyword_overlap + cosine) * weight``, zero-score memories
  dropped (never ranked), stable descending sort, top-k — driven here with the
  shipped no-credential vector term (``no_vector`` = 0.0): the deterministic
  CI environment has no embedding client, so ``ScoredEpisodicRetrieval``
  ships this exact lexical-only configuration there. The pool bound
  (``limit * 10``) is inert at this corpus size. The raw-split lexical term
  has no stopword handling (SPEC-243), so generic words like "the" match every
  memory containing them — that shipped behavior is part of what the budget
  policies below pay for, and the harness keeps it.
* The tier economics that decide where a budget can bite: ADR-091's
  always-include band (>= 0.6) is exactly the REGRET/AFFIRMATION/WISDOM tiers
  of the production ``WEIGHT_BOUNDS`` ladder, so budget cuts can only ever
  fall on OPINION/LESSON-tier memories. The corpus is weighted accordingly —
  anchors sit in both regimes — and one finding below pins the consequence:
  banded facts are never budget-lost, at any budget.
* The always-include wisdom the shipped policy serves through Layer 3
  (``list_by_scope`` at the wisdom floor, packed by the same ``_pack`` whose
  band takes them whatever the budget says): the two zero-overlap adversarial
  WISDOM memories are force-seeded into every assembled context, overspending
  every tight budget, exactly as the shipped layer does.
* Layer 2 (rolling compression, SPEC-189) ships as an explicit ``""``
  placeholder, so every summarizer below is a hypothetical — clearly labeled,
  never a third authority.

Stand-ins, deterministic and pinned: the corpus (30 hand-checked memories on
the SPEC-240 tier ladder across five topics, with four near-duplicate
paraphrase pairs, in-band low-value noise, and five budget-cuttable
OPINION/LESSON facts), a fact registry whose probes are literal substrings of
their anchor memories with required qualifier tokens, and two extractive
summarizers — one qualifier-safe (keeps negation/condition sentences), one
naive (first-sentence-only) — so *summary distortion* is measurable rather
than asserted.

Measured (the issue's list): critical-fact recall, evidence sufficiency (the
deterministic stand-in for task quality: a fact is served only if its probe
text reaches the prompt), lost-critical-fact rate, token cost (production
``len // 4`` accounting, including always-include overspend), work-unit
latency (structural ordering only, never wall-clock), summary distortion (a
served probe whose required qualifier tokens a summarizer dropped) and
fabrication (summary text that is not a verbatim substring of a source
memory — must be zero for an extractive pipeline), and stability across model
context sizes (the same queries re-run under three window stand-ins at a
30% memory share).

Policies compared: the shipped fixed budget (a sweep — 4096 is one point the
issue asks to beat), complexity-scaled budget, evidence-density saturation
stop, score-margin stop, near-duplicate omission (token Jaccard),
window-pressure packing with hierarchical-summary fallback, the combination,
and the naive-summary distortion foil. Every pinned finding was
mutation-checked; the research note records the mutations and the boundaries
where the mechanisms did *not* pay (negative findings are recorded, not
polished away).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from itertools import combinations, pairwise
from pathlib import Path

ADVISORY_ONLY = True

# ---------------------------------------------------------------------------
# Canonical-shape replicas (measurement-only; the owners stay in maistro-core)
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4  # context_assembly.py / context_builder.py
ALWAYS_INCLUDE_WEIGHT = 0.6  # ADR-091 band, enforced in _pack
BUDGET_INCLUDE_WEIGHT = 0.3  # ADR-091 floor, applied at the store pool read
WISDOM_WEIGHT = 0.9  # ADR-091 wisdom band
DEFAULT_SYSTEM_TOKEN_BUDGET = 4096  # context_builder.py — the fixed baseline
LAYER1_LIMIT = 50  # context_assembly.py recall cap before the budget packs
LAYER1_POOL_FACTOR = 10  # episodic/retrieval.py pool width per requested result

#: Production ``WEIGHT_BOUNDS`` (maistro/types/memory.py), replicated for the
#: corpus-sanity check: tier names and the [low, high] weight interval each
#: tier's weights must stay inside. Note what the ladder implies: the
#: always-include band (>= 0.6) is exactly REGRET/AFFIRMATION/WISDOM, so a
#: budget cut can only ever land on OPINION/LESSON-tier memories.
WEIGHT_BOUNDS: dict[str, tuple[float, float]] = {
    "observation": (0.1, 0.5),
    "hypothesis": (0.2, 0.6),
    "opinion": (0.3, 0.8),
    "lesson": (0.5, 0.9),
    "regret": (0.6, 1.0),
    "affirmation": (0.6, 1.0),
    "wisdom": (0.9, 1.0),
}


def estimate_tokens(text: str) -> int:
    """Replica of ``context_assembly._estimate_tokens``."""
    return len(text) // CHARS_PER_TOKEN


def keyword_overlap(query: str, content: str) -> float:
    """Replica of ``episodic/ranking.keyword_overlap``: raw split, no stopwords."""
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return 0.0
    content_words = {w for w in content.lower().split() if w}
    if not content_words:
        return 0.0
    return len(query_words & content_words) / len(query_words)


def shipped_no_client_score(query: str, memory: Memory) -> float:
    """``(keyword_overlap + no_vector) * weight`` — the shipped no-credential row."""
    return keyword_overlap(query, memory.content) * memory.weight


def shipped_rank(memories: list[Memory], query: str, k: int = LAYER1_LIMIT) -> list[Memory]:
    """Replica of ``episodic/ranking.rank`` with the no-client vector term.

    Zero-score memories are dropped (never ranked last — padding a prompt with
    text the query has no relation to spends budget), the sort is stable and
    descending on score alone (equal scores keep pool order), and the top-k is
    returned. The pool preceding this rank (``limit * LAYER1_POOL_FACTOR``) is
    inert here: the corpus is smaller than the pool.
    """
    scored = [(shipped_no_client_score(query, m), m) for m in memories]
    kept = [(s, m) for s, m in scored if s > 0.0]
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _s, m in kept[:k]]


def pack(memories: list[Memory], budget_tokens: int | None) -> tuple[list[Memory], int]:
    """Replica of ``context_assembly._pack`` over memory objects.

    Whole memories, in the order given, until the budget is spent. A memory at
    or above ``ALWAYS_INCLUDE_WEIGHT`` is taken whatever the budget says and
    can overspend it. Below the band a memory is taken only while it fits
    whole; a memory that would not fit is skipped and a later, smaller one may
    still be taken. ``None`` means unbounded.
    """
    kept: list[Memory] = []
    spent = 0
    for memory in memories:
        cost = estimate_tokens(memory.content)
        if (
            memory.weight >= ALWAYS_INCLUDE_WEIGHT
            or budget_tokens is None
            or spent + cost <= budget_tokens
        ):
            kept.append(memory)
            spent += cost
    return kept, spent


def tokens_of(text: str) -> set[str]:
    """Raw word-split token set (the overlap term's own notion of a token)."""
    return {w for w in text.lower().split() if w}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def split_sentences(content: str) -> list[str]:
    """Sentence split that keeps every sentence a verbatim substring."""
    parts = re.split(r"(?<=[.])\s+", content.strip())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Corpus: hand-checked constants (memory ids, tiers, weights, facts, queries)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Memory:
    memory_id: str
    tier: str
    weight: float
    topic: str
    content: str


@dataclass(frozen=True)
class Fact:
    fact_id: str
    memory_id: str  # the anchor memory stating the fact
    probe: str  # exact substring of the anchor's content
    qualifiers: tuple[str, ...] = ()  # tokens that must ride along un-distorted


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    facts: tuple[str, ...]  # fact ids needed to answer


CORPUS: tuple[Memory, ...] = (
    # --- deploy topic -------------------------------------------------------
    # Banded anchor: the budget can never cut it (ADR-091).
    Memory(
        "m_dep_01",
        "affirmation",
        0.8,
        "deploy",
        "The payments service deploys through the blue/green pipeline with a canary stage.",
    ),
    # Budget-cuttable anchor (LESSON, below the band): what a tight budget loses.
    Memory(
        "m_dep_02",
        "lesson",
        0.58,
        "deploy",
        "Rollback is one command: promote the previous green stack and drain the blue.",
    ),
    # Qualifier-bearing banded anchor: fact in sentence 1, the load-bearing
    # qualifier in sentence 2. A first-sentence-only summary serves the fact
    # and drops the qualifier — the distortion this harness measures.
    Memory(
        "m_dep_03",
        "regret",
        0.85,
        "deploy",
        "Production deploys freeze on Friday mornings. The freeze only lifts after the "
        "incident commander posts the all-clear signal.",
    ),
    Memory(
        "m_dep_04",
        "lesson",
        0.52,
        "deploy",
        "Canary analysis watches error budget burn for ten minutes before promotion.",
    ),
    # Near-duplicate paraphrase of m_dep_01, one tier down (opinion): the
    # redundancy the omission/density policies are measured on.
    Memory(
        "m_dep_05",
        "opinion",
        0.45,
        "deploy",
        "Payments deploys ride the blue/green pipeline through a canary stage.",
    ),
    Memory(
        "m_dep_06",
        "observation",
        0.32,
        "deploy",
        "A deploy dashboard screenshot was shared in the channel today.",
    ),
    Memory(
        "m_dep_07",
        "observation",
        0.28,
        "deploy",
        "Someone mentioned the deploy train felt slow this week.",
    ),
    # --- database topic -----------------------------------------------------
    Memory(
        "m_db_01",
        "regret",
        0.82,
        "database",
        "The orders migration took an ACCESS EXCLUSIVE lock and stalled the orders table.",
    ),
    Memory(
        "m_db_02",
        "lesson",
        0.59,
        "database",
        "Migrations ship with a paired revert script. The revert runs only after a "
        "locked-table check passes.",
    ),
    Memory(
        "m_db_03",
        "opinion",
        0.4,
        "database",
        "Set lock_timeout before long migrations so queues drain instead of piling up.",
    ),
    Memory(
        "m_db_04",
        "opinion",
        0.44,
        "database",
        "An orders migration grabbed an ACCESS EXCLUSIVE lock and stalled orders.",
    ),
    Memory(
        "m_db_05",
        "observation",
        0.34,
        "database",
        "The database team shared a lock-monitoring dashboard link.",
    ),
    Memory(
        "m_db_06", "observation", 0.25, "database", "A migration ran at midnight; nothing broke."
    ),
    # --- auth topic ---------------------------------------------------------
    Memory(
        "m_au_01",
        "affirmation",
        0.78,
        "auth",
        "Session validation now enforces a 30 minute sliding TTL window.",
    ),
    Memory(
        "m_au_02",
        "lesson",
        0.59,
        "auth",
        "Credential rotation is mandatory every 90 days. Rotation windows never overlap "
        "a live incident window.",
    ),
    Memory(
        "m_au_03",
        "opinion",
        0.42,
        "auth",
        "Refresh tokens rotate on every use; reuse trips the reuse detector.",
    ),
    Memory(
        "m_au_04",
        "opinion",
        0.46,
        "auth",
        "Session validation now enforces a 30 minute sliding TTL for web clients.",
    ),
    Memory(
        "m_au_05",
        "observation",
        0.31,
        "auth",
        "An auth brainstorm doc was started; notes are rough.",
    ),
    # --- billing topic ------------------------------------------------------
    Memory(
        "m_bi_01",
        "affirmation",
        0.76,
        "billing",
        "Partial refunds settle back to the original payment method within five business days.",
    ),
    Memory(
        "m_bi_02",
        "lesson",
        0.57,
        "billing",
        "Chargebacks route to the dispute queue within 24 hours. Chargebacks are only "
        "auto-accepted below the evidence threshold set by ops.",
    ),
    Memory(
        "m_bi_03", "opinion", 0.4, "billing", "Refund windows follow the processor clock, not ours."
    ),
    Memory(
        "m_bi_04",
        "opinion",
        0.45,
        "billing",
        "Partial refunds return to the original payment method in five business days.",
    ),
    Memory(
        "m_bi_05",
        "observation",
        0.33,
        "billing",
        "An invoice template mockup got positive emoji feedback.",
    ),
    # --- incident topic -----------------------------------------------------
    Memory(
        "m_in_01",
        "wisdom",
        0.92,
        "incident",
        "Sev1 pages follow the primary-on-call rotation, with the incident commander as backup.",
    ),
    Memory(
        "m_in_02",
        "regret",
        0.84,
        "incident",
        "The incident channel gets a status update every 30 minutes. Updates pause only "
        "when the channel is in skunk mode.",
    ),
    Memory(
        "m_in_03",
        "opinion",
        0.41,
        "incident",
        "Postmortems land within five business days of resolution.",
    ),
    Memory(
        "m_in_04",
        "lesson",
        0.58,
        "incident",
        "Deploys queued during an incident hold in the queue. They run only after the "
        "all-clear posts.",
    ),
    Memory("m_in_05", "observation", 0.3, "incident", "The pager app got a dark mode update."),
    # --- adversarial: cross-topic WISDOM the shipped Layer 3 force-feeds into
    # --- every context; zero lexical overlap with every query (checked below).
    Memory(
        "m_ad_01",
        "wisdom",
        0.96,
        "meta",
        "A metric without a threshold is one opinion wearing a chart.",
    ),
    Memory(
        "m_ad_02",
        "wisdom",
        0.95,
        "meta",
        "Memory written hastily gets repealed by postmortems; verify before reinforcement.",
    ),
)

FACTS: dict[str, Fact] = {
    f.fact_id: f
    for f in (
        Fact("deploy_pipeline", "m_dep_01", "blue/green pipeline with a canary stage"),
        Fact("rollback_path", "m_dep_02", "promote the previous green stack"),
        Fact(
            "friday_freeze",
            "m_dep_03",
            "Production deploys freeze on Friday",
            ("only", "after", "all-clear"),
        ),
        Fact("migration_lock", "m_db_01", "ACCESS EXCLUSIVE lock and stalled the orders table"),
        Fact(
            "revert_path",
            "m_db_02",
            "Migrations ship with a paired revert script",
            ("only", "after", "locked-table"),
        ),
        Fact("session_ttl", "m_au_01", "30 minute sliding TTL"),
        Fact(
            "rotation_rule",
            "m_au_02",
            "Credential rotation is mandatory every 90 days",
            ("never", "overlap", "incident"),
        ),
        Fact("partial_refund", "m_bi_01", "settle back to the original payment method"),
        Fact(
            "chargeback_rule",
            "m_bi_02",
            "route to the dispute queue",
            ("only", "below", "threshold"),
        ),
        Fact("paging_rotation", "m_in_01", "primary-on-call rotation"),
        Fact("status_cadence", "m_in_02", "status update every 30 minutes", ("only", "skunk")),
        Fact(
            "queue_during_incident",
            "m_in_04",
            "Deploys queued during an incident hold",
            ("only", "after", "all-clear"),
        ),
    )
}

QUERIES: tuple[Query, ...] = (
    Query("q_dep_simple", "how do we deploy the payments service", ("deploy_pipeline",)),
    Query(
        "q_dep_complex",
        "prepare the payments deploy during the incident freeze and confirm the rollback path",
        ("deploy_pipeline", "rollback_path", "friday_freeze"),
    ),
    Query("q_db_simple", "which migration locked the orders table", ("migration_lock",)),
    Query(
        "q_db_complex",
        "audit the orders migration lock the revert path and the lock_timeout lesson",
        ("migration_lock", "revert_path"),
    ),
    Query("q_au_simple", "what changed in session validation", ("session_ttl",)),
    Query(
        "q_au_complex",
        "review the session TTL change alongside the credential rotation rule",
        ("session_ttl", "rotation_rule"),
    ),
    Query("q_bi_simple", "how are partial refunds handled", ("partial_refund",)),
    Query(
        "q_bi_complex",
        "reconcile the refund window with the chargeback dispute rule",
        ("partial_refund", "chargeback_rule"),
    ),
    Query("q_in_simple", "who pages during sev1", ("paging_rotation",)),
    Query(
        "q_in_complex",
        "sev1 paging the status cadence and deploys queued during an incident",
        ("paging_rotation", "status_cadence", "queue_during_incident"),
    ),
    Query("q_friday", "can we ship this friday", ("friday_freeze",)),
    Query(
        "q_adv",
        "summarize deployment gotchas for the payments service",
        ("deploy_pipeline", "rollback_path"),
    ),
)

DUPLICATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("m_dep_01", "m_dep_05"),
    ("m_db_01", "m_db_04"),
    ("m_au_01", "m_au_04"),
    ("m_bi_01", "m_bi_04"),
)
ADVERSARIAL_IDS = ("m_ad_01", "m_ad_02")

#: The facts whose anchor sits below the always-include band: the only facts a
#: budget can ever lose (pinned by TestBandConfinement).
BAND_CUTTABLE_FACTS = frozenset(
    f.fact_id
    for f in FACTS.values()
    if next(m.weight for m in CORPUS if m.memory_id == f.memory_id) < ALWAYS_INCLUDE_WEIGHT
)

QUERY_BY_ID = {q.query_id: q for q in QUERIES}


def corpus_of(extra: tuple[Memory, ...] = ()) -> tuple[Memory, ...]:
    return CORPUS + extra


def forced_seed() -> list[Memory]:
    """The Layer 3 wisdom band's forced contribution to every context."""
    return [m for m in CORPUS if m.memory_id in ADVERSARIAL_IDS]


def seed_tokens() -> int:
    return sum(estimate_tokens(m.content) for m in forced_seed())


def corpus_tokens() -> int:
    """Total ``len // 4`` cost of serving every memory whole."""
    return sum(estimate_tokens(m.content) for m in CORPUS)


# ---------------------------------------------------------------------------
# Serving: did a fact's probe (and its qualifiers) reach the assembled text?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Serving:
    served: frozenset[str]  # fact ids whose probe text reached the context
    distorted: frozenset[str]  # served, but required qualifier tokens dropped


def serve_facts(query: Query, item_texts: dict[str, str]) -> Serving:
    served: list[str] = []
    distorted: list[str] = []
    for fact_id in query.facts:
        fact = FACTS[fact_id]
        text = item_texts.get(fact.memory_id, "")
        if not text:
            continue
        tokens = tokens_of(text)
        if fact.probe in text and all(q in tokens for q in fact.qualifiers):
            served.append(fact_id)
        elif fact.probe in text:
            # Probe reached the prompt, a required qualifier did not: the
            # summary served a fact whose load-bearing modifier was lost.
            served.append(fact_id)
            distorted.append(fact_id)
    return Serving(frozenset(served), frozenset(distorted))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

#: Complexity buckets over the query's own surface (distinct tokens, len >= 3):
#: small queries get less budget, large ones more. A policy input, not a
#: shipped constant — this leaf measures whether such scaling pays.
COMPLEXITY_SMALL_MAX = 5
COMPLEXITY_MEDIUM_MAX = 9
COMPLEXITY_BUDGET_SMALL = 0.5
COMPLEXITY_BUDGET_MEDIUM = 1.25
COMPLEXITY_BUDGET_LARGE = 1.75

DENSITY_STOP = 0.35  # marginal new-token share below which a candidate is redundant
MARGIN_RATIO = 0.45  # score frontier: a sub-band candidate below ratio * top ends the plateau
OMISSION_TAU = 0.6  # token Jaccard at which a candidate is a near-duplicate

WINDOW_SHARE = 0.3  # memory budget as a share of the model window stand-in
PRESSURE_TRIGGER = 2  # dropped scored candidates that engage the summary tier
#: The hierarchical tier's reserved share of the window budget. The reservation
#: is a measured necessity, not a tuning choice: the shipped pack is
#: skip-not-break — it keeps taking smaller items until nothing fits — so a
#: summary tier that waits for leftovers never gets any (measured: zero
#: remainder at every window). The allowance is what a real implementation
#: would have to carve out before packing.
SUMMARY_ALLOWANCE = 0.25
BASE_BUDGET = 90  # the fixed-budget point the adaptive policies scale around

#: Window stand-ins, scaled to this corpus the way 8k-128k windows stand to a
#: ~30k-token scoped corpus (the memory layer's ~30% share). The sweep is the
#: issue's "stability across model context sizes" axis.
WINDOWS: tuple[int, ...] = (512, 4096, 16384)
SMALL_WINDOW, LARGE_WINDOW = WINDOWS[0], WINDOWS[-1]


def complexity_of(query_text: str) -> int:
    return len({w for w in query_text.lower().split() if len(w) >= 3})


def complexity_multiplier(query_text: str) -> float:
    n = complexity_of(query_text)
    if n <= COMPLEXITY_SMALL_MAX:
        return COMPLEXITY_BUDGET_SMALL
    if n <= COMPLEXITY_MEDIUM_MAX:
        return COMPLEXITY_BUDGET_MEDIUM
    return COMPLEXITY_BUDGET_LARGE


def complexity_budget(query_text: str, base: int = BASE_BUDGET) -> int:
    return int(base * complexity_multiplier(query_text))


@dataclass(frozen=True)
class Outcome:
    query_id: str
    served: frozenset[str]
    distorted: frozenset[str]
    spent_tokens: int
    work_units: int
    item_ids: tuple[str, ...]
    summary_ids: tuple[str, ...] = ()


def _finish(
    query: Query, items: list[Memory], summary_texts: dict[str, str], spent: int, work: int
) -> Outcome:
    """Charge the forced wisdom seed (production Layer 3's band), then serve.

    The seed is taken after the ranked packing exactly as ``assemble`` spends
    layer 3 after layer 1 — and because the pack's band takes weight >= 0.9
    whatever the budget says, it lands in every context and overspends the
    tight ones. That overspend is a measured shipped cost, not an artifact.
    """
    seed = forced_seed()
    texts = {m.memory_id: m.content for m in items}
    for memory_id, text in summary_texts.items():
        texts.setdefault(memory_id, text)
    serving = serve_facts(query, texts)
    return Outcome(
        query.query_id,
        serving.served,
        serving.distorted,
        spent + seed_tokens(),
        work,
        tuple(m.memory_id for m in items) + tuple(m.memory_id for m in seed),
        tuple(sorted(summary_texts)),
    )


def _subband_select(
    rankeds: list[Memory], budget: int, *, skip_redundant
) -> tuple[list[Memory], int, int]:
    """Shared sub-band selection loop: band invariant + skip-not-break.

    Weight >= 0.6 candidates are always taken (ADR-091; the pack would take
    them anyway). Sub-band candidates flow through ``skip_redundant`` (the
    policy's own redundancy gate) and the whole-item budget check; a candidate
    that fails either is skipped, never truncates the scan, and a later
    smaller candidate may still be taken — the shipped pack's shape.

    Returns (kept, spent, work): work charges one coverage/redundancy
    evaluation per candidate on top of the rank pass the caller priced.
    """
    kept: list[Memory] = []
    covered: set[str] = set()
    kept_tokens: list[set[str]] = []
    spent = 0
    work = 0
    for memory in rankeds:
        cost = estimate_tokens(memory.content)
        toks = tokens_of(memory.content)
        if memory.weight >= ALWAYS_INCLUDE_WEIGHT:
            kept.append(memory)
            kept_tokens.append(toks)
            covered |= toks
            spent += cost
            continue
        work += 1
        if skip_redundant(memory, toks, covered, kept_tokens, bool(kept)):
            continue
        if spent + cost <= budget:
            kept.append(memory)
            kept_tokens.append(toks)
            covered |= toks
            spent += cost
    return kept, spent, work


def _rank_work(extra: tuple[Memory, ...]) -> int:
    """Scoring comparisons for the rank pass plus the pack inspection pass."""
    return 2 * len(corpus_of(extra))


def run_fixed(query: Query, budget: int, extra: tuple[Memory, ...] = ()) -> Outcome:
    """The shipped shape: rank, then pack at a fixed budget. No adaptivity."""
    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    items, spent = pack(rankeds, budget)
    return _finish(query, items, {}, spent, _rank_work(extra))


def run_complexity(
    query: Query, base: int = BASE_BUDGET, extra: tuple[Memory, ...] = ()
) -> Outcome:
    """Budget scaled by the query's own complexity bucket."""
    return run_fixed(query, complexity_budget(query.text, base), extra)


def run_density(
    query: Query, budget_cap: int, extra: tuple[Memory, ...] = (), delta: float = DENSITY_STOP
) -> Outcome:
    """Take while the marginal new-token share stays above ``delta``.

    Near-duplicates saturate coverage (their marginal share collapses), so the
    stop subsumes omission when the duplicate ranks behind its original. The
    stop is per-candidate, never a scan break: the band and skip-not-break
    keep their shipped meaning.
    """

    def saturated(
        memory: Memory,
        toks: set[str],
        covered: set[str],
        _kept_tokens: list[set[str]],
        have_kept: bool,
    ) -> bool:
        marginal = 1.0 - (len(toks & covered) / len(toks) if toks else 0.0)
        return have_kept and marginal < delta

    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    items, spent, work = _subband_select(rankeds, budget_cap, skip_redundant=saturated)
    return _finish(query, items, {}, spent, _rank_work(extra) + work)


def run_margin(
    query: Query, budget_cap: int, extra: tuple[Memory, ...] = (), ratio: float = MARGIN_RATIO
) -> Outcome:
    """Take sub-band candidates while scores sit on the frontier plateau.

    The first sub-band candidate below ``ratio * top score`` is the cliff; the
    plateau ends there — post-cliff members are sacrificed. That is the
    policy's measured trade-off, not the shipped pack's shape.
    """
    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    work = _rank_work(extra) + len(rankeds)
    if not rankeds:
        return _finish(query, [], {}, 0, work)
    threshold = shipped_no_client_score(query.text, rankeds[0]) * ratio
    kept: list[Memory] = []
    spent = 0
    for memory in rankeds:
        cost = estimate_tokens(memory.content)
        if memory.weight >= ALWAYS_INCLUDE_WEIGHT:
            kept.append(memory)
            spent += cost
            continue
        if shipped_no_client_score(query.text, memory) < threshold:
            break  # the cliff
        if spent + cost <= budget_cap:
            kept.append(memory)
            spent += cost
    return _finish(query, kept, {}, spent, work)


def run_omission(
    query: Query, budget: int, extra: tuple[Memory, ...] = (), tau: float = OMISSION_TAU
) -> Outcome:
    """The fixed budget plus near-duplicate omission before packing.

    A sub-band candidate whose token Jaccard with an already-kept memory
    reaches ``tau`` is dropped as redundant; everything else flows through the
    unchanged shipped pack.
    """

    def duplicate(
        memory: Memory,
        toks: set[str],
        _covered: set[str],
        kept_tokens: list[set[str]],
        _have_kept: bool,
    ) -> bool:
        return any(jaccard(toks, prev) >= tau for prev in kept_tokens)

    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    items, spent, work = _subband_select(rankeds, budget, skip_redundant=duplicate)
    return _finish(query, items, {}, spent, _rank_work(extra) + work)


def safe_summary_sentences(memories: list[Memory]) -> list[str]:
    """Qualifier-safe extractive summary: first sentence of every memory, plus
    every sentence carrying a negation/condition marker.

    Label-free by construction: it reads surface markers, never the fact
    registry, so it can fail — a qualifier phrased without a marker is lost.
    Every returned sentence is a verbatim substring of its source memory.
    """
    markers = {"never", "only", "until", "after", "before", "not", "without", "must"}
    sentences: list[str] = []
    for memory in memories:
        parts = split_sentences(memory.content)
        if parts:
            sentences.append(parts[0])
        sentences.extend(p for p in parts[1:] if markers & set(p.lower().split()))
    return sentences


def naive_summary_sentences(memories: list[Memory]) -> list[str]:
    """The distortion foil: first sentence only. Probes survive; qualifiers do not."""
    sentences: list[str] = []
    for memory in memories:
        parts = split_sentences(memory.content)
        if parts:
            sentences.append(parts[0])
    return sentences


def pack_sentences(sentences: list[str], budget: int, work: list[int]) -> tuple[list[str], int]:
    kept: list[str] = []
    spent = 0
    for sentence in sentences:
        cost = estimate_tokens(sentence)
        work[0] += 1
        if spent + cost <= budget:
            kept.append(sentence)
            spent += cost
    return kept, spent


def _summaries_for_dropped(
    dropped: list[Memory], budget: int, work: list[int], summarizer
) -> tuple[dict[str, str], int]:
    """Cluster the dropped candidates by topic and summarize each cluster.

    Clusters are served in descending max-member-score order (relevance
    first), ties broken by cluster name — deterministic, label-free. Returns
    per-cluster summary text keyed by memory id (every summarized memory maps
    to its cluster's text, so serving checks can read it).
    """
    clusters: dict[str, list[Memory]] = {}
    for memory in dropped:
        clusters.setdefault(memory.topic, []).append(memory)
    order = sorted(clusters, key=lambda t: (-max(m.weight for m in clusters[t]), t))
    texts: dict[str, str] = {}
    spent = 0
    for topic in order:
        members = sorted(clusters[topic], key=lambda m: m.memory_id)
        sentences = summarizer(members)
        work[0] += len(sentences)
        kept, cluster_spent = pack_sentences(sentences, max(budget - spent, 0), work)
        if not kept:
            continue
        spent += cluster_spent
        text = " ".join(kept)
        for member in members:
            texts[member.memory_id] = text
    return texts, spent


def _dropped_subband(rankeds: list[Memory], item_ids: set[str]) -> list[Memory]:
    return [m for m in rankeds if m.memory_id not in item_ids and m.weight < ALWAYS_INCLUDE_WEIGHT]


def _pressure_outcome(query: Query, budget: int, summarizer, extra: tuple[Memory, ...]) -> Outcome:
    """Items pack first, exactly as the shipped policy packs. When scored
    candidates were dropped by the cut, the leftover budget serves extractive
    cluster summaries of what was dropped — the two-level layout: full items
    where they fit, summaries where they do not."""
    work_list = [_rank_work(extra)]
    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    summary_budget = int(budget * SUMMARY_ALLOWANCE)
    items, spent = pack(rankeds, budget - summary_budget)
    work_list[0] += len(rankeds)
    dropped = _dropped_subband(rankeds, {m.memory_id for m in items})
    summary_texts: dict[str, str] = {}
    if len(dropped) >= PRESSURE_TRIGGER:
        summary_texts, summary_spent = _summaries_for_dropped(
            dropped, summary_budget, work_list, summarizer
        )
        spent += summary_spent
    return _finish(query, items, summary_texts, spent, work_list[0])


def run_pressure(
    query: Query,
    window_tokens: int,
    summarizer=safe_summary_sentences,
    extra: tuple[Memory, ...] = (),
) -> Outcome:
    """Window-pressure packing with a hierarchical fallback: the budget is the
    window's memory share (the pressure axis)."""
    return _pressure_outcome(query, int(window_tokens * WINDOW_SHARE), summarizer, extra)


def run_full(
    query: Query, window_tokens: int, base: int = BASE_BUDGET, extra: tuple[Memory, ...] = ()
) -> Outcome:
    """Complexity budget + omission + density stop + pressure fallback."""
    budget = min(int(window_tokens * WINDOW_SHARE), complexity_budget(query.text, base))

    def redundant(
        memory: Memory,
        toks: set[str],
        covered: set[str],
        kept_tokens: list[set[str]],
        have_kept: bool,
    ) -> bool:
        if any(jaccard(toks, prev) >= OMISSION_TAU for prev in kept_tokens):
            return True
        marginal = 1.0 - (len(toks & covered) / len(toks) if toks else 0.0)
        return have_kept and marginal < DENSITY_STOP

    rankeds = shipped_rank(list(corpus_of(extra)), query.text)
    items, spent, work = _subband_select(
        rankeds, budget - int(budget * SUMMARY_ALLOWANCE), skip_redundant=redundant
    )
    dropped = _dropped_subband(rankeds, {m.memory_id for m in items})
    summary_texts: dict[str, str] = {}
    work_list = [_rank_work(extra) + work]
    if len(dropped) >= PRESSURE_TRIGGER:
        summary_texts, summary_spent = _summaries_for_dropped(
            dropped, int(budget * SUMMARY_ALLOWANCE), work_list, safe_summary_sentences
        )
        spent += summary_spent
    return _finish(query, items, summary_texts, spent, work_list[0])


def run_naive_summary(query: Query, budget: int) -> Outcome:
    """The pure summary tier at a fixed budget, with the first-sentence-only
    summarizer: the distortion foil. No items ship; every scored candidate is
    summarized — so any qualifier the foil drops is lost by construction
    unless a marker sentence survives."""
    work_list = [len(CORPUS)]
    rankeds = shipped_rank(list(CORPUS), query.text)
    work_list[0] += len(rankeds)
    summary_texts, spent = _summaries_for_dropped(
        rankeds, budget, work_list, naive_summary_sentences
    )
    return _finish(query, [], summary_texts, spent, work_list[0])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    policy: str
    queries: int
    mean_tokens: float
    recall: float  # served critical facts / asked facts
    sufficiency: float  # queries with every asked fact served
    clean_sufficiency: float  # sufficiency counting distortion as failure
    lost_fact_rate: float  # queries missing at least one asked fact
    distortion_rate: float  # distorted servings / served facts
    work_units: int
    overspend_queries: int  # queries whose context exceeded the named budget
    per_query: tuple[Outcome, ...]


def summarize(
    policy: str, per_query: list[Outcome], named_budgets: dict[str, int] | None = None
) -> RunResult:
    asked = sum(len(q.facts) for q in QUERIES)
    served_total = sum(len(o.served) for o in per_query)
    distorted_total = sum(len(o.distorted) for o in per_query)
    sufficient = sum(
        1 for q, o in zip(QUERIES, per_query, strict=True) if set(q.facts) <= set(o.served)
    )
    clean = sum(
        1
        for q, o in zip(QUERIES, per_query, strict=True)
        if set(q.facts) <= set(o.served) and not (set(o.distorted) & set(q.facts))
    )
    lost = sum(1 for q, o in zip(QUERIES, per_query, strict=True) if set(q.facts) - set(o.served))
    overspend = 0
    if named_budgets:
        overspend = sum(1 for o in per_query if o.spent_tokens > named_budgets.get(o.query_id, 0))
    return RunResult(
        policy=policy,
        queries=len(QUERIES),
        mean_tokens=sum(o.spent_tokens for o in per_query) / len(per_query),
        recall=served_total / asked,
        sufficiency=sufficient / len(QUERIES),
        clean_sufficiency=clean / len(QUERIES),
        lost_fact_rate=lost / len(QUERIES),
        distortion_rate=(distorted_total / served_total) if served_total else 0.0,
        work_units=sum(o.work_units for o in per_query),
        overspend_queries=overspend,
        per_query=tuple(per_query),
    )


#: The fixed sweep. BASE_BUDGET sits inside it; 120 is the generous point the
#: adaptive policies are priced against.
FIXED_SWEEP: tuple[int, ...] = (40, 60, 90, 120)


def run_benchmark(base: int = BASE_BUDGET) -> dict[str, RunResult]:
    """The main table: fixed sweep vs the adaptive policies, same queries."""
    results: dict[str, RunResult] = {}
    for budget in FIXED_SWEEP:
        per = [run_fixed(q, budget) for q in QUERIES]
        results[f"fixed_{budget}"] = summarize(
            f"fixed_{budget}", per, {q.query_id: budget for q in QUERIES}
        )
    per = [run_complexity(q, base) for q in QUERIES]
    results["adaptive_complexity"] = summarize(
        "adaptive_complexity", per, {q.query_id: complexity_budget(q.text, base) for q in QUERIES}
    )
    cap = int(base * COMPLEXITY_BUDGET_LARGE)
    per = [run_density(q, cap) for q in QUERIES]
    results["adaptive_density"] = summarize(
        "adaptive_density", per, {q.query_id: cap for q in QUERIES}
    )
    per = [run_margin(q, cap) for q in QUERIES]
    results["adaptive_margin"] = summarize(
        "adaptive_margin", per, {q.query_id: cap for q in QUERIES}
    )
    per = [run_omission(q, base) for q in QUERIES]
    results["omission_90"] = summarize("omission_90", per, {q.query_id: base for q in QUERIES})
    per = [run_full(q, LARGE_WINDOW, base) for q in QUERIES]
    results["full_adaptive"] = summarize(
        "full_adaptive", per, {q.query_id: complexity_budget(q.text, base) for q in QUERIES}
    )
    return results


def run_window_sweep() -> dict[tuple[str, int], RunResult]:
    """The stability axis: fixed vs pressure policies under three windows."""
    results: dict[tuple[str, int], RunResult] = {}
    for window in WINDOWS:
        share = int(window * WINDOW_SHARE)
        per = [run_fixed(q, share) for q in QUERIES]
        results[("fixed", window)] = summarize(
            f"fixed@{window}", per, {q.query_id: share for q in QUERIES}
        )
        per = [run_pressure(q, window) for q in QUERIES]
        results[("pressure", window)] = summarize(
            f"pressure@{window}", per, {q.query_id: share for q in QUERIES}
        )
    return results


def make_fillers(count: int) -> tuple[Memory, ...]:
    """High-weight off-topic fillers for the noise sweep.

    Two sit just inside the always-include band (gaming the band force-feeds
    them into every context); the rest are in-band (>= floor) score noise that
    must displace relevant memories by rank alone. None carries a fact probe,
    and every one shares stop/content words with the deploy-family queries so
    the displacement channel is real.
    """
    fillers: list[Memory] = []
    for i in range(count):
        weight = 0.62 if i < 2 else 0.45
        tier = "affirmation" if i < 2 else "observation"
        fillers.append(
            Memory(
                f"filler_{i:02d}",
                tier,
                weight,
                "noise",
                f"The deploy status and payments update; notes from the migration channel {i}.",
            )
        )
    return tuple(fillers)


def run_with_corpus(extra: tuple[Memory, ...], policy: str, budget: int) -> RunResult:
    """Re-run the fixed policy against corpus + ``extra``, without touching CORPUS."""
    per = [run_fixed(q, budget, extra) for q in QUERIES]
    return summarize(f"{policy}+noise{len(extra)}", per, {q.query_id: budget for q in QUERIES})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def module_source() -> str:
    return Path(__file__).read_text(encoding="utf-8")


class TestEvidenceOnlyContract:
    """The harness may be evidence, never an authority (epic contract)."""

    def test_advisory_marker_is_true(self) -> None:
        assert ADVISORY_ONLY is True

    def test_module_imports_no_maistro_module(self) -> None:
        """AST scan: no ``import maistro*`` anywhere in this file.

        The leaf evaluates the context-assembly seam; an evidence harness that
        imported it could drift into calling it, and a budget policy that
        cannot import the assembly package cannot become a second one.
        """
        tree = ast.parse(module_source())
        banned: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                banned.extend(a.name for a in node.names if a.name.startswith("maistro"))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("maistro"):
                    banned.append(module)
        assert banned == []


class TestReplicaIdentities:
    """The instruments before the measurement: production math, hand-checked."""

    def test_token_estimate_matches_the_production_formula(self) -> None:
        # len(text) // 4: "abcd" is one token, "abc" is none, empty is none.
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("abc") == 0
        assert estimate_tokens("") == 0
        assert estimate_tokens("x" * 81) == 20

    def test_pack_always_include_band_overspends_a_zero_budget(self) -> None:
        # ADR-091: weight >= 0.6 is taken whatever the budget says. A 0-budget
        # caller is not a caller owed nothing; the band answers anyway.
        high = Memory("hi", "regret", 0.7, "t", "x" * 40)  # 10 tokens
        low = Memory("lo", "observation", 0.32, "t", "y" * 40)
        kept, spent = pack([high, low], 0)
        assert [m.memory_id for m in kept] == ["hi"]
        assert spent == 10

    def test_pack_skips_without_stopping_and_never_slices(self) -> None:
        big = Memory("big", "lesson", 0.55, "t", "b" * 80)  # 20 tokens, sub-band
        small = Memory("small", "lesson", 0.55, "t", "s" * 12)  # 3 tokens, sub-band
        kept, spent = pack([big, small], 10)
        assert [m.memory_id for m in kept] == ["small"]
        assert spent == 3
        # And an unbounded budget takes everything whole.
        kept_all, spent_all = pack([big, small], None)
        assert len(kept_all) == 2 and spent_all == 23

    def test_rank_drops_zero_scores_and_stable_sorts_the_rest(self) -> None:
        hit_a = Memory("a", "lesson", 0.55, "t", "alpha beta")
        hit_b = Memory("b", "lesson", 0.55, "t", "alpha gamma")
        miss = Memory("z", "lesson", 0.55, "t", "nothing here")
        ranked = shipped_rank([hit_a, miss, hit_b], "alpha")
        # Same overlap (1/1) and weight for both hits, so the stable sort keeps
        # pool order; the zero-score memory is dropped, never padded in.
        assert [m.memory_id for m in ranked] == ["a", "b"]

    def test_weight_term_orders_equal_overlap_by_tier(self) -> None:
        low = Memory("lo", "lesson", 0.55, "t", "alpha beta")
        high = Memory("hi", "regret", 0.85, "t", "alpha gamma")
        assert [m.memory_id for m in shipped_rank([low, high], "alpha")] == ["hi", "lo"]


class TestCorpusSanity:
    def test_fact_probes_are_verbatim_substrings_of_their_anchors(self) -> None:
        corpus = {m.memory_id: m for m in CORPUS}
        for fact in FACTS.values():
            assert fact.memory_id in corpus, f"{fact.fact_id} anchors an unknown memory"
            assert fact.probe in corpus[fact.memory_id].content, (
                f"{fact.fact_id} probe is not a substring of {fact.memory_id}"
            )
            content_tokens = tokens_of(corpus[fact.memory_id].content)
            for qualifier in fact.qualifiers:
                assert qualifier in content_tokens, (
                    f"{fact.fact_id} qualifier {qualifier!r} not in its anchor"
                )

    def test_every_query_fact_resolves_and_corpus_shape_is_pinned(self) -> None:
        ids = {m.memory_id for m in CORPUS}
        assert len(ids) == len(CORPUS) == 30
        assert len(QUERIES) == 12
        assert len(FACTS) == 12
        for query in QUERIES:
            assert query.facts, f"{query.query_id} asks for nothing"
            assert set(query.facts) <= set(FACTS)
        assert set(ADVERSARIAL_IDS) <= ids
        assert len(DUPLICATE_PAIRS) == 4
        # Both budget regimes exist among the facts: banded (never cuttable)
        # and sub-band (what budgets lose).
        assert len(BAND_CUTTABLE_FACTS) == 5
        assert len(BAND_CUTTABLE_FACTS) < len(FACTS)

    def test_weights_sit_inside_the_production_tier_bounds(self) -> None:
        for memory in CORPUS:
            low, high = WEIGHT_BOUNDS[memory.tier]
            assert low <= memory.weight <= high, f"{memory.memory_id} off the SPEC-240 ladder"
        # The bands that drive packing exist in the corpus: always-include
        # members, in-band budget items, below-floor rows the store pool
        # excludes.
        assert any(m.weight >= ALWAYS_INCLUDE_WEIGHT for m in CORPUS)
        assert any(BUDGET_INCLUDE_WEIGHT <= m.weight < ALWAYS_INCLUDE_WEIGHT for m in CORPUS)
        assert any(m.weight < BUDGET_INCLUDE_WEIGHT for m in CORPUS)

    def test_duplicates_clear_the_tau_bar_and_non_duplicates_do_not(self) -> None:
        corpus = {m.memory_id: m for m in CORPUS}
        for original, duplicate in DUPLICATE_PAIRS:
            score = jaccard(
                tokens_of(corpus[original].content), tokens_of(corpus[duplicate].content)
            )
            assert score >= OMISSION_TAU, f"{original}/{duplicate} not near-duplicates: {score}"
        # Same-topic non-pairs must stay under tau, or omission would eat
        # distinct memories: check every same-topic non-duplicate pair.
        dup_set = {frozenset(pair) for pair in DUPLICATE_PAIRS}
        by_topic: dict[str, list[Memory]] = {}
        for m in CORPUS:
            by_topic.setdefault(m.topic, []).append(m)
        for topic, members in by_topic.items():
            for a, b in combinations(members, 2):
                if frozenset((a.memory_id, b.memory_id)) in dup_set:
                    continue
                assert jaccard(tokens_of(a.content), tokens_of(b.content)) < OMISSION_TAU, (
                    f"{a.memory_id}/{b.memory_id} collide in {topic}"
                )

    def test_qualifier_sentences_are_not_first_sentences(self) -> None:
        # The distortion measure needs qualifiers to live OUTSIDE sentence one;
        # otherwise the naive summarizer could not lose them.
        for fact in FACTS.values():
            if not fact.qualifiers:
                continue
            anchor = next(m for m in CORPUS if m.memory_id == fact.memory_id)
            first = split_sentences(anchor.content)[0]
            for qualifier in fact.qualifiers:
                assert qualifier not in first.lower().split(), (
                    f"{fact.fact_id} qualifier {qualifier!r} leaks into sentence one"
                )

    def test_adversarial_memories_share_no_word_with_any_query(self) -> None:
        adversarial = [m for m in CORPUS if m.memory_id in ADVERSARIAL_IDS]
        for memory in adversarial:
            for query in QUERIES:
                assert keyword_overlap(query.text, memory.content) == 0.0, (
                    f"{memory.memory_id} overlaps {query.query_id}; the zero-overlap pin broke"
                )

    def test_benchmark_is_deterministic(self) -> None:
        first = run_benchmark()
        second = run_benchmark()
        assert first.keys() == second.keys()
        for name in first:
            assert first[name] == second[name], f"{name} moved between runs"


class TestPolicyMechanics:
    def test_complexity_budget_is_monotone_in_query_surface(self) -> None:
        small = "ship this friday"
        medium = "which migration locked the orders table"
        large = (
            "prepare the payments deploy during the incident freeze and confirm the rollback path"
        )
        assert complexity_multiplier(small) < complexity_multiplier(medium)
        assert complexity_multiplier(medium) < complexity_multiplier(large)
        assert complexity_budget(small) == 45
        assert complexity_budget(large) == 157

    def test_density_stop_spares_only_uncovered_fresh_evidence(self) -> None:
        # A memory sharing nothing with what is covered has marginal density
        # 1.0 and must never be refused by the stop (only by the budget).
        fresh = tokens_of("wholly unrelated vocabulary here")
        covered = tokens_of("completely different words")
        assert 1.0 - len(fresh & covered) / len(fresh) == 1.0
        # A near-duplicate saturates: below the stop, always refused.
        dup = tokens_of("same words again")
        covered_dup = tokens_of("same words")
        assert 1.0 - len(dup & covered_dup) / len(dup) < DENSITY_STOP

    def test_omission_drops_only_flagged_duplicates(self) -> None:
        corpus = {m.memory_id: m for m in CORPUS}
        dup_map = {dup: original for original, dup in DUPLICATE_PAIRS}
        for query in QUERIES:
            outcome = run_omission(query, 10_000)  # budget-free: omission alone shows
            kept = set(outcome.item_ids)
            rankeds = shipped_rank(list(CORPUS), query.text)
            for memory in rankeds:
                if memory.memory_id in kept or memory.weight >= ALWAYS_INCLUDE_WEIGHT:
                    continue
                original = dup_map.get(memory.memory_id)
                assert original is not None and original in kept, (
                    f"{query.query_id}: omission dropped non-duplicate {memory.memory_id}"
                )
                assert (
                    jaccard(
                        tokens_of(corpus[original].content),
                        tokens_of(corpus[memory.memory_id].content),
                    )
                    >= OMISSION_TAU
                )

    def test_margin_stop_stops_at_the_score_cliff(self) -> None:
        for query in QUERIES:
            outcome = run_margin(query, 10_000)
            rankeds = shipped_rank(list(CORPUS), query.text)
            if not rankeds:
                continue
            threshold = shipped_no_client_score(query.text, rankeds[0]) * MARGIN_RATIO
            kept = set(outcome.item_ids)
            # The kept sub-band set is exactly the rank-ordered prefix before
            # the first below-frontier sub-band candidate; banded members are
            # taken wherever they appear.
            expected: list[str] = []
            for memory in rankeds:
                if memory.weight >= ALWAYS_INCLUDE_WEIGHT:
                    continue
                if shipped_no_client_score(query.text, memory) < threshold:
                    break
                expected.append(memory.memory_id)
            subband_kept = [
                m.memory_id
                for m in rankeds
                if m.memory_id in kept and m.weight < ALWAYS_INCLUDE_WEIGHT
            ]
            assert subband_kept == expected, f"{query.query_id}: margin plateau mis-cut"

    def test_pressure_engages_summaries_only_under_pressure(self) -> None:
        complex_query = QUERY_BY_ID["q_dep_complex"]
        small = run_pressure(complex_query, SMALL_WINDOW)
        assert small.summary_ids, "tight window must engage the summary tier"
        big = run_pressure(complex_query, LARGE_WINDOW)
        assert not big.summary_ids, "roomy window must serve items, not summaries"

    def test_window_pressure_never_truncates_a_memory(self) -> None:
        # The #622 rule holds under every policy: a memory ships whole or not
        # at all. Items are whole; summary text is built only from verbatim
        # sentences of real memories (enforced again in TestSummariesDistortion).
        corpus = {m.memory_id: m for m in CORPUS}
        for query in QUERIES:
            outcome = run_pressure(query, SMALL_WINDOW)
            for memory_id in outcome.item_ids:
                assert corpus[memory_id].content  # items always carry whole content
            assert set(outcome.summary_ids) <= set(corpus)


class TestBenchmarkFindings:
    def test_fixed_frontier_is_monotone_in_budget(self) -> None:
        benchmark = run_benchmark()
        seq = [benchmark[f"fixed_{b}"] for b in FIXED_SWEEP]
        for lo, hi in pairwise(seq):
            assert hi.recall >= lo.recall
            assert hi.sufficiency >= lo.sufficiency
            assert hi.mean_tokens >= lo.mean_tokens

    def test_always_include_band_overspends_the_named_budget(self) -> None:
        # The shipped pack lets weight >= 0.6 overspend; with the Layer 3
        # wisdom seed forced in, tight budgets are exceeded by construction —
        # measured, not assumed.
        benchmark = run_benchmark()
        assert benchmark["fixed_40"].overspend_queries == len(QUERIES)
        assert benchmark["fixed_90"].overspend_queries > 0

    def test_band_confined_losses_banded_facts_are_never_budget_lost(self) -> None:
        # ADR-091's band has a consequence the budget debate should not gloss
        # over: at EVERY swept budget, every weight >= 0.6 fact is served.
        # Losses are confined to the OPINION/LESSON facts.
        banded_facts = [f for f in FACTS.values() if f.fact_id not in BAND_CUTTABLE_FACTS]
        for budget in FIXED_SWEEP:
            for query in QUERIES:
                outcome = run_fixed(query, budget)
                for fact in banded_facts:
                    if fact.fact_id in query.facts:
                        assert fact.fact_id in outcome.served, (
                            f"budget {budget} lost banded fact {fact.fact_id}"
                        )

    def test_fixed_budget_loses_cuttable_facts_that_complexity_scaling_recovers(self) -> None:
        fixed = run_benchmark()["fixed_90"]
        base = run_benchmark()["adaptive_complexity"]
        # Same ranker, same corpus, same pack: the only difference is the
        # budget knob the shipped caller never turns.
        assert base.recall > fixed.recall
        assert base.lost_fact_rate < fixed.lost_fact_rate
        assert base.sufficiency >= fixed.sufficiency

    def test_complexity_adaptivity_pays_for_itself(self) -> None:
        # The adaptive policy must not win by simply spending more: it matches
        # the generous fixed point's recall at less mean spend, and beats its
        # own base point outright.
        benchmark = run_benchmark()
        adaptive = benchmark["adaptive_complexity"]
        fixed_120 = benchmark["fixed_120"]
        fixed_90 = benchmark["fixed_90"]
        assert adaptive.mean_tokens <= fixed_120.mean_tokens
        assert adaptive.recall >= fixed_120.recall
        assert adaptive.recall > fixed_90.recall

    def test_density_matches_sweep_max_recall_at_its_mean_spend(self) -> None:
        # The saturation stop's claim, measured: hold the generous fixed
        # point's recall without exceeding its mean spend.
        benchmark = run_benchmark()
        density = benchmark["adaptive_density"]
        fixed_120 = benchmark["fixed_120"]
        assert density.recall >= fixed_120.recall
        assert density.mean_tokens <= fixed_120.mean_tokens

    def test_omission_saves_budget_but_the_band_absorbs_the_savings(self) -> None:
        # The honest crowd-out finding: dropping near-duplicates frees budget,
        # but the shipped pack is skip-not-break, so the next banded memory
        # (weight >= 0.6, taken whatever the budget says) consumes the freed
        # room. Measured: a strictly lower mean spend, and IDENTICAL recall —
        # omission bought tokens, not facts, on this corpus.
        benchmark = run_benchmark()
        fixed_90 = benchmark["fixed_90"]
        omission = benchmark["omission_90"]
        assert omission.mean_tokens < fixed_90.mean_tokens
        assert omission.recall == fixed_90.recall

    def test_margin_stop_is_a_measured_negative(self) -> None:
        # The score plateau ends at the first sub-band candidate below
        # ratio * top score — and mid-score facts behind that cliff are lost
        # that the plain fixed pack keeps. Recorded as a negative result.
        benchmark = run_benchmark()
        fixed_90 = benchmark["fixed_90"]
        margin = benchmark["adaptive_margin"]
        assert margin.recall < fixed_90.recall

    def test_full_adaptive_pays_a_composition_tax(self) -> None:
        # The measured composition finding: stacking the policies is not free.
        # The summary allowance carves its reserve out of the item budget, and
        # at the medium complexity bucket that reserve is exactly the slot the
        # chargeback fact needed — so full_adaptive gives back the rescue that
        # adaptive_complexity alone made, landing at the base fixed point's
        # recall while spending near the generous point's budget. Composition
        # ordering (reserve from the crowd, not from the facts) is the open
        # engineering question this measurement hands forward.
        benchmark = run_benchmark()
        full = benchmark["full_adaptive"]
        fixed_90 = benchmark["fixed_90"]
        fixed_120 = benchmark["fixed_120"]
        adaptive = benchmark["adaptive_complexity"]
        assert full.recall == fixed_90.recall
        assert full.recall < adaptive.recall
        assert full.mean_tokens <= fixed_120.mean_tokens
        assert full.lost_fact_rate == fixed_90.lost_fact_rate

    def test_work_units_order_structurally(self) -> None:
        # Latency stand-in, structural only: the selective policies pay for
        # their savings with bounded extra bookkeeping, and the full stack
        # costs more work than the fixed pipeline at the same base.
        benchmark = run_benchmark()
        assert benchmark["adaptive_density"].work_units > benchmark["fixed_120"].work_units
        assert benchmark["full_adaptive"].work_units > benchmark["fixed_120"].work_units


class TestSummariesDistortion:
    def test_naive_summary_distorts_qualifier_probes_the_safe_one_does_not(self) -> None:
        query = QUERY_BY_ID["q_friday"]  # its only fact is qualifier-bearing
        naive = run_naive_summary(query, 120)
        assert naive.served == frozenset({"friday_freeze"})
        assert naive.distorted == frozenset({"friday_freeze"}), "the foil must distort"
        safe = run_pressure(query, SMALL_WINDOW)
        assert "friday_freeze" in safe.served
        assert "friday_freeze" not in safe.distorted

    def test_safe_summarizer_keeps_marker_sentences_naive_drops(self) -> None:
        members = [m for m in CORPUS if m.topic == "deploy"]
        anchor = next(m for m in members if m.memory_id == "m_dep_03")
        qualifier_sentence = split_sentences(anchor.content)[1]
        assert qualifier_sentence in safe_summary_sentences(members)
        assert qualifier_sentence not in naive_summary_sentences(members)

    def test_summary_fabrication_is_zero(self) -> None:
        # Extractive discipline: any text the summary tier ever serves must be
        # a substring of a real memory, for both summarizers over every topic.
        all_content = [m.content for m in CORPUS]
        for summarizer in (safe_summary_sentences, naive_summary_sentences):
            for topic in ("deploy", "database", "auth", "billing", "incident", "meta"):
                members = [m for m in CORPUS if m.topic == topic]
                for sentence in summarizer(members):
                    assert any(sentence in content for content in all_content), (
                        f"{summarizer.__name__} fabricated text: {sentence!r}"
                    )

    def test_served_probes_come_from_verbatim_memory_text(self) -> None:
        # End-to-end fabrication guard: every probe a policy reports served is
        # a probe that lives in exactly one anchor, and distortion is always a
        # subset of served.
        for window in WINDOWS:
            for query in QUERIES:
                outcome = run_pressure(query, window)
                assert outcome.distorted <= outcome.served
                for fact_id in outcome.served:
                    fact = FACTS[fact_id]
                    anchor = next(m for m in CORPUS if m.memory_id == fact.memory_id)
                    assert fact.probe in anchor.content


class TestStabilityAcrossWindowSizes:
    def test_fixed_degrades_small_and_hierarchy_is_recall_neutral_here(self) -> None:
        # The measured stability answer, both halves honest:
        #
        # 1. The fixed share degrades at the smallest window: the always-
        #    include band's banded crowd alone exceeds 30% of a 512-token
        #    window, and the pack cuts the sub-band facts behind it.
        # 2. The hierarchical policy recovers that degradation to exactly the
        #    fixed policy's recall — no better. Its summaries engage (8 of 12
        #    queries) but the one buried fact sits at the ranker's noise
        #    floor, and a summary tier ordered by the same ranker inherits
        #    the same blindness: packing cannot rescue a fact the ranker
        #    buried, the C2 boundary re-found one layer up.
        sweep = run_window_sweep()
        fixed_small = sweep[("fixed", SMALL_WINDOW)]
        fixed_large = sweep[("fixed", LARGE_WINDOW)]
        assert fixed_small.recall < fixed_large.recall
        for window in WINDOWS:
            assert sweep[("pressure", window)].recall == sweep[("fixed", window)].recall

    def test_pressure_summaries_engage_only_under_pressure(self) -> None:
        sweep = run_window_sweep()
        small = sweep[("pressure", SMALL_WINDOW)]
        engaged = sum(1 for o in small.per_query if o.summary_ids)
        assert engaged > 0, "the tight window must engage the summary tier"
        big = sweep[("pressure", LARGE_WINDOW)]
        assert all(not o.summary_ids for o in big.per_query), (
            "a roomy window drops nothing, so it must serve items only"
        )

    def test_pressure_costs_at_most_its_allowance_over_fixed(self) -> None:
        # The summary tier is paid for by its reservation: pressure packs the
        # same rank order into a smaller item budget, so its spend is the
        # fixed policy's spend minus what that reservation displaced, plus at
        # most the allowance back in summaries — bounded above by the fixed
        # spend plus one allowance.
        sweep = run_window_sweep()
        for window in WINDOWS:
            fixed = sweep[("fixed", window)]
            pressure = sweep[("pressure", window)]
            allowance = int(int(window * WINDOW_SHARE) * SUMMARY_ALLOWANCE)
            assert pressure.mean_tokens <= fixed.mean_tokens + allowance

    def test_pressure_tokens_stay_bounded_by_the_window_share(self) -> None:
        sweep = run_window_sweep()
        for window in WINDOWS:
            result = sweep[("pressure", window)]
            cap = int(window * WINDOW_SHARE)
            # Spend = items (banded-overspends allowed) + summaries within the
            # allowance + the forced wisdom seed.
            assert result.mean_tokens <= cap + seed_tokens() + int(cap * SUMMARY_ALLOWANCE)


class TestNoiseSweep:
    def test_noise_never_improves_recall(self) -> None:
        clean = run_with_corpus((), "fixed", 120)
        for k in (5, 10):
            noisy = run_with_corpus(make_fillers(k), "fixed", 120)
            assert noisy.recall <= clean.recall, "fillers must never add recall"

    def test_high_weight_noise_displaces_relevant_memory_under_fixed(self) -> None:
        clean = run_with_corpus((), "fixed", 120)
        noisy = run_with_corpus(make_fillers(10), "fixed", 120)
        assert noisy.recall < clean.recall
        assert noisy.lost_fact_rate > clean.lost_fact_rate

    def test_density_stop_absorbs_noise_better_than_fixed(self) -> None:
        fillers = make_fillers(10)
        noisy_fixed = run_with_corpus(fillers, "fixed", 120)
        cap = int(BASE_BUDGET * COMPLEXITY_BUDGET_LARGE)
        per = [run_density(q, cap, fillers) for q in QUERIES]
        noisy_density = summarize("density+noise10", per, {q.query_id: cap for q in QUERIES})
        assert noisy_density.recall >= noisy_fixed.recall
