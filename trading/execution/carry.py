from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class CarryPhase(StrEnum):
    BLOCKED = "blocked"
    FLAT_READY = "flat_ready"
    HEDGED = "hedged"
    REPAIR_REQUIRED = "repair_required"
    CLOSE_REQUIRED = "close_required"


@dataclass(frozen=True, slots=True)
class CarryGuardConfig:
    target_notional_usdt: float = 10.0
    minimum_free_reserve_usdt: float = 10.0
    maintenance_margin_rate: float = 0.05
    minimum_margin_ratio: float = 3.0
    maximum_quantity_mismatch_fraction: float = 0.02

    def __post_init__(self) -> None:
        positive = {
            "target_notional_usdt": self.target_notional_usdt,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "minimum_margin_ratio": self.minimum_margin_ratio,
            "maximum_quantity_mismatch_fraction": self.maximum_quantity_mismatch_fraction,
        }
        if any(not math.isfinite(value) or value <= 0 for value in positive.values()):
            raise ValueError("carry guard limits must be finite and positive")
        if not math.isfinite(self.minimum_free_reserve_usdt) or self.minimum_free_reserve_usdt < 0:
            raise ValueError("minimum_free_reserve_usdt must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CarryOwnership:
    spot_quantity: float = 0.0
    perp_quantity: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.spot_quantity) or self.spot_quantity < 0:
            raise ValueError("owned Spot quantity must be finite and non-negative")
        if not math.isfinite(self.perp_quantity) or self.perp_quantity > 0:
            raise ValueError("owned perpetual quantity must be finite and non-positive")


def read_carry_ownership(path: Path) -> CarryOwnership:
    if not path.exists():
        return CarryOwnership()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported carry ownership ledger schema")
    return CarryOwnership(float(payload["spot_quantity"]), float(payload["perp_quantity"]))


def write_carry_ownership(path: Path, ownership: CarryOwnership) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spot_quantity": ownership.spot_quantity,
                "perp_quantity": ownership.perp_quantity,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(frozen=True, slots=True)
class CarryAccountSnapshot:
    reconciliation_complete: bool
    spot_quantity: float
    perp_quantity: float
    spot_price: float | None
    perp_price: float | None
    free_usdt: float
    open_orders: int = 0
    minimum_quantity: float = 0.0
    quantity_increment: float = 0.0

    def __post_init__(self) -> None:
        numeric = (
            self.spot_quantity,
            self.perp_quantity,
            self.free_usdt,
            self.minimum_quantity,
            self.quantity_increment,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("carry snapshot values must be finite")
        if self.free_usdt < 0 or self.open_orders < 0 or self.minimum_quantity < 0 or self.quantity_increment < 0:
            raise ValueError("carry balances and order counts cannot be negative")
        for price in (self.spot_price, self.perp_price):
            if price is not None and (not math.isfinite(price) or price <= 0):
                raise ValueError("carry prices must be finite and positive")


@dataclass(frozen=True, slots=True)
class CarryLegAction:
    instrument: str
    side: str
    quantity: float
    reduce_only: bool
    risk_reducing: bool
    group: str


@dataclass(frozen=True, slots=True)
class CarryGuardDecision:
    phase: CarryPhase
    reasons: tuple[str, ...]
    actions: tuple[CarryLegAction, ...]
    target_quantity: float
    coin_delta: float
    mismatch_fraction: float
    margin_ratio_proxy: float | None

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["phase"] = self.phase.value
        return payload


@dataclass(frozen=True, slots=True)
class CarryPairFillDecision:
    complete: bool
    spot_unwind_quantity: float
    perp_unwind_quantity: float


def evaluate_pair_fills(target_quantity: float, spot_filled: float, perp_filled: float) -> CarryPairFillDecision:
    values = (target_quantity, spot_filled, perp_filled)
    if any(not math.isfinite(value) or value < 0 for value in values) or target_quantity <= 0:
        raise ValueError("pair fill quantities must be finite and target must be positive")
    tolerance = max(target_quantity * 1e-9, 1e-12)
    complete = abs(spot_filled - target_quantity) <= tolerance and abs(perp_filled - target_quantity) <= tolerance
    return CarryPairFillDecision(
        complete=complete,
        spot_unwind_quantity=0.0 if complete else spot_filled,
        perp_unwind_quantity=0.0 if complete else perp_filled,
    )


class CarryExecutionGuard:
    """Evaluates a two-leg carry position without submitting orders."""

    def __init__(
        self,
        config: CarryGuardConfig,
        spot_instrument: str = "BTCUSDT-SPOT.BYBIT",
        perp_instrument: str = "BTCUSDT-LINEAR.BYBIT",
    ) -> None:
        self.config = config
        self.spot_instrument = spot_instrument
        self.perp_instrument = perp_instrument

    def evaluate(self, snapshot: CarryAccountSnapshot) -> CarryGuardDecision:
        if not snapshot.reconciliation_complete:
            return self._decision(CarryPhase.BLOCKED, snapshot, ("startup reconciliation is incomplete",))
        if snapshot.open_orders:
            return self._decision(CarryPhase.BLOCKED, snapshot, ("open orders must be reconciled first",))
        if snapshot.spot_price is None or snapshot.perp_price is None:
            return self._decision(CarryPhase.BLOCKED, snapshot, ("both leg prices are required",))

        target_quantity = self._target_quantity(snapshot)
        if target_quantity < snapshot.minimum_quantity:
            minimum_notional = snapshot.minimum_quantity * max(snapshot.spot_price, snapshot.perp_price)
            reason = (
                f"minimum shared quantity {snapshot.minimum_quantity:g} requires about "
                f"{minimum_notional:.2f} USDT per leg, above the configured cap"
            )
            return self._decision(CarryPhase.BLOCKED, snapshot, (reason,))
        coin_delta = snapshot.spot_quantity + snapshot.perp_quantity
        gross_quantity = max(abs(snapshot.spot_quantity), abs(snapshot.perp_quantity))
        mismatch_fraction = abs(coin_delta) / max(gross_quantity, target_quantity)
        margin_requirement = abs(snapshot.perp_quantity) * snapshot.perp_price * self.config.maintenance_margin_rate
        margin_ratio = snapshot.free_usdt / margin_requirement if margin_requirement > 0 else None

        if snapshot.spot_quantity < 0 or snapshot.perp_quantity > 0:
            actions = self._close_invalid_sides(snapshot)
            return CarryGuardDecision(
                CarryPhase.REPAIR_REQUIRED,
                ("carry legs have an invalid direction",),
                actions,
                target_quantity,
                coin_delta,
                mismatch_fraction,
                margin_ratio,
            )

        is_flat = abs(snapshot.spot_quantity) < 1e-12 and abs(snapshot.perp_quantity) < 1e-12
        if is_flat:
            required = 2 * self.config.target_notional_usdt + self.config.minimum_free_reserve_usdt
            if snapshot.free_usdt < required:
                reason = f"free USDT {snapshot.free_usdt:.2f} is below required {required:.2f}"
                return self._decision(CarryPhase.BLOCKED, snapshot, (reason,))
            actions = (
                CarryLegAction(self.spot_instrument, "buy", target_quantity, False, False, "open_pair"),
                CarryLegAction(self.perp_instrument, "sell", target_quantity, False, False, "open_pair"),
            )
            return CarryGuardDecision(
                CarryPhase.FLAT_READY,
                (),
                actions,
                target_quantity,
                0.0,
                0.0,
                None,
            )

        if margin_ratio is not None and margin_ratio < self.config.minimum_margin_ratio:
            return CarryGuardDecision(
                CarryPhase.CLOSE_REQUIRED,
                ("margin ratio proxy is below the configured minimum",),
                self._close_both(snapshot),
                target_quantity,
                coin_delta,
                mismatch_fraction,
                margin_ratio,
            )

        spot_notional = snapshot.spot_quantity * snapshot.spot_price
        perp_notional = abs(snapshot.perp_quantity) * snapshot.perp_price
        if max(spot_notional, perp_notional) > self.config.target_notional_usdt * (
            1 + self.config.maximum_quantity_mismatch_fraction
        ):
            actions = self._reduce_to_target(snapshot, target_quantity)
            return CarryGuardDecision(
                CarryPhase.REPAIR_REQUIRED,
                ("position notional exceeds the configured carry cap",),
                actions,
                target_quantity,
                coin_delta,
                mismatch_fraction,
                margin_ratio,
            )

        if mismatch_fraction > self.config.maximum_quantity_mismatch_fraction:
            actions = self._reduce_excess_delta(snapshot, coin_delta)
            return CarryGuardDecision(
                CarryPhase.REPAIR_REQUIRED,
                ("spot and perpetual quantities are not delta neutral",),
                actions,
                target_quantity,
                coin_delta,
                mismatch_fraction,
                margin_ratio,
            )

        return CarryGuardDecision(
            CarryPhase.HEDGED,
            (),
            (),
            target_quantity,
            coin_delta,
            mismatch_fraction,
            margin_ratio,
        )

    def _decision(
        self,
        phase: CarryPhase,
        snapshot: CarryAccountSnapshot,
        reasons: tuple[str, ...],
    ) -> CarryGuardDecision:
        target = self._target_quantity(snapshot)
        delta = snapshot.spot_quantity + snapshot.perp_quantity
        gross = max(abs(snapshot.spot_quantity), abs(snapshot.perp_quantity), target)
        return CarryGuardDecision(phase, reasons, (), target, delta, abs(delta) / gross if gross else 0.0, None)

    def _target_quantity(self, snapshot: CarryAccountSnapshot) -> float:
        if not snapshot.spot_price:
            return 0.0
        raw = self.config.target_notional_usdt / snapshot.spot_price
        if snapshot.quantity_increment <= 0:
            return raw
        steps = math.floor((raw + 1e-15) / snapshot.quantity_increment)
        return steps * snapshot.quantity_increment

    def _reduce_excess_delta(
        self,
        snapshot: CarryAccountSnapshot,
        coin_delta: float,
    ) -> tuple[CarryLegAction, ...]:
        if coin_delta > 0:
            quantity = min(coin_delta, snapshot.spot_quantity)
            return (CarryLegAction(self.spot_instrument, "sell", quantity, False, True, "repair_pair"),)
        quantity = min(abs(coin_delta), abs(snapshot.perp_quantity))
        return (CarryLegAction(self.perp_instrument, "buy", quantity, True, True, "repair_pair"),)

    def _reduce_to_target(
        self,
        snapshot: CarryAccountSnapshot,
        target_quantity: float,
    ) -> tuple[CarryLegAction, ...]:
        actions = []
        if snapshot.spot_quantity > target_quantity:
            actions.append(
                CarryLegAction(
                    self.spot_instrument,
                    "sell",
                    snapshot.spot_quantity - target_quantity,
                    False,
                    True,
                    "reduce_pair",
                )
            )
        if abs(snapshot.perp_quantity) > target_quantity:
            actions.append(
                CarryLegAction(
                    self.perp_instrument,
                    "buy",
                    abs(snapshot.perp_quantity) - target_quantity,
                    True,
                    True,
                    "reduce_pair",
                )
            )
        return tuple(actions)

    def _close_invalid_sides(self, snapshot: CarryAccountSnapshot) -> tuple[CarryLegAction, ...]:
        actions = []
        if snapshot.spot_quantity < 0:
            actions.append(
                CarryLegAction(self.spot_instrument, "buy", abs(snapshot.spot_quantity), False, True, "repair_pair")
            )
        if snapshot.perp_quantity > 0:
            actions.append(
                CarryLegAction(self.perp_instrument, "sell", snapshot.perp_quantity, True, True, "repair_pair")
            )
        return tuple(actions)

    def _close_both(self, snapshot: CarryAccountSnapshot) -> tuple[CarryLegAction, ...]:
        actions = []
        if snapshot.spot_quantity > 0:
            actions.append(
                CarryLegAction(self.spot_instrument, "sell", snapshot.spot_quantity, False, True, "close_pair")
            )
        if snapshot.perp_quantity < 0:
            actions.append(
                CarryLegAction(self.perp_instrument, "buy", abs(snapshot.perp_quantity), True, True, "close_pair")
            )
        return tuple(actions)
