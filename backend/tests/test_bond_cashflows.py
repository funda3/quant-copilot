"""
Tests for POST /price/bond/cashflows — bond cashflow schedule endpoint.

Canonical flat-curve bond:
  valuation_date: 2024-01-01
  issue_date:     2024-01-01
  maturity_date:  2029-01-01  (5Y annual)
  face_value:     1_000_000
  coupon_rate:    0.08        (8%)
  coupon_frequency: annual
  day_count:      ACT_365F
  curve: flat 8% proxy

Bootstrapped-curve tests use the same mixed curve fixture as test_bond_price.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_URL = "/price/bond/cashflows"

_FLAT_PAYLOAD = {
    "valuation_date": "2024-01-01",
    "issue_date": "2024-01-01",
    "maturity_date": "2029-01-01",
    "face_value": 1_000_000.0,
    "coupon_rate": 0.08,
    "coupon_frequency": "annual",
    "day_count": "ACT_365F",
}

_ZCB_PAYLOAD = {
    "valuation_date": "2024-01-01",
    "issue_date": "2024-01-01",
    "maturity_date": "2029-01-01",
    "face_value": 1_000_000.0,
    "coupon_rate": 0.0,
    "coupon_frequency": "annual",
    "day_count": "ACT_365F",
}

_SEMIANNUAL_PAYLOAD = {
    "valuation_date": "2024-01-01",
    "issue_date": "2024-01-01",
    "maturity_date": "2027-01-01",
    "face_value": 500_000.0,
    "coupon_rate": 0.07,
    "coupon_frequency": "semiannual",
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

_TOP_LEVEL_KEYS = {
    "request_id",
    "instrument_type",
    "status",
    "dirty_price",
    "n_remaining_coupons",
    "cashflows",
    "assumptions",
    "warnings",
}

_ROW_KEYS = {
    "payment_date",
    "accrual_start",
    "accrual_end",
    "year_fraction",
    "coupon_cashflow",
    "principal_cashflow",
    "total_cashflow",
    "discount_factor",
    "pv_cashflow",
    "time_to_payment_years",
}


# ---------------------------------------------------------------------------
# HTTP status — flat and bootstrapped paths
# ---------------------------------------------------------------------------


def test_flat_path_returns_200() -> None:
    resp = client.post(_URL, json=_FLAT_PAYLOAD)
    assert resp.status_code == 200


def test_bootstrapped_path_returns_200() -> None:
    resp = client.post(_URL, json=_BOOTSTRAP_PAYLOAD)
    assert resp.status_code == 200


def test_zcb_flat_path_returns_200() -> None:
    resp = client.post(_URL, json=_ZCB_PAYLOAD)
    assert resp.status_code == 200


def test_semiannual_flat_path_returns_200() -> None:
    resp = client.post(_URL, json=_SEMIANNUAL_PAYLOAD)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Top-level response shape
# ---------------------------------------------------------------------------


def test_response_has_all_required_top_level_keys() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert _TOP_LEVEL_KEYS <= set(data.keys())


def test_status_is_indicative_for_flat() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_status_is_indicative_for_bootstrapped() -> None:
    data = client.post(_URL, json=_BOOTSTRAP_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_instrument_type_is_bond() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert data["instrument_type"] == "bond"


def test_request_id_echo() -> None:
    payload = {**_FLAT_PAYLOAD, "request_id": "test-cf-001"}
    data = client.post(_URL, json=payload).json()
    assert data["request_id"] == "test-cf-001"


def test_request_id_generated_when_omitted() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_dirty_price_positive() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert data["dirty_price"] > 0.0


def test_assumptions_non_empty() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert len(data["assumptions"]) > 0


def test_warnings_empty_for_valid_flat_request() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert data["warnings"] == []


# ---------------------------------------------------------------------------
# Cashflow list
# ---------------------------------------------------------------------------


def test_cashflows_is_a_list() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert isinstance(data["cashflows"], list)


def test_cashflow_rows_have_all_required_keys() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        assert _ROW_KEYS <= set(row.keys())


def test_five_year_annual_has_five_cashflow_rows() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert len(data["cashflows"]) == 5


def test_semiannual_3y_has_six_cashflow_rows() -> None:
    data = client.post(_URL, json=_SEMIANNUAL_PAYLOAD).json()
    assert len(data["cashflows"]) == 6


def test_zcb_has_one_cashflow_row() -> None:
    data = client.post(_URL, json=_ZCB_PAYLOAD).json()
    assert len(data["cashflows"]) == 1


def test_row_count_matches_n_remaining_coupons_coupon_bond() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    assert len(data["cashflows"]) == data["n_remaining_coupons"]


def test_row_count_matches_n_remaining_coupons_semiannual() -> None:
    data = client.post(_URL, json=_SEMIANNUAL_PAYLOAD).json()
    assert len(data["cashflows"]) == data["n_remaining_coupons"]


def test_zcb_n_remaining_coupons_is_zero() -> None:
    data = client.post(_URL, json=_ZCB_PAYLOAD).json()
    assert data["n_remaining_coupons"] == 0


# ---------------------------------------------------------------------------
# Final row carries principal
# ---------------------------------------------------------------------------


def test_final_row_has_principal_for_coupon_bond() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    rows = data["cashflows"]
    assert rows[-1]["principal_cashflow"] == pytest.approx(
        _FLAT_PAYLOAD["face_value"], rel=1e-10
    )


def test_final_row_has_principal_for_zcb() -> None:
    data = client.post(_URL, json=_ZCB_PAYLOAD).json()
    rows = data["cashflows"]
    assert rows[-1]["principal_cashflow"] == pytest.approx(
        _ZCB_PAYLOAD["face_value"], rel=1e-10
    )


def test_non_final_rows_have_zero_principal() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    rows = data["cashflows"]
    for row in rows[:-1]:
        assert row["principal_cashflow"] == pytest.approx(0.0, abs=1e-8)


def test_zcb_coupon_cashflow_is_zero() -> None:
    data = client.post(_URL, json=_ZCB_PAYLOAD).json()
    assert data["cashflows"][0]["coupon_cashflow"] == pytest.approx(0.0, abs=1e-8)


# ---------------------------------------------------------------------------
# PV sum matches dirty price
# ---------------------------------------------------------------------------


def test_pv_sum_matches_dirty_price_flat() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["dirty_price"], rel=1e-8)


def test_pv_sum_matches_dirty_price_bootstrapped() -> None:
    data = client.post(_URL, json=_BOOTSTRAP_PAYLOAD).json()
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["dirty_price"], rel=1e-8)


def test_pv_sum_matches_dirty_price_zcb() -> None:
    data = client.post(_URL, json=_ZCB_PAYLOAD).json()
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["dirty_price"], rel=1e-8)


def test_pv_sum_matches_dirty_price_semiannual() -> None:
    data = client.post(_URL, json=_SEMIANNUAL_PAYLOAD).json()
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["dirty_price"], rel=1e-8)


# ---------------------------------------------------------------------------
# Row sanity
# ---------------------------------------------------------------------------


def test_discount_factors_between_zero_and_one() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        assert 0.0 < row["discount_factor"] <= 1.0


def test_year_fractions_are_positive() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        assert row["year_fraction"] > 0.0


def test_time_to_payment_years_positive() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        assert row["time_to_payment_years"] > 0.0


def test_total_cashflow_equals_coupon_plus_principal() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        assert row["total_cashflow"] == pytest.approx(
            row["coupon_cashflow"] + row["principal_cashflow"], rel=1e-10
        )


def test_payment_dates_are_iso_strings() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    for row in data["cashflows"]:
        # Must be parseable YYYY-MM-DD
        from datetime import date as _date
        _date.fromisoformat(row["payment_date"])
        _date.fromisoformat(row["accrual_start"])
        _date.fromisoformat(row["accrual_end"])


def test_payment_dates_are_chronological() -> None:
    data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    dates = [r["payment_date"] for r in data["cashflows"]]
    assert dates == sorted(dates)


def test_dirty_price_matches_price_bond_endpoint() -> None:
    """Cashflow dirty_price must equal the price_bond endpoint dirty_price."""
    cf_data = client.post(_URL, json=_FLAT_PAYLOAD).json()
    price_data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert cf_data["dirty_price"] == pytest.approx(
        price_data["dirty_price"], rel=1e-8
    )


# ---------------------------------------------------------------------------
# Invalid input rejection
# ---------------------------------------------------------------------------


def test_invalid_coupon_rate_rejected() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 1.5}
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422


def test_invalid_face_value_zero_rejected() -> None:
    payload = {**_FLAT_PAYLOAD, "face_value": 0.0}
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422


def test_invalid_day_count_rejected() -> None:
    payload = {**_FLAT_PAYLOAD, "day_count": "ACTUAL_FAKE"}
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422


def test_invalid_coupon_frequency_rejected() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_frequency": "weekly"}
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422


def test_missing_required_field_rejected() -> None:
    # No maturity_date
    payload = {
        k: v for k, v in _FLAT_PAYLOAD.items() if k != "maturity_date"
    }
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422


def test_invalid_date_format_rejected() -> None:
    payload = {**_FLAT_PAYLOAD, "maturity_date": "29-01-2029"}
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 422
