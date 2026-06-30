from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_portfolio import _BASE_REQUEST, _mixed_positions


client = TestClient(app)


def test_portfolio_risk_returns_grouped_and_position_sensitivities() -> None:
    payload = {
        **_BASE_REQUEST,
        "positions": [
            _mixed_positions()[2],  # fx_forward
            _mixed_positions()[4],  # fx_option
            _mixed_positions()[5],  # equity_option
        ],
    }

    response = client.post("/portfolio/risk", json=payload)

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "indicative"
    assert data["position_count"] == 3
    assert data["valued_count"] == 3
    assert data["unsupported_count"] == 0
    assert data["total_portfolio_pv"] != 0.0

    conventions = data["sensitivity_conventions"]
    assert "+1bp" in conventions["rates_sensitivity"]
    assert "+1% FX spot" in conventions["fx_spot_sensitivity"]
    assert "+1% equity spot" in conventions["equity_spot_sensitivity"]
    assert "+1 vol point" in conventions["vol_sensitivity"]

    totals = data["total_sensitivities"]
    assert set(totals) == {
        "rates_sensitivity",
        "fx_spot_sensitivity",
        "equity_spot_sensitivity",
        "vol_sensitivity",
    }
    assert totals["fx_spot_sensitivity"] != 0.0
    assert totals["equity_spot_sensitivity"] != 0.0
    assert totals["vol_sensitivity"] != 0.0

    assert "fx_forward" in data["grouped_sensitivities_by_instrument_type"]
    assert "fx" in data["grouped_sensitivities_by_asset_class"]
    assert "equity" in data["grouped_sensitivities_by_asset_class"]

    position_total = sum(row["fx_spot_sensitivity"] for row in data["positions"])
    assert totals["fx_spot_sensitivity"] == pytest.approx(position_total, rel=1e-12)


def test_portfolio_risk_warns_for_ignored_dimensions() -> None:
    payload = {
        **_BASE_REQUEST,
        "positions": [_mixed_positions()[1]],  # FRA without curve inputs
    }

    response = client.post("/portfolio/risk", json=payload)

    assert response.status_code == 200
    data = response.json()
    row = data["positions"][0]

    assert row["status"] == "valued"
    assert row["warnings"]
    assert any("rates_sensitivity ignored" in warning for warning in row["warnings"])
    assert any("fx_spot_sensitivity not applicable" in warning for warning in row["warnings"])
    assert row["rates_sensitivity"] == 0.0
