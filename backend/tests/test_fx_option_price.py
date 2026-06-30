from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.price import FXOptionPriceRequest

client = TestClient(app)

_PAYLOAD = {
    "request_id": "fx-option-1",
    "instrument_type": "fx_option",
    "valuation_date": "2024-01-01",
    "expiry_date": "2024-07-01",
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
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "domestic_currency",
    "foreign_currency",
    "year_fraction",
    "settlement_year_fraction",
    "domestic_discount_factor",
    "foreign_discount_factor",
    "forward_rate",
    "premium_domestic",
    "premium_foreign",
    "delta",
    "gamma",
    "vega",
    "pv_currency",
    "model_source",
    "assumptions",
    "warnings",
}


def test_fx_option_route_returns_200() -> None:
    assert client.post("/price/fx-option", json=_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/price/fx-option", json=_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_model_source_is_garman_kohlhagen() -> None:
    data = client.post("/price/fx-option", json=_PAYLOAD).json()
    assert data["model_source"] == "garman_kohlhagen"


def test_put_call_parity_holds_in_response() -> None:
    call_data = client.post("/price/fx-option", json={**_PAYLOAD, "option_type": "call"}).json()
    put_data = client.post("/price/fx-option", json={**_PAYLOAD, "option_type": "put"}).json()
    parity_rhs = _PAYLOAD["notional_foreign"] * (
        _PAYLOAD["spot_rate"] * call_data["foreign_discount_factor"]
        - _PAYLOAD["strike_rate"] * call_data["domestic_discount_factor"]
    )
    assert call_data["premium_domestic"] - put_data["premium_domestic"] == pytest.approx(
        parity_rhs,
        rel=1e-12,
    )


def test_short_position_sign_flips_premium_and_greeks() -> None:
    long_data = client.post("/price/fx-option", json={**_PAYLOAD, "position": "long"}).json()
    short_data = client.post("/price/fx-option", json={**_PAYLOAD, "position": "short"}).json()
    assert long_data["premium_domestic"] == pytest.approx(-short_data["premium_domestic"], rel=1e-12)
    assert long_data["delta"] == pytest.approx(-short_data["delta"], rel=1e-12)
    assert long_data["gamma"] == pytest.approx(-short_data["gamma"], rel=1e-12)
    assert long_data["vega"] == pytest.approx(-short_data["vega"], rel=1e-12)


def test_settlement_date_defaults_to_expiry_when_omitted() -> None:
    data = client.post("/price/fx-option", json=_PAYLOAD).json()
    assert data["settlement_year_fraction"] == pytest.approx(data["year_fraction"], rel=1e-12)


def test_invalid_option_type_rejected_clearly() -> None:
    response = client.post("/price/fx-option", json={**_PAYLOAD, "option_type": "digital"})
    assert response.status_code == 422
    assert "option_type" in str(response.json()["detail"]).lower()


def test_invalid_position_rejected_clearly() -> None:
    response = client.post("/price/fx-option", json={**_PAYLOAD, "position": "buyer"})
    assert response.status_code == 422
    assert "position" in str(response.json()["detail"]).lower()


def test_settlement_before_expiry_rejected_clearly() -> None:
    response = client.post(
        "/price/fx-option",
        json={**_PAYLOAD, "settlement_date": "2024-06-30"},
    )
    assert response.status_code == 422
    assert "settlement_date" in str(response.json()["detail"]).lower()


def test_fx_option_schema_rejects_same_currency_pair() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FXOptionPriceRequest(**{**_PAYLOAD, "foreign_currency": "ZAR"})
    assert "currency" in str(exc_info.value).lower()