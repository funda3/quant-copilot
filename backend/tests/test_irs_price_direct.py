"""
test_irs_price_direct — Integration tests for POST /price/irs.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys present and correct types
  - Numeric correctness: price and pv01 are real numbers in a plausible range
  - Default fixed_rate behaviour (omitted → default 8.5% used, status indicative)
  - Explicit fixed_rate (provided → different NPV vs default)
  - curve_source explicit ("flat_fallback" / "bootstrapped_mixed_curve")
  - Invalid payloads rejected via 422 (unsupported currency, floating_index,
    direction, out-of-range tenor, negative notional)
  - Cross-endpoint comparison: POST /price/irs vs POST /price return identical
    NPV and PV01 for the same canonical ZAR IRS trade (flat and bootstrapped)
  - request_id round-trip
  - Assumptions and warnings are lists
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
    "request_id": "direct-flat-payer",
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
    "request_id": "direct-flat-recv",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "receiver",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 100_000_000,
    "fixed_rate": 0.085,
}

_BOOT_PAYER = {
    "request_id": "direct-boot-payer",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 100_000_000,
    "fixed_rate": 0.085,
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

# Matching extracted_fields payload for POST /price (comparison tests)
_PRICE_ENDPOINT_FLAT = {
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

_PRICE_ENDPOINT_BOOT = {
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
    "curve_inputs": _BOOT_PAYER["curve_inputs"],
}


# ===========================================================================
# TestHTTPStatus
# ===========================================================================

class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        assert resp.status_code == 200

    def test_missing_body_returns_422(self):
        resp = client.post("/price/irs", json={})
        assert resp.status_code == 422


# ===========================================================================
# TestResponseShape
# ===========================================================================

class TestResponseShape:
    def test_all_required_keys_present(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        data = resp.json()
        for key in ("request_id", "instrument_type", "currency", "status",
                    "price", "pv01", "curve_source", "assumptions", "warnings"):
            assert key in data, f"Missing key: {key}"

    def test_status_is_indicative(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["currency"] == "ZAR"

    def test_price_is_float(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert isinstance(resp.json()["price"], float)

    def test_pv01_is_float(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert isinstance(resp.json()["pv01"], float)

    def test_assumptions_is_list(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert isinstance(resp.json()["assumptions"], list)

    def test_warnings_is_list(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert isinstance(resp.json()["warnings"], list)

    def test_request_id_round_trip(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["request_id"] == "direct-flat-payer"


# ===========================================================================
# TestPriceNumeric
# ===========================================================================

class TestPriceNumeric:
    def test_price_not_nan_flat(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert not math.isnan(resp.json()["price"])

    def test_pv01_not_nan_flat(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert not math.isnan(resp.json()["pv01"])

    def test_price_not_nan_boot(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        assert not math.isnan(resp.json()["price"])

    def test_pv01_not_nan_boot(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        assert not math.isnan(resp.json()["pv01"])

    def test_price_in_plausible_range_flat(self):
        # 5Y 100m notional at 8.5% fixed vs 8% flat market rate.
        # Fixed is above market → payer NPV is negative (pay above market).
        # |NPV| should be well below 100% of notional = 10m.
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        price = resp.json()["price"]
        assert abs(price) < 10_000_000

    def test_pv01_nonzero(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["pv01"] != 0.0

    def test_payer_receiver_npv_opposite_sign(self):
        payer_resp = client.post("/price/irs", json=_FLAT_PAYER)
        recv_resp = client.post("/price/irs", json=_FLAT_RECEIVER)
        payer_price = payer_resp.json()["price"]
        recv_price = recv_resp.json()["price"]
        # Payer and receiver should have opposite NPV signs (approx)
        assert payer_price == pytest.approx(-recv_price, abs=1.0)


# ===========================================================================
# TestDefaultFixedRate
# ===========================================================================

class TestDefaultFixedRate:
    def test_omitted_fixed_rate_returns_indicative(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_omitted_fixed_rate_same_as_explicit_default(self):
        # Default is 8.5%; explicitly providing 0.085 should give the same price
        explicit_resp = client.post("/price/irs", json=_FLAT_PAYER)
        payload_no_rate = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        default_resp = client.post("/price/irs", json=payload_no_rate)
        assert explicit_resp.json()["price"] == pytest.approx(
            default_resp.json()["price"], abs=0.01
        )

    def test_default_mentioned_in_assumptions(self):
        payload = {k: v for k, v in _FLAT_PAYER.items() if k != "fixed_rate"}
        resp = client.post("/price/irs", json=payload)
        assumptions_text = " ".join(resp.json()["assumptions"]).lower()
        assert "default" in assumptions_text or "not provided" in assumptions_text


# ===========================================================================
# TestExplicitFixedRate
# ===========================================================================

class TestExplicitFixedRate:
    def test_explicit_fixed_rate_works(self):
        payload = dict(_FLAT_PAYER)
        payload["fixed_rate"] = 0.06
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_different_fixed_rate_gives_different_npv(self):
        resp_high = client.post("/price/irs", json={**_FLAT_PAYER, "fixed_rate": 0.10})
        resp_low = client.post("/price/irs", json={**_FLAT_PAYER, "fixed_rate": 0.06})
        assert resp_high.json()["price"] != pytest.approx(resp_low.json()["price"], abs=1.0)

    def test_lower_fixed_rate_higher_payer_npv(self):
        # For a payer (pay fixed, receive float): lower fixed rate → higher NPV
        resp_high = client.post("/price/irs", json={**_FLAT_PAYER, "fixed_rate": 0.10})
        resp_low = client.post("/price/irs", json={**_FLAT_PAYER, "fixed_rate": 0.06})
        assert resp_low.json()["price"] > resp_high.json()["price"]


# ===========================================================================
# TestCurveSource
# ===========================================================================

class TestCurveSource:
    def test_flat_path_curve_source(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert resp.json()["curve_source"] == "flat_fallback"

    def test_bootstrapped_path_curve_source(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        assert resp.json()["curve_source"] == "bootstrapped_mixed_curve"


# ===========================================================================
# TestAssumptionsContent
# ===========================================================================

class TestAssumptionsContent:
    def test_assumptions_non_empty_flat(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        assert len(resp.json()["assumptions"]) > 0

    def test_assumptions_non_empty_boot(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        assert len(resp.json()["assumptions"]) > 0

    def test_assumptions_mention_fixed_rate(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "fixed" in text and "rate" in text

    def test_assumptions_mention_floating_method(self):
        resp = client.post("/price/irs", json=_FLAT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "floating" in text

    def test_boot_assumptions_mention_bootstrap(self):
        resp = client.post("/price/irs", json=_BOOT_PAYER)
        text = " ".join(resp.json()["assumptions"]).lower()
        assert "bootstrap" in text


# ===========================================================================
# TestInvalidPayloads
# ===========================================================================

class TestInvalidPayloads:
    def test_unsupported_currency_rejected(self):
        payload = {**_FLAT_PAYER, "currency": "USD"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_unsupported_floating_index_rejected(self):
        payload = {**_FLAT_PAYER, "floating_index": "LIBOR"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_invalid_direction_rejected(self):
        payload = {**_FLAT_PAYER, "direction": "buy"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_invalid_tenor_format_rejected(self):
        payload = {**_FLAT_PAYER, "tenor": "5 years"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_tenor_out_of_range_rejected(self):
        payload = {**_FLAT_PAYER, "tenor": "100Y"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_zero_notional_rejected(self):
        payload = {**_FLAT_PAYER, "notional": 0}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_invalid_instrument_type_rejected(self):
        payload = {**_FLAT_PAYER, "instrument_type": "bond"}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422

    def test_fixed_rate_out_of_range_rejected(self):
        payload = {**_FLAT_PAYER, "fixed_rate": 1.5}
        resp = client.post("/price/irs", json=payload)
        assert resp.status_code == 422


# ===========================================================================
# TestCrossEndpointComparison
# ===========================================================================

class TestCrossEndpointComparison:
    """
    For the same canonical ZAR IRS trade, POST /price/irs and POST /price
    must return identical NPV and PV01 (both delegate to the same
    quant_core.pricing.irs_pricer.price_irs function with identical arguments).
    """

    def test_npv_matches_price_endpoint_flat(self):
        direct_resp = client.post("/price/irs", json=_FLAT_PAYER)
        price_resp = client.post("/price", json=_PRICE_ENDPOINT_FLAT)

        assert direct_resp.status_code == 200
        assert price_resp.status_code == 200

        direct_data = direct_resp.json()
        price_data = price_resp.json()

        assert direct_data["status"] == "indicative"
        assert price_data["status"] == "indicative"

        assert direct_data["price"] == pytest.approx(price_data["price"], abs=0.01)

    def test_pv01_matches_price_endpoint_flat(self):
        direct_resp = client.post("/price/irs", json=_FLAT_PAYER)
        price_resp = client.post("/price", json=_PRICE_ENDPOINT_FLAT)

        direct_data = direct_resp.json()
        price_data = price_resp.json()

        assert direct_data["pv01"] == pytest.approx(price_data["pv01"], abs=0.01)

    def test_npv_matches_price_endpoint_bootstrapped(self):
        direct_resp = client.post("/price/irs", json=_BOOT_PAYER)
        price_resp = client.post("/price", json=_PRICE_ENDPOINT_BOOT)

        assert direct_resp.status_code == 200
        assert price_resp.status_code == 200

        direct_data = direct_resp.json()
        price_data = price_resp.json()

        assert direct_data["status"] == "indicative"
        assert price_data["status"] == "indicative"

        assert direct_data["price"] == pytest.approx(price_data["price"], abs=0.01)

    def test_pv01_matches_price_endpoint_bootstrapped(self):
        direct_resp = client.post("/price/irs", json=_BOOT_PAYER)
        price_resp = client.post("/price", json=_PRICE_ENDPOINT_BOOT)

        direct_data = direct_resp.json()
        price_data = price_resp.json()

        assert direct_data["pv01"] == pytest.approx(price_data["pv01"], abs=0.01)
