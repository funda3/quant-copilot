from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_portfolio import _BASE_REQUEST, _mixed_positions


client = TestClient(app)


def test_portfolio_scenario_compare_default_pack_returns_comparison_grids() -> None:
    payload = {
        **_BASE_REQUEST,
        "positions": [
            _mixed_positions()[2],  # fx_forward
            _mixed_positions()[4],  # fx_option
            _mixed_positions()[5],  # equity_option
        ],
    }

    response = client.post("/portfolio/scenario-compare", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "indicative"
    assert data["scenario_pack"] == "Core Market Moves"
    assert data["scenario_count"] == 8
    assert data["position_count"] == 3

    scenario_names = [row["scenario_name"] for row in data["scenarios"]]
    assert scenario_names == [
        "Rates Up",
        "Rates Down",
        "FX Up",
        "FX Down",
        "Equity Up",
        "Equity Down",
        "Vol Up",
        "Combined Stress",
    ]

    conventions = data["scenario_conventions"]
    assert "basis points" in conventions["rates_bps"]
    assert "spot_rate x 1.05" in conventions["fx_spot_pct"]
    assert "volatility x 1.05" in conventions["vol_pct"]

    assert "FX Up" in data["grouped_delta_by_instrument_type"]
    assert "fx_forward" in data["grouped_delta_by_instrument_type"]["FX Up"]
    assert "FX Up" in data["grouped_delta_by_asset_class"]
    assert "fx" in data["grouped_delta_by_asset_class"]["FX Up"]

    fx_up = next(row for row in data["scenarios"] if row["scenario_name"] == "FX Up")
    assert fx_up["delta_portfolio_pv"] != 0.0
    assert fx_up["largest_contributor"]

    fxfwd = next(row for row in data["positions"] if row["position_id"] == "fxfwd-1")
    assert "FX Up" in fxfwd["deltas_by_scenario"]
    assert fxfwd["deltas_by_scenario"]["FX Up"] != 0.0


def test_portfolio_scenario_compare_accepts_custom_scenarios() -> None:
    payload = {
        **_BASE_REQUEST,
        "positions": [_mixed_positions()[5]],  # equity_option
        "scenarios": [
            {
                "name": "Custom Equity Down",
                "description": "Equity spot -10%.",
                "shocks": {"equity_spot_pct": -10.0},
            }
        ],
    }

    response = client.post("/portfolio/scenario-compare", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["scenario_pack"] == "Custom scenarios"
    assert data["scenario_count"] == 1
    assert data["scenarios"][0]["scenario_name"] == "Custom Equity Down"
    assert data["scenarios"][0]["delta_portfolio_pv"] == pytest.approx(
        data["positions"][0]["deltas_by_scenario"]["Custom Equity Down"],
        rel=1e-12,
    )
