from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.price import FRAPriceRequest

client = TestClient(app)

_FLAT_PAYLOAD = {
    "request_id": "fra-flat-1",
    "instrument_type": "fra",
    "valuation_date": "2024-01-01",
    "start_date": "2024-07-01",
    "end_date": "2025-01-01",
    "notional": 1_000_000.0,
    "contract_rate": 0.08,
    "day_count": "ACT_365F",
    "position": "payer",
}

_BOOTSTRAP_CURVE_INPUTS = {
    "valuation_date": "2024-01-01",
    "payment_frequency": "annual",
    "day_count": "ACT_365F",
    "deposits": [
        {"tenor_months": 1, "rate": 0.078},
        {"tenor_months": 3, "rate": 0.079},
        {"tenor_months": 6, "rate": 0.080},
    ],
    "fras": [
        {"start_months": 6, "end_months": 9, "rate": 0.081},
        {"start_months": 9, "end_months": 12, "rate": 0.0815},
    ],
    "swaps": [
        {"tenor_years": 2, "par_rate": 0.082},
        {"tenor_years": 3, "par_rate": 0.083},
        {"tenor_years": 5, "par_rate": 0.085},
    ],
}

_BOOT_PAYLOAD = {**_FLAT_PAYLOAD, "request_id": "fra-boot-1", "curve_inputs": _BOOTSTRAP_CURVE_INPUTS}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "forward_rate",
    "year_fraction",
    "discount_factor_to_payment",
    "payoff_undiscounted",
    "pv",
    "curve_source",
    "assumptions",
    "warnings",
}


def _flat_forward_rate(valuation_date: str, start_date: str, end_date: str, rate: float) -> float:
    val = date.fromisoformat(valuation_date)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    tau = (end - start).days / 365.0
    tau_start = (start - val).days / 365.0
    tau_end = (end - val).days / 365.0
    df_start = 1.0 / (1.0 + rate * tau_start)
    df_end = 1.0 / (1.0 + rate * tau_end)
    return (df_start / df_end - 1.0) / tau


def test_flat_path_returns_200() -> None:
    assert client.post("/price/fra", json=_FLAT_PAYLOAD).status_code == 200


def test_bootstrapped_path_returns_200() -> None:
    assert client.post("/price/fra", json=_BOOT_PAYLOAD).status_code == 200


def test_bootstrapped_path_with_aligned_curve_valuation_date_returns_200() -> None:
    payload = {
        **_FLAT_PAYLOAD,
        "request_id": "fra-boot-aligned",
        "curve_inputs": {**_BOOTSTRAP_CURVE_INPUTS, "valuation_date": _FLAT_PAYLOAD["valuation_date"]},
    }
    response = client.post("/price/fra", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "indicative"


@pytest.mark.parametrize("day_count", ["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"])
def test_fra_schema_accepts_supported_day_counts(day_count: str) -> None:
    request = FRAPriceRequest(**{**_FLAT_PAYLOAD, "day_count": day_count})
    assert request.day_count == day_count


@pytest.mark.parametrize("day_count", ["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"])
def test_flat_path_accepts_supported_day_counts(day_count: str) -> None:
    payload = {**_FLAT_PAYLOAD, "request_id": f"fra-{day_count.lower()}", "day_count": day_count}
    response = client.post("/price/fra", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "indicative"


def test_response_has_required_keys() -> None:
    data = client.post("/price/fra", json=_FLAT_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_flat_path_curve_source_is_flat_fallback() -> None:
    data = client.post("/price/fra", json=_FLAT_PAYLOAD).json()
    assert data["curve_source"] == "flat_fallback"


def test_bootstrapped_path_curve_source_is_bootstrapped() -> None:
    data = client.post("/price/fra", json=_BOOT_PAYLOAD).json()
    assert data["curve_source"] == "bootstrapped_mixed_curve"


def test_near_par_case_gives_pv_near_zero() -> None:
    par_rate = _flat_forward_rate(
        _FLAT_PAYLOAD["valuation_date"],
        _FLAT_PAYLOAD["start_date"],
        _FLAT_PAYLOAD["end_date"],
        rate=0.08,
    )
    payload = {**_FLAT_PAYLOAD, "request_id": "fra-par", "contract_rate": par_rate}
    data = client.post("/price/fra", json=payload).json()
    assert abs(data["pv"]) < 1e-8


def test_invalid_payload_rejected_clearly() -> None:
    payload = {**_FLAT_PAYLOAD, "start_date": "2024-01-01"}
    resp = client.post("/price/fra", json=payload)
    assert resp.status_code == 422
    assert "start_date" in str(resp.json()["detail"]).lower()


def test_invalid_position_rejected_clearly() -> None:
    payload = {**_FLAT_PAYLOAD, "position": "long"}
    resp = client.post("/price/fra", json=payload)
    assert resp.status_code == 422
    assert "position" in str(resp.json()["detail"]).lower()


def test_invalid_day_count_rejected_clearly() -> None:
    payload = {**_FLAT_PAYLOAD, "day_count": "ACT_252"}
    resp = client.post("/price/fra", json=payload)
    assert resp.status_code == 422
    assert "day_count" in str(resp.json()["detail"]).lower()


def test_fra_schema_rejects_invalid_day_count() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FRAPriceRequest(**{**_FLAT_PAYLOAD, "day_count": "ACT_252"})
    assert "day_count" in str(exc_info.value).lower()


def test_mismatched_curve_valuation_date_rejected_clearly() -> None:
    payload = {
        **_FLAT_PAYLOAD,
        "curve_inputs": {**_BOOTSTRAP_CURVE_INPUTS, "valuation_date": "2024-01-02"},
    }
    resp = client.post("/price/fra", json=payload)
    assert resp.status_code == 422
    detail = str(resp.json()["detail"]).lower()
    assert "curve_inputs.valuation_date" in detail
    assert "valuation_date" in detail


def test_fra_schema_rejects_mismatched_curve_valuation_date() -> None:
    with pytest.raises(ValidationError) as exc_info:
        FRAPriceRequest(
            **{
                **_FLAT_PAYLOAD,
                "curve_inputs": {**_BOOTSTRAP_CURVE_INPUTS, "valuation_date": "2024-01-02"},
            }
        )
    message = str(exc_info.value)
    assert "curve_inputs.valuation_date" in message
    assert "valuation_date" in message