"""
test_irs_fair_rate — Integration tests for POST /price/irs/fair-rate.

Coverage:
  - HTTP status: flat path, bootstrapped path, missing body
  - Response shape: all required keys present
  - fair_rate positive and in a sensible range
  - fair_rate direction-invariant (payer == receiver)
  - Repricing with fair_rate gives near-zero NPV on the flat path and
    the bootstrapped path (via POST /price endpoint)
  - fixed_leg_annuity positive
  - curve_source explicit ("flat_fallback" / "bootstrapped_mixed_curve")
  - Invalid payloads rejected gracefully (USD, wrong instrument type,
    missing tenor)
  - request_id round-trip
  - Assumptions list non-empty and mentions fair-rate method
  - Warnings list is a list (possibly empty)
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

_FLAT_PAYER = {
    "request_id": "fr-test-flat",
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
        "fixed_rate": 0.085,
    },
}

_FLAT_RECEIVER = {
    "request_id": "fr-test-recv",
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "receiver",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
        "fixed_rate": 0.085,
    },
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
    "request_id": "fr-test-boot",
    "extracted_fields": {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 100_000_000,
        "fixed_rate": 0.085,
    },
    "curve_inputs": _BOOT_CURVE,
}


# ===========================================================================
# HTTP status
# ===========================================================================


class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        r = client.post("/price/irs/fair-rate", json=_FLAT_PAYER)
        assert r.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        r = client.post("/price/irs/fair-rate", json=_BOOT_PAYER)
        assert r.status_code == 200

    def test_missing_body_returns_422(self):
        r = client.post("/price/irs/fair-rate")
        assert r.status_code == 422


# ===========================================================================
# Response shape
# ===========================================================================


class TestResponseShape:
    """All 9 required top-level keys must be present."""

    def setup_method(self):
        self.data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()

    _REQUIRED_KEYS = {
        "request_id",
        "instrument_type",
        "currency",
        "status",
        "fair_rate",
        "fixed_leg_annuity",
        "curve_source",
        "assumptions",
        "warnings",
    }

    def test_all_required_keys_present(self):
        for key in self._REQUIRED_KEYS:
            assert key in self.data, f"missing key: {key}"

    def test_status_is_indicative(self):
        assert self.data["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        assert self.data["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        assert self.data["currency"] == "ZAR"

    def test_assumptions_is_list(self):
        assert isinstance(self.data["assumptions"], list)

    def test_warnings_is_list(self):
        assert isinstance(self.data["warnings"], list)

    def test_request_id_round_trips(self):
        assert self.data["request_id"] == "fr-test-flat"


# ===========================================================================
# fair_rate numeric properties
# ===========================================================================


class TestFairRateNumeric:
    def test_fair_rate_positive_flat(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert data["fair_rate"] > 0.0

    def test_fair_rate_positive_bootstrapped(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        assert data["fair_rate"] > 0.0

    def test_fair_rate_in_sensible_range_flat(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert 0.01 < data["fair_rate"] < 0.99

    def test_fair_rate_in_sensible_range_bootstrapped(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        assert 0.01 < data["fair_rate"] < 0.99

    def test_fair_rate_not_nan(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert not math.isnan(data["fair_rate"])

    def test_fixed_leg_annuity_positive(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert data["fixed_leg_annuity"] > 0.0

    def test_fixed_leg_annuity_not_nan(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert not math.isnan(data["fixed_leg_annuity"])


# ===========================================================================
# Direction invariance
# ===========================================================================


class TestDirectionInvariance:
    """Payer and receiver must return the same fair_rate and annuity."""

    def test_payer_and_receiver_fair_rate_equal(self):
        dp = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        dr = client.post("/price/irs/fair-rate", json=_FLAT_RECEIVER).json()
        assert dp["fair_rate"] == pytest.approx(dr["fair_rate"], rel=1e-6)

    def test_payer_and_receiver_annuity_equal(self):
        dp = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        dr = client.post("/price/irs/fair-rate", json=_FLAT_RECEIVER).json()
        assert dp["fixed_leg_annuity"] == pytest.approx(
            dr["fixed_leg_annuity"], rel=1e-6
        )


# ===========================================================================
# Repricing with fair_rate gives near-zero NPV
# ===========================================================================


class TestRepricingAtFairRate:
    """
    After solving the fair rate, pass it to POST /price as the fixed_rate.
    The resulting NPV must be approximately zero (within rounding tolerance).
    """

    def _reprice_npv(self, fair_rate: float, curve_inputs=None) -> float:
        body = {
            "extracted_fields": {
                "instrument_type": "irs",
                "currency": "ZAR",
                "direction": "payer",
                "floating_index": "JIBAR",
                "payment_frequency": "quarterly",
                "tenor": "5Y",
                "notional": 100_000_000,
                "fixed_rate": fair_rate,
            }
        }
        if curve_inputs:
            body["curve_inputs"] = curve_inputs
        resp = client.post("/price", json=body)
        assert resp.status_code == 200
        return resp.json()["price"]

    def test_reprice_flat_path_near_zero_npv(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        fair = data["fair_rate"]
        npv = self._reprice_npv(fair)
        # Backend rounds to 2dp; tolerance is 1 ZAR on 100m notional
        assert abs(npv) < 100.0

    def test_reprice_bootstrapped_path_near_zero_npv(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        fair = data["fair_rate"]
        npv = self._reprice_npv(fair, curve_inputs=_BOOT_CURVE)
        assert abs(npv) < 100.0


# ===========================================================================
# curve_source
# ===========================================================================


class TestCurveSource:
    def test_flat_path_curve_source_is_flat_fallback(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert data["curve_source"] == "flat_fallback"

    def test_bootstrapped_path_curve_source_is_bootstrapped(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        assert data["curve_source"] == "bootstrapped_mixed_curve"


# ===========================================================================
# Assumptions content
# ===========================================================================


class TestAssumptionsContent:
    def test_assumptions_non_empty_flat(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        assert len(data["assumptions"]) > 0

    def test_assumptions_non_empty_bootstrapped(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        assert len(data["assumptions"]) > 0

    def test_assumptions_mention_fair_rate_method_flat(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        combined = " ".join(data["assumptions"]).lower()
        assert "fair rate" in combined or "fair_rate" in combined

    def test_assumptions_mention_floating_leg_method(self):
        data = client.post("/price/irs/fair-rate", json=_FLAT_PAYER).json()
        combined = " ".join(data["assumptions"]).lower()
        assert "par-floating" in combined or "floating" in combined

    def test_bootstrapped_assumptions_mention_bootstrap(self):
        data = client.post("/price/irs/fair-rate", json=_BOOT_PAYER).json()
        combined = " ".join(data["assumptions"]).lower()
        assert "bootstrap" in combined


# ===========================================================================
# Invalid payloads
# ===========================================================================


class TestInvalidPayloads:
    def test_usd_currency_returns_unsupported(self):
        body = {
            "extracted_fields": {
                "instrument_type": "irs",
                "currency": "USD",
                "direction": "payer",
                "floating_index": "LIBOR",
                "payment_frequency": "quarterly",
                "tenor": "5Y",
                "notional": 1_000_000,
                "fixed_rate": 0.05,
            }
        }
        data = client.post("/price/irs/fair-rate", json=body).json()
        assert data["status"] == "unsupported"

    def test_fra_instrument_returns_unsupported(self):
        body = {
            "extracted_fields": {
                "instrument_type": "fra",
                "currency": "ZAR",
                "direction": "payer",
                "floating_index": "JIBAR",
                "payment_frequency": "quarterly",
                "tenor": "3M",
                "notional": 1_000_000,
                "fixed_rate": 0.08,
            }
        }
        data = client.post("/price/irs/fair-rate", json=body).json()
        assert data["status"] == "unsupported"

    def test_missing_tenor_returns_unsupported(self):
        body = {
            "extracted_fields": {
                "instrument_type": "irs",
                "currency": "ZAR",
                "direction": "payer",
                "floating_index": "JIBAR",
                "payment_frequency": "quarterly",
                "notional": 100_000_000,
            }
        }
        data = client.post("/price/irs/fair-rate", json=body).json()
        assert data["status"] == "unsupported"

    def test_missing_notional_returns_unsupported(self):
        body = {
            "extracted_fields": {
                "instrument_type": "irs",
                "currency": "ZAR",
                "direction": "payer",
                "floating_index": "JIBAR",
                "payment_frequency": "quarterly",
                "tenor": "5Y",
            }
        }
        data = client.post("/price/irs/fair-rate", json=body).json()
        assert data["status"] == "unsupported"
