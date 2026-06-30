"""
Tests for POST /price/bond — fixed-rate bond pricing endpoint.

Canonical flat-curve bond:
  valuation_date: 2024-01-01
  issue_date:     2024-01-01
  maturity_date:  2029-01-01  (5Y)
  face_value:     1_000_000
  coupon_rate:    0.08        (8%)
  coupon_frequency: annual
  day_count:      ACT_365F
  curve: flat 8% proxy

Canon bootstrapped curve:
  Same as test_mixed_curve.py canonical fixture.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FLAT_PAYLOAD = {
    "valuation_date": "2024-01-01",
    "issue_date": "2024-01-01",
    "maturity_date": "2029-01-01",
    "face_value": 1_000_000.0,
    "coupon_rate": 0.08,
    "coupon_frequency": "annual",
    "day_count": "ACT_365F",
}

_CANON_CURVE_INPUTS = {
    "valuation_date": "2024-01-15",
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

_BOOTSTRAP_PAYLOAD = {**_FLAT_PAYLOAD, "curve_inputs": _CANON_CURVE_INPUTS}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "clean_price",
    "dirty_price",
    "accrued_interest",
    "n_remaining_coupons",
    "assumptions",
    "warnings",
}


# ---------------------------------------------------------------------------
# Contract / shape
# ---------------------------------------------------------------------------


def test_flat_path_returns_200() -> None:
    assert client.post("/price/bond", json=_FLAT_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_missing_valuation_date_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "valuation_date"}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_missing_maturity_date_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "maturity_date"}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_missing_face_value_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "face_value"}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_invalid_date_format_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "valuation_date": "01/01/2024"}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_negative_face_value_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "face_value": -1_000.0}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_coupon_rate_above_one_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 1.5}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_unsupported_frequency_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_frequency": "monthly"}
    assert client.post("/price/bond", json=payload).status_code == 422


def test_unsupported_day_count_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "day_count": "ACT_252"}
    assert client.post("/price/bond", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# Status and values — flat path
# ---------------------------------------------------------------------------


def test_flat_path_status_is_indicative() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_flat_path_instrument_type_is_bond() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["instrument_type"] == "bond"


def test_flat_path_clean_price_is_float() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["clean_price"], float)


def test_flat_path_dirty_price_is_float() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["dirty_price"], float)


def test_flat_path_accrued_interest_non_negative() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["accrued_interest"] >= 0.0


def test_flat_path_n_remaining_coupons_positive() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["n_remaining_coupons"] > 0


# ---------------------------------------------------------------------------
# Clean <= dirty when accrued > 0
# ---------------------------------------------------------------------------


def test_clean_price_lte_dirty_price_at_issue() -> None:
    # At issue: accrued = 0 → clean == dirty.
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert abs(data["clean_price"] - data["dirty_price"]) < 1e-4


def test_clean_price_lt_dirty_price_mid_period() -> None:
    # Mid-period valuation: accrued > 0 → clean < dirty.
    payload = {**_FLAT_PAYLOAD, "valuation_date": "2024-07-01"}
    data = client.post("/price/bond", json=payload).json()
    assert data["accrued_interest"] > 0.0
    assert data["clean_price"] < data["dirty_price"]


def test_dirty_minus_clean_equals_accrued() -> None:
    payload = {**_FLAT_PAYLOAD, "valuation_date": "2024-07-01"}
    data = client.post("/price/bond", json=payload).json()
    assert abs(
        data["dirty_price"] - data["clean_price"] - data["accrued_interest"]
    ) < 1e-4


# ---------------------------------------------------------------------------
# Par bond
# ---------------------------------------------------------------------------


def test_below_par_coupon_produces_dirty_below_face() -> None:
    """
    5% coupon on an 8% flat curve → bond prices below par (discount bond).
    """
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.05}
    data = client.post("/price/bond", json=payload).json()
    assert data["dirty_price"] < _FLAT_PAYLOAD["face_value"]


def test_above_par_coupon_produces_dirty_above_face() -> None:
    """
    12% coupon on an 8% flat curve → bond prices above par (premium bond).
    """
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.12}
    data = client.post("/price/bond", json=payload).json()
    assert data["dirty_price"] > _FLAT_PAYLOAD["face_value"]


# ---------------------------------------------------------------------------
# Zero-coupon bond
# ---------------------------------------------------------------------------


def test_zero_coupon_bond_returns_indicative() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/price/bond", json=payload).json()
    assert data["status"] == "indicative"


def test_zero_coupon_bond_accrued_is_zero() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/price/bond", json=payload).json()
    assert data["accrued_interest"] == pytest.approx(0.0, abs=1e-8)


def test_zero_coupon_bond_clean_equals_dirty() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/price/bond", json=payload).json()
    assert data["clean_price"] == pytest.approx(data["dirty_price"], rel=1e-10)


def test_zero_coupon_bond_n_remaining_is_zero() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/price/bond", json=payload).json()
    assert data["n_remaining_coupons"] == 0


# ---------------------------------------------------------------------------
# request_id handling
# ---------------------------------------------------------------------------


def test_provided_request_id_echoed() -> None:
    payload = {**_FLAT_PAYLOAD, "request_id": "bond-test-001"}
    data = client.post("/price/bond", json=payload).json()
    assert data["request_id"] == "bond-test-001"


def test_generated_request_id_when_omitted() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_generated_request_ids_are_unique() -> None:
    r1 = client.post("/price/bond", json=_FLAT_PAYLOAD).json()["request_id"]
    r2 = client.post("/price/bond", json=_FLAT_PAYLOAD).json()["request_id"]
    assert r1 != r2


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


def test_bootstrap_path_returns_200() -> None:
    assert client.post("/price/bond", json=_BOOTSTRAP_PAYLOAD).status_code == 200


def test_bootstrap_path_status_is_indicative() -> None:
    data = client.post("/price/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_bootstrap_path_clean_price_differs_from_flat() -> None:
    """Bootstrapped curve should produce a different price to the flat proxy."""
    flat_data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    bs_data = client.post("/price/bond", json=_BOOTSTRAP_PAYLOAD).json()
    # Prices should differ because curves differ.
    assert abs(flat_data["clean_price"] - bs_data["clean_price"]) > 1.0


def test_bootstrap_path_accrued_non_negative() -> None:
    data = client.post("/price/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["accrued_interest"] >= 0.0


# ---------------------------------------------------------------------------
# Semiannual and quarterly bonds
# ---------------------------------------------------------------------------


def test_semiannual_coupon_bond_returns_indicative() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_frequency": "semiannual"}
    data = client.post("/price/bond", json=payload).json()
    assert data["status"] == "indicative"
    assert data["n_remaining_coupons"] > 0


def test_quarterly_coupon_bond_returns_indicative() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_frequency": "quarterly"}
    data = client.post("/price/bond", json=payload).json()
    assert data["status"] == "indicative"
    assert data["n_remaining_coupons"] > 0


def test_quarterly_has_more_coupons_than_annual() -> None:
    annual = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    qtly = client.post(
        "/price/bond", json={**_FLAT_PAYLOAD, "coupon_frequency": "quarterly"}
    ).json()
    assert qtly["n_remaining_coupons"] > annual["n_remaining_coupons"]


# ---------------------------------------------------------------------------
# Assumptions and warnings
# ---------------------------------------------------------------------------


def test_flat_path_assumptions_non_empty() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert len(data["assumptions"]) > 0


def test_flat_path_warnings_empty() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["warnings"] == []


def test_bootstrap_path_assumptions_mention_bootstrapped() -> None:
    data = client.post("/price/bond", json=_BOOTSTRAP_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "bootstrap" in combined


# ---------------------------------------------------------------------------
# Regression: existing endpoints still work
# ---------------------------------------------------------------------------


def test_healthz_still_works() -> None:
    assert client.get("/healthz").status_code == 200


def test_price_irs_still_works() -> None:
    payload = {
        "extracted_fields": {
            "instrument_type": "irs",
            "currency": "ZAR",
            "direction": "payer",
            "floating_index": "JIBAR",
            "payment_frequency": "quarterly",
            "tenor": "5Y",
            "notional": 250_000_000,
            "fixed_rate": 0.085,
        }
    }
    data = client.post("/price", json=payload).json()
    assert data["status"] == "indicative"


def test_ladder_still_works() -> None:
    payload = {
        "extracted_fields": {
            "instrument_type": "irs",
            "currency": "ZAR",
            "direction": "payer",
            "floating_index": "JIBAR",
            "payment_frequency": "quarterly",
            "tenor": "5Y",
            "notional": 250_000_000,
            "fixed_rate": 0.085,
        }
    }
    data = client.post("/risk/ladder", json=payload).json()
    assert data["status"] == "indicative"
