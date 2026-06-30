"""
Tests for POST /curve â€” bootstrap discount curve from par swap quotes.

Conventions used in canonical fixture
--------------------------------------
valuation_date : date.today() (set by the endpoint)
swap_quotes    : 1Y @ 8.00%, 2Y @ 8.10%, 3Y @ 8.20%, 5Y @ 8.50%
frequency      : annual
day_count      : ACT_365F

Single-quote algebraic check (1Y annual ACT/365F):
    tau ~ 1.0  â†’  df_1Y = 1 / (1 + 0.08 * tau)
    For a 365-day year tau = 1.0 exactly, so df_1Y â‰ˆ 1 / 1.08 â‰ˆ 0.925926
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SINGLE_1Y = {"swap_quotes": [{"tenor_years": 1, "par_rate": 0.08}]}

_LADDER_4Q = {
    "swap_quotes": [
        {"tenor_years": 1, "par_rate": 0.0800},
        {"tenor_years": 2, "par_rate": 0.0810},
        {"tenor_years": 3, "par_rate": 0.0820},
        {"tenor_years": 5, "par_rate": 0.0850},
    ]
}

_SEMIANNUAL_2Y = {
    "swap_quotes": [
        {"tenor_years": 1, "par_rate": 0.08},
        {"tenor_years": 2, "par_rate": 0.081},
    ],
    "payment_frequency": "semiannual",
}

_QUARTERLY_2Y = {
    "swap_quotes": [
        {"tenor_years": 1, "par_rate": 0.08},
        {"tenor_years": 2, "par_rate": 0.081},
    ],
    "payment_frequency": "quarterly",
}


# ===========================================================================
# 1. HTTP contract
# ===========================================================================


class TestHttpContract:
    def test_valid_request_returns_200(self) -> None:
        assert client.post("/api/curve/swap", json=_SINGLE_1Y).status_code == 200

    def test_response_has_required_keys(self) -> None:
        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        for key in ("request_id", "valuation_date", "pillar_dates", "discount_factors", "status", "warnings"):
            assert key in data, f"missing key: {key}"

    def test_status_is_ok(self) -> None:
        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        assert data["status"] == "ok"

    def test_warnings_is_empty_list_for_valid_input(self) -> None:
        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        assert data["warnings"] == []

    def test_request_id_is_uuid_string(self) -> None:
        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        rid = data["request_id"]
        assert isinstance(rid, str)
        assert len(rid) == 36  # UUID4 canonical form

    def test_two_calls_produce_different_request_ids(self) -> None:
        r1 = client.post("/api/curve/swap", json=_SINGLE_1Y).json()["request_id"]
        r2 = client.post("/api/curve/swap", json=_SINGLE_1Y).json()["request_id"]
        assert r1 != r2

    def test_missing_swap_quotes_returns_422(self) -> None:
        assert client.post("/api/curve/swap", json={}).status_code == 422


# ===========================================================================
# 2. Input validation â€” 422 paths
# ===========================================================================


class TestInputValidation:
    def test_empty_quote_list_returns_422(self) -> None:
        assert client.post("/api/curve/swap", json={"swap_quotes": []}).status_code == 422

    def test_duplicate_tenor_returns_422(self) -> None:
        payload = {
            "swap_quotes": [
                {"tenor_years": 2, "par_rate": 0.08},
                {"tenor_years": 2, "par_rate": 0.081},
            ]
        }
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_tenor_zero_returns_422(self) -> None:
        payload = {"swap_quotes": [{"tenor_years": 0, "par_rate": 0.08}]}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_tenor_negative_returns_422(self) -> None:
        payload = {"swap_quotes": [{"tenor_years": -1, "par_rate": 0.08}]}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_par_rate_zero_returns_422(self) -> None:
        payload = {"swap_quotes": [{"tenor_years": 1, "par_rate": 0.0}]}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_par_rate_above_one_returns_422(self) -> None:
        payload = {"swap_quotes": [{"tenor_years": 1, "par_rate": 1.1}]}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_unsupported_frequency_returns_422(self) -> None:
        payload = {**_SINGLE_1Y, "payment_frequency": "biannual"}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_unsupported_day_count_returns_422(self) -> None:
        payload = {**_SINGLE_1Y, "day_count": "ACT_252"}
        assert client.post("/api/curve/swap", json=payload).status_code == 422

    def test_monotone_df_violation_returns_422(self) -> None:
        # 90% 1Y then 1% 2Y would produce increasing df â€” pathological
        payload = {
            "swap_quotes": [
                {"tenor_years": 1, "par_rate": 0.90},
                {"tenor_years": 2, "par_rate": 0.01},
            ]
        }
        assert client.post("/api/curve/swap", json=payload).status_code == 422


# ===========================================================================
# 3. Output structure
# ===========================================================================


class TestOutputStructure:
    def test_single_quote_annual_pillar_count(self) -> None:
        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        # Annual 1Y: only one maturity pillar (no intermediate coupons)
        assert len(data["pillar_dates"]) == 1

    def test_four_quote_annual_pillar_count_matches_quotes(self) -> None:
        data = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        # 4 annual quotes â†’ 4 maturity pillars
        assert len(data["pillar_dates"]) == 4

    def test_pillar_dates_match_discount_factors_length(self) -> None:
        data = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        assert len(data["pillar_dates"]) == len(data["discount_factors"])

    def test_pillar_dates_are_iso_format(self) -> None:
        from datetime import date

        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        for ds in data["pillar_dates"]:
            date.fromisoformat(ds)  # raises if not valid ISO-8601

    def test_valuation_date_is_iso_format(self) -> None:
        from datetime import date

        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        date.fromisoformat(data["valuation_date"])

    def test_semiannual_two_quote_pillar_count(self) -> None:
        data = client.post("/api/curve/swap", json=_SEMIANNUAL_2Y).json()
        # 1Y semiannual: 2 pillars (6M + 1Y); 2Y adds 1 more â†’ 3 total
        assert len(data["pillar_dates"]) == 3

    def test_quarterly_two_quote_pillar_count(self) -> None:
        data = client.post("/api/curve/swap", json=_QUARTERLY_2Y).json()
        # 1Y quarterly: 4 intermediate pillars; 2Y adds maturity â†’ 5 total
        assert len(data["pillar_dates"]) == 5


# ===========================================================================
# 4. Discount factor validity
# ===========================================================================


class TestDiscountFactorValidity:
    def test_all_discount_factors_positive(self) -> None:
        data = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        for df in data["discount_factors"]:
            assert df > 0.0

    def test_all_discount_factors_below_one(self) -> None:
        data = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        for df in data["discount_factors"]:
            assert df < 1.0

    def test_discount_factors_nonincreasing(self) -> None:
        data = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        dfs = data["discount_factors"]
        for i in range(1, len(dfs)):
            assert dfs[i] <= dfs[i - 1], f"df not non-increasing at index {i}"


# ===========================================================================
# 5. Single-quote algebraic check
# ===========================================================================


class TestSingleQuoteAlgebra:
    def test_1y_annual_df_matches_algebraic_formula(self) -> None:
        from datetime import date

        data = client.post("/api/curve/swap", json=_SINGLE_1Y).json()
        df_api = data["discount_factors"][0]
        pillar = date.fromisoformat(data["pillar_dates"][0])
        val = date.fromisoformat(data["valuation_date"])
        tau = (pillar - val).days / 365.0  # ACT/365F
        df_expected = 1.0 / (1.0 + 0.08 * tau)
        assert abs(df_api - df_expected) < 1e-10


# ===========================================================================
# 6. Input ordering
# ===========================================================================


class TestInputOrdering:
    def test_reversed_input_produces_same_curve(self) -> None:
        quotes = list(reversed(_LADDER_4Q["swap_quotes"]))
        payload = {**_LADDER_4Q, "swap_quotes": quotes}
        data_fwd = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        data_rev = client.post("/api/curve/swap", json=payload).json()
        assert data_fwd["pillar_dates"] == data_rev["pillar_dates"]
        for a, b in zip(data_fwd["discount_factors"], data_rev["discount_factors"]):
            assert abs(a - b) < 1e-12

    def test_shuffled_input_produces_same_curve(self) -> None:
        shuffled = [
            {"tenor_years": 3, "par_rate": 0.0820},
            {"tenor_years": 1, "par_rate": 0.0800},
            {"tenor_years": 5, "par_rate": 0.0850},
            {"tenor_years": 2, "par_rate": 0.0810},
        ]
        data_orig = client.post("/api/curve/swap", json=_LADDER_4Q).json()
        data_shuf = client.post("/api/curve/swap", json={"swap_quotes": shuffled}).json()
        assert data_orig["pillar_dates"] == data_shuf["pillar_dates"]
        for a, b in zip(data_orig["discount_factors"], data_shuf["discount_factors"]):
            assert abs(a - b) < 1e-12


# ===========================================================================
# 7. Accepted day-count and frequency variants
# ===========================================================================


class TestAcceptedVariants:
    def test_act_360_day_count_accepted(self) -> None:
        payload = {**_SINGLE_1Y, "day_count": "ACT_360"}
        assert client.post("/api/curve/swap", json=payload).status_code == 200

    def test_30_360_day_count_accepted(self) -> None:
        payload = {**_SINGLE_1Y, "day_count": "30_360"}
        assert client.post("/api/curve/swap", json=payload).status_code == 200

    def test_act_act_isda_day_count_accepted(self) -> None:
        payload = {**_SINGLE_1Y, "day_count": "ACT_ACT_ISDA"}
        assert client.post("/api/curve/swap", json=payload).status_code == 200

    def test_quarterly_frequency_accepted(self) -> None:
        assert client.post("/api/curve/swap", json=_QUARTERLY_2Y).status_code == 200

    def test_semiannual_frequency_accepted(self) -> None:
        assert client.post("/api/curve/swap", json=_SEMIANNUAL_2Y).status_code == 200
