#!/usr/bin/env python3
"""Demonstrate the two-tier RLPHD parameter design and its key safety property.

Supporting artifact for docs/reviews/2026-07-29-rsi-containment-review.md §9.6.

Tier A -- operator-set, explainable: a handful of named features the operator can
reason about and hand-edit (judge_score, composite, kind flags, bias), plus the
decision parameters theta, z, and latent_budget.

Tier B -- learned, latent, unnamable: coordinates from embedding the promotion
(diff + objective + target). These capture structure nobody articulated -- "these
are alike in some way but we can't say how". Their weights are learned; their
meaning is exhibited via nearest exemplars rather than explained.

Three claims are demonstrated here:

  1. Tier B earns its place: adding latent coordinates raises the auto-decided
     share and the accuracy on it, because the explicit five cannot express
     everything that predicts approval.

  2. NOVELTY IS FLAGGED FOR FREE. This is the property that matters. A candidate
     whose latent coordinates sit far from the training set has a large
     x' Sigma x, hence a wide interval, hence it lands in the flagged band --
     even when the model is otherwise well trained and confident. "I have never
     seen a promotion like this" becomes a computed reason to ask the human,
     which the five hand-picked features cannot express at all.

  3. latent_budget bounds unexplainable authority. The clamp keeps the total
     latent contribution small enough that it can move a decision near the line
     but never override a strong explicit signal.

Embeddings are simulated as 3-D coordinates drawn from a few latent "topics".
A real implementation would embed text and pin cluster centroids (§9.6 rule 7);
the geometry that produces the flagging behaviour is identical either way.

Pure Python on purpose -- see rlphd_band_sim.py for the rationale.

Run: python3 scripts/rlphd_two_tier_sim.py
"""

from __future__ import annotations

import math
import random

EXPLICIT = ("bias", "judge_score", "composite", "is_spec_completion", "is_feature")
LATENT = ("z1", "z2", "z3")

THETA = 0.6
Z = 1.64
RIDGE_EXPLICIT = 1e-2  # light: the operator asserted these matter
RIDGE_LATENT = 1.0  # strong: emergence must pay for itself (§9.6 rule 2)
LATENT_BUDGET = 1.5  # cap on |sum of latent contributions| (§9.6 rule 1)

# The operator's real preference. Note it depends on a latent topic the explicit
# features cannot see -- topic 2 promotions are disliked regardless of their
# scores. That is the structure Tier B is supposed to discover.
TRUE_EXPLICIT = {
    "bias": -3.4,
    "judge_score": 3.0,
    "composite": 2.6,
    "is_spec_completion": 1.0,
    "is_feature": -0.5,
}
TRUE_TOPIC_EFFECT = {0: +1.1, 1: 0.0, 2: -2.2, 3: +0.4}

# Latent topic centroids in embedding space. Topic 4 is held out of training
# entirely -- it is the "never seen anything like this" case for claim 2.
CENTROIDS = {
    0: (0.9, 0.1, 0.2),
    1: (0.1, 0.9, 0.1),
    2: (0.2, 0.2, 0.9),
    3: (0.6, 0.6, 0.1),
    4: (-1.4, -1.3, -1.2),  # held out
}
TRAIN_TOPICS = (0, 1, 2, 3)


def sigmoid(x: float) -> float:
    if x < -700:
        return 0.0
    if x > 700:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return math.log(p / (1 - p))


def sample(rng: random.Random, topic: int | None = None) -> dict[str, float]:
    t = rng.choice(TRAIN_TOPICS) if topic is None else topic
    cx, cy, cz = CENTROIDS[t]
    kind = rng.choice(["spec", "feature", "other"])
    x = {
        "bias": 1.0,
        "judge_score": round(rng.uniform(0.2, 1.0), 3),
        "composite": round(rng.uniform(0.0, 1.0), 3),
        "is_spec_completion": 1.0 if kind == "spec" else 0.0,
        "is_feature": 1.0 if kind == "feature" else 0.0,
        "z1": round(cx + rng.gauss(0, 0.12), 3),
        "z2": round(cy + rng.gauss(0, 0.12), 3),
        "z3": round(cz + rng.gauss(0, 0.12), 3),
    }
    x["_topic"] = float(t)
    return x


def true_eta(x: dict[str, float]) -> float:
    base = sum(w * x[f] for f, w in TRUE_EXPLICIT.items())
    return base + TRUE_TOPIC_EFFECT[int(x["_topic"])]


def label(x: dict[str, float], rng: random.Random) -> int:
    return 1 if rng.random() < sigmoid(true_eta(x)) else 0


def invert(m: list[list[float]]) -> list[list[float]]:
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-14:
            a[col][col] += 1e-9
            piv = col
        a[col], a[piv] = a[piv], a[col]
        d = a[col][col]
        a[col] = [v / d for v in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col], strict=True)]
    return [row[n:] for row in a]


def fit(
    xs: list[dict[str, float]], ys: list[int], feats: tuple[str, ...], iters: int = 60
) -> tuple[dict[str, float], list[list[float]]]:
    """IRLS fit with per-feature ridge: light on Tier A, strong on Tier B."""
    n = len(feats)
    ridge = [RIDGE_LATENT if f in LATENT else RIDGE_EXPLICIT for f in feats]
    beta = dict.fromkeys(feats, 0.0)
    cov = [[0.0] * n for _ in range(n)]
    for _ in range(iters):
        grad = [0.0] * n
        hess = [[ridge[i] if i == j else 0.0 for j in range(n)] for i in range(n)]
        for x, y in zip(xs, ys, strict=True):
            p = sigmoid(sum(beta[f] * x[f] for f in feats))
            w = max(p * (1 - p), 1e-9)
            for i, fi in enumerate(feats):
                grad[i] += (y - p) * x[fi]
                for j, fj in enumerate(feats):
                    hess[i][j] += w * x[fi] * x[fj]
        for i, f in enumerate(feats):
            grad[i] -= ridge[i] * beta[f]
        cov = invert(hess)
        step = [sum(cov[i][j] * grad[j] for j in range(n)) for i in range(n)]
        for i, f in enumerate(feats):
            beta[f] += step[i]
        if max(abs(s) for s in step) < 1e-10:
            break
    return beta, cov


def eta_and_se(
    beta: dict[str, float], cov: list[list[float]], x: dict[str, float], feats: tuple[str, ...]
) -> tuple[float, float, float]:
    """Returns (eta, se, latent_contribution) with latent_budget enforced."""
    explicit = sum(beta[f] * x[f] for f in feats if f not in LATENT)
    raw_latent = sum(beta[f] * x[f] for f in feats if f in LATENT)
    clamped = max(-LATENT_BUDGET, min(LATENT_BUDGET, raw_latent))
    v = [x[f] for f in feats]
    n = len(feats)
    var = sum(v[i] * cov[i][j] * v[j] for i in range(n) for j in range(n))
    return explicit + clamped, math.sqrt(max(var, 0.0)), raw_latent


def band(
    beta: dict[str, float], cov: list[list[float]], x: dict[str, float], feats: tuple[str, ...]
) -> tuple[str, float, float]:
    eta, se, _ = eta_and_se(beta, cov, x, feats)
    half = Z * se
    if abs(eta - logit(THETA)) < half:
        return "flag", sigmoid(eta), half
    return ("approve" if eta > logit(THETA) else "deny"), sigmoid(eta), half


def evaluate(
    beta: dict[str, float],
    cov: list[list[float]],
    feats: tuple[str, ...],
    test: list[dict[str, float]],
) -> tuple[float, float]:
    auto = correct = 0
    for x in test:
        b, _p, _h = band(beta, cov, x, feats)
        if b == "flag":
            continue
        auto += 1
        if (b == "approve") == (sigmoid(true_eta(x)) >= THETA):
            correct += 1
    return auto / len(test), (correct / auto if auto else float("nan"))


def main() -> None:
    rng = random.Random(11)
    train = [sample(rng) for _ in range(400)]
    ys = [label(x, rng) for x in train]
    test = [sample(rng) for _ in range(600)]

    print(f"theta={THETA}  z={Z}  latent_budget={LATENT_BUDGET}")
    print(f"ridge: Tier A={RIDGE_EXPLICIT}  Tier B={RIDGE_LATENT}  (emergence pays for itself)")

    print("\n--- Claim 1: Tier B earns its place ---")
    print(f"{'model':<28} {'auto-decided':>13} {'accuracy':>10}")
    rows = []
    for name, feats in (
        ("Tier A only (explicit 5)", EXPLICIT),
        ("Tier A + Tier B (latent)", EXPLICIT + LATENT),
    ):
        beta, cov = fit(train, ys, feats)
        rate, acc = evaluate(beta, cov, feats, test)
        rows.append((name, feats, beta, cov, rate, acc))
        print(f"{name:<28} {rate:>12.1%} {acc:>10.1%}")
    print(
        "  The operator's true preference includes a latent topic effect the explicit\n"
        "  five cannot see (topic 2 is disliked regardless of its scores), so Tier A\n"
        "  alone is systematically wrong on those and Tier B recovers them."
    )

    _n2, feats2, beta2, cov2, _r2, _a2 = rows[1]

    print("\n--- Claim 2: novelty is flagged for free (the safety property) ---")
    print(f"{'candidate':<34} {'band':>8} {'p':>7} {'half-width':>11}")
    for topic, desc in ((0, "familiar topic 0"), (2, "familiar topic 2"), (4, "UNSEEN topic 4")):
        seen = [sample(rng, topic) for _ in range(80)]
        flagged = 0
        hw = 0.0
        p_mean = 0.0
        for x in seen:
            b, p, h = band(beta2, cov2, x, feats2)
            flagged += b == "flag"
            hw += h
            p_mean += p
        print(
            f"{desc:<34} {f'{flagged / len(seen):.0%} flag':>8} "
            f"{p_mean / len(seen):>7.3f} {hw / len(seen):>11.3f}"
        )
    print(
        "  The unseen region sits far from the training set, so x' Sigma x is large,\n"
        "  the interval is wide, and it lands in the flagged band -- without anyone\n"
        "  writing a novelty rule. 'I have never seen a promotion like this' becomes\n"
        "  a computed reason to ask the human."
    )

    print("\n--- Claim 3: latent_budget bounds unexplainable authority ---")
    strong = {
        "bias": 1.0,
        "judge_score": 1.0,
        "composite": 1.0,
        "is_spec_completion": 1.0,
        "is_feature": 0.0,
        "z1": CENTROIDS[2][0],
        "z2": CENTROIDS[2][1],
        "z3": CENTROIDS[2][2],
        "_topic": 2.0,
    }
    eta, _se, raw = eta_and_se(beta2, cov2, strong, feats2)
    explicit_only = sum(beta2[f] * strong[f] for f in feats2 if f not in LATENT)
    print(f"  strong explicit signal alone      eta = {explicit_only:+.3f}")
    print(f"  raw latent contribution           {raw:+.3f}")
    print(
        f"  after clamp to +/-{LATENT_BUDGET}            {max(-LATENT_BUDGET, min(LATENT_BUDGET, raw)):+.3f}"
    )
    print(f"  final eta                         {eta:+.3f}   (p = {sigmoid(eta):.3f})")
    print(
        "  An unexplainable factor can move a decision near the line; with a modest\n"
        "  budget it cannot override a confident explainable one. Raise the budget to\n"
        "  trade explainability for accuracy -- that trade should be the operator's."
    )

    print("\n--- What the operator would see for a latent dimension ---")
    for zf in LATENT:
        contrib = [(abs(beta2[zf] * x[zf]), x) for x in train]
        contrib.sort(key=lambda t: t[0], reverse=True)
        topics = [int(x["_topic"]) for _, x in contrib[:5]]
        direction = "deny" if beta2[zf] < 0 else "approve"
        print(
            f"  {zf}: weight {beta2[zf]:+.3f} -> pushes toward {direction};"
            f" top exemplars come from topics {topics}"
        )
    print(
        "  Unnamable, but exhibitable: show those exemplar diffs and the operator can\n"
        "  trust, veto, or NAME the pattern -- graduating it into Tier A (§9.6 rule 4)."
    )


if __name__ == "__main__":
    main()
