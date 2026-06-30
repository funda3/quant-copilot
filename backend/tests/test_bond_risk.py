"""
Tests for POST /risk/bond — fixed-rate bond DV01 and modified duration endpoint.

Canonical flat-curve bond:
  valuation_date: 2024-01-01
  issue_date:     2024-01-01
  maturity_date:  2029-01-01  (5Y)
  face_value:     1_000_000
  coupon_rate:    0.08
  coupon_frequency: annual
  day_count:      ACT_365F
  curve: flat 8% proxy
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
    "dirty_price",
    "dv01",
    "modified_duration",
    "macaulay_duration",
    "convexity",
    "assumptions",
    "warnings",
}


# ---------------------------------------------------------------------------
# Contract / shape
# ---------------------------------------------------------------------------


def test_flat_path_returns_200() -> None:
    assert client.post("/risk/bond", json=_FLAT_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_flat_path_status_is_indicative() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_flat_path_instrument_type_is_bond() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["instrument_type"] == "bond"


# ---------------------------------------------------------------------------
# Schema validation — invalid payloads rejected
# ---------------------------------------------------------------------------


def test_missing_valuation_date_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "valuation_date"}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_missing_maturity_date_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "maturity_date"}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_missing_face_value_returns_422() -> None:
    payload = {k: v for k, v in _FLAT_PAYLOAD.items() if k != "face_value"}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_negative_face_value_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "face_value": -1.0}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_coupon_rate_above_one_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 1.5}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_invalid_date_format_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "valuation_date": "01/01/2024"}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_unsupported_frequency_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_frequency": "monthly"}
    assert client.post("/risk/bond", json=payload).status_code == 422


def test_unsupported_day_count_returns_422() -> None:
    payload = {**_FLAT_PAYLOAD, "day_count": "ACT_252"}
    assert client.post("/risk/bond", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# DV01 correctness — flat path
# ---------------------------------------------------------------------------


def test_dv01_is_positive() -> None:
    """Rate rise decreases bond value → DV01 > 0."""
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["dv01"] > 0.0


def test_dv01_is_float() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["dv01"], float)


def test_doubling_face_doubles_dv01() -> None:
    d1 = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d2 = client.post("/risk/bond", json={**_FLAT_PAYLOAD, "face_value": 2_000_000.0}).json()
    assert abs(d2["dv01"] - 2.0 * d1["dv01"]) < 1e-2


def test_longer_maturity_higher_dv01() -> None:
    d5y = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d10y = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "maturity_date": "2034-01-01"}
    ).json()
    assert d10y["dv01"] > d5y["dv01"]


# ---------------------------------------------------------------------------
# Modified duration correctness — flat path
# ---------------------------------------------------------------------------


def test_modified_duration_is_positive() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["modified_duration"] > 0.0


def test_modified_duration_is_float() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["modified_duration"], float)


def test_modified_duration_unchanged_by_face() -> None:
    """Duration is face-neutral."""
    d1 = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d2 = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "face_value": 5_000_000.0}
    ).json()
    assert abs(d1["modified_duration"] - d2["modified_duration"]) < 1e-6


def test_longer_maturity_higher_duration() -> None:
    d5y = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d10y = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "maturity_date": "2034-01-01"}
    ).json()
    assert d10y["modified_duration"] > d5y["modified_duration"]


def test_modified_duration_consistent_with_dv01() -> None:
    """modified_duration == dv01 / dirty_price * 10,000 (to float precision)."""
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    expected = data["dv01"] / data["dirty_price"] * 10_000.0
    assert abs(data["modified_duration"] - expected) < 1e-6


# ---------------------------------------------------------------------------
# Zero-coupon bond
# ---------------------------------------------------------------------------


def test_zero_coupon_dv01_positive() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/risk/bond", json=payload).json()
    assert data["dv01"] > 0.0


def test_zero_coupon_duration_positive() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/risk/bond", json=payload).json()
    assert data["modified_duration"] > 0.0


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


def test_bootstrap_path_returns_200() -> None:
    assert client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).status_code == 200


def test_bootstrap_path_status_is_indicative() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_bootstrap_path_dv01_positive() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["dv01"] > 0.0


def test_bootstrap_path_duration_positive() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["modified_duration"] > 0.0


def test_bootstrap_path_dv01_differs_from_flat() -> None:
    """Different curve → different DV01."""
    flat_dv01 = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()["dv01"]
    bs_dv01 = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()["dv01"]
    assert abs(flat_dv01 - bs_dv01) > 0.01


# ---------------------------------------------------------------------------
# Assumptions and warnings
# ---------------------------------------------------------------------------


def test_flat_path_assumptions_non_empty() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert len(data["assumptions"]) > 0


def test_flat_path_warnings_empty() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["warnings"] == []


def test_bootstrap_assumptions_mention_bootstrap() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "bootstrap" in combined


def test_assumptions_mention_dv01() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "dv01" in combined


# ---------------------------------------------------------------------------
# request_id handling
# ---------------------------------------------------------------------------


def test_provided_request_id_echoed() -> None:
    payload = {**_FLAT_PAYLOAD, "request_id": "risk-test-001"}
    data = client.post("/risk/bond", json=payload).json()
    assert data["request_id"] == "risk-test-001"


def test_generated_request_id_when_omitted() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


# ---------------------------------------------------------------------------
# Convexity — flat path
# ---------------------------------------------------------------------------


def test_flat_path_convexity_present() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert "convexity" in data


def test_flat_path_convexity_positive() -> None:
    """Convexity must be strictly positive for any standard bond."""
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["convexity"] > 0.0


def test_flat_path_convexity_is_float() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["convexity"], float)


def test_longer_maturity_higher_convexity() -> None:
    d5y = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d10y = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "maturity_date": "2034-01-01"}
    ).json()
    assert d10y["convexity"] > d5y["convexity"]


def test_zero_coupon_convexity_positive() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/risk/bond", json=payload).json()
    assert data["convexity"] > 0.0


def test_convexity_face_neutral() -> None:
    """Convexity is face-value-neutral (normalised by P0 in the formula)."""
    d1 = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d2 = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "face_value": 5_000_000.0}
    ).json()
    assert abs(d1["convexity"] - d2["convexity"]) < 1e-6


# ---------------------------------------------------------------------------
# Convexity — bootstrapped path
# ---------------------------------------------------------------------------


def test_bootstrap_path_convexity_positive() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["convexity"] > 0.0


def test_bootstrap_path_convexity_present() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert "convexity" in data


def test_bootstrap_path_convexity_differs_from_flat() -> None:
    """Different discount curve → different convexity."""
    flat_cx = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()["convexity"]
    bs_cx = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()["convexity"]
    assert abs(flat_cx - bs_cx) > 1e-4


# ---------------------------------------------------------------------------
# Assumptions mention convexity
# ---------------------------------------------------------------------------


def test_assumptions_mention_convexity() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "convexity" in combined


# ---------------------------------------------------------------------------
# Regressions: existing endpoints still work
# ---------------------------------------------------------------------------


def test_healthz_still_works() -> None:
    assert client.get("/healthz").status_code == 200


def test_price_bond_still_works() -> None:
    data = client.post("/price/bond", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


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
    assert client.post("/risk/ladder", json=payload).status_code == 200


# ---------------------------------------------------------------------------
# Macaulay Duration — flat path
# ---------------------------------------------------------------------------


def test_flat_path_macaulay_present() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert "macaulay_duration" in data


def test_flat_path_macaulay_positive() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["macaulay_duration"] > 0.0


def test_flat_path_macaulay_is_float() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["macaulay_duration"], float)


def test_macaulay_ge_modified_duration() -> None:
    """Macaulay Duration >= Modified Duration for positive yield."""
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    assert data["macaulay_duration"] >= data["modified_duration"]


def test_macaulay_face_neutral() -> None:
    """Macaulay Duration is independent of face value."""
    d1 = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d2 = client.post("/risk/bond", json={**_FLAT_PAYLOAD, "face_value": 5_000_000.0}).json()
    assert abs(d1["macaulay_duration"] - d2["macaulay_duration"]) < 1e-6


def test_zero_coupon_macaulay_positive() -> None:
    payload = {**_FLAT_PAYLOAD, "coupon_rate": 0.0}
    data = client.post("/risk/bond", json=payload).json()
    assert data["macaulay_duration"] > 0.0


def test_longer_maturity_higher_macaulay() -> None:
    d5y = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    d10y = client.post(
        "/risk/bond", json={**_FLAT_PAYLOAD, "maturity_date": "2034-01-01"}
    ).json()
    assert d10y["macaulay_duration"] > d5y["macaulay_duration"]


# ---------------------------------------------------------------------------
# Macaulay Duration — bootstrapped path
# ---------------------------------------------------------------------------


def test_bootstrap_path_macaulay_present() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert "macaulay_duration" in data


def test_bootstrap_path_macaulay_positive() -> None:
    data = client.post("/risk/bond", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["macaulay_duration"] > 0.0


# ---------------------------------------------------------------------------
# Assumptions mention macaulay
# ---------------------------------------------------------------------------


def test_assumptions_mention_macaulay() -> None:
    data = client.post("/risk/bond", json=_FLAT_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "macaulay" in combined
