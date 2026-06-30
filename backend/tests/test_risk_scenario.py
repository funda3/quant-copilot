"""
Tests for POST /risk/scenario — parallel curve-shift scenario endpoint.

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
    "status",
    "scenario_npv",
    "base_npv",
    "assumptions",
    "warnings",
}

_DEFAULT_SCENARIO_LABELS = {"-200bp", "-100bp", "-50bp", "0bp", "50bp", "100bp", "200bp"}


# ---------------------------------------------------------------------------
# Contract / shape
# ---------------------------------------------------------------------------


def test_flat_path_returns_200() -> None:
    assert client.post("/risk/scenario", json=_FLAT_PAYLOAD).status_code == 200


def test_response_has_required_keys() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    for key in _REQUIRED_KEYS:
        assert key in data, f"missing key: {key}"


def test_missing_extracted_fields_returns_422() -> None:
    assert client.post("/risk/scenario", json={"request_id": "x"}).status_code == 422


# ---------------------------------------------------------------------------
# Status and default scenario — flat path
# ---------------------------------------------------------------------------


def test_flat_path_status_is_indicative() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_flat_path_default_scenario_keys() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert set(data["scenario_npv"].keys()) == _DEFAULT_SCENARIO_LABELS


def test_flat_path_base_npv_is_float() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["base_npv"], float)


def test_flat_path_scenario_npv_values_are_floats() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    for label, val in data["scenario_npv"].items():
        assert isinstance(val, float), f"scenario_npv[{label!r}] should be float"


# ---------------------------------------------------------------------------
# 0bp equals base_npv
# ---------------------------------------------------------------------------


def test_zero_shift_equals_base_npv() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert abs(data["scenario_npv"]["0bp"] - data["base_npv"]) < 1e-6


def test_zero_shift_custom_payload_equals_base_npv() -> None:
    payload = {**_FLAT_PAYLOAD, "shift_bps": [0]}
    data = client.post("/risk/scenario", json=payload).json()
    assert abs(data["scenario_npv"]["0bp"] - data["base_npv"]) < 1e-6


# ---------------------------------------------------------------------------
# Monotonicity — payer
# ---------------------------------------------------------------------------


def test_flat_path_payer_npv_monotonically_increases() -> None:
    """Payer IRS: NPV should increase as the rate shift increases."""
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    snpv = data["scenario_npv"]
    shifts_sorted = sorted(int(k.replace("bp", "")) for k in snpv)
    npvs = [snpv[f"{s}bp"] for s in shifts_sorted]
    for i in range(1, len(npvs)):
        assert npvs[i] > npvs[i - 1], (
            f"Payer NPV should be strictly increasing; "
            f"shift {shifts_sorted[i - 1]}bp={npvs[i - 1]:.2f} "
            f">= shift {shifts_sorted[i]}bp={npvs[i]:.2f}"
        )


def test_flat_path_positive_shift_above_base() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert data["scenario_npv"]["200bp"] > data["base_npv"]


def test_flat_path_negative_shift_below_base() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert data["scenario_npv"]["-200bp"] < data["base_npv"]


# ---------------------------------------------------------------------------
# Custom shift_bps
# ---------------------------------------------------------------------------


def test_custom_shift_bps_produces_correct_labels() -> None:
    payload = {**_FLAT_PAYLOAD, "shift_bps": [-100, 0, 100]}
    data = client.post("/risk/scenario", json=payload).json()
    assert set(data["scenario_npv"].keys()) == {"-100bp", "0bp", "100bp"}


def test_custom_shift_bps_single_shift() -> None:
    payload = {**_FLAT_PAYLOAD, "shift_bps": [50]}
    data = client.post("/risk/scenario", json=payload).json()
    assert set(data["scenario_npv"].keys()) == {"50bp"}
    assert isinstance(data["scenario_npv"]["50bp"], float)


# ---------------------------------------------------------------------------
# request_id handling
# ---------------------------------------------------------------------------


def test_provided_request_id_is_echoed() -> None:
    payload = {"request_id": "scen-abc-123", "extracted_fields": _ZAR_IRS_FIELDS}
    data = client.post("/risk/scenario", json=payload).json()
    assert data["request_id"] == "scen-abc-123"


def test_generated_request_id_when_omitted() -> None:
    data = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_generated_request_ids_are_unique() -> None:
    r1 = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()["request_id"]
    r2 = client.post("/risk/scenario", json=_FLAT_PAYLOAD).json()["request_id"]
    assert r1 != r2


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


def test_bootstrap_path_returns_200() -> None:
    assert client.post("/risk/scenario", json=_BOOTSTRAP_PAYLOAD).status_code == 200


def test_bootstrap_path_status_is_indicative() -> None:
    data = client.post("/risk/scenario", json=_BOOTSTRAP_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_bootstrap_path_default_scenario_keys() -> None:
    data = client.post("/risk/scenario", json=_BOOTSTRAP_PAYLOAD).json()
    assert set(data["scenario_npv"].keys()) == _DEFAULT_SCENARIO_LABELS


def test_bootstrap_path_zero_shift_equals_base_npv() -> None:
    data = client.post("/risk/scenario", json=_BOOTSTRAP_PAYLOAD).json()
    assert abs(data["scenario_npv"]["0bp"] - data["base_npv"]) < 1e-6


def test_bootstrap_path_payer_npv_monotone() -> None:
    data = client.post("/risk/scenario", json=_BOOTSTRAP_PAYLOAD).json()
    snpv = data["scenario_npv"]
    shifts_sorted = sorted(int(k.replace("bp", "")) for k in snpv)
    npvs = [snpv[f"{s}bp"] for s in shifts_sorted]
    for i in range(1, len(npvs)):
        assert npvs[i] > npvs[i - 1]


# ---------------------------------------------------------------------------
# Unsupported trade — graceful degradation
# ---------------------------------------------------------------------------


def test_unsupported_instrument_returns_unsupported_status() -> None:
    payload = {
        "extracted_fields": {
            "instrument_type": "bond",
            "currency": "ZAR",
            "direction": "payer",
            "floating_index": "JIBAR",
            "payment_frequency": "annual",
            "tenor": "5Y",
            "notional": 1_000_000,
        }
    }
    data = client.post("/risk/scenario", json=payload).json()
    assert data["status"] == "unsupported"
    assert data["scenario_npv"] == {}
    assert data["base_npv"] == 0.0
    assert len(data["warnings"]) > 0


def test_unsupported_currency_returns_unsupported_status() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "USD"}
    data = client.post("/risk/scenario", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


# ---------------------------------------------------------------------------
# Regression: existing endpoints still work
# ---------------------------------------------------------------------------


def test_health_still_works() -> None:
    assert client.get("/healthz").status_code == 200


def test_ladder_still_works() -> None:
    data = client.post("/risk/ladder", json=_FLAT_PAYLOAD).json()
    assert data["status"] == "indicative"
    assert "bucket_pv01" in data
