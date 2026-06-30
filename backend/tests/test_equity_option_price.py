from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.price import EquityOptionPriceRequest

client = TestClient(app)

_PAYLOAD = {
    "request_id": "equity-option-1",
    "instrument_type": "equity_option",
    "valuation_date": "2024-01-01",
    "expiry_date": "2024-07-01",
    "spot_price": 100.0,
    "strike_price": 105.0,
    "risk_free_rate": 0.05,
    "dividend_yield": 0.02,
    "volatility": 0.25,
    "quantity_shares": 1000.0,
    "option_type": "call",
    "position": "long",
    "currency": "USD",
    "underlying_name": "ACME",
    "day_count": "ACT_365F",
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "underlying_name",
    "currency",
    "year_fraction",
    "discount_factor",
    "dividend_discount_factor",
    "forward_price",
    "premium",
    "delta",
    "gamma",
    "vega",
    "pv_currency",
    "model_source",
    "assumptions",
    "warnings",
}


def test_equity_option_route_returns_200() -> None:
    assert client.post("/price/equity-option", json=_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/price/equity-option", json=_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_model_source_is_black_scholes_merton() -> None:
    data = client.post("/price/equity-option", json=_PAYLOAD).json()
    assert data["model_source"] == "black_scholes_merton"


def test_put_call_parity_holds_in_response() -> None:
    call_data = client.post("/price/equity-option", json={**_PAYLOAD, "option_type": "call"}).json()
    put_data = client.post("/price/equity-option", json={**_PAYLOAD, "option_type": "put"}).json()
    parity_rhs = _PAYLOAD["quantity_shares"] * (
        _PAYLOAD["spot_price"] * call_data["dividend_discount_factor"]
        - _PAYLOAD["strike_price"] * call_data["discount_factor"]
    )
    assert call_data["premium"] - put_data["premium"] == pytest.approx(
        parity_rhs,
        rel=1e-12,
    )


def test_short_position_sign_flips_premium_and_greeks() -> None:
    long_data = client.post("/price/equity-option", json={**_PAYLOAD, "position": "long"}).json()
    short_data = client.post("/price/equity-option", json={**_PAYLOAD, "position": "short"}).json()
    assert long_data["premium"] == pytest.approx(-short_data["premium"], rel=1e-12)
    assert long_data["delta"] == pytest.approx(-short_data["delta"], rel=1e-12)
    assert long_data["gamma"] == pytest.approx(-short_data["gamma"], rel=1e-12)
    assert long_data["vega"] == pytest.approx(-short_data["vega"], rel=1e-12)


def test_underlying_name_can_be_omitted() -> None:
    data = client.post("/price/equity-option", json={k: v for k, v in _PAYLOAD.items() if k != "underlying_name"}).json()
    assert data["underlying_name"] is None


def test_invalid_option_type_rejected_clearly() -> None:
    response = client.post("/price/equity-option", json={**_PAYLOAD, "option_type": "digital"})
    assert response.status_code == 422
    assert "option_type" in str(response.json()["detail"]).lower()


def test_invalid_position_rejected_clearly() -> None:
    response = client.post("/price/equity-option", json={**_PAYLOAD, "position": "buyer"})
    assert response.status_code == 422
    assert "position" in str(response.json()["detail"]).lower()


def test_expiry_not_after_valuation_rejected_clearly() -> None:
    response = client.post(
        "/price/equity-option",
        json={**_PAYLOAD, "expiry_date": "2024-01-01"},
    )
    assert response.status_code == 422
    assert "expiry_date" in str(response.json()["detail"]).lower()


def test_equity_option_schema_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EquityOptionPriceRequest(**{**_PAYLOAD, "quantity_shares": 0.0})
    assert "quantity_shares" in str(exc_info.value).lower()