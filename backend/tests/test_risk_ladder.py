"""
Tests for POST /risk/ladder — bucketed PV01 ladder endpoint.

Canon flat-curve trade (mirrors test_price.py canonical fixture):
  ZAR 5Y payer IRS, 250m notional, quarterly JIBAR, no fixed_rate supplied
  → default 8.5% fixed, flat 8% ZAR JIBAR proxy curve.

Canon bootstrapped curve (mirrors test_mixed_curve.py fixture):
  Deposits: 1M 7.8%, 3M 7.9%, 6M 8.0%
  FRAs    : 6x9 8.1%, 9x12 8.15%
  Swaps   : 2Y 8.2%, 3Y 8.3%, 5Y 8.5%
  valuation_date: "2024-01-15", payment_frequency: "annual", day_count: "ACT_365F"
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_ZAR_IRS_FIELDS = {
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 250_000_000,
}

_FLAT_PAYLOAD = {"extracted_fields": _ZAR_IRS_FIELDS}

_CANON_DEPOSITS = [
    {"tenor_months": 1, "rate": 0.078},
    {"tenor_months": 3, "rate": 0.079},
    {"tenor_months": 6, "rate": 0.080},
]
_CANON_FRAS = [
    {"start_months": 6, "end_months": 9, "rate": 0.081},
    {"start_months": 9, "end_months": 12, "rate": 0.0815},
]
_CANON_SWAPS = [
    {"tenor_years": 2, "par_rate": 0.082},
    {"tenor_years": 3, "par_rate": 0.083},
    {"tenor_years": 5, "par_rate": 0.085},
]

_CANON_CURVE_INPUTS = {
    "valuation_date": "2024-01-15",
    "payment_frequency": "annual",
    "day_count": "ACT_365F",
    "deposits": _CANON_DEPOSITS,
    "fras": _CANON_FRAS,
    "swaps": _CANON_SWAPS,
}

_BOOTSTRAP_PAYLOAD = {
    "extracted_fields": _ZAR_IRS_FIELDS,
    "curve_inputs": _CANON_CURVE_INPUTS,
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "currency",
    "bucket_pv01",
    "total_abs_pv01",
    "status",
    "assumptions",
    "warnings",
}

_DEFAULT_BUCKET_LABELS = {"1Y", "2Y", "3Y", "5Y", "7Y", "10Y"}


# ---------------------------------------------------------------------------
# Contract / shape
# ---------------------------------------------------------------------------


def test_flat_path_returns_200() -> None:
    assert client.post("/risk/ladder", json=_FLAT_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_missing_extracted_fields_returns_422() -> None:
    assert client.post("/risk/ladder", json={"request_id": "x"}).status_code == 422


# ---------------------------------------------------------------------------
# Status and indicative result — flat path
# ---------------------------------------------------------------------------


def test_flat_path_status_is_indicative() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_flat_path_bucket_keys() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert set(data["bucket_pv01"].keys()) == _DEFAULT_BUCKET_LABELS


def test_flat_path_in_range_buckets_nonzero() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    bp = data["bucket_pv01"]
    # 5Y quarterly curve covers 1Y…5Y; 7Y, 10Y are 0.0
    for label in ("1Y", "2Y", "3Y", "5Y"):
        assert bp[label] != 0.0, f"{label} should be non-zero"


def test_flat_path_payer_in_range_positive() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    bp = data["bucket_pv01"]
    for label in ("1Y", "2Y", "3Y", "5Y"):
        assert bp[label] > 0.0, f"payer {label} should be positive; got {bp[label]}"


def test_flat_path_far_buckets_zero() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    bp = data["bucket_pv01"]
    assert bp["7Y"] == 0.0
    assert bp["10Y"] == 0.0


# ---------------------------------------------------------------------------
# total_abs_pv01
# ---------------------------------------------------------------------------


def test_total_abs_pv01_non_negative() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert data["total_abs_pv01"] >= 0.0


def test_total_abs_pv01_equals_sum_of_abs_buckets() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    bp = data["bucket_pv01"]
    expected = sum(abs(v) for v in bp.values())
    assert abs(data["total_abs_pv01"] - expected) < 1e-9


def test_total_abs_pv01_is_positive_for_valid_swap() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert data["total_abs_pv01"] > 0.0


# ---------------------------------------------------------------------------
# request_id handling
# ---------------------------------------------------------------------------


def test_provided_request_id_is_echoed() -> None:
    payload = {"request_id": "risk-id-abc", "extracted_fields": _ZAR_IRS_FIELDS}
    data = client.post("/risk/ladder", json=payload).json()
    assert data["request_id"] == "risk-id-abc"


def test_generated_request_id_when_omitted() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_generated_request_ids_are_unique() -> None:
    r1 = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()["request_id"]
    r2 = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()["request_id"]
    assert r1 != r2


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


def test_bootstrap_path_returns_200() -> None:
    assert client.post("/risk/ladder", json=_BOOTSTRAP_PAYLOAD).status_code == 200


def test_bootstrap_path_status_is_indicative() -> None:
    data = client.post("/risk/ladder", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_bootstrap_path_bucket_keys() -> None:
    data = client.post("/risk/ladder", json=_BOOTSTRAP_PAYLOAD).json()
    assert set(data["bucket_pv01"].keys()) == _DEFAULT_BUCKET_LABELS


def test_bootstrap_path_total_abs_pv01_positive() -> None:
    data = client.post("/risk/ladder", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["total_abs_pv01"] > 0.0


# ---------------------------------------------------------------------------
# Custom bucket_years
# ---------------------------------------------------------------------------


def test_custom_bucket_years_works() -> None:
    payload = {**_FLAT_PAYLOAD, "bucket_years": [1, 3, 5]}
    data = client.post("/risk/ladder", json=payload).json()
    assert data["status"] == "indicative"
    assert set(data["bucket_pv01"].keys()) == {"1Y", "3Y", "5Y"}


def test_custom_single_bucket() -> None:
    payload = {**_FLAT_PAYLOAD, "bucket_years": [2]}
    data = client.post("/risk/ladder", json=payload).json()
    assert "2Y" in data["bucket_pv01"]
    assert data["bucket_pv01"]["2Y"] != 0.0


def test_invalid_bucket_years_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "bucket_years": [0]}
    resp = client.post("/risk/ladder", json=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Unsupported trade degrades gracefully
# ---------------------------------------------------------------------------


def test_unsupported_currency_returns_gracefully() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "USD"}
    data = client.post("/risk/ladder", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"
    assert data["bucket_pv01"] == {}
    assert data["total_abs_pv01"] == 0.0
    assert len(data["warnings"]) > 0


def test_unsupported_instrument_returns_gracefully() -> None:
    fields = {**_ZAR_IRS_FIELDS, "instrument_type": "bond"}
    data = client.post("/risk/ladder", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"
    assert data["bucket_pv01"] == {}


def test_unsupported_has_empty_total() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "EUR"}
    data = client.post("/risk/ladder", json={"extracted_fields": fields}).json()
    assert data["total_abs_pv01"] == 0.0


# ---------------------------------------------------------------------------
# Receiver swap — sign convention
# ---------------------------------------------------------------------------


def test_receiver_in_range_buckets_negative() -> None:
    fields = {**_ZAR_IRS_FIELDS, "direction": "receiver"}
    data = client.post("/risk/ladder", json={"extracted_fields": fields}).json()
    bp = data["bucket_pv01"]
    for label in ("1Y", "2Y", "3Y", "5Y"):
        assert bp[label] < 0.0, f"receiver {label} should be negative; got {bp[label]}"


# ---------------------------------------------------------------------------
# Regression: existing endpoints still work
# ---------------------------------------------------------------------------


def test_price_endpoint_still_works() -> None:
    from app.schemas.price import PricingRequest

    resp = client.post(
        "/price",
        json={
            "extracted_fields": _ZAR_IRS_FIELDS,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "indicative"


def test_quote_endpoint_still_works() -> None:
    resp = client.post(
        "/quote",
        json={"prompt": "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"},
    )
    assert resp.status_code == 200
