"""
test_irs_scenario_direct — Integration tests for POST /risk/scenario/direct.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys present, correct types, request_id round-trip
  - Default shift set works and key order is deterministic
  - Custom shift_bps works
  - 0bp scenario equals base_npv
  - Invalid payloads rejected via 422 (unsupported currency, floating_index,
    direction, out-of-range tenor, zero notional)
  - Cross-endpoint comparison: /risk/scenario/direct and /risk/scenario match for the
    same canonical trade and curve path
  - Existing quote, direct ladder, and direct fair-rate endpoints still work
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_FLAT_PAYER = {
    "request_id": "scenario-direct-flat",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 250_000_000,
}

_BOOT_CURVE = {
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

_BOOT_PAYER = {
    **_FLAT_PAYER,
    "request_id": "scenario-direct-boot",
    "curve_inputs": _BOOT_CURVE,
}

_URL = "/risk/scenario/direct"

_LEGACY_FIELDS = {
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 250_000_000,
}

_REQUIRED_KEYS = {
    "request_id",
    "instrument_type",
    "currency",
    "status",
    "scenario_npv",
    "base_npv",
    "curve_source",
    "assumptions",
    "warnings",
}

_DEFAULT_SHIFT_LABELS = ["-200bp", "-100bp", "-50bp", "0bp", "50bp", "100bp", "200bp"]


class TestHTTPStatus:
    def test_flat_path_returns_200(self):
        assert client.post(_URL, json=_FLAT_PAYER).status_code == 200

    def test_bootstrapped_path_returns_200(self):
        assert client.post(_URL, json=_BOOT_PAYER).status_code == 200

    def test_missing_body_returns_422(self):
        assert client.post(_URL, json={}).status_code == 422


class TestResponseShape:
    def _data(self) -> dict:
        return client.post(_URL, json=_FLAT_PAYER).json()

    def test_response_has_required_keys(self):
        data = self._data()
        for key in _REQUIRED_KEYS:
            assert key in data, f"missing key: {key}"

    def test_request_id_round_trip(self):
        assert self._data()["request_id"] == "scenario-direct-flat"

    def test_status_is_indicative(self):
        assert self._data()["status"] == "indicative"

    def test_scenario_npv_is_dict(self):
        assert isinstance(self._data()["scenario_npv"], dict)

    def test_base_npv_is_float(self):
        assert isinstance(self._data()["base_npv"], float)

    def test_curve_source_flat(self):
        assert self._data()["curve_source"] == "flat_fallback"


class TestDefaultShifts:
    def test_default_shift_set(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert list(data["scenario_npv"].keys()) == _DEFAULT_SHIFT_LABELS

    def test_zero_bp_equals_base_npv(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert abs(data["scenario_npv"]["0bp"] - data["base_npv"]) < 1e-6

    def test_shift_values_are_floats(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        for value in data["scenario_npv"].values():
            assert isinstance(value, float)

    def test_positive_shift_above_base_for_payer(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert data["scenario_npv"]["200bp"] > data["base_npv"]

    def test_negative_shift_below_base_for_payer(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert data["scenario_npv"]["-200bp"] < data["base_npv"]


class TestCustomShifts:
    def test_custom_shift_bps_works(self):
        payload = {**_FLAT_PAYER, "shift_bps": [-100, 0, 100]}
        data = client.post(_URL, json=payload).json()
        assert list(data["scenario_npv"].keys()) == ["-100bp", "0bp", "100bp"]

    def test_custom_single_shift(self):
        payload = {**_FLAT_PAYER, "shift_bps": [50]}
        data = client.post(_URL, json=payload).json()
        assert list(data["scenario_npv"].keys()) == ["50bp"]
        assert isinstance(data["scenario_npv"]["50bp"], float)

    def test_boot_curve_source(self):
        data = client.post(_URL, json=_BOOT_PAYER).json()
        assert data["curve_source"] == "bootstrapped_mixed_curve"

    def test_boot_zero_bp_equals_base_npv(self):
        data = client.post(_URL, json=_BOOT_PAYER).json()
        assert abs(data["scenario_npv"]["0bp"] - data["base_npv"]) < 1e-6


class TestInvalidPayloads:
    def test_invalid_currency_rejected(self):
        payload = {**_FLAT_PAYER, "currency": "USD"}
        assert client.post(_URL, json=payload).status_code == 422

    def test_invalid_floating_index_rejected(self):
        payload = {**_FLAT_PAYER, "floating_index": "LIBOR"}
        assert client.post(_URL, json=payload).status_code == 422

    def test_invalid_direction_rejected(self):
        payload = {**_FLAT_PAYER, "direction": "buy"}
        assert client.post(_URL, json=payload).status_code == 422

    def test_invalid_tenor_rejected(self):
        payload = {**_FLAT_PAYER, "tenor": "100Y"}
        assert client.post(_URL, json=payload).status_code == 422

    def test_zero_notional_rejected(self):
        payload = {**_FLAT_PAYER, "notional": 0}
        assert client.post(_URL, json=payload).status_code == 422


class TestCrossEndpointComparison:
    _TOL = 1e-6

    def test_flat_scenario_npv_matches_legacy(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post(
            "/risk/scenario",
            json={"extracted_fields": _LEGACY_FIELDS},
        ).json()
        assert list(direct["scenario_npv"].keys()) == list(legacy["scenario_npv"].keys())
        for key, value in direct["scenario_npv"].items():
            assert abs(value - legacy["scenario_npv"][key]) < self._TOL

    def test_flat_base_npv_matches_legacy(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post(
            "/risk/scenario",
            json={"extracted_fields": _LEGACY_FIELDS},
        ).json()
        assert abs(direct["base_npv"] - legacy["base_npv"]) < self._TOL

    def test_boot_scenario_npv_matches_legacy(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post(
            "/risk/scenario",
            json={"extracted_fields": _LEGACY_FIELDS, "curve_inputs": _BOOT_CURVE},
        ).json()
        assert list(direct["scenario_npv"].keys()) == list(legacy["scenario_npv"].keys())
        for key, value in direct["scenario_npv"].items():
            assert abs(value - legacy["scenario_npv"][key]) < self._TOL

    def test_boot_base_npv_matches_legacy(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post(
            "/risk/scenario",
            json={"extracted_fields": _LEGACY_FIELDS, "curve_inputs": _BOOT_CURVE},
        ).json()
        assert abs(direct["base_npv"] - legacy["base_npv"]) < self._TOL


class TestRegressionGuardrails:
    def test_quote_still_works(self):
        resp = client.post(
            "/quote",
            json={"prompt": "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"},
        )
        assert resp.status_code == 200

    def test_direct_ladder_still_works(self):
        resp = client.post(
            "/risk/ladder/direct",
            json={**_FLAT_PAYER, "bucket_years": [1, 2, 3, 5, 7, 10]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_direct_fair_rate_still_works(self):
        resp = client.post("/price/irs/fair-rate/direct", json=_FLAT_PAYER)
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"
