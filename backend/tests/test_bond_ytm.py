"""
test_bond_ytm — Integration tests for POST /price/bond/ytm.

Coverage:
  - Valid coupon bond request → 200
  - Valid zero-coupon bond request → 200
  - Response shape and field types
  - market_dirty_price=0 rejected (422)
  - market_dirty_price<0 rejected (422)
  - Round-trip: price via /price/bond then recover yield via /price/bond/ytm
  - Canonical ZCB deterministic case
  - request_id echo
  - YTM increases when price decreases (monotone sanity)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_BASE = dict(
    instrument_type="bond",
    valuation_date="2024-01-01",
    issue_date="2024-01-01",
    maturity_date="2029-01-01",
    face_value=1_000_000.0,
    coupon_rate=0.08,
    coupon_frequency="annual",
    day_count="ACT_365F",
)


class TestBondYTMEndpoint:

    # ------------------------------------------------------------------
    # HTTP status
    # ------------------------------------------------------------------

    def test_valid_coupon_bond_returns_200(self):
        payload = {**_BASE, "market_dirty_price": 950_000.0}
        resp = client.post("/price/bond/ytm", json=payload)
        assert resp.status_code == 200

    def test_valid_zcb_returns_200(self):
        payload = {**_BASE, "coupon_rate": 0.0, "market_dirty_price": 700_000.0}
        resp = client.post("/price/bond/ytm", json=payload)
        assert resp.status_code == 200

    # ------------------------------------------------------------------
    # Response shape
    # ------------------------------------------------------------------

    def test_response_shape(self):
        payload = {**_BASE, "market_dirty_price": 950_000.0}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert "request_id" in data
        assert data["instrument_type"] == "bond"
        assert data["status"] == "solved"
        assert "market_dirty_price" in data
        assert "ytm" in data
        assert isinstance(data["assumptions"], list)
        assert isinstance(data["warnings"], list)

    def test_ytm_is_float(self):
        payload = {**_BASE, "market_dirty_price": 950_000.0}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert isinstance(data["ytm"], float)

    def test_market_dirty_price_echoed(self):
        payload = {**_BASE, "market_dirty_price": 987_654.32}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert abs(data["market_dirty_price"] - 987_654.32) < 0.01

    def test_request_id_echoed_when_provided(self):
        payload = {**_BASE, "request_id": "ytm-test-001", "market_dirty_price": 950_000.0}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert data["request_id"] == "ytm-test-001"

    def test_request_id_auto_generated_when_absent(self):
        payload = {**_BASE, "market_dirty_price": 950_000.0}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert data["request_id"] != ""
        assert data["request_id"] is not None

    def test_assumptions_non_empty(self):
        payload = {**_BASE, "market_dirty_price": 950_000.0}
        data = client.post("/price/bond/ytm", json=payload).json()
        assert len(data["assumptions"]) > 0

    # ------------------------------------------------------------------
    # Validation — market_dirty_price must be > 0
    # ------------------------------------------------------------------

    def test_market_dirty_price_zero_rejected(self):
        payload = {**_BASE, "market_dirty_price": 0.0}
        resp = client.post("/price/bond/ytm", json=payload)
        assert resp.status_code == 422

    def test_market_dirty_price_negative_rejected(self):
        payload = {**_BASE, "market_dirty_price": -500.0}
        resp = client.post("/price/bond/ytm", json=payload)
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # Round-trip: price → YTM → recover yield
    # ------------------------------------------------------------------

    def test_coupon_bond_round_trip_8pct(self):
        """Price bond at flat 8% proxy; YTM endpoint must recover ~8%."""
        price_data = client.post("/price/bond", json=_BASE).json()
        dirty_price = price_data["dirty_price"]

        ytm_payload = {**_BASE, "market_dirty_price": dirty_price}
        ytm_data = client.post("/price/bond/ytm", json=ytm_payload).json()

        assert ytm_data["status"] == "solved"
        assert abs(ytm_data["ytm"] - 0.08) < 1e-6

    def test_zcb_round_trip_8pct(self):
        """Price ZCB at flat 8%; YTM endpoint must recover ~8%."""
        zcb_base = {**_BASE, "coupon_rate": 0.0}
        price_data = client.post("/price/bond", json=zcb_base).json()
        dirty_price = price_data["dirty_price"]

        ytm_payload = {**zcb_base, "market_dirty_price": dirty_price}
        ytm_data = client.post("/price/bond/ytm", json=ytm_payload).json()

        assert ytm_data["status"] == "solved"
        assert abs(ytm_data["ytm"] - 0.08) < 1e-6

    # ------------------------------------------------------------------
    # Canonical deterministic case (ZCB, ACT/365F)
    # ------------------------------------------------------------------

    def test_canonical_zcb_ytm_deterministic(self):
        """
        5Y ZCB, ACT/365F.  Dirty price at 8% flat:
          P = F / (1 + 0.08 × τ(2024-01-01, 2029-01-01, ACT/365F))

        The backend's /price/bond uses the same simple-rate convention, so
        the round-trip must hold to 1e-6 in yield space.
        """
        from datetime import date
        from quant_core.conventions.day_count import DayCount, accrual_fraction

        tau = accrual_fraction(date(2024, 1, 1), date(2029, 1, 1), DayCount.ACT_365F)
        expected_price = 1_000_000.0 / (1.0 + 0.08 * tau)

        payload = {**_BASE, "coupon_rate": 0.0, "market_dirty_price": expected_price}
        data = client.post("/price/bond/ytm", json=payload).json()

        assert data["status"] == "solved"
        assert abs(data["ytm"] - 0.08) < 1e-7

    # ------------------------------------------------------------------
    # Monotone sanity: higher price → lower YTM
    # ------------------------------------------------------------------

    def test_ytm_monotone_higher_price_lower_ytm(self):
        price_low = 900_000.0
        price_high = 1_100_000.0

        ytm_low = client.post("/price/bond/ytm", json={**_BASE, "market_dirty_price": price_low}).json()["ytm"]
        ytm_high = client.post("/price/bond/ytm", json={**_BASE, "market_dirty_price": price_high}).json()["ytm"]

        assert ytm_low > ytm_high

    # ------------------------------------------------------------------
    # Semiannual coupon
    # ------------------------------------------------------------------

    def test_semiannual_coupon_round_trip(self):
        sa_base = {**_BASE, "coupon_frequency": "semiannual"}
        price_data = client.post("/price/bond", json=sa_base).json()
        dirty_price = price_data["dirty_price"]

        ytm_payload = {**sa_base, "market_dirty_price": dirty_price}
        ytm_data = client.post("/price/bond/ytm", json=ytm_payload).json()

        assert ytm_data["status"] == "solved"
        assert abs(ytm_data["ytm"] - 0.08) < 1e-5

    def test_seasoned_bond_does_not_fail_on_first_pillar_mismatch(self):
        payload = {
            **_BASE,
            "valuation_date": "2026-03-26",
            "issue_date": "2024-01-01",
            "maturity_date": "2029-01-01",
            "coupon_frequency": "annual",
            "market_dirty_price": 980_000.0,
        }
        resp = client.post("/price/bond/ytm", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "solved"
