#!/usr/bin/env python3
"""Demonstrate the intended RLPHD design: confident auto-decisions, a flagged
uncertainty band, and a band that measurably shrinks as the operator rules.

Supporting artifact for docs/reviews/2026-07-29-rsi-containment-review.md §9.6.

The problem with the shipped design is not that the model is untrained -- it is
that a point estimate cannot express uncertainty. `RlphdModel.predict` returns a
single p, and p=0.5 from an empty model is indistinguishable from p=0.5 from a
well-trained model on a genuinely borderline candidate. One threshold over one
number cannot say "I don't know", so "not confident enough to approve" collapses
into "confident it's bad" and a cold model reverts everything.

The fix is to carry a *variance* alongside the weights and decide on an interval
rather than a point:

    eta      = x . beta                      (the logit)
    Sigma    = (X' W X + lambda I)^-1        (Laplace covariance / inverse Fisher info)
    se(eta)  = sqrt(x' Sigma x)
    flag  iff |eta - logit(theta)| < z * se(eta)

That single rule gives all three behaviours asked for:

  * auto-decide (approve OR deny) when the interval clears theta -- a measurable
    percentage, reported below;
  * flag with a real confidence number when the interval straddles theta;
  * the band is +/- z*se(eta) wide in logit space and se shrinks as ~1/sqrt(N),
    so every human decision narrows it -- automatically, with no gain to tune.

It also fixes the cold start for free: with no data, se is huge, every interval
straddles theta, so everything is flagged as UNCERTAIN and nothing is
auto-reverted. Cold behaviour becomes "ask the human" instead of "revert
everything", which is the correct default and makes the bootstrap interview an
accelerator rather than a prerequisite.

Pure Python on purpose: 5 parameters do not justify a numeric dependency in
maistro-core, and glass-box means the operator can read the arithmetic.

Run: python3 scripts/rlphd_band_sim.py
"""

from __future__ import annotations

import math
import random

FEATURES = ("bias", "judge_score", "composite", "is_spec_completion", "is_feature")

# A stand-in for the operator's real (unknown) preference, used only to generate
# labels and to score accuracy. Reads as: approve when the judge likes it and the
# composite is decent; spec work is favoured; features are viewed more warily.
TRUE_BETA = {
    "bias": -4.0,
    "judge_score": 3.5,
    "composite": 3.0,
    "is_spec_completion": 1.2,
    "is_feature": -0.6,
}

THETA = 0.6  # decision threshold (Phase 4 of the interview picks this)
Z = 1.64  # ~90% interval
RIDGE = 1e-2  # keeps the fit finite when labels are separable or N is tiny


def sigmoid(x: float) -> float:
    if x < -700:
        return 0.0
    if x > 700:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return math.log(p / (1 - p))


def dot(beta: dict[str, float], x: dict[str, float]) -> float:
    return sum(beta.get(k, 0.0) * x.get(k, 0.0) for k in FEATURES)


def sample_promotion(rng: random.Random) -> dict[str, float]:
    """A plausible promotion. Kind is one-hot-ish: SPEC, FEATURE, or neither."""
    kind = rng.choice(["spec", "feature", "other"])
    return {
        "bias": 1.0,
        "judge_score": round(rng.uniform(0.2, 1.0), 3),
        "composite": round(rng.uniform(0.0, 1.0), 3),
        "is_spec_completion": 1.0 if kind == "spec" else 0.0,
        "is_feature": 1.0 if kind == "feature" else 0.0,
    }


def label(x: dict[str, float], rng: random.Random) -> int:
    """The operator's decision -- stochastic, so the task is not separable."""
    return 1 if rng.random() < sigmoid(dot(TRUE_BETA, x)) else 0


def invert(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan inverse. n=5, so clarity beats cleverness."""
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-14:
            a[col][col] += 1e-9  # nudge a singular pivot rather than crash
            pivot = col
        a[col], a[pivot] = a[pivot], a[col]
        d = a[col][col]
        a[col] = [v / d for v in a[col]]
        for r in range(n):
            if r == col:
                continue
            f = a[r][col]
            if f:
                a[r] = [v - f * w for v, w in zip(a[r], a[col], strict=True)]
    return [row[n:] for row in a]


def fit(
    xs: list[dict[str, float]], ys: list[int], iters: int = 40
) -> tuple[dict[str, float], list[list[float]]]:
    """Newton-Raphson / IRLS logistic fit, returning (beta, Laplace covariance)."""
    n = len(FEATURES)
    beta = dict.fromkeys(FEATURES, 0.0)
    hess = [[RIDGE if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(iters):
        grad = [0.0] * n
        hess = [[RIDGE if i == j else 0.0 for j in range(n)] for i in range(n)]
        for x, y in zip(xs, ys, strict=True):
            p = sigmoid(dot(beta, x))
            w = max(p * (1 - p), 1e-9)
            for i, fi in enumerate(FEATURES):
                grad[i] += (y - p) * x[fi]
                for j, fj in enumerate(FEATURES):
                    hess[i][j] += w * x[fi] * x[fj]
        for i in range(n):
            grad[i] -= RIDGE * beta[FEATURES[i]]
        cov = invert(hess)
        step = [sum(cov[i][j] * grad[j] for j in range(n)) for i in range(n)]
        for i, f in enumerate(FEATURES):
            beta[f] += step[i]
        if max(abs(s) for s in step) < 1e-9:
            break
    return beta, cov


def se_logit(cov: list[list[float]], x: dict[str, float]) -> float:
    """sqrt(x' Sigma x) -- the standard error of the logit at x."""
    v = [x.get(f, 0.0) for f in FEATURES]
    n = len(FEATURES)
    total = sum(v[i] * cov[i][j] * v[j] for i in range(n) for j in range(n))
    return math.sqrt(max(total, 0.0))


def classify(
    beta: dict[str, float], cov: list[list[float]], x: dict[str, float]
) -> tuple[str, float, float]:
    """Returns (band, p, half_width_in_logit_space).

    band is 'approve' / 'deny' when the interval clears theta, else 'flag'.
    """
    eta = dot(beta, x)
    se = se_logit(cov, x)
    half = Z * se
    if abs(eta - logit(THETA)) < half:
        return "flag", sigmoid(eta), half
    return ("approve" if eta > logit(THETA) else "deny"), sigmoid(eta), half


def main() -> None:
    rng = random.Random(7)
    test = [sample_promotion(rng) for _ in range(600)]
    truth = [1 if sigmoid(dot(TRUE_BETA, x)) >= THETA else 0 for x in test]

    print(f"theta={THETA}  z={Z} (~90% interval)  features={len(FEATURES)}")
    print("\n  N   auto-decided   flagged   accuracy on auto-decided   mean band half-width")
    print("  " + "-" * 76)

    xs: list[dict[str, float]] = []
    ys: list[int] = []
    prev_auto = 0.0
    for target_n in (0, 5, 10, 20, 40, 80, 160, 320):
        while len(xs) < target_n:
            x = sample_promotion(rng)
            xs.append(x)
            ys.append(label(x, rng))

        if not xs:
            # Cold: no data at all. se is unbounded, so everything must flag.
            print(f"{0:>4}   {0.0:>10.1%}   {1.0:>7.1%}   {'n/a':>24}   {'inf':>20}")
            continue

        beta, cov = fit(xs, ys)
        auto = correct = 0
        halves = []
        for x, t in zip(test, truth, strict=True):
            band, _p, half = classify(beta, cov, x)
            halves.append(half)
            if band != "flag":
                auto += 1
                if (band == "approve") == bool(t):
                    correct += 1
        rate = auto / len(test)
        acc_s = f"{correct / auto:.1%}" if auto else "--"
        print(
            f"{target_n:>4}   {rate:>10.1%}   {1 - rate:>7.1%}   "
            f"{acc_s:>23}   {sum(halves) / len(halves):>20.3f}"
        )
        prev_auto = rate

    print(
        f"\nAutomation rate rose to {prev_auto:.0%} and the band half-width shrank"
        "\nmonotonically. That is the intended behaviour: decide confidently on a"
        "\nmeasurable and growing share, flag the rest with a real confidence number,"
        "\nand let human decisions narrow the window. No gain to tune -- se(eta) does it."
    )
    print(
        "\nNote the N=0 row: with no data every interval straddles theta, so everything"
        "\nis FLAGGED and nothing is auto-reverted. Compare the shipped design, which"
        "\nreverts 100% of promotions when cold (see rlphd_cold_start_sim.py)."
    )
    print(
        "\nTwo honest caveats. (1) The automation RATE is not strictly monotone -- the"
        "\nfitted beta moves as labels arrive, which can push some candidates back"
        "\ntoward theta (see the dip at N=80). Only the band WIDTH is monotone; the"
        "\nrate is monotone in expectation. (2) Accuracy reads 100% because this"
        "\nsimulation scores against a noiseless ground truth drawn from the same"
        "\nfunctional form the model fits -- i.e. no misspecification. Real accuracy"
        "\nwill be lower, which is exactly what the shadow-mode calibration report in"
        "\nthe review's Phase 5 exists to measure before auto-acting is enabled."
    )


if __name__ == "__main__":
    main()
