from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Fold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def expanding_walk_forward(n: int, min_train: int, test_size: int) -> list[Fold]:
    if min_train <= 0 or test_size <= 0:
        raise ValueError("sizes must be positive")
    folds: list[Fold] = []
    train_end = min_train
    while train_end < n:
        test_end = min(train_end + test_size, n)
        folds.append(Fold(0, train_end, train_end, test_end))
        train_end = test_end
    return folds
