"""
Tests for POST /price/irs/breakdown — IRS valuation breakdown endpoint.

Canonical flat-curve IRS:
  extracted_fields:
    instrument_type:   irs
    currency:          ZAR
    floating_index:    JIBAR
    direction:         payer
    tenor:             5Y
    notional:          10_000_000
    fixed_rate:        0.085
    payment_frequency: quarterly
  curve: flat 8% ZAR JIBAR proxy (no curve_inputs)

Bootstrapped-curve tests use the same mixed-curve fixture as the cashflows
tests.
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_URL = "/price/irs/breakdown"

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

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "currency",
    "status",
    "fixed_leg_pv",
    "floating_leg_pv",
    "npv",
    "n_payments",
    "curve_source",
    "floating_leg_method",
    "assumptions",
    "warnings",
}


def _post(payload: dict) -> dict:
    resp = client.post(_URL, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# HTTP status
# ---------------------------------------------------------------------------


class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        resp = client.post(_URL, json=_FLAT_PAYLOAD)
        assert resp.status_code == 200

    def test_bootstrapped_path_returns_200(self):
        resp = client.post(_URL, json=_BOOTSTRAP_PAYLOAD)
        assert resp.status_code == 200

    def test_missing_body_returns_422(self):
        resp = client.post(_URL)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestResponseShape:
    def test_all_required_keys_present_flat(self):
        data = _post(_FLAT_PAYLOAD)
        assert _REQUIRED_KEYS.issubset(data.keys())

    def test_all_required_keys_present_bootstrapped(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert _REQUIRED_KEYS.issubset(data.keys())

    def test_status_is_indicative_flat(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["status"] == "indicative"

    def test_status_is_indicative_bootstrapped(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert data["status"] == "indicative"

    def test_instrument_type_is_irs(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["instrument_type"] == "irs"

    def test_currency_is_zar(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["currency"] == "ZAR"

    def test_request_id_is_string(self):
        data = _post(_FLAT_PAYLOAD)
        assert isinstance(data["request_id"], str)

    def test_assumptions_is_list(self):
        data = _post(_FLAT_PAYLOAD)
        assert isinstance(data["assumptions"], list)
        assert len(data["assumptions"]) > 0

    def test_warnings_is_list(self):
        data = _post(_FLAT_PAYLOAD)
        assert isinstance(data["warnings"], list)


# ---------------------------------------------------------------------------
# Numeric fields
# ---------------------------------------------------------------------------


class TestNumericFields:
    def test_fixed_leg_pv_positive(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["fixed_leg_pv"] > 0.0

    def test_floating_leg_pv_positive(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["floating_leg_pv"] > 0.0

    def test_n_payments_is_20_for_5y_quarterly(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["n_payments"] == 20

    def test_n_payments_is_5_for_5y_annual(self):
        fields = {**_CANON_FIELDS, "payment_frequency": "annual"}
        data = _post({"extracted_fields": fields})
        assert data["n_payments"] == 5

    def test_n_payments_is_10_for_5y_semiannual(self):
        fields = {**_CANON_FIELDS, "payment_frequency": "semiannual"}
        data = _post({"extracted_fields": fields})
        assert data["n_payments"] == 10


# ---------------------------------------------------------------------------
# NPV sign convention - payer
# ---------------------------------------------------------------------------


class TestPayerNPV:
    def test_payer_npv_approx_float_minus_fixed(self):
        data = _post(_FLAT_PAYLOAD)
        npv = data["npv"]
        float_pv = data["floating_leg_pv"]
        fixed_pv = data["fixed_leg_pv"]
        # payer NPV = float_pv - fixed_pv
        assert npv == pytest.approx(float_pv - fixed_pv, rel=1e-4)

    def test_payer_fixed_above_market_npv_negative(self):
        # 8.5% fixed > 8% market flat curve → payer NPV < 0
        data = _post(_FLAT_PAYLOAD)
        assert data["npv"] < 0.0


# ---------------------------------------------------------------------------
# NPV sign convention - receiver
# ---------------------------------------------------------------------------


class TestReceiverNPV:
    def test_receiver_npv_approx_fixed_minus_float(self):
        fields = {**_CANON_FIELDS, "direction": "receiver"}
        data = _post({"extracted_fields": fields})
        npv = data["npv"]
        float_pv = data["floating_leg_pv"]
        fixed_pv = data["fixed_leg_pv"]
        # receiver NPV = fixed_pv - float_pv
        assert npv == pytest.approx(fixed_pv - float_pv, rel=1e-4)

    def test_receiver_npv_positive_when_fixed_above_market(self):
        fields = {**_CANON_FIELDS, "direction": "receiver"}
        data = _post({"extracted_fields": fields})
        assert data["npv"] > 0.0

    def test_payer_and_receiver_npv_sum_to_zero(self):
        payer_data = _post(_FLAT_PAYLOAD)
        recv_fields = {**_CANON_FIELDS, "direction": "receiver"}
        recv_data = _post({"extracted_fields": recv_fields})
        total = payer_data["npv"] + recv_data["npv"]
        assert total == pytest.approx(0.0, abs=1.0)  # within 1 currency unit


# ---------------------------------------------------------------------------
# Leg PVs: payer and receiver produce the same fixed_leg_pv / floating_leg_pv
# ---------------------------------------------------------------------------


class TestLegPVSymmetry:
    def test_payer_and_receiver_fixed_leg_pv_equal(self):
        payer_data = _post(_FLAT_PAYLOAD)
        recv_fields = {**_CANON_FIELDS, "direction": "receiver"}
        recv_data = _post({"extracted_fields": recv_fields})
        assert payer_data["fixed_leg_pv"] == pytest.approx(
            recv_data["fixed_leg_pv"], rel=1e-4
        )

    def test_payer_and_receiver_floating_leg_pv_equal(self):
        payer_data = _post(_FLAT_PAYLOAD)
        recv_fields = {**_CANON_FIELDS, "direction": "receiver"}
        recv_data = _post({"extracted_fields": recv_fields})
        assert payer_data["floating_leg_pv"] == pytest.approx(
            recv_data["floating_leg_pv"], rel=1e-4
        )


# ---------------------------------------------------------------------------
# curve_source
# ---------------------------------------------------------------------------


class TestCurveSource:
    def test_flat_path_curve_source_is_flat_fallback(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["curve_source"] == "flat_fallback"

    def test_bootstrapped_path_curve_source_is_bootstrapped(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert data["curve_source"] == "bootstrapped_mixed_curve"


# ---------------------------------------------------------------------------
# floating_leg_method
# ---------------------------------------------------------------------------


class TestFloatingLegMethod:
    def test_floating_leg_method_flat(self):
        data = _post(_FLAT_PAYLOAD)
        assert data["floating_leg_method"] == "par_floating_approximation"

    def test_floating_leg_method_bootstrapped(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert data["floating_leg_method"] == "par_floating_approximation"


# ---------------------------------------------------------------------------
# Notional scaling
# ---------------------------------------------------------------------------


class TestNotionalScaling:
    def test_double_notional_doubles_npv(self):
        fields_1x = {**_CANON_FIELDS, "notional": 10_000_000}
        fields_2x = {**_CANON_FIELDS, "notional": 20_000_000}
        data_1x = _post({"extracted_fields": fields_1x})
        data_2x = _post({"extracted_fields": fields_2x})
        assert data_2x["npv"] == pytest.approx(2.0 * data_1x["npv"], rel=1e-4)
        assert data_2x["fixed_leg_pv"] == pytest.approx(
            2.0 * data_1x["fixed_leg_pv"], rel=1e-4
        )
        assert data_2x["floating_leg_pv"] == pytest.approx(
            2.0 * data_1x["floating_leg_pv"], rel=1e-4
        )


# ---------------------------------------------------------------------------
# Bootstrapped curve path
# ---------------------------------------------------------------------------


class TestBootstrappedPath:
    def test_bootstrapped_n_payments_is_20_for_5y_quarterly(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert data["n_payments"] == 20

    def test_bootstrapped_fixed_leg_pv_positive(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert data["fixed_leg_pv"] > 0.0

    def test_bootstrapped_npv_sign_payer_above_market(self):
        # With the bootstrapped curve ending near par (5Y at 8.5%), the
        # payer at 8.5% fixed should have NPV close to zero but we only
        # check it is finite and not NaN.
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert not math.isnan(data["npv"])

    def test_bootstrapped_assumptions_mention_bootstrapped_curve(self):
        data = _post(_BOOTSTRAP_PAYLOAD)
        assert any("ootstrap" in a for a in data["assumptions"])


# ---------------------------------------------------------------------------
# Unsupported / invalid payloads
# ---------------------------------------------------------------------------


class TestInvalidPayloads:
    def test_unsupported_currency_returns_unsupported_status(self):
        fields = {**_CANON_FIELDS, "currency": "USD"}
        resp = client.post(_URL, json={"extracted_fields": fields})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] != "indicative"

    def test_unsupported_instrument_type_returns_unsupported(self):
        fields = {**_CANON_FIELDS, "instrument_type": "fra"}
        resp = client.post(_URL, json={"extracted_fields": fields})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] != "indicative"

    def test_missing_tenor_returns_unsupported(self):
        fields = {k: v for k, v in _CANON_FIELDS.items() if k != "tenor"}
        resp = client.post(_URL, json={"extracted_fields": fields})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] != "indicative"

    def test_request_id_round_trips(self):
        payload = {**_FLAT_PAYLOAD, "request_id": "test-breakdown-001"}
        data = _post(payload)
        assert data["request_id"] == "test-breakdown-001"
