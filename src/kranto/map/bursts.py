"""Is a lineage moving? Burst states and significance over new arrivals.

A lineage's trajectory records, per snapshot, how many observations arrived
in the library since the previous snapshot (``d``), how many of those landed
in the lineage (``r``), and how many the previous snapshot's per-source rates
predicted (``e``). Two questions are asked of that series.

Is the lineage in a burst? Kleinberg (2002), "Bursty and Hierarchical
Structure in Streams", section 4, the batched two-state model. State 0 emits
arrivals at the lineage's long-run share ``p0 = sum(r) / sum(d)``; state 1 at
``p1 = s * p0``. Each snapshot costs the negative log-likelihood of its
``(r, d)`` under the state's rate, and moving up into the burst state costs
``gamma * ln(n)`` for a series of ``n`` snapshots; moving down is free. The
cheapest state sequence (Viterbi) gives a state per snapshot. The transition
cost is what stops one lucky snapshot from reading as a burst.

Is this snapshot's count more than the sources explain? A one-sided binomial
test of ``r`` against ``Binomial(d, e / d)``, with Benjamini-Hochberg
correction across the lineages of one snapshot, since every snapshot tests
all of them at once. The burst model knows nothing about which sources were
running; the test is what keeps "one source posted more" from reading as a
theme gaining ground.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from scipy.stats import binom

BURST_SCALE = 2.0
TRANSITION_GAMMA = 1.0
SIGNIFICANCE = 0.05
# The cross-source rule's form (principle 12), applied to the new stories' origins.
ORIGIN_MAX_SHARE = 0.70


def burst_rate(p0: float, s: float = BURST_SCALE) -> float:
    """``s * p0``, capped below 1 by shrinking the odds of *not* arriving by ``s``.

    Kleinberg's model needs ``p1 < 1``. For the usual small ``p0`` the cap
    never binds (p0 = 0.1 gives p1 = 0.2); for a lineage holding most of the
    library it keeps the burst state reachable: p0 = 0.6 gives p1 = 0.8, not 1.
    """
    return min(s * p0, 1.0 - (1.0 - p0) / s)


def _cost(r: int, d: int, p: float) -> float:
    """Negative log-likelihood of r of d under rate p, without the binomial coefficient
    (it is the same in both states, so it cannot change which state is cheaper)."""
    return -(r * math.log(p) + (d - r) * math.log1p(-p))


def burst_states(
    series: Sequence[tuple[int, int]],
    *,
    s: float = BURST_SCALE,
    gamma: float = TRANSITION_GAMMA,
) -> list[int]:
    """Viterbi state (0 or 1) per ``(r, d)`` point. Ties go to the base state."""
    n = len(series)
    if n == 0:
        return []
    total_r = sum(r for r, _ in series)
    total_d = sum(d for _, d in series)
    if total_d == 0 or total_r == 0 or total_r >= total_d:
        return [0] * n
    p0 = total_r / total_d
    rates = (p0, burst_rate(p0, s))
    up = gamma * math.log(n)

    # cost[i]: cheapest cost of a path ending in state i; back[t][i]: its previous state.
    cost = [0.0, math.inf]  # the process starts in the base state
    back: list[tuple[int, int]] = []
    for r, d in series:
        emit = [_cost(r, d, p) for p in rates]
        stay0, from1 = cost[0], cost[1]
        prev0 = 0 if stay0 <= from1 else 1
        stay1, from0 = cost[1], cost[0] + up
        prev1 = 1 if stay1 < from0 else 0
        cost = [min(stay0, from1) + emit[0], min(stay1, from0) + emit[1]]
        back.append((prev0, prev1))
    state = 0 if cost[0] <= cost[1] else 1
    path = [state]
    for prev in reversed(back[1:]):
        state = prev[state]
        path.append(state)
    return path[::-1]


def binomial_p_value(r: int, d: int, expected: float) -> float | None:
    """P(X >= r) for X ~ Binomial(d, expected / d). None when there is nothing to test."""
    if d <= 0:
        return None
    p = min(max(expected / d, 0.0), 1.0)
    if r <= 0:
        return 1.0
    return float(binom.sf(r - 1, d, p))


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """BH-adjusted q-values in input order; None entries are skipped and stay None."""
    indexed = [(p, i) for i, p in enumerate(p_values) if p is not None]
    m = len(indexed)
    out: list[float | None] = [None] * len(p_values)
    running = 1.0
    for rank, (p, i) in reversed(list(enumerate(sorted(indexed), 1))):
        running = min(running, p * m / rank)
        out[i] = min(1.0, running)
    return out


def entered_burst(trajectory: Sequence[dict]) -> bool:
    """The latest point is in the burst state and the one before it was not.

    Compared with the state recorded at the previous snapshot, not with a
    re-smoothed path: a lineage already reported as bursting is not reported
    again because more data moved where the burst began.
    """
    if not trajectory or trajectory[-1].get("burst") != 1:
        return False
    return len(trajectory) < 2 or trajectory[-2].get("burst") != 1


def rising(trajectory: Sequence[dict], cross_source: bool) -> bool:
    """Entered a burst this snapshot, beyond what the sources explain, cross-source,
    and with no single origin behind more than 70% of the new stories.

    One definition serves both the idea-card "rising" path and burst strike
    candidates. Points written before #35 have no origin share and are not
    held back by it.
    """
    if not cross_source or not entered_burst(trajectory):
        return False
    origin_share = trajectory[-1].get("new_max_origin_share")
    if origin_share is not None and origin_share > ORIGIN_MAX_SHARE:
        return False
    q = trajectory[-1].get("q_value")
    return q is not None and q < SIGNIFICANCE
