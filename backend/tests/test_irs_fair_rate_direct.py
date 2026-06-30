"""
test_irs_fair_rate_direct — Integration tests for POST /price/irs/fair-rate/direct.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys present, correct types, request_id round-trip
  - fair_rate positive, < 1, in sensible range (0.01–0.30)
  - fair_rate direction-invariant: payer == receiver for the same trade
  - fixed_leg_annuity > 0
  - fixed_rate supplied: warning included, solving still produces a valid fair_rate
  - fixed_rate omitted: works fine (no validation error, no warning)
  - curve_source explicit ("flat_fallback" / "bootstrapped_mixed_curve")
  - Assumptions list non-empty, mentions fair-rate method and float-leg method
  - Bootstrapped assumptions mention "bootstrap"
  - Invalid payloads rejected via 422 (unsupported currency, floating_index,
    direction, out-of-range tenor, zero notional)
  - Cross-endpoint comparison: /price/irs/fair-rate/direct and the existing
    /price/irs/fair-rate return the same fair_rate within tolerance (1e-6) —
    proves the new endpoint is a cleaner surface over the same engine
  - Pricing consistency: solve fair_rate via direct endpoint, then price the
    same IRS via POST /price/irs with that fair_rate as fixed_rate — NPV ≈ 0
    (abs < 100 on a 100 M notional, i.e. < 0.0001%)
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
    "request_id": "fr-direct-flat",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 100_000_000,
}

_FLAT_RECEIVER = {
    **_FLAT_PAYER,
    "request_id": "fr-direct-flat-recv",
    "direction": "receiver",
}

_FLAT_PAYER_WITH_RATE = {
    **_FLAT_PAYER,
    "request_id": "fr-direct-flat-with-rate",
    "fixed_rate": 0.085,
}

_BOOT_CURVE = {
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
}

_BOOT_PAYER = {
    **_FLAT_PAYER,
    "request_id": "fr-direct-boot",
    "curve_inputs": _BOOT_CURVE,
}

_BOOT_PAYER_WITH_RATE = {
    **_BOOT_PAYER,
    "request_id": "fr-direct-boot-with-rate",
    "fixed_rate": 0.090,
}

_URL = "/price/irs/fair-rate/direct"

# Legacy endpoint payloads (for cross-endpoint comparison)
_LEGACY_FLAT = {
    "request_id": "fr-legacy-flat",
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
    },
}

_LEGACY_BOOT = {
    "request_id": "fr-legacy-boot",
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
    },
    "curve_inputs": _BOOT_CURVE,
}


# ===========================================================================
# Class 1: HTTP Status
# ===========================================================================

class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        resp = client.post(_URL, json=_BOOT_PAYER)
        assert resp.status_code == 200

    def test_empty_body_returns_422(self):
        resp = client.post(_URL, json={})
        assert resp.status_code == 422


# ===========================================================================
# Class 2: Response Shape
# ===========================================================================

class TestResponseShape:
    """Every required key must be present with the correct type."""

    def _data(self) -> dict:
        return client.post(_URL, json=_FLAT_PAYER).json()

    def test_request_id_present(self):
        assert "request_id" in self._data()

    def test_instrument_type_present(self):
        assert "instrument_type" in self._data()

    def test_currency_present(self):
        assert "currency" in self._data()

    def test_status_present(self):
        assert "status" in self._data()

    def test_fair_rate_present(self):
        assert "fair_rate" in self._data()

    def test_fixed_leg_annuity_present(self):
        assert "fixed_leg_annuity" in self._data()

    def test_curve_source_present(self):
        assert "curve_source" in self._data()

    def test_assumptions_present(self):
        assert "assumptions" in self._data()

    def test_warnings_present(self):
        assert "warnings" in self._data()

    def test_fair_rate_is_float(self):
        assert isinstance(self._data()["fair_rate"], float)

    def test_fixed_leg_annuity_is_float(self):
        assert isinstance(self._data()["fixed_leg_annuity"], float)

    def test_request_id_round_trip(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["request_id"] == "fr-direct-flat"

    def test_status_is_indicative(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["currency"] == "ZAR"


# ===========================================================================
# Class 3: Fair Rate Values
# ===========================================================================

class TestFairRateValues:
    """Fair rate must be positive, below 1, and in a sensible range."""

    def test_flat_fair_rate_positive(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["fair_rate"] > 0.0

    def test_flat_fair_rate_below_one(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["fair_rate"] < 1.0

    def test_flat_fair_rate_sensible_range(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        fr = resp.json()["fair_rate"]
        assert 0.01 <= fr <= 0.30, f"fair_rate {fr} outside sensible range"

    def test_boot_fair_rate_positive(self):
        resp = client.post(_URL, json=_BOOT_PAYER)
        assert resp.json()["fair_rate"] > 0.0

    def test_fixed_leg_annuity_positive_flat(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["fixed_leg_annuity"] > 0.0

    def test_fixed_leg_annuity_positive_boot(self):
        resp = client.post(_URL, json=_BOOT_PAYER)
        assert resp.json()["fixed_leg_annuity"] > 0.0

    def test_fair_rate_direction_invariant_flat(self):
        """Payer and receiver on the same trade must produce the same fair rate."""
        payer = client.post(_URL, json=_FLAT_PAYER).json()
        receiver = client.post(_URL, json=_FLAT_RECEIVER).json()
        assert abs(payer["fair_rate"] - receiver["fair_rate"]) < 1e-8


# ===========================================================================
# Class 4: Fixed Rate Handling
# ===========================================================================

class TestFixedRateHandling:
    def test_fixed_rate_supplied_still_returns_200(self):
        resp = client.post(_URL, json=_FLAT_PAYER_WITH_RATE)
        assert resp.status_code == 200

    def test_fixed_rate_supplied_emits_warning(self):
        resp = client.post(_URL, json=_FLAT_PAYER_WITH_RATE)
        data = resp.json()
        assert len(data["warnings"]) > 0

    def test_fixed_rate_supplied_warning_mentions_ignored(self):
        resp = client.post(_URL, json=_FLAT_PAYER_WITH_RATE)
        warning_text = " ".join(resp.json()["warnings"]).lower()
        assert "ignored" in warning_text

    def test_fixed_rate_absent_no_warning(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["warnings"] == []

    def test_fixed_rate_supplied_same_fair_rate_as_omitted(self):
        """fair_rate must be independent of the pre-specified fixed_rate."""
        without = client.post(_URL, json=_FLAT_PAYER).json()["fair_rate"]
        with_rate = client.post(_URL, json=_FLAT_PAYER_WITH_RATE).json()["fair_rate"]
        assert abs(without - with_rate) < 1e-8

    def test_boot_fixed_rate_supplied_still_returns_200(self):
        resp = client.post(_URL, json=_BOOT_PAYER_WITH_RATE)
        assert resp.status_code == 200

    def test_boot_fixed_rate_supplied_emits_warning(self):
        resp = client.post(_URL, json=_BOOT_PAYER_WITH_RATE)
        assert len(resp.json()["warnings"]) > 0


# ===========================================================================
# Class 5: Curve Source
# ===========================================================================

class TestCurveSource:
    def test_flat_curve_source(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert resp.json()["curve_source"] == "flat_fallback"

    def test_boot_curve_source(self):
        resp = client.post(_URL, json=_BOOT_PAYER)
        assert resp.json()["curve_source"] == "bootstrapped_mixed_curve"


# ===========================================================================
# Class 6: Assumptions Content
# ===========================================================================

class TestAssumptionsContent:
    def test_flat_assumptions_non_empty(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        assert len(resp.json()["assumptions"]) > 0

    def test_flat_assumptions_mention_fair_rate(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "fair" in text and "rate" in text

    def test_flat_assumptions_mention_float_leg(self):
        resp = client.post(_URL, json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "float" in text

    def test_boot_assumptions_mention_bootstrap(self):
        resp = client.post(_URL, json=_BOOT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "bootstrap" in text


# ===========================================================================
# Class 7: Invalid Payloads
# ===========================================================================

class TestInvalidPayloads:
    def test_usd_currency_rejected(self):
        payload = {**_FLAT_PAYER, "currency": "USD"}
        resp = client.post(_URL, json=payload)
        assert resp.status_code == 422

    def test_libor_floating_index_rejected(self):
        payload = {**_FLAT_PAYER, "floating_index": "LIBOR"}
        resp = client.post(_URL, json=payload)
        assert resp.status_code == 422

    def test_buy_direction_rejected(self):
        payload = {**_FLAT_PAYER, "direction": "buy"}
        resp = client.post(_URL, json=payload)
        assert resp.status_code == 422

    def test_out_of_range_tenor_rejected(self):
        payload = {**_FLAT_PAYER, "tenor": "100Y"}
        resp = client.post(_URL, json=payload)
        assert resp.status_code == 422

    def test_zero_notional_rejected(self):
        payload = {**_FLAT_PAYER, "notional": 0}
        resp = client.post(_URL, json=payload)
        assert resp.status_code == 422


# ===========================================================================
# Class 8: Cross-Endpoint Comparison (new == legacy)
# ===========================================================================

class TestCrossEndpointComparison:
    """
    The direct structured endpoint must produce the same fair_rate as the
    existing extracted-fields endpoint for the same canonical IRS trade.
    Tolerance: 1e-6 (both endpoints call the same quant-core solver).
    """

    _TOL = 1e-6

    def test_fair_rate_matches_legacy_flat(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/fair-rate", json=_LEGACY_FLAT).json()
        assert abs(direct["fair_rate"] - legacy["fair_rate"]) < self._TOL

    def test_fixed_leg_annuity_matches_legacy_flat(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post("/price/irs/fair-rate", json=_LEGACY_FLAT).json()
        assert abs(direct["fixed_leg_annuity"] - legacy["fixed_leg_annuity"]) < self._TOL

    def test_fair_rate_matches_legacy_bootstrapped(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/fair-rate", json=_LEGACY_BOOT).json()
        assert abs(direct["fair_rate"] - legacy["fair_rate"]) < self._TOL

    def test_fixed_leg_annuity_matches_legacy_bootstrapped(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post("/price/irs/fair-rate", json=_LEGACY_BOOT).json()
        assert abs(direct["fixed_leg_annuity"] - legacy["fixed_leg_annuity"]) < self._TOL


# ===========================================================================
# Class 9: Pricing Consistency (fair_rate → NPV ≈ 0)
# ===========================================================================

class TestPricingConsistency:
    """
    Solve fair_rate via POST /price/irs/fair-rate/direct, then re-price the
    same structured IRS via POST /price/irs using that fair_rate as the
    fixed coupon rate.  The resulting NPV must be approximately zero.

    Tolerance: abs(NPV) < 100 on a 100 M notional (< 0.0001 % of notional).
    """

    _NPV_TOL = 100.0  # ZAR

    def _solve_and_price(self, fair_rate_payload: dict, price_base: dict) -> float:
        fr_resp = client.post(_URL, json=fair_rate_payload)
        assert fr_resp.status_code == 200, fr_resp.text
        fair_rate = fr_resp.json()["fair_rate"]

        price_payload = {**price_base, "fixed_rate": fair_rate}
        p_resp = client.post("/price/irs", json=price_payload)
        assert p_resp.status_code == 200, p_resp.text
        return p_resp.json()["price"]

    def test_flat_fair_rate_gives_near_zero_npv_payer(self):
        price_base = {k: v for k, v in _FLAT_PAYER.items() if k != "request_id"}
        npv = self._solve_and_price(_FLAT_PAYER, price_base)
        assert abs(npv) < self._NPV_TOL, f"NPV {npv:.2f} not near zero"

    def test_flat_fair_rate_gives_near_zero_npv_receiver(self):
        price_base = {k: v for k, v in _FLAT_RECEIVER.items() if k != "request_id"}
        npv = self._solve_and_price(_FLAT_RECEIVER, price_base)
        assert abs(npv) < self._NPV_TOL, f"NPV {npv:.2f} not near zero"

    def test_boot_fair_rate_gives_near_zero_npv(self):
        price_base = {k: v for k, v in _BOOT_PAYER.items() if k != "request_id"}
        npv = self._solve_and_price(_BOOT_PAYER, price_base)
        assert abs(npv) < self._NPV_TOL, f"NPV {npv:.2f} not near zero"
