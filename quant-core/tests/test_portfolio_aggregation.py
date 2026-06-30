from __future__ import annotations

from quant_core.pricing.portfolio import (
    PositionPV,
    aggregate_position_pvs,
    infer_asset_class,
)


def test_infer_asset_class_known_mapping() -> None:
    assert infer_asset_class("bond") == "rates"
    assert infer_asset_class("fra") == "rates"
    assert infer_asset_class("fx_forward") == "fx"
    assert infer_asset_class("fx_swap") == "fx"
    assert infer_asset_class("fx_option") == "fx"
    assert infer_asset_class("equity_option") == "equity"


def test_infer_asset_class_unknown_defaults_to_other() -> None:
    assert infer_asset_class("crypto_option") == "other"


def test_aggregate_position_pvs_totals_and_groups() -> None:
    rows = [
        PositionPV(
            position_id="p1",
            instrument_type="bond",
            pv=100.0,
            status="indicative",
            asset_class="rates",
        ),
        PositionPV(
            position_id="p2",
            instrument_type="fx_forward",
            pv=-40.0,
            status="indicative",
            asset_class="fx",
        ),
        PositionPV(
            position_id="p3",
            instrument_type="equity_option",
            pv=10.0,
            status="unsupported",
            asset_class="equity",
        ),
    ]

    agg = aggregate_position_pvs(rows)

    assert agg.total_pv == 70.0
    assert agg.position_count == 3
    assert agg.valued_count == 2
    assert agg.unsupported_count == 1
    assert agg.grouped_pv_by_instrument_type["bond"] == 100.0
    assert agg.grouped_pv_by_instrument_type["fx_forward"] == -40.0
    assert agg.grouped_pv_by_asset_class["rates"] == 100.0
    assert agg.grouped_pv_by_asset_class["fx"] == -40.0
    assert agg.grouped_pv_by_asset_class["equity"] == 10.0
