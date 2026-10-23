"""The mixture: sleeping experts over the programs that forecast each target.

This is the specialists algorithm of Freund, Schapire, Singer and Warmuth
(1997).  Targets are taken in `target_order`.  At a target with reference week
`r`, the programs that forecast it are *awake*; each gets weight proportional to
`exp(cur_m(r) / tau)`, where `cur_m(r)` is its advantage over the targets that
had resolved by issue `r`, each discounted by `2^(-(r - target_week) / half_life)`.
The mixture forecasts with those weights, and each awake program's advantage at
the target is its log score minus the mixture's.  A program that is asleep
(did not forecast) neither gains nor loses, so a newcomer starts at zero
against incumbents that have earned their weight.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
from scipy.special import logsumexp, softmax

from scienceme.model import Frozen, Target
from scienceme.scoring import PointScore, ResolvedTarget, target_order


class MixtureStep(Frozen):
    """The mixture at one target: the awake programs' weights and the mixture's score."""

    target: Target
    weights: dict[str, float]
    score: PointScore


class Advantages(Frozen):
    """Each program's advantage over the mixture: summed (`cumulative`) and discounted to `as_of` (`current`)."""

    cumulative: dict[str, float]
    current: dict[str, float]
    steps: tuple[MixtureStep, ...]


def normalized_weights(advantage: Mapping[str, float], awake: Iterable[str], tau: float) -> dict[str, float]:
    """Weights over `awake` proportional to `exp(advantage / tau)`; a program missing from `advantage` counts 0.

    Empty when nobody is awake.  Programs in `advantage` that are not awake get no weight.
    """
    names = sorted(set(awake))
    if not names:
        return {}
    w = softmax(np.array([advantage.get(m, 0.0) for m in names]) / tau)
    return {m: float(x) for m, x in zip(names, w)}


def _discounted(
    advantages: Iterable[tuple[Target, Mapping[str, float]]], at: int, half_life: float
) -> dict[str, float]:
    """Each program's advantages summed, each discounted to issue `at` by `2^(-(at - target_week) / half_life)`.

    An infinite `half_life` never forgets: every factor is 1.  Keyed in name order.
    """
    total: defaultdict[str, float] = defaultdict(float)
    for target, a in advantages:
        factor = 2.0 ** (-(at - target.target_week) / half_life)
        for m, v in a.items():
            total[m] += factor * v
    return dict(sorted(total.items()))


def _mix(k: ResolvedTarget, weights: Mapping[str, float]) -> PointScore:
    """The score of the `weights` mixture of the forecasts at `k`."""
    names = list(weights)
    w = np.array([weights[m] for m in names])
    scores = [k.scores[m] for m in names]
    return PointScore(
        log_p=float(logsumexp([s.log_p for s in scores], b=w)),
        cdf_below=float(w @ np.array([s.cdf_below for s in scores])),
        cdf_at=float(w @ np.array([s.cdf_at for s in scores])),
    )


def run_mixture(resolved: Sequence[ResolvedTarget], tau: float, half_life: float, as_of: int) -> Advantages:
    """Run the sleeping-experts mixture over `resolved` (taken in `target_order`), discounting to issue `as_of`."""
    ordered = sorted(resolved, key=lambda k: target_order(k.target))
    done: list[tuple[Target, dict[str, float]]] = []
    steps: list[MixtureStep] = []
    week: int | None = None
    cur: dict[str, float] = {}
    for k in ordered:
        r = k.target.reference_week
        if r != week:
            # every target resolved by issue r has reference week < r, so it is already in `done`
            week = r
            cur = _discounted(((t, a) for t, a in done if t.resolution_issue <= r), r, half_life)
        weights = normalized_weights(cur, k.scores, tau)
        mixture = _mix(k, weights)
        done.append((k.target, {m: s.log_p - mixture.log_p for m, s in k.scores.items()}))
        steps.append(MixtureStep(target=k.target, weights=weights, score=mixture))
    return Advantages(
        cumulative=_discounted(done, as_of, math.inf),
        current=_discounted(done, as_of, half_life),
        steps=tuple(steps),
    )


def regime_tv(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Total variation distance between two weight tables: `0.5 * sum |a - b|` over the union of keys."""
    return 0.5 * sum(abs(a.get(m, 0.0) - b.get(m, 0.0)) for m in a.keys() | b.keys())
