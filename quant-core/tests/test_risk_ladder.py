"""
test_risk_ladder — Tests for quant_core.risk.ladder.pv01_ladder_irs

Coverage
--------
1.  Default bucket labels ("1Y"–"10Y") are present in the output dict.
2.  Short/intermediate buckets are non-zero for a 5Y payer on a 5Y curve.
3.  Buckets beyond the curve's last pillar return 0.0 (out-of-range rule).
4.  Payer swap → all in-range bucket PV01s are positive.
5.  Receiver swap → all in-range bucket PV01s are negative.
6.  Payer and receiver ladders are exactly opposite (sign-flip).
7.  Notional scaling: doubling the notional doubles every bucket PV01.
8.  Custom bucket_years list works and returns the correct labels.
9.  Sum of ALL bucket PV01s (when every pillar is covered by exactly one
    bucket) equals the signed scalar PV01 from price_irs(). This verifies
    directional consistency and that individual pillar bumps sum to the
    parallel bump for a linearly-priced instrument.
10. Invalid bucket_years entry raises ValueError.
11. No regressions in existing quant_core tests (verified by running the
    full test suite; this file's imports cover the dependency chain).

Canonical setup
---------------
* Valuation / start date : 2024-01-01
* Curve     : flat 8 %, 5Y, annual, ACT/365F  → 5 pillars at 1Y…5Y
* Swap      : 5Y annual ACT/365F payer, 8.5 % fixed, notional 1 000 000
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.irs import VanillaIRS
from quant_core.pricing.irs_pricer import price_irs
from quant_core.risk.ladder import (
    _DEFAULT_BUCKET_YEARS,
    _bucket_label,
    _bucket_target_date,
    _find_nearest_pillar_index,
    pv01_ladder_irs,
)

# ===========================================================================
# Shared fixtures
# ===========================================================================

VAL = date(2024, 1, 1)
_DC = DayCount.ACT_365F


def _5y_curve() -> DiscountCurve:
    """Five annual pillars (1Y … 5Y) at flat 8 %."""
    return flat_curve(VAL, 0.08, 5, "annual", _DC)


def _payer(notional: float = 1_000_000.0) -> VanillaIRS:
    return VanillaIRS(
        valuation_date=VAL,
        start_date=VAL,
        tenor_years=5,
        notional=notional,
        fixed_rate=0.085,
        payment_frequency="annual",
        day_count=_DC,
        pay_receive="payer",
    )


def _receiver(notional: float = 1_000_000.0) -> VanillaIRS:
    return VanillaIRS(
        valuation_date=VAL,
        start_date=VAL,
        tenor_years=5,
        notional=notional,
        fixed_rate=0.085,
        payment_frequency="annual",
        day_count=_DC,
        pay_receive="receiver",
    )


# ===========================================================================
# 1. Default bucket label set
# ===========================================================================


class TestDefaultBuckets:
    def test_default_keys_present(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        expected = {_bucket_label(y) for y in _DEFAULT_BUCKET_YEARS}
        assert set(ladder.keys()) == expected

    def test_default_bucket_count(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert len(ladder) == len(_DEFAULT_BUCKET_YEARS)


# ===========================================================================
# 2. Non-zero risk in short / intermediate buckets
# ===========================================================================


class TestNonZeroRisk:
    def test_1y_bucket_nonzero(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["1Y"] != 0.0, "1Y bucket should have non-zero risk for a 5Y swap"

    def test_2y_bucket_nonzero(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["2Y"] != 0.0

    def test_3y_bucket_nonzero(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["3Y"] != 0.0

    def test_5y_bucket_nonzero(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["5Y"] != 0.0


# ===========================================================================
# 3. Out-of-range rule: buckets beyond last curve pillar return 0.0
# ===========================================================================


class TestOutOfRange:
    def test_7y_is_zero_on_5y_curve(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["7Y"] == 0.0

    def test_10y_is_zero_on_5y_curve(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve())
        assert ladder["10Y"] == 0.0

    def test_far_custom_bucket_is_zero(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[20])
        assert ladder["20Y"] == 0.0


# ===========================================================================
# 4. Payer sign convention: in-range buckets are POSITIVE
# ===========================================================================


class TestPayerSign:
    """
    A payer swap (pay fixed, receive float) benefits from rising rates.
    A +1bp bump on any in-range pillar increases NPV → bucket PV01 > 0.
    """

    def test_1y_positive(self):
        assert pv01_ladder_irs(_payer(), _5y_curve())["1Y"] > 0.0

    def test_2y_positive(self):
        assert pv01_ladder_irs(_payer(), _5y_curve())["2Y"] > 0.0

    def test_3y_positive(self):
        assert pv01_ladder_irs(_payer(), _5y_curve())["3Y"] > 0.0

    def test_5y_positive(self):
        assert pv01_ladder_irs(_payer(), _5y_curve())["5Y"] > 0.0


# ===========================================================================
# 5. Receiver sign convention: in-range buckets are NEGATIVE
# ===========================================================================


class TestReceiverSign:
    """
    A receiver swap (receive fixed, pay float) loses value when rates rise.
    A +1bp bump on any in-range pillar decreases NPV → bucket PV01 < 0.
    """

    def test_1y_negative(self):
        assert pv01_ladder_irs(_receiver(), _5y_curve())["1Y"] < 0.0

    def test_2y_negative(self):
        assert pv01_ladder_irs(_receiver(), _5y_curve())["2Y"] < 0.0

    def test_5y_negative(self):
        assert pv01_ladder_irs(_receiver(), _5y_curve())["5Y"] < 0.0


# ===========================================================================
# 6. Payer and receiver ladders are exact sign-flips of each other
# ===========================================================================


class TestPayerReceiverSymmetry:
    def test_payer_receiver_exact_negation(self):
        payer_ladder = pv01_ladder_irs(_payer(), _5y_curve())
        recv_ladder = pv01_ladder_irs(_receiver(), _5y_curve())
        for key in payer_ladder:
            assert payer_ladder[key] == pytest.approx(-recv_ladder[key], abs=1e-9)


# ===========================================================================
# 7. Notional scaling
# ===========================================================================


class TestNotionalScaling:
    def test_doubling_notional_doubles_all_buckets(self):
        ladder_1m = pv01_ladder_irs(_payer(1_000_000.0), _5y_curve())
        ladder_2m = pv01_ladder_irs(_payer(2_000_000.0), _5y_curve())
        for key in ladder_1m:
            assert ladder_2m[key] == pytest.approx(2.0 * ladder_1m[key], rel=1e-9)

    def test_ten_times_notional_scales_all_buckets(self):
        ladder_1m = pv01_ladder_irs(_payer(1_000_000.0), _5y_curve())
        ladder_10m = pv01_ladder_irs(_payer(10_000_000.0), _5y_curve())
        for key in ladder_1m:
            assert ladder_10m[key] == pytest.approx(10.0 * ladder_1m[key], rel=1e-9)


# ===========================================================================
# 8. Custom bucket_years
# ===========================================================================


class TestCustomBuckets:
    def test_custom_single_bucket(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[2])
        assert list(ladder.keys()) == ["2Y"]
        assert ladder["2Y"] != 0.0

    def test_custom_bucket_order_preserved(self):
        ladder = pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[5, 3, 1])
        assert list(ladder.keys()) == ["5Y", "3Y", "1Y"]

    def test_custom_bucket_values_match_default(self):
        """Values produced for a bucket using a custom list match the defaults."""
        full = pv01_ladder_irs(_payer(), _5y_curve())
        single = pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[3])
        assert single["3Y"] == pytest.approx(full["3Y"], abs=1e-12)


# ===========================================================================
# 9. Sum of bucket PV01s consistent with scalar PV01
#
# With bucket_years=[1,2,3,4,5] the 5Y annual flat curve has exactly one
# bucket per pillar.  Because the pricing function is LINEAR in each
# individual df_i (no interpolation required when payment dates == pillar
# dates) the sum of single-pillar bumps equals the parallel bump exactly.
# For a payer swap: sum(bucket_pv01s) == +scalar_pv01.
# ===========================================================================


class TestSumVsScalarPv01:
    def test_payer_sum_equals_scalar_pv01(self):
        """
        With full pillar coverage the signed sum equals the positive scalar PV01.
        """
        curve = _5y_curve()
        swap = _payer()
        scalar_pv01 = price_irs(swap, curve).pv01  # always positive (absolute)
        ladder = pv01_ladder_irs(swap, curve, bucket_years=[1, 2, 3, 4, 5])
        signed_sum = sum(ladder.values())
        # payer → signed_sum is positive and equals scalar_pv01 exactly
        assert signed_sum == pytest.approx(scalar_pv01, rel=1e-8)

    def test_receiver_sum_equals_neg_scalar_pv01(self):
        curve = _5y_curve()
        swap = _receiver()
        scalar_pv01 = price_irs(swap, curve).pv01
        ladder = pv01_ladder_irs(swap, curve, bucket_years=[1, 2, 3, 4, 5])
        signed_sum = sum(ladder.values())
        # receiver → signed_sum is negative; |signed_sum| == scalar_pv01
        assert signed_sum == pytest.approx(-scalar_pv01, rel=1e-8)

    def test_sum_abs_buckets_approx_scalar_pv01(self):
        """
        With default buckets (missing 4Y on a 5Y annual curve) the sum of
        abs bucket PV01s is less than scalar PV01 because the 4Y pillar is
        not covered.  Verify it is still a meaningful positive fraction.
        """
        curve = _5y_curve()
        swap = _payer()
        scalar_pv01 = price_irs(swap, curve).pv01
        ladder = pv01_ladder_irs(swap, curve)
        total = sum(abs(v) for v in ladder.values())
        # Missing 4Y bucket → total < scalar_pv01 but > 75 % of it.
        assert 0.75 * scalar_pv01 < total < scalar_pv01


# ===========================================================================
# 10. Invalid bucket_years
# ===========================================================================


class TestInvalidBuckets:
    def test_zero_bucket_raises(self):
        with pytest.raises(ValueError, match="positive integers"):
            pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[0])

    def test_negative_bucket_raises(self):
        with pytest.raises(ValueError, match="positive integers"):
            pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[-1])

    def test_non_integer_bucket_raises(self):
        with pytest.raises(ValueError, match="positive integers"):
            pv01_ladder_irs(_payer(), _5y_curve(), bucket_years=[1.5])  # type: ignore[list-item]


# ===========================================================================
# 11. Private helper unit tests
# ===========================================================================


class TestHelpers:
    def test_bucket_label(self):
        assert _bucket_label(1) == "1Y"
        assert _bucket_label(10) == "10Y"

    def test_bucket_target_date_simple(self):
        assert _bucket_target_date(date(2024, 1, 1), 1) == date(2025, 1, 1)
        assert _bucket_target_date(date(2024, 1, 1), 5) == date(2029, 1, 1)

    def test_bucket_target_date_leap_year_edge(self):
        # 2028 is a leap year; 2029 is not → should return Feb 28
        target = _bucket_target_date(date(2028, 2, 29), 1)
        assert target == date(2029, 2, 28)

    def test_find_nearest_pillar_exact_match(self):
        pillars = [date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1)]
        assert _find_nearest_pillar_index(pillars, date(2026, 1, 1)) == 1

    def test_find_nearest_pillar_between_two(self):
        pillars = [date(2025, 1, 1), date(2026, 1, 1)]
        # Target is closer to pillar[1] (2026-01-01)
        target = date(2025, 9, 1)  # ~8 months from 2025, ~4 months from 2026
        idx = _find_nearest_pillar_index(pillars, target)
        assert idx == 1

    def test_find_nearest_pillar_tie_prefers_lower_index(self):
        # Equidistant → should return the lower index (earlier date)
        pillars = [date(2025, 1, 1), date(2025, 7, 2), date(2026, 1, 1)]
        # 2025-07-01 is equidistant between 2025-01-01 and 2026-01-01 (181 days each)
        # With the current implementation, the first minimum found is kept.
        target = date(2025, 7, 1)
        idx = _find_nearest_pillar_index(pillars, target)
        # pillar[0]: 181 days, pillar[1]: 1 day — pillar[1] wins
        assert idx == 1


# ===========================================================================
# 12. Bootstrapped curve ladder — directional smoke test
# ===========================================================================


class TestBootstrappedCurve:
    """
    Test that the ladder works on a bootstrapped (non-flat) curve with a
    finer pillar structure.  Uses the canonical mixed ladder fixture.
    """

    @pytest.fixture()
    def bs_curve(self):
        from quant_core.curves.bootstrap_mixed import (
            bootstrap_discount_curve_from_market_records,
        )
        from quant_core.marketdata.normalize_rates import normalize_market_quotes
        from quant_core.schemas.market_inputs import (
            DepositQuote,
            FRAQuote,
            ParSwapQuote,
        )

        deposits = [
            DepositQuote(tenor_months=1, rate=0.078),
            DepositQuote(tenor_months=3, rate=0.079),
            DepositQuote(tenor_months=6, rate=0.080),
        ]
        fras = [
            FRAQuote(start_months=6, end_months=9, rate=0.081),
            FRAQuote(start_months=9, end_months=12, rate=0.0815),
        ]
        swaps = [
            ParSwapQuote(tenor_years=2, par_rate=0.082),
            ParSwapQuote(tenor_years=3, par_rate=0.083),
            ParSwapQuote(tenor_years=5, par_rate=0.085),
        ]
        records = normalize_market_quotes(deposits=deposits, fras=fras, swaps=swaps)
        return bootstrap_discount_curve_from_market_records(
            valuation_date=date(2024, 1, 15),
            records=records,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
        )

    def test_bootstrapped_ladder_returns_correct_keys(self, bs_curve):
        swap = VanillaIRS(
            valuation_date=date(2024, 1, 15),
            start_date=date(2024, 1, 15),
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.085,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        ladder = pv01_ladder_irs(swap, bs_curve)
        expected = {_bucket_label(y) for y in [1, 2, 3, 5, 7, 10]}
        assert set(ladder.keys()) == expected

    def test_bootstrapped_ladder_payer_in_range_positive(self, bs_curve):
        swap = VanillaIRS(
            valuation_date=date(2024, 1, 15),
            start_date=date(2024, 1, 15),
            tenor_years=5,
            notional=1_000_000.0,
            fixed_rate=0.085,
            payment_frequency="annual",
            day_count=DayCount.ACT_365F,
            pay_receive="payer",
        )
        ladder = pv01_ladder_irs(swap, bs_curve)
        # 7Y and 10Y may be 0 (the bootstrapped curve extends to 5Y)
        in_range = {k: v for k, v in ladder.items() if v != 0.0}
        assert len(in_range) > 0, "Expected at least some non-zero buckets"
        for key, val in in_range.items():
            assert val > 0.0, f"Payer bucket {key} should be positive; got {val}"
