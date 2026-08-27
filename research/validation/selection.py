from __future__ import annotations

import itertools
import math
from statistics import NormalDist, mean, pstdev


def deflated_sharpe_probability(returns: list[float], trials: int) -> float:
    """Probability that Sharpe exceeds the multiple-testing expected maximum.

    Implements the Bailey/Lopez de Prado deflated Sharpe construction using
    sample skewness and kurtosis. Returns zero when the sample is degenerate.
    """
    if len(returns) < 3 or trials <= 0:
        return 0.0
    sigma = pstdev(returns)
    if sigma == 0:
        return 0.0
    n = len(returns)
    sr = mean(returns) / sigma
    centered = [(value - mean(returns)) / sigma for value in returns]
    skew = mean([value**3 for value in centered])
    kurtosis = mean([value**4 for value in centered])
    variance = max((1 - skew * sr + ((kurtosis - 1) / 4) * sr**2) / (n - 1), 1e-12)
    normal = NormalDist()
    euler_gamma = 0.5772156649015329
    expected_max = (
        math.sqrt(variance)
        * ((1 - euler_gamma) * normal.inv_cdf(1 - 1 / trials) + euler_gamma * normal.inv_cdf(1 - 1 / (trials * math.e)))
        if trials > 1
        else 0.0
    )
    return normal.cdf((sr - expected_max) / math.sqrt(variance))


def probability_of_backtest_overfitting(candidate_block_returns: dict[str, list[float]]) -> float:
    """Estimate PBO with combinatorially symmetric cross-validation blocks."""
    if len(candidate_block_returns) < 2:
        return 0.0
    lengths = {len(values) for values in candidate_block_returns.values()}
    if len(lengths) != 1:
        raise ValueError("candidate block return lengths must match")
    blocks = lengths.pop()
    if blocks < 4 or blocks % 2:
        raise ValueError("PBO requires an even number of at least four blocks")

    names = sorted(candidate_block_returns)
    overfit = 0
    combinations = 0
    for train in itertools.combinations(range(blocks), blocks // 2):
        test = set(range(blocks)) - set(train)
        train_scores = {
            name: sum(math.log1p(candidate_block_returns[name][index]) for index in train) for name in names
        }
        selected = max(names, key=lambda name: (train_scores[name], name))
        test_scores = {name: sum(math.log1p(candidate_block_returns[name][index]) for index in test) for name in names}
        selected_rank = sorted(test_scores, key=lambda name: (test_scores[name], name)).index(selected)
        percentile = (selected_rank + 1) / len(names)
        overfit += percentile <= 0.5
        combinations += 1
    return overfit / combinations
