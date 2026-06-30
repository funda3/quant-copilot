"""
test_irs_ladder_direct — Integration tests for POST /risk/ladder/direct.

Coverage:
  - HTTP status: flat path (200), bootstrapped path (200), missing body (422)
  - Response shape: all required keys present, correct types, request_id round-trip
  - Default bucket set works
  - Custom bucket_years works
  - total_abs_pv01 equals sum(abs(bucket_pv01.values()))
  - Invalid payloads rejected via 422 (unsupported currency, floating_index,
    direction, out-of-range tenor, zero notional, invalid bucket_years)
  - Cross-endpoint comparison: /risk/ladder/direct and /risk/ladder match for the
    same canonical trade and curve path
  - Existing quote and price endpoints still work after adding the direct route
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_FLAT_PAYER = {
    "request_id": "ladder-direct-flat",
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 250_000_000,
}

_FLAT_RECEIVER = {
    **_FLAT_PAYER,
    "request_id": "ladder-direct-flat-recv",
    "direction": "receiver",
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
    "request_id": "ladder-direct-boot",
    "curve_inputs": _BOOT_CURVE,
}

_URL = "/risk/ladder/direct"

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
    "bucket_pv01",
    "total_abs_pv01",
    "curve_source",
    "status",
    "assumptions",
    "warnings",
}

_DEFAULT_BUCKET_LABELS = {"1Y", "2Y", "3Y", "5Y", "7Y", "10Y"}


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
        assert self._data()["request_id"] == "ladder-direct-flat"

    def test_status_is_indicative(self):
        assert self._data()["status"] == "indicative"

    def test_bucket_pv01_is_dict(self):
        assert isinstance(self._data()["bucket_pv01"], dict)

    def test_total_abs_pv01_is_float(self):
        assert isinstance(self._data()["total_abs_pv01"], float)

    def test_curve_source_flat(self):
        assert self._data()["curve_source"] == "flat_fallback"


class TestDefaultBuckets:
    def test_default_bucket_set(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert set(data["bucket_pv01"].keys()) == _DEFAULT_BUCKET_LABELS

    def test_in_range_buckets_non_zero(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        for label in ("1Y", "2Y", "3Y", "5Y"):
            assert data["bucket_pv01"][label] != 0.0

    def test_far_buckets_zero(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        assert data["bucket_pv01"]["7Y"] == 0.0
        assert data["bucket_pv01"]["10Y"] == 0.0

    def test_total_abs_equals_sum_of_abs_buckets(self):
        data = client.post(_URL, json=_FLAT_PAYER).json()
        expected = sum(abs(v) for v in data["bucket_pv01"].values())
        assert abs(data["total_abs_pv01"] - expected) < 1e-9

    def test_receiver_sign_convention(self):
        data = client.post(_URL, json=_FLAT_RECEIVER).json()
        for label in ("1Y", "2Y", "3Y", "5Y"):
            assert data["bucket_pv01"][label] < 0.0


class TestCustomBuckets:
    def test_custom_bucket_years_works(self):
        payload = {**_FLAT_PAYER, "bucket_years": [1, 3, 5]}
        data = client.post(_URL, json=payload).json()
        assert data["status"] == "indicative"
        assert set(data["bucket_pv01"].keys()) == {"1Y", "3Y", "5Y"}

    def test_custom_single_bucket(self):
        payload = {**_FLAT_PAYER, "bucket_years": [2]}
        data = client.post(_URL, json=payload).json()
        assert set(data["bucket_pv01"].keys()) == {"2Y"}
        assert data["bucket_pv01"]["2Y"] != 0.0

    def test_boot_curve_source(self):
        data = client.post(_URL, json=_BOOT_PAYER).json()
        assert data["curve_source"] == "bootstrapped_mixed_curve"


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

    def test_invalid_bucket_years_rejected(self):
        payload = {**_FLAT_PAYER, "bucket_years": [0]}
        assert client.post(_URL, json=payload).status_code == 422


class TestCrossEndpointComparison:
    _TOL = 1e-9

    def test_flat_bucket_pv01_matches_legacy(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post(
            "/risk/ladder",
            json={"extracted_fields": _LEGACY_FIELDS},
        ).json()
        assert set(direct["bucket_pv01"].keys()) == set(legacy["bucket_pv01"].keys())
        for key, value in direct["bucket_pv01"].items():
            assert abs(value - legacy["bucket_pv01"][key]) < self._TOL

    def test_flat_total_abs_matches_legacy(self):
        direct = client.post(_URL, json=_FLAT_PAYER).json()
        legacy = client.post(
            "/risk/ladder",
            json={"extracted_fields": _LEGACY_FIELDS},
        ).json()
        assert abs(direct["total_abs_pv01"] - legacy["total_abs_pv01"]) < self._TOL

    def test_boot_bucket_pv01_matches_legacy(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post(
            "/risk/ladder",
            json={"extracted_fields": _LEGACY_FIELDS, "curve_inputs": _BOOT_CURVE},
        ).json()
        assert set(direct["bucket_pv01"].keys()) == set(legacy["bucket_pv01"].keys())
        for key, value in direct["bucket_pv01"].items():
            assert abs(value - legacy["bucket_pv01"][key]) < self._TOL

    def test_boot_total_abs_matches_legacy(self):
        direct = client.post(_URL, json=_BOOT_PAYER).json()
        legacy = client.post(
            "/risk/ladder",
            json={"extracted_fields": _LEGACY_FIELDS, "curve_inputs": _BOOT_CURVE},
        ).json()
        assert abs(direct["total_abs_pv01"] - legacy["total_abs_pv01"]) < self._TOL


class TestRegressionGuardrails:
    def test_price_irs_still_works(self):
        resp = client.post("/price/irs", json={**_FLAT_PAYER, "fixed_rate": 0.085})
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"

    def test_quote_still_works(self):
        resp = client.post(
            "/quote",
            json={"prompt": "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"},
        )
        assert resp.status_code == 200

    def test_legacy_ladder_still_works(self):
        resp = client.post("/risk/ladder", json={"extracted_fields": _LEGACY_FIELDS})
        assert resp.status_code == 200
        assert resp.json()["status"] == "indicative"
