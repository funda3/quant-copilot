"""
Minimal portfolio aggregation primitives for position-level PV results.

This module intentionally stays small and explicit for v1 portfolio workflows.
It does not price instruments. It only classifies and aggregates already-priced
position PV values.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ASSET_CLASS_BY_INSTRUMENT: dict[str, str] = {
    "bond": "rates",
    "fra": "rates",
    "fx_forward": "fx",
    "fx_swap": "fx",
    "fx_option": "fx",
    "equity_option": "equity",
}


@dataclass(frozen=True)
class PositionPV:
    """Normalized position PV used by portfolio aggregation."""

    position_id: str
    instrument_type: str
    pv: float
    status: str
    asset_class: str | None = None


@dataclass(frozen=True)
class PortfolioAggregation:
    """Aggregated portfolio PV totals and groupings."""

    total_pv: float
    grouped_pv_by_instrument_type: dict[str, float]
    grouped_pv_by_asset_class: dict[str, float]
    position_count: int
    valued_count: int
    unsupported_count: int


def infer_asset_class(instrument_type: str) -> str:
    """Map an instrument type to a coarse v1 asset class label."""
    return ASSET_CLASS_BY_INSTRUMENT.get(str(instrument_type).lower(), "other")


def aggregate_position_pvs(positions: Iterable[PositionPV]) -> PortfolioAggregation:
    """
    Aggregate normalized position PV rows into portfolio totals and groupings.

    A position is treated as valued when ``status`` is one of:
    ``indicative``, ``solved``, or ``valued``.
    """
    grouped_by_instrument: dict[str, float] = {}
    grouped_by_asset: dict[str, float] = {}

    total_pv = 0.0
    position_count = 0
    valued_count = 0

    for row in positions:
        position_count += 1
        instrument_type = str(row.instrument_type).lower()
        asset_class = row.asset_class or infer_asset_class(instrument_type)

        grouped_by_instrument[instrument_type] = (
            grouped_by_instrument.get(instrument_type, 0.0) + row.pv
        )
        grouped_by_asset[asset_class] = grouped_by_asset.get(asset_class, 0.0) + row.pv
        total_pv += row.pv

        if str(row.status).lower() in {"indicative", "solved", "valued"}:
            valued_count += 1

    return PortfolioAggregation(
        total_pv=total_pv,
        grouped_pv_by_instrument_type=grouped_by_instrument,
        grouped_pv_by_asset_class=grouped_by_asset,
        position_count=position_count,
        valued_count=valued_count,
        unsupported_count=position_count - valued_count,
    )
