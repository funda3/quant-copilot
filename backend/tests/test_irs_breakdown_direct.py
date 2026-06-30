"""
test_irs_breakdown_direct — Integration tests for POST /price/irs/breakdown/direct.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys, correct types, request_id round-trip
  - NPV components: fixed_leg_pv > 0, floating_leg_pv > 0, n_payments > 0
  - NPV sign convention: payer npv sign, receiver npv sign (opposite)
  - Default fixed_rate behaviour (omitted → default 8.5% used, status indicative)
  - Explicit fixed_rate (different rate → different fixed_leg_pv)
  - curve_source explicit ("flat_fallback" / "bootstrapped_mixed_curve")
  - floating_leg_method field present and non-empty
  - Assumptions content: non-empty, mentions fixed rate, bootstrap mentioned in boot path
  - Invalid payloads rejected via 422 (unsupported currency, floating_index, direction,
    out-of-range tenor, zero notional)
  - Cross-endpoint comparison: /price/irs/breakdown/direct and the existing
    /price/irs/breakdown return the same fixed_leg_pv, floating_leg_pv, npv, and
    n_payments within tolerance — proves the new endpoint is a cleaner surface over
    the same engine
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

_FLAT_PAYER = {
    "request_id": "bd-direct-flat",
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
    "request_id": "bd-direct-flat-recv",
    "direction": "receiver",
}

_BOOT_PAYER = {
    **_FLAT_PAYER,
    "request_id": "bd-direct-boot",
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

# Matching extracted_fields payload for POST /price/irs/breakdown (legacy path)
_LEGACY_FLAT = {
    "extracted_fields": {k: v for k, v in _FLAT_PAYER.items() if k != "request_id"},
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
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        resp = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER)
        assert resp.status_code == 200

    def test_missing_body_returns_422(self):
        resp = client.post("/price/irs/breakdown/direct", json={})
        assert resp.status_code == 422


# ===========================================================================
# TestResponseShape
# ===========================================================================

class TestResponseShape:
    def test_all_required_keys_present(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        data = resp.json()
        for key in (
            "request_id", "instrument_type", "currency", "status",
            "fixed_leg_pv", "floating_leg_pv", "npv", "n_payments",
            "curve_source", "floating_leg_method", "assumptions", "warnings",
        ):
            assert key in data, f"Missing key: {key}"

    def test_status_is_indicative(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["currency"] == "ZAR"

    def test_fixed_leg_pv_is_float(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["fixed_leg_pv"], float)

    def test_floating_leg_pv_is_float(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["floating_leg_pv"], float)

    def test_npv_is_float(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["npv"], float)

    def test_n_payments_is_int(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["n_payments"], int)

    def test_assumptions_is_list(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["assumptions"], list)

    def test_warnings_is_list(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert isinstance(resp.json()["warnings"], list)

    def test_request_id_round_trip(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["request_id"] == "bd-direct-flat"


# ===========================================================================
# TestNPVComponents
# ===========================================================================

class TestNPVComponents:
    def test_fixed_leg_pv_positive_flat(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["fixed_leg_pv"] > 0

    def test_floating_leg_pv_positive_flat(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["floating_leg_pv"] > 0

    def test_n_payments_positive_flat(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["n_payments"] > 0

    def test_payer_receiver_npv_opposite_sign(self):
        payer = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER).json()
        recv = client.post("/price/irs/breakdown/direct", json=_FLAT_RECEIVER).json()
        # NPV for payer and receiver should be opposite signs (or equal magnitude opposite)
        assert (payer["npv"] > 0) != (recv["npv"] > 0) or (
            abs(payer["npv"] + recv["npv"]) < 1.0
        )

    def test_npv_equals_float_minus_fixed_for_payer(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        d = resp.json()
        expected = round(d["floating_leg_pv"] - d["fixed_leg_pv"], 2)
        assert d["npv"] == pytest.approx(expected, abs=0.01)

    def test_floating_leg_method_non_empty(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["floating_leg_method"] != ""


# ===========================================================================
# TestDefaultFixedRate
# ===========================================================================

class TestDefaultFixedRate:
    def test_omitted_fixed_rate_returns_indicative(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs/breakdown/direct", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_omitted_fixed_rate_same_as_explicit_default(self):
        explicit_resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        payload_no_rate = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        default_resp = client.post("/price/irs/breakdown/direct", json=payload_no_rate)
        assert explicit_resp.json()["fixed_leg_pv"] == pytest.approx(
            default_resp.json()["fixed_leg_pv"], abs=0.01
        )

    def test_default_mentioned_in_assumptions(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs/breakdown/direct", json=payload)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "default" in text or "not provided" in text


# ===========================================================================
# TestExplicitFixedRate
# ===========================================================================

class TestExplicitFixedRate:
    def test_explicit_fixed_rate_works(self):
        payload = {**_FLAT_PAYER, "fixed_rate": 0.06}
        resp = client.post("/price/irs/breakdown/direct", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_higher_fixed_rate_gives_larger_fixed_leg_pv(self):
        resp_high = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "fixed_rate": 0.10}
        )
        resp_low = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "fixed_rate": 0.06}
        )
        # Higher fixed rate → larger fixed cashflows → larger fixed_leg_pv
        assert resp_high.json()["fixed_leg_pv"] > resp_low.json()["fixed_leg_pv"]


# ===========================================================================
# TestCurveSource
# ===========================================================================

class TestCurveSource:
    def test_flat_path_curve_source(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert resp.json()["curve_source"] == "flat_fallback"

    def test_bootstrapped_path_curve_source(self):
        resp = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER)
        assert resp.json()["curve_source"] == "bootstrapped_mixed_curve"


# ===========================================================================
# TestAssumptionsContent
# ===========================================================================

class TestAssumptionsContent:
    def test_assumptions_non_empty_flat(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        assert len(resp.json()["assumptions"]) > 0

    def test_assumptions_mention_fixed_rate(self):
        resp = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "fixed" in text and "rate" in text

    def test_boot_assumptions_mention_bootstrap(self):
        resp = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "bootstrap" in text


# ===========================================================================
# TestInvalidPayloads
# ===========================================================================

class TestInvalidPayloads:
    def test_unsupported_currency_rejected(self):
        resp = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "currency": "USD"}
        )
        assert resp.status_code == 422

    def test_unsupported_floating_index_rejected(self):
        resp = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "floating_index": "LIBOR"}
        )
        assert resp.status_code == 422

    def test_invalid_direction_rejected(self):
        resp = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "direction": "buy"}
        )
        assert resp.status_code == 422

    def test_tenor_out_of_range_rejected(self):
        resp = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "tenor": "100Y"}
        )
        assert resp.status_code == 422

    def test_zero_notional_rejected(self):
        resp = client.post(
            "/price/irs/breakdown/direct", json={**_FLAT_PAYER, "notional": 0}
        )
        assert resp.status_code == 422


# ===========================================================================
# TestCrossEndpointComparison
# ===========================================================================

class TestCrossEndpointComparison:
    """
    For the same canonical ZAR IRS trade, POST /price/irs/breakdown/direct
    and the existing POST /price/irs/breakdown (NLP path) must return the
    same fixed_leg_pv, floating_leg_pv, npv, and n_payments — both delegate
    to the same quant_core.pricing.irs_pricer.irs_valuation_breakdown function
    with identical arguments.
    """

    def test_fixed_leg_pv_matches_legacy_flat(self):
        direct = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_FLAT).json()
        assert direct["fixed_leg_pv"] == pytest.approx(legacy["fixed_leg_pv"], abs=0.01)

    def test_floating_leg_pv_matches_legacy_flat(self):
        direct = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_FLAT).json()
        assert direct["floating_leg_pv"] == pytest.approx(legacy["floating_leg_pv"], abs=0.01)

    def test_npv_matches_legacy_flat(self):
        direct = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_FLAT).json()
        assert direct["npv"] == pytest.approx(legacy["npv"], abs=0.01)

    def test_n_payments_matches_legacy_flat(self):
        direct = client.post("/price/irs/breakdown/direct", json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_FLAT).json()
        assert direct["n_payments"] == legacy["n_payments"]

    def test_fixed_leg_pv_matches_legacy_bootstrapped(self):
        direct = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_BOOT).json()
        assert direct["fixed_leg_pv"] == pytest.approx(legacy["fixed_leg_pv"], abs=0.01)

    def test_floating_leg_pv_matches_legacy_bootstrapped(self):
        direct = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_BOOT).json()
        assert direct["floating_leg_pv"] == pytest.approx(legacy["floating_leg_pv"], abs=0.01)

    def test_npv_matches_legacy_bootstrapped(self):
        direct = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_BOOT).json()
        assert direct["npv"] == pytest.approx(legacy["npv"], abs=0.01)

    def test_n_payments_matches_legacy_bootstrapped(self):
        direct = client.post("/price/irs/breakdown/direct", json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/breakdown", json=_LEGACY_BOOT).json()
        assert direct["n_payments"] == legacy["n_payments"]
