from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.price import FXForwardPriceRequest

client = TestClient(app)

_PAYLOAD = {
    "request_id": "fxfwd-1",
    "instrument_type": "fx_forward",
    "valuation_date": "2024-01-01",
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
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "domestic_currency",
    "foreign_currency",
    "year_fraction",
    "domestic_discount_factor",
    "foreign_discount_factor",
    "implied_forward_rate",
    "forward_points",
    "payoff_undiscounted_domestic",
    "present_value_domestic",
    "pv_currency",
    "rate_source",
    "assumptions",
    "warnings",
}


def _par_forward_rate(payload: dict) -> float:
    valuation_date = date.fromisoformat(payload["valuation_date"])
    maturity_date = date.fromisoformat(payload["maturity_date"])
    year_fraction = (maturity_date - valuation_date).days / 365.0
    domestic_df = 1.0 / (1.0 + payload["domestic_rate"] * year_fraction)
    foreign_df = 1.0 / (1.0 + payload["foreign_rate"] * year_fraction)
    return payload["spot_rate"] * foreign_df / domestic_df


def test_fx_forward_route_returns_200() -> None:
    assert client.post("/price/fx-forward", json=_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/price/fx-forward", json=_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_rate_source_is_flat_inputs() -> None:
    data = client.post("/price/fx-forward", json=_PAYLOAD).json()
    assert data["rate_source"] == "flat_interest_rate_inputs"


def test_par_forward_gives_pv_near_zero() -> None:
    payload = {**_PAYLOAD, "contract_forward_rate": _par_forward_rate(_PAYLOAD)}
    data = client.post("/price/fx-forward", json=payload).json()
    assert abs(data["present_value_domestic"]) < 1e-8


def test_short_foreign_sign_flips_pv() -> None:
    long_payload = {**_PAYLOAD, "contract_forward_rate": 18.50, "position": "long_foreign"}
    short_payload = {**_PAYLOAD, "contract_forward_rate": 18.50, "position": "short_foreign"}
    long_data = client.post("/price/fx-forward", json=long_payload).json()
    short_data = client.post("/price/fx-forward", json=short_payload).json()
    assert long_data["present_value_domestic"] == pytest.approx(
        -short_data["present_value_domestic"],
        rel=1e-12,
    )


def test_invalid_currency_pair_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "foreign_currency": "ZAR"}
    response = client.post("/price/fx-forward", json=payload)
    assert response.status_code == 422
    assert "currency" in str(response.json()["detail"]).lower()


def test_invalid_position_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "position": "long"}
    response = client.post("/price/fx-forward", json=payload)
    assert response.status_code == 422
    assert "position" in str(response.json()["detail"]).lower()


def test_maturity_not_after_valuation_rejected_clearly() -> None:
    payload = {**_PAYLOAD, "maturity_date": "2024-01-01"}
    response = client.post("/price/fx-forward", json=payload)
    assert response.status_code == 422
    assert "maturity_date" in str(response.json()["detail"]).lower()


def test_fx_forward_schema_rejects_same_currency_pair() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FXForwardPriceRequest(**{**_PAYLOAD, "foreign_currency": "ZAR"})
    assert "currency" in str(exc_info.value).lower()