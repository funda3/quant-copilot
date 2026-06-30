from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.price import FXSwapPriceRequest

client = TestClient(app)

_PAYLOAD = {
    "request_id": "fxswap-1",
    "instrument_type": "fx_swap",
    "valuation_date": "2024-01-01",
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
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "domestic_currency",
    "foreign_currency",
    "year_fraction_near",
    "year_fraction_far",
    "domestic_discount_factor_near",
    "domestic_discount_factor_far",
    "near_leg_value_domestic",
    "far_leg_value_domestic",
    "swap_points",
    "present_value_domestic",
    "pv_currency",
    "rate_source",
    "assumptions",
    "warnings",
}


def test_fx_swap_route_returns_200() -> None:
    assert client.post("/price/fx-swap", json=_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/price/fx-swap", json=_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_rate_source_is_flat_domestic_inputs() -> None:
    data = client.post("/price/fx-swap", json=_PAYLOAD).json()
    assert data["rate_source"] == "flat_domestic_discount_rate_input"


def test_par_swap_gives_pv_near_zero() -> None:
    payload = {**_PAYLOAD, "near_rate": 18.25, "far_rate": 18.25}
    data = client.post("/price/fx-swap", json=payload).json()
    assert abs(data["present_value_domestic"]) < 1e-8


def test_short_foreign_sign_flips_pv() -> None:
    long_payload = {**_PAYLOAD, "position": "long_foreign"}
    short_payload = {**_PAYLOAD, "position": "short_foreign"}
    long_data = client.post("/price/fx-swap", json=long_payload).json()
    short_data = client.post("/price/fx-swap", json=short_payload).json()
    assert long_data["present_value_domestic"] == pytest.approx(
        -short_data["present_value_domestic"],
        rel=1e-12,
    )


def test_invalid_currency_pair_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "foreign_currency": "ZAR"}
    response = client.post("/price/fx-swap", json=payload)
    assert response.status_code == 422
    assert "currency" in str(response.json()["detail"]).lower()


def test_invalid_position_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "position": "long"}
    response = client.post("/price/fx-swap", json=payload)
    assert response.status_code == 422
    assert "position" in str(response.json()["detail"]).lower()


def test_far_not_after_near_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "far_settlement_date": "2024-01-03"}
    response = client.post("/price/fx-swap", json=payload)
    assert response.status_code == 422
    assert "far_settlement_date" in str(response.json()["detail"]).lower()


def test_fx_swap_schema_rejects_same_currency_pair() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FXSwapPriceRequest(**{**_PAYLOAD, "foreign_currency": "ZAR"})
    assert "currency" in str(exc_info.value).lower()