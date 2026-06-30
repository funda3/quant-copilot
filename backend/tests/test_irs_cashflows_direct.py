"""
test_irs_cashflows_direct — Integration tests for POST /price/irs/cashflows/direct.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys, correct types, request_id round-trip
  - Row content: rows non-empty, all row fields present, sum(pv_cashflow)==fixed_leg_pv,
    n_payments == len(cashflows), payment_date parseable ISO strings
  - Default fixed_rate behaviour (omitted → default 8.5% used, status indicative)
  - Explicit fixed_rate (different rate → different fixed_leg_pv)
  - curve_source explicit ("flat_fallback" / "bootstrapped_mixed_curve")
  - Assumptions content: non-empty, mentions fixed rate, bootstrap mentioned in boot path
  - Invalid payloads rejected via 422 (unsupported currency, floating_index, direction,
    out-of-range tenor, zero notional)
  - Cross-endpoint comparison: /price/irs/cashflows/direct and the existing
    /price/irs/cashflows return the same row count and matching fixed_leg_pv (within
    tolerance) for the same canonical ZAR IRS trade — proves the new endpoint is a
    cleaner surface over the same engine
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

_FLAT_PAYER = {
    "request_id": "cf-direct-flat",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 100_000_000,
    "fixed_rate": 0.085,
}

_FLAT_RECEIVER = {
    **_FLAT_PAYER,
    "request_id": "cf-direct-flat-recv",
    "direction": "receiver",
}

_BOOT_PAYER = {
    **_FLAT_PAYER,
    "request_id": "cf-direct-boot",
    "curve_inputs": {
        "valuation_date": "2026-03-24",
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
    },
}

# Matching extracted_fields payload for POST /price/irs/cashflows (legacy path)
_LEGACY_FLAT = {
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
        "fixed_rate": 0.085,
    }
}

_LEGACY_BOOT = {
    **_LEGACY_FLAT,
    "curve_inputs": _BOOT_PAYER["curve_inputs"],
}


# ===========================================================================
# TestHTTPStatus
# ===========================================================================

class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        assert resp.status_code == 200

    def test_missing_body_returns_422(self):
        resp = client.post("/price/irs/cashflows/direct", json={})
        assert resp.status_code == 422


# ===========================================================================
# TestResponseShape
# ===========================================================================

class TestResponseShape:
    def test_all_required_keys_present(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        data = resp.json()
        for key in (
            "request_id", "instrument_type", "currency", "status",
            "fixed_leg_pv", "n_payments", "cashflows",
            "curve_source", "assumptions", "warnings",
        ):
            assert key in data, f"Missing key: {key}"

    def test_status_is_indicative(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.json()["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.json()["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.json()["currency"] == "ZAR"

    def test_fixed_leg_pv_is_float(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["fixed_leg_pv"], float)

    def test_n_payments_is_int(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["n_payments"], int)

    def test_cashflows_is_list(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["cashflows"], list)

    def test_assumptions_is_list(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["assumptions"], list)

    def test_warnings_is_list(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["warnings"], list)

    def test_request_id_round_trip(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.json()["request_id"] == "cf-direct-flat"


# ===========================================================================
# TestRowContent
# ===========================================================================

class TestRowContent:
    def test_cashflows_non_empty_flat(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert len(resp.json()["cashflows"]) > 0

    def test_cashflows_non_empty_boot(self):
        resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        assert len(resp.json()["cashflows"]) > 0

    def test_row_has_all_required_fields(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        row = resp.json()["cashflows"][0]
        for field in (
            "payment_date", "accrual_start", "accrual_end",
            "year_fraction", "fixed_rate", "notional",
            "fixed_cashflow", "discount_factor", "pv_cashflow",
            "time_to_payment_years",
        ):
            assert field in row, f"Missing row field: {field}"

    def test_n_payments_equals_cashflow_len(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        data = resp.json()
        assert data["n_payments"] == len(data["cashflows"])

    def test_fixed_leg_pv_equals_sum_of_pv_cashflows(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        data = resp.json()
        pv_sum = round(sum(r["pv_cashflow"] for r in data["cashflows"]), 2)
        assert data["fixed_leg_pv"] == pytest.approx(pv_sum, abs=0.01)

    def test_payment_date_is_parseable_iso(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        for row in resp.json()["cashflows"]:
            datetime.fromisoformat(row["payment_date"])  # must not raise


# ===========================================================================
# TestDefaultFixedRate
# ===========================================================================

class TestDefaultFixedRate:
    def test_omitted_fixed_rate_returns_indicative(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs/cashflows/direct", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_omitted_fixed_rate_same_as_explicit_default(self):
        explicit_resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        payload_no_rate = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        default_resp = client.post("/price/irs/cashflows/direct", json=payload_no_rate)
        assert explicit_resp.json()["fixed_leg_pv"] == pytest.approx(
            default_resp.json()["fixed_leg_pv"], abs=0.01
        )

    def test_default_mentioned_in_assumptions(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs/cashflows/direct", json=payload)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "default" in text or "not provided" in text


# ===========================================================================
# TestExplicitFixedRate
# ===========================================================================

class TestExplicitFixedRate:
    def test_explicit_fixed_rate_works(self):
        payload = {**_FLAT_PAYER, "fixed_rate": 0.06}
        resp = client.post("/price/irs/cashflows/direct", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_different_fixed_rate_gives_different_pv(self):
        resp_high = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "fixed_rate": 0.10}
        )
        resp_low = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "fixed_rate": 0.06}
        )
        # Higher fixed rate → larger fixed cashflows → larger fixed_leg_pv
        assert resp_high.json()["fixed_leg_pv"] > resp_low.json()["fixed_leg_pv"]


# ===========================================================================
# TestCurveSource
# ===========================================================================

class TestCurveSource:
    def test_flat_path_curve_source(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert resp.json()["curve_source"] == "flat_fallback"

    def test_bootstrapped_path_curve_source(self):
        resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        assert resp.json()["curve_source"] == "bootstrapped_mixed_curve"


# ===========================================================================
# TestAssumptionsContent
# ===========================================================================

class TestAssumptionsContent:
    def test_assumptions_non_empty_flat(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        assert len(resp.json()["assumptions"]) > 0

    def test_assumptions_mention_fixed_rate(self):
        resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "fixed" in text and "rate" in text

    def test_boot_assumptions_mention_bootstrap(self):
        resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "bootstrap" in text


# ===========================================================================
# TestInvalidPayloads
# ===========================================================================

class TestInvalidPayloads:
    def test_unsupported_currency_rejected(self):
        resp = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "currency": "USD"}
        )
        assert resp.status_code == 422

    def test_unsupported_floating_index_rejected(self):
        resp = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "floating_index": "LIBOR"}
        )
        assert resp.status_code == 422

    def test_invalid_direction_rejected(self):
        resp = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "direction": "buy"}
        )
        assert resp.status_code == 422

    def test_tenor_out_of_range_rejected(self):
        resp = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "tenor": "100Y"}
        )
        assert resp.status_code == 422

    def test_zero_notional_rejected(self):
        resp = client.post(
            "/price/irs/cashflows/direct", json={**_FLAT_PAYER, "notional": 0}
        )
        assert resp.status_code == 422


# ===========================================================================
# TestCrossEndpointComparison
# ===========================================================================

class TestCrossEndpointComparison:
    """
    For the same canonical ZAR IRS trade, POST /price/irs/cashflows/direct
    and the existing POST /price/irs/cashflows (NLP path) must return the
    same row count and matching fixed_leg_pv — both delegate to the same
    quant_core.pricing.irs_pricer.irs_cashflow_schedule function with
    identical arguments.
    """

    def test_row_count_matches_legacy_flat(self):
        direct_resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        legacy_resp = client.post("/price/irs/cashflows", json=_LEGACY_FLAT)
        assert direct_resp.status_code == 200
        assert legacy_resp.status_code == 200
        assert direct_resp.json()["n_payments"] == legacy_resp.json()["n_payments"]

    def test_fixed_leg_pv_matches_legacy_flat(self):
        direct_resp = client.post("/price/irs/cashflows/direct", json=_FLAT_PAYER)
        legacy_resp = client.post("/price/irs/cashflows", json=_LEGACY_FLAT)
        assert direct_resp.json()["fixed_leg_pv"] == pytest.approx(
            legacy_resp.json()["fixed_leg_pv"], abs=0.01
        )

    def test_row_count_matches_legacy_bootstrapped(self):
        direct_resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        legacy_resp = client.post("/price/irs/cashflows", json=_LEGACY_BOOT)
        assert direct_resp.status_code == 200
        assert legacy_resp.status_code == 200
        assert direct_resp.json()["n_payments"] == legacy_resp.json()["n_payments"]

    def test_fixed_leg_pv_matches_legacy_bootstrapped(self):
        direct_resp = client.post("/price/irs/cashflows/direct", json=_BOOT_PAYER)
        legacy_resp = client.post("/price/irs/cashflows", json=_LEGACY_BOOT)
        assert direct_resp.json()["fixed_leg_pv"] == pytest.approx(
            legacy_resp.json()["fixed_leg_pv"], abs=0.01
        )
