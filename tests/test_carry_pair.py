from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.trader.carry_pair import (
    CARRY_PAIR_CONFIRMATION,
    CarryPairError,
    CarryPairExecutor,
    validate_pair_confirmation,
)
from trading.execution.carry import CarryOwnership


def test_demo_pair_requires_exact_confirmation() -> None:
    with pytest.raises(CarryPairError, match="locked"):
        validate_pair_confirmation("yes")

    validate_pair_confirmation(CARRY_PAIR_CONFIRMATION)


def test_close_requires_equal_owned_legs_and_matching_short() -> None:
    ownership = CarryOwnership(0.001, -0.001)

    assert CarryPairExecutor._close_quantity(ownership, -0.001) == Decimal("0.001")
    with pytest.raises(CarryPairError, match="does not match"):
        CarryPairExecutor._close_quantity(ownership, 0.001)
    with pytest.raises(CarryPairError, match="no open"):
        CarryPairExecutor._close_quantity(CarryOwnership(), 0.0)


@pytest.mark.asyncio
async def test_executor_rejects_read_only_key() -> None:
    client = SimpleNamespace(get_account_details=_async_result(SimpleNamespace(read_only=1)))
    executor = CarryPairExecutor(client, SimpleNamespace(), {}, 0.01)

    with pytest.raises(CarryPairError, match="read-only"):
        await executor.execute("open")


def _async_result(value):
    async def result():
        return value

    return result
