"""
Tests for POST /price/irs/cashflows — IRS fixed-leg cashflow schedule endpoint.

Canonical flat-curve IRS:
  extracted_fields:
    instrument_type: irs
    currency:        ZAR
    floating_index:  JIBAR
    direction:       payer
    tenor:           5Y
    notional:        10_000_000
    fixed_rate:      0.085
    payment_frequency: quarterly
  curve: flat 8% ZAR JIBAR proxy (no curve_inputs)

Bootstrapped-curve tests use the same mixed curve fixture as test_price.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_URL = "/price/irs/cashflows"

_CANON_FIELDS = {
    "instrument_type": "irs",
    "currency": "ZAR",
    "floating_index": "JIBAR",
    "direction": "payer",
    "tenor": "5Y",
    "notional": 10_000_000,
    "fixed_rate": 0.085,
    "payment_frequency": "quarterly",
}

_FLAT_PAYLOAD = {"extracted_fields": _CANON_FIELDS}

_CURVE_INPUTS = {
    "valuation_date": "2024-01-15",
    "payment_frequency": "quarterly",
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

_BOOTSTRAP_PAYLOAD = {
    "extracted_fields": _CANON_FIELDS,
    "curve_inputs": _CURVE_INPUTS,
}

_TOP_LEVEL_KEYS = {
    "request_id",
    "instrument_type",
    "currency",
    "status",
    "fixed_leg_pv",
    "n_payments",
    "cashflows",
    "assumptions",
    "warnings",
}

_ROW_KEYS = {
    "payment_date",
    "accrual_start",
    "accrual_end",
    "year_fraction",
    "fixed_rate",
    "notional",
    "fixed_cashflow",
    "discount_factor",
    "pv_cashflow",
    "time_to_payment_years",
}


def _post(payload: dict) -> dict:
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Response shape — flat curve
# ---------------------------------------------------------------------------


def test_status_200_flat() -> None:
    resp = client.post(_URL, json=_FLAT_PAYLOAD)
    assert resp.status_code == 200


def test_top_level_keys_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert _TOP_LEVEL_KEYS.issubset(data.keys())


def test_status_is_indicative_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert data["status"] == "indicative"


def test_instrument_type_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert data["instrument_type"] == "irs"


def test_currency_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert data["currency"] == "ZAR"


def test_warnings_empty_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert data["warnings"] == []


def test_assumptions_non_empty_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert len(data["assumptions"]) > 0


def test_request_id_is_string_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_custom_request_id_preserved() -> None:
    payload = {**_FLAT_PAYLOAD, "request_id": "test-irs-cf-001"}
    data = _post(payload)
    assert data["request_id"] == "test-irs-cf-001"


# ---------------------------------------------------------------------------
# Row count
# ---------------------------------------------------------------------------


def test_5y_quarterly_has_20_rows() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert len(data["cashflows"]) == 20


def test_row_count_matches_n_payments() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert len(data["cashflows"]) == data["n_payments"]


def test_5y_annual_has_5_rows() -> None:
    fields = {**_CANON_FIELDS, "payment_frequency": "annual"}
    data = _post({"extracted_fields": fields})
    assert len(data["cashflows"]) == 5


def test_5y_semiannual_has_10_rows() -> None:
    fields = {**_CANON_FIELDS, "payment_frequency": "semiannual"}
    data = _post({"extracted_fields": fields})
    assert len(data["cashflows"]) == 10


def test_1y_quarterly_has_4_rows() -> None:
    fields = {**_CANON_FIELDS, "tenor": "1Y", "payment_frequency": "quarterly"}
    data = _post({"extracted_fields": fields})
    assert len(data["cashflows"]) == 4


def test_2y_semiannual_has_4_rows() -> None:
    fields = {**_CANON_FIELDS, "tenor": "2Y", "payment_frequency": "semiannual"}
    data = _post({"extracted_fields": fields})
    assert len(data["cashflows"]) == 4


# ---------------------------------------------------------------------------
# Row schema
# ---------------------------------------------------------------------------


def test_row_keys_present() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert _ROW_KEYS.issubset(row.keys())


def test_payment_dates_are_iso_strings() -> None:
    from datetime import date

    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        date.fromisoformat(row["payment_date"])  # raises if invalid


def test_accrual_start_accrual_end_are_iso_strings() -> None:
    from datetime import date

    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        date.fromisoformat(row["accrual_start"])
        date.fromisoformat(row["accrual_end"])


def test_accrual_end_equals_payment_date() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["accrual_end"] == row["payment_date"]


def test_year_fractions_positive() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["year_fraction"] > 0.0


def test_year_fractions_approx_quarterly() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert 0.20 < row["year_fraction"] < 0.30


def test_fixed_rate_matches_request() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["fixed_rate"] == pytest.approx(0.085, rel=1e-9)


def test_notional_matches_request() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["notional"] == pytest.approx(10_000_000.0, rel=1e-9)


def test_fixed_cashflow_equals_notional_rate_tau() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        expected = row["notional"] * row["fixed_rate"] * row["year_fraction"]
        assert row["fixed_cashflow"] == pytest.approx(expected, rel=1e-9)


def test_discount_factors_in_0_1() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert 0.0 < row["discount_factor"] < 1.0


def test_pv_cashflow_equals_cf_times_df() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["pv_cashflow"] == pytest.approx(
            row["fixed_cashflow"] * row["discount_factor"], rel=1e-9
        )


def test_time_to_payment_positive() -> None:
    data = _post(_FLAT_PAYLOAD)
    for row in data["cashflows"]:
        assert row["time_to_payment_years"] > 0.0


# ---------------------------------------------------------------------------
# Aggregate invariants
# ---------------------------------------------------------------------------


def test_pv_sum_matches_fixed_leg_pv_flat() -> None:
    data = _post(_FLAT_PAYLOAD)
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["fixed_leg_pv"], rel=1e-4)


def test_fixed_leg_pv_positive() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert data["fixed_leg_pv"] > 0.0


def test_payment_dates_ascending() -> None:
    data = _post(_FLAT_PAYLOAD)
    dates = [r["payment_date"] for r in data["cashflows"]]
    assert dates == sorted(dates)


def test_discount_factors_decreasing() -> None:
    data = _post(_FLAT_PAYLOAD)
    dfs = [r["discount_factor"] for r in data["cashflows"]]
    assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))


# ---------------------------------------------------------------------------
# Notional scaling
# ---------------------------------------------------------------------------


def test_fixed_leg_pv_scales_with_notional() -> None:
    fields_1m = {**_CANON_FIELDS, "notional": 1_000_000}
    fields_2m = {**_CANON_FIELDS, "notional": 2_000_000}
    data_1m = _post({"extracted_fields": fields_1m})
    data_2m = _post({"extracted_fields": fields_2m})
    assert data_2m["fixed_leg_pv"] == pytest.approx(2.0 * data_1m["fixed_leg_pv"], rel=1e-9)


def test_cashflow_rows_scale_with_notional() -> None:
    fields_1m = {**_CANON_FIELDS, "notional": 1_000_000}
    fields_3m = {**_CANON_FIELDS, "notional": 3_000_000}
    data_1m = _post({"extracted_fields": fields_1m})
    data_3m = _post({"extracted_fields": fields_3m})
    for r1, r3 in zip(data_1m["cashflows"], data_3m["cashflows"]):
        assert r3["fixed_cashflow"] == pytest.approx(3.0 * r1["fixed_cashflow"], rel=1e-9)


# ---------------------------------------------------------------------------
# Default fixed rate (no fixed_rate in extracted_fields)
# ---------------------------------------------------------------------------


def test_default_fixed_rate_used_when_not_provided() -> None:
    fields = {k: v for k, v in _CANON_FIELDS.items() if k != "fixed_rate"}
    data = _post({"extracted_fields": fields})
    assert data["status"] == "indicative"
    assert data["fixed_leg_pv"] > 0.0
    for row in data["cashflows"]:
        assert row["fixed_rate"] == pytest.approx(0.085, rel=1e-9)


# ---------------------------------------------------------------------------
# Receiver vs payer — cashflows identical (fixed-leg only)
# ---------------------------------------------------------------------------


def test_receiver_has_same_cashflows_as_payer() -> None:
    fields_payer = {**_CANON_FIELDS, "direction": "payer"}
    fields_recv = {**_CANON_FIELDS, "direction": "receiver"}
    data_p = _post({"extracted_fields": fields_payer})
    data_r = _post({"extracted_fields": fields_recv})
    assert data_p["fixed_leg_pv"] == pytest.approx(data_r["fixed_leg_pv"], rel=1e-9)
    for rp, rr in zip(data_p["cashflows"], data_r["cashflows"]):
        assert rp["pv_cashflow"] == pytest.approx(rr["pv_cashflow"], rel=1e-9)


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


def test_status_200_bootstrap() -> None:
    resp = client.post(_URL, json=_BOOTSTRAP_PAYLOAD)
    assert resp.status_code == 200


def test_status_indicative_bootstrap() -> None:
    data = _post(_BOOTSTRAP_PAYLOAD)
    assert data["status"] == "indicative"


def test_20_rows_bootstrap() -> None:
    data = _post(_BOOTSTRAP_PAYLOAD)
    assert len(data["cashflows"]) == 20


def test_pv_sum_matches_fixed_leg_pv_bootstrap() -> None:
    data = _post(_BOOTSTRAP_PAYLOAD)
    pv_sum = sum(r["pv_cashflow"] for r in data["cashflows"])
    assert pv_sum == pytest.approx(data["fixed_leg_pv"], rel=1e-4)


def test_row_keys_present_bootstrap() -> None:
    data = _post(_BOOTSTRAP_PAYLOAD)
    for row in data["cashflows"]:
        assert _ROW_KEYS.issubset(row.keys())


def test_assumptions_mention_bootstrapped() -> None:
    data = _post(_BOOTSTRAP_PAYLOAD)
    assert any("ootstrap" in a for a in data["assumptions"])


def test_assumptions_mention_flat_for_flat_path() -> None:
    data = _post(_FLAT_PAYLOAD)
    assert any("lat" in a for a in data["assumptions"])


# ---------------------------------------------------------------------------
# Unsupported / invalid payloads → 200 with status=unsupported
# ---------------------------------------------------------------------------


def test_unsupported_currency_returns_unsupported() -> None:
    fields = {**_CANON_FIELDS, "currency": "USD"}
    data = _post({"extracted_fields": fields})
    assert data["status"] == "unsupported"
    assert data["cashflows"] == []
    assert len(data["warnings"]) > 0


def test_unsupported_instrument_type_returns_unsupported() -> None:
    fields = {**_CANON_FIELDS, "instrument_type": "option"}
    data = _post({"extracted_fields": fields})
    assert data["status"] == "unsupported"


def test_invalid_tenor_returns_unsupported() -> None:
    fields = {**_CANON_FIELDS, "tenor": "ABC"}
    data = _post({"extracted_fields": fields})
    assert data["status"] == "unsupported"


def test_zero_notional_returns_unsupported() -> None:
    fields = {**_CANON_FIELDS, "notional": 0}
    data = _post({"extracted_fields": fields})
    assert data["status"] == "unsupported"


def test_missing_required_field_returns_422() -> None:
    # extracted_fields is required
    resp = client.post(_URL, json={})
    assert resp.status_code == 422
