from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


_BASE_REQUEST = {
    "portfolio_name": "Demo Basket",
    "valuation_date": "2024-01-01",
}


def _mixed_positions() -> list[dict]:
    return [
        {
            "position_id": "bond-1",
            "instrument_type": "bond",
            "quantity": 1.0,
            "fields": {
                "issue_date": "2024-01-01",
                "maturity_date": "2029-01-01",
                "face_value": 1_000_000.0,
                "coupon_rate": 0.08,
                "coupon_frequency": "annual",
                "day_count": "ACT_365F",
            },
        },
        {
            "position_id": "fra-1",
            "instrument_type": "fra",
            "quantity": 1.0,
            "fields": {
                "start_date": "2024-07-01",
                "end_date": "2025-01-01",
                "notional": 1_000_000.0,
                "contract_rate": 0.08,
                "day_count": "ACT_365F",
                "position": "payer",
            },
        },
        {
            "position_id": "fxfwd-1",
            "instrument_type": "fx_forward",
            "quantity": 1.0,
            "fields": {
                "maturity_date": "2024-07-01",
                "notional_foreign": 1_000_000.0,
                "spot_rate": 18.25,
                "contract_forward_rate": 18.60,
                "domestic_rate": 0.08,
                "foreign_rate": 0.05,
                "domestic_currency": "ZAR",
                "foreign_currency": "USD",
                "day_count": "ACT_365F",
                "position": "long_foreign",
            },
        },
        {
            "position_id": "fxswap-1",
            "instrument_type": "fx_swap",
            "quantity": 1.0,
            "fields": {
                "near_settlement_date": "2024-01-03",
                "far_settlement_date": "2024-07-01",
                "spot_rate": 18.25,
                "near_rate": 18.27,
                "far_rate": 18.65,
                "notional_foreign": 1_000_000.0,
                "domestic_currency": "ZAR",
                "foreign_currency": "USD",
                "domestic_rate": 0.08,
                "day_count": "ACT_365F",
                "position": "long_foreign",
            },
        },
        {
            "position_id": "fxopt-1",
            "instrument_type": "fx_option",
            "quantity": 1.0,
            "fields": {
                "expiry_date": "2024-07-01",
                "settlement_date": "2024-07-01",
                "spot_rate": 18.25,
                "strike_rate": 18.40,
                "domestic_rate": 0.08,
                "foreign_rate": 0.05,
                "volatility": 0.18,
                "notional_foreign": 1_000_000.0,
                "option_type": "call",
                "position": "long",
                "domestic_currency": "ZAR",
                "foreign_currency": "USD",
                "day_count": "ACT_365F",
            },
        },
        {
            "position_id": "eqopt-1",
            "instrument_type": "equity_option",
            "quantity": 1.0,
            "fields": {
                "expiry_date": "2024-07-01",
                "spot_price": 100.0,
                "strike_price": 105.0,
                "risk_free_rate": 0.05,
                "dividend_yield": 0.02,
                "volatility": 0.25,
                "quantity_shares": 1_000.0,
                "option_type": "call",
                "position": "long",
                "currency": "USD",
                "day_count": "ACT_365F",
                "underlying_name": "ACME",
            },
        },
    ]


def test_portfolio_value_mixed_basket_returns_200_and_grouping() -> None:
    payload = {**_BASE_REQUEST, "positions": _mixed_positions()}
    response = client.post("/portfolio/value", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "indicative"
    assert data["position_count"] == 6
    assert data["valued_count"] == 6
    assert data["unsupported_count"] == 0

    by_type = data["grouped_pv_by_instrument_type"]
    assert "bond" in by_type
    assert "fra" in by_type
    assert "fx_forward" in by_type
    assert "fx_swap" in by_type
    assert "fx_option" in by_type
    assert "equity_option" in by_type

    by_asset = data["grouped_pv_by_asset_class"]
    assert "rates" in by_asset
    assert "fx" in by_asset
    assert "equity" in by_asset

    sum_positions = sum(p["pv"] for p in data["positions"])
    assert data["total_portfolio_pv"] == pytest.approx(sum_positions, rel=1e-12)


def test_portfolio_value_malformed_position_returns_structured_warning() -> None:
    bad_positions = [
        _mixed_positions()[0],
        {
            "position_id": "bad-fxfwd",
            "instrument_type": "fx_forward",
            "fields": {
                "maturity_date": "2024-07-01",
                "notional_foreign": 1_000_000.0,
                "spot_rate": 18.25,
                # contract_forward_rate intentionally missing
                "domestic_rate": 0.08,
                "foreign_rate": 0.05,
                "domestic_currency": "ZAR",
                "foreign_currency": "USD",
                "day_count": "ACT_365F",
                "position": "long_foreign",
            },
        },
    ]
    payload = {**_BASE_REQUEST, "positions": bad_positions}
    response = client.post("/portfolio/value", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["unsupported_count"] == 1

    bad_row = next(row for row in data["positions"] if row["position_id"] == "bad-fxfwd")
    assert bad_row["status"] == "unsupported"
    assert bad_row["warnings"]


def test_portfolio_scenario_returns_base_shocked_and_delta() -> None:
    scenario_positions = [
        _mixed_positions()[2],
        _mixed_positions()[4],
        _mixed_positions()[5],
    ]
    payload = {
        **_BASE_REQUEST,
        "positions": scenario_positions,
        "shocks": {
            "rates_bps": 25,
            "fx_spot_pct": 2.0,
            "equity_spot_pct": -3.0,
            "vol_pct": 10.0,
        },
    }

    response = client.post("/portfolio/scenario", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["position_count"] == 3
    assert data["valued_count"] == 3
    assert data["unsupported_count"] == 0
    assert data["delta_portfolio_pv"] == pytest.approx(
        data["shocked_portfolio_pv"] - data["base_portfolio_pv"], rel=1e-12
    )
    assert data["grouped_delta_pv_by_asset_class"]["fx"] == pytest.approx(
        sum(row["delta_pv"] for row in data["positions"] if row["asset_class"] == "fx"),
        rel=1e-12,
    )
    assert data["grouped_delta_pv_by_asset_class"]["equity"] == pytest.approx(
        sum(row["delta_pv"] for row in data["positions"] if row["asset_class"] == "equity"),
        rel=1e-12,
    )

    for row in data["positions"]:
        assert "base_pv" in row
        assert "shocked_pv" in row
        assert "delta_pv" in row
        assert row["delta_pv"] == pytest.approx(row["shocked_pv"] - row["base_pv"], rel=1e-12)


def test_portfolio_scenario_rates_shock_warns_for_bond_without_curve_inputs() -> None:
    payload = {
        **_BASE_REQUEST,
        "positions": [_mixed_positions()[0]],
        "shocks": {
            "rates_bps": 100,
            "fx_spot_pct": 0.0,
            "equity_spot_pct": 0.0,
            "vol_pct": 0.0,
        },
    }

    response = client.post("/portfolio/scenario", json=payload)
    assert response.status_code == 200
    data = response.json()

    row = data["positions"][0]
    assert row["warnings"]
    assert any("rates_bps shock ignored" in w for w in row["warnings"])
