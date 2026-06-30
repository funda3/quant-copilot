"""
Tests for POST /mixed-curve â€” bootstrap a discount curve from mixed
deposit, FRA, and par-swap market quotes.

Canon mixed ladder (mirrors quant-core Step 8 canonical fixture):
  Deposits : 1M @ 7.8 %, 3M @ 7.9 %, 6M @ 8.0 %
  FRAs     : 6x9 @ 8.1 %, 9x12 @ 8.15 %
  Swaps    : 2Y @ 8.2 %, 3Y @ 8.3 %, 5Y @ 8.5 %

valuation_date : "2024-01-15"
payment_frequency : "annual"
day_count : "ACT_365F"
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Canonical fixture helpers
# ---------------------------------------------------------------------------

_VAL = "2024-01-15"

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

_CANON = {
    "valuation_date": _VAL,
    "deposits": _CANON_DEPOSITS,
    "fras": _CANON_FRAS,
    "swaps": _CANON_SWAPS,
}

_DEPOSITS_ONLY = {
    "valuation_date": _VAL,
    "deposits": _CANON_DEPOSITS,
}

_DEPOSITS_AND_FRAS = {
    "valuation_date": _VAL,
    "deposits": _CANON_DEPOSITS,
    "fras": _CANON_FRAS,
}


# ===========================================================================
# 1. HTTP contract
# ===========================================================================


class TestHttpContract:
    def test_valid_deposit_only_returns_200(self) -> None:
        assert client.post("/api/curve", json=_DEPOSITS_ONLY).status_code == 200

    def test_valid_deposit_fra_returns_200(self) -> None:
        assert client.post("/api/curve", json=_DEPOSITS_AND_FRAS).status_code == 200

    def test_valid_mixed_ladder_returns_200(self) -> None:
        assert client.post("/api/curve", json=_CANON).status_code == 200

    def test_response_has_required_keys(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        for key in (
            "request_id",
            "valuation_date",
            "pillar_dates",
            "discount_factors",
            "n_pillars",
            "status",
            "warnings",
        ):
            assert key in data, f"missing response key: {key}"

    def test_status_is_ok(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        assert data["status"] == "ok"

    def test_warnings_is_empty_list(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        assert data["warnings"] == []

    def test_request_id_is_uuid_string(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        rid = data["request_id"]
        assert isinstance(rid, str) and len(rid) == 36

    def test_two_calls_produce_different_request_ids(self) -> None:
        r1 = client.post("/api/curve", json=_DEPOSITS_ONLY).json()["request_id"]
        r2 = client.post("/api/curve", json=_DEPOSITS_ONLY).json()["request_id"]
        assert r1 != r2

    def test_valuation_date_echoed_in_response(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        assert data["valuation_date"] == _VAL

    def test_n_pillars_matches_pillar_dates_length(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        assert data["n_pillars"] == len(data["pillar_dates"])

    def test_n_pillars_matches_discount_factors_length(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        assert data["n_pillars"] == len(data["discount_factors"])


# ===========================================================================
# 2. Input validation â€” rejected inputs return 422
# ===========================================================================


class TestInputValidation:
    def test_empty_body_returns_422(self) -> None:
        assert client.post("/api/curve", json={}).status_code == 422

    def test_all_empty_lists_returns_422(self) -> None:
        payload = {"valuation_date": _VAL, "deposits": [], "fras": [], "swaps": []}
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_missing_all_instruments_returns_422(self) -> None:
        payload = {"valuation_date": _VAL}
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_invalid_valuation_date_returns_422(self) -> None:
        payload = {**_DEPOSITS_ONLY, "valuation_date": "not-a-date"}
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_unsupported_frequency_returns_422(self) -> None:
        payload = {**_DEPOSITS_ONLY, "payment_frequency": "weekly"}
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_unsupported_day_count_returns_422(self) -> None:
        payload = {**_DEPOSITS_ONLY, "day_count": "ACT_252"}
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_deposit_rate_zero_returns_422(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "deposits": [{"tenor_months": 3, "rate": 0.0}],
        }
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_deposit_rate_above_one_returns_422(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "deposits": [{"tenor_months": 3, "rate": 1.1}],
        }
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_fra_end_before_start_returns_422(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "deposits": [{"tenor_months": 6, "rate": 0.078}],
            "fras": [{"start_months": 9, "end_months": 6, "rate": 0.081}],
        }
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_duplicate_deposit_tenors_returns_422(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "deposits": [
                {"tenor_months": 3, "rate": 0.079},
                {"tenor_months": 3, "rate": 0.085},  # same tenor, different rate
            ],
        }
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_fra_without_prior_deposit_returns_422(self) -> None:
        """A FRA with start_months > 0 and no covering deposit must fail."""
        payload = {
            "valuation_date": _VAL,
            "fras": [{"start_months": 6, "end_months": 9, "rate": 0.081}],
        }
        assert client.post("/api/curve", json=payload).status_code == 422

    def test_swap_non_integer_year_returns_422(self) -> None:
        # tenor_months = 18 â†’ 1.5 years (not supported)
        # SwapInput uses tenor_years (int), so 18-month swap isn't directly
        # expressible.  Verify a zero-tenor swap is rejected.
        payload = {
            "valuation_date": _VAL,
            "swaps": [{"tenor_years": 0, "par_rate": 0.08}],
        }
        assert client.post("/api/curve", json=payload).status_code == 422


# ===========================================================================
# 3. Pillar count correctness
# ===========================================================================


class TestPillarCount:
    def test_three_deposits_produce_three_pillars(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        assert data["n_pillars"] == 3

    def test_deposits_plus_two_fras_produce_five_pillars(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_AND_FRAS).json()
        assert data["n_pillars"] == 5

    def test_canon_mixed_ladder_pillar_count(self) -> None:
        """
        Canon: 3 deposits + 2 FRAs + 3 swap maturities.
        Swaps bootstrapped annually: the 2Y, 3Y, 5Y maturities are added.
        The 12M FRA pillar coincides with the 1Y coupon of the 2Y swap
        â†’ still 5 short-end + 3 long-end = 8 pillars total.
        """
        data = client.post("/api/curve", json=_CANON).json()
        assert data["n_pillars"] == 8

    def test_single_deposit_produces_one_pillar(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "deposits": [{"tenor_months": 6, "rate": 0.080}],
        }
        data = client.post("/api/curve", json=payload).json()
        assert data["n_pillars"] == 1


# ===========================================================================
# 4. Response shape and ordering
# ===========================================================================


class TestResponseShape:
    def test_pillar_dates_are_iso_format(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        for ds in data["pillar_dates"]:
            date.fromisoformat(ds)  # raises if not valid ISO-8601

    def test_valuation_date_is_iso_format(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        date.fromisoformat(data["valuation_date"])

    def test_pillar_dates_strictly_increasing(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        dates = [date.fromisoformat(d) for d in data["pillar_dates"]]
        for i in range(1, len(dates)):
            assert dates[i] > dates[i - 1], f"pillar dates not strictly increasing at index {i}"

    def test_discount_factors_list_aligns_with_pillar_dates(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        assert len(data["discount_factors"]) == len(data["pillar_dates"])

    def test_first_pillar_is_1m(self) -> None:
        """Earliest instrument is 1M deposit â†’ first pillar is 2024-02-15."""
        data = client.post("/api/curve", json=_CANON).json()
        expected_1m = date(2024, 2, 15).isoformat()
        assert data["pillar_dates"][0] == expected_1m

    def test_last_pillar_is_5y(self) -> None:
        """Latest instrument is 5Y swap â†’ last pillar is 2029-01-15."""
        data = client.post("/api/curve", json=_CANON).json()
        expected_5y = date(2029, 1, 15).isoformat()
        assert data["pillar_dates"][-1] == expected_5y


# ===========================================================================
# 5. Discount factor validity
# ===========================================================================


class TestDiscountFactorValidity:
    def test_all_discount_factors_positive(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        for df in data["discount_factors"]:
            assert df > 0.0, f"non-positive df: {df}"

    def test_all_discount_factors_below_one(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        for df in data["discount_factors"]:
            assert df < 1.0, f"df >= 1.0: {df}"

    def test_discount_factors_non_increasing(self) -> None:
        data = client.post("/api/curve", json=_CANON).json()
        dfs = data["discount_factors"]
        for i in range(1, len(dfs)):
            assert dfs[i] <= dfs[i - 1], f"dfs not non-increasing at index {i}"

    def test_deposit_only_discount_factors_positive(self) -> None:
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        assert all(df > 0 for df in data["discount_factors"])

    def test_mixed_all_dfs_in_reasonable_range(self) -> None:
        """At ~8% for up to 5 years, all dfs must sit in (0.60, 1.00)."""
        data = client.post("/api/curve", json=_CANON).json()
        for df in data["discount_factors"]:
            assert 0.60 < df < 1.00, f"df={df:.6f} outside expected range"


# ===========================================================================
# 6. Formula correctness spot-checks
# ===========================================================================


class TestFormulaSpotChecks:
    def test_1m_deposit_formula(self) -> None:
        """df(1M) = 1 / (1 + 0.078 * Ï„(val, 1M)) â€” exact to floating precision."""
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        t_val = date.fromisoformat(_VAL)
        t_1m = date.fromisoformat(data["pillar_dates"][0])
        tau = (t_1m - t_val).days / 365.0  # ACT/365F
        expected = 1.0 / (1.0 + 0.078 * tau)
        assert abs(data["discount_factors"][0] - expected) < 1e-10

    def test_6m_deposit_formula(self) -> None:
        """df(6M) = 1 / (1 + 0.080 * Ï„(val, 6M))."""
        data = client.post("/api/curve", json=_DEPOSITS_ONLY).json()
        t_val = date.fromisoformat(_VAL)
        # third pillar is 6M
        t_6m = date.fromisoformat(data["pillar_dates"][2])
        tau = (t_6m - t_val).days / 365.0
        expected = 1.0 / (1.0 + 0.080 * tau)
        assert abs(data["discount_factors"][2] - expected) < 1e-10

    def test_fra_9m_formula(self) -> None:
        """df(9M) = df(6M) / (1 + 0.081 * Ï„(6M, 9M))."""
        data = client.post("/api/curve", json=_DEPOSITS_AND_FRAS).json()
        pillar_dates = [date.fromisoformat(d) for d in data["pillar_dates"]]
        dfs = data["discount_factors"]
        # find 6M and 9M indices
        t_val = date.fromisoformat(_VAL)
        t_6m = date(2024, 7, 15)
        t_9m = date(2024, 10, 15)
        idx_6m = pillar_dates.index(t_6m)
        idx_9m = pillar_dates.index(t_9m)
        df_6m = dfs[idx_6m]
        tau = (t_9m - t_6m).days / 365.0
        expected_df_9m = df_6m / (1.0 + 0.081 * tau)
        assert abs(dfs[idx_9m] - expected_df_9m) < 1e-10


# ===========================================================================
# 7. Determinism and input-order independence
# ===========================================================================


class TestDeterminism:
    def test_same_input_produces_same_curve(self) -> None:
        d1 = client.post("/api/curve", json=_CANON).json()
        d2 = client.post("/api/curve", json=_CANON).json()
        assert d1["pillar_dates"] == d2["pillar_dates"]
        for a, b in zip(d1["discount_factors"], d2["discount_factors"]):
            assert abs(a - b) < 1e-15

    def test_reversed_deposits_produce_same_curve(self) -> None:
        payload_fwd = _DEPOSITS_ONLY
        payload_rev = {**_DEPOSITS_ONLY, "deposits": list(reversed(_CANON_DEPOSITS))}
        d_fwd = client.post("/api/curve", json=payload_fwd).json()
        d_rev = client.post("/api/curve", json=payload_rev).json()
        assert d_fwd["pillar_dates"] == d_rev["pillar_dates"]
        for a, b in zip(d_fwd["discount_factors"], d_rev["discount_factors"]):
            assert abs(a - b) < 1e-12

    def test_reversed_full_mixed_inputs_produce_same_curve(self) -> None:
        """Mixed inputs in reverse order must produce the same curve."""
        rev_payload = {
            "valuation_date": _VAL,
            "deposits": list(reversed(_CANON_DEPOSITS)),
            "fras": list(reversed(_CANON_FRAS)),
            "swaps": list(reversed(_CANON_SWAPS)),
        }
        d_fwd = client.post("/api/curve", json=_CANON).json()
        d_rev = client.post("/api/curve", json=rev_payload).json()
        assert d_fwd["pillar_dates"] == d_rev["pillar_dates"]
        for a, b in zip(d_fwd["discount_factors"], d_rev["discount_factors"]):
            assert abs(a - b) < 1e-12


# ===========================================================================
# 8. Canonical regression â€” pinned leading/trailing dfs
# ===========================================================================


class TestCanonicalRegression:
    """
    Pins the leading (1M) and trailing (5Y) discount factors from the canon
    ladder.  If the bootstrap algorithm regresses, these will shift.
    """

    def _data(self):
        return client.post("/api/curve", json=_CANON).json()

    def test_leading_df_1m_matches_formula(self) -> None:
        data = self._data()
        t_val = date.fromisoformat(_VAL)
        t_1m = date.fromisoformat(data["pillar_dates"][0])
        tau = (t_1m - t_val).days / 365.0
        expected = 1.0 / (1.0 + 0.078 * tau)
        assert abs(data["discount_factors"][0] - expected) < 1e-12

    def test_trailing_df_5y_in_range(self) -> None:
        """5Y df at ~8.5% should be near exp(-0.085 * 5) â‰ˆ 0.652; allow Â±5%."""
        import math

        data = self._data()
        df_5y = data["discount_factors"][-1]
        rough = math.exp(-0.085 * 5)
        assert abs(df_5y - rough) / rough < 0.05

    def test_all_eight_canon_tenor_pillars_present(self) -> None:
        """All 8 tenors (1M, 3M, 6M, 9M, 12M, 2Y, 3Y, 5Y) must appear."""
        data = self._data()
        dates = set(data["pillar_dates"])
        expected = {
            "2024-02-15",  # 1M
            "2024-04-15",  # 3M
            "2024-07-15",  # 6M
            "2024-10-15",  # 9M
            "2025-01-15",  # 12M
            "2026-01-15",  # 2Y
            "2027-01-15",  # 3Y
            "2029-01-15",  # 5Y
        }
        assert expected == dates


# ===========================================================================
# 9. Accepted day-count and frequency variants
# ===========================================================================


class TestAcceptedVariants:
    def test_act_360_accepted(self) -> None:
        payload = {**_DEPOSITS_ONLY, "day_count": "ACT_360"}
        assert client.post("/api/curve", json=payload).status_code == 200

    def test_30_360_accepted(self) -> None:
        payload = {**_DEPOSITS_ONLY, "day_count": "30_360"}
        assert client.post("/api/curve", json=payload).status_code == 200

    def test_act_act_isda_accepted(self) -> None:
        payload = {**_DEPOSITS_ONLY, "day_count": "ACT_ACT_ISDA"}
        assert client.post("/api/curve", json=payload).status_code == 200

    def test_semiannual_frequency_accepted(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "swaps": [{"tenor_years": 2, "par_rate": 0.082}],
            "payment_frequency": "semiannual",
        }
        assert client.post("/api/curve", json=payload).status_code == 200

    def test_quarterly_frequency_accepted(self) -> None:
        payload = {
            "valuation_date": _VAL,
            "swaps": [{"tenor_years": 2, "par_rate": 0.082}],
            "payment_frequency": "quarterly",
        }
        assert client.post("/api/curve", json=payload).status_code == 200

    def test_valuation_date_optional_defaults_to_today(self) -> None:
        payload = {"deposits": [{"tenor_months": 3, "rate": 0.079}]}
        resp = client.post("/api/curve", json=payload)
        assert resp.status_code == 200
        assert resp.json()["valuation_date"] == date.today().isoformat()


# ===========================================================================
# 10. Old /curve endpoint is untouched
# ===========================================================================


class TestLegacyEndpointUnchanged:
    """Confirm the existing swap-only /curve endpoint still works."""

    _LEGACY_PAYLOAD = {
        "swap_quotes": [
            {"tenor_years": 1, "par_rate": 0.08},
            {"tenor_years": 2, "par_rate": 0.082},
        ]
    }

    def test_legacy_endpoint_returns_200(self) -> None:
        assert client.post("/api/curve/swap", json=self._LEGACY_PAYLOAD).status_code == 200

    def test_legacy_response_has_no_n_pillars_key(self) -> None:
        data = client.post("/api/curve/swap", json=self._LEGACY_PAYLOAD).json()
        assert "n_pillars" not in data

    def test_legacy_response_has_status_ok(self) -> None:
        data = client.post("/api/curve/swap", json=self._LEGACY_PAYLOAD).json()
        assert data["status"] == "ok"
