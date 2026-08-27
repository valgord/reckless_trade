from research.validation.metrics import max_drawdown, sharpe
from research.validation.walk_forward import expanding_walk_forward


def test_max_drawdown():
    assert round(max_drawdown([100, 120, 90, 110]), 2) == -0.25


def test_sharpe_positive():
    assert sharpe([0.01, 0.02, 0.015, 0.01], 365) > 0


def test_walk_forward_no_overlap_with_future():
    folds = expanding_walk_forward(1000, 500, 100)
    assert folds[0].train_end == folds[0].test_start
    assert folds[-1].test_end == 1000
