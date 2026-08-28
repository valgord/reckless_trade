from research.attribution.directional import attribute_directional_candidate
from research.backtests.simple_engine import CostModel
from research.experiments.m3_runner import Candidate, PreparedCandidate


def test_directional_attribution_separates_gross_edge_and_cost_drag():
    prepared = PreparedCandidate(
        Candidate("test", ("trend",), min_hold_bars=0),
        [0.5, 0.5, 0.0, 0.0],
        ["trend_up"] * 4,
        {},
    )

    report = attribute_directional_candidate(prepared, [100.0, 110.0, 121.0, 121.0], CostModel(10, 0, 0))

    assert report["gross_return_usdt"] > report["net_return_usdt"] > 0
    assert report["cost_drag"] > 0
    assert report["closed_trades"] == 1
    assert report["win_rate_after_estimated_cost"] == 1.0


def test_directional_attribution_marks_negative_raw_edge():
    prepared = PreparedCandidate(
        Candidate("test", ("trend",), min_hold_bars=0),
        [0.5, 0.5, 0.0, 0.0],
        ["trend_up"] * 4,
        {},
    )

    report = attribute_directional_candidate(prepared, [100.0, 90.0, 80.0, 80.0], CostModel(0, 0, 0))

    assert report["gross_edge_positive"] is False
    assert report["net_return_usdt"] < 0
