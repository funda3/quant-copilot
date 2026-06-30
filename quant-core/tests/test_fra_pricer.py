from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.curves.build_flat import flat_curve
from quant_core.curves.discount_curve import DiscountCurve
from quant_core.instruments.fra import FRA
from quant_core.pricing.fra_pricer import FRAPricingResult, price_fra


def _fra(**overrides) -> FRA:
    defaults = dict(
        valuation_date=date(2024, 1, 1),
        start_date=date(2024, 7, 1),
        end_date=date(2025, 1, 1),
        notional=1_000_000.0,
        contract_rate=0.08,
        day_count=DayCount.ACT_365F,
        position="payer",
    )
    defaults.update(overrides)
    return FRA(**defaults)


def _curve_for_fra(
    fra: FRA,
    rate: float = 0.08,
    day_count: DayCount | None = None,
) -> DiscountCurve:
    resolved_day_count = day_count or fra.day_count
    df_start = 1.0 / (
        1.0 + rate * accrual_fraction(fra.valuation_date, fra.start_date, resolved_day_count)
    )
    df_end = 1.0 / (
        1.0 + rate * accrual_fraction(fra.valuation_date, fra.end_date, resolved_day_count)
    )
    return DiscountCurve(
        fra.valuation_date,
        [fra.start_date, fra.end_date],
        [df_start, df_end],
    )


class TestFRAConstruction:
    def test_start_not_after_valuation_raises(self):
        with pytest.raises(ValueError, match="start_date"):
            _fra(start_date=date(2024, 1, 1))

    def test_end_not_after_start_raises(self):
        with pytest.raises(ValueError, match="end_date"):
            _fra(end_date=date(2024, 7, 1))

    def test_notional_non_positive_raises(self):
        with pytest.raises(ValueError, match="notional"):
            _fra(notional=0.0)

    def test_contract_rate_negative_raises(self):
        with pytest.raises(ValueError, match="contract_rate"):
            _fra(contract_rate=-0.01)

    def test_contract_rate_one_raises(self):
        with pytest.raises(ValueError, match="contract_rate"):
            _fra(contract_rate=1.0)

    def test_invalid_position_raises(self):
        with pytest.raises(ValueError, match="position"):
            _fra(position="long")

    def test_position_case_normalised(self):
        fra = _fra(position="RECEIVER")
        assert fra.position == "receiver"


class TestFRAPricing:
    def test_result_type(self):
        fra = _fra()
        result = price_fra(fra, _curve_for_fra(fra, rate=0.081))
        assert isinstance(result, FRAPricingResult)

    def test_forward_rate_positive_on_positive_curve(self):
        fra = _fra()
        result = price_fra(fra, _curve_for_fra(fra, rate=0.08))
        assert result.forward_rate > 0.0

    def test_payer_receiver_sign_flip(self):
        payer = _fra(position="payer", contract_rate=0.07)
        receiver = _fra(position="receiver", contract_rate=0.07)
        curve = _curve_for_fra(payer, rate=0.08)
        payer_result = price_fra(payer, curve)
        receiver_result = price_fra(receiver, curve)
        assert payer_result.payoff_undiscounted == pytest.approx(
            -receiver_result.payoff_undiscounted, rel=1e-12
        )
        assert payer_result.pv == pytest.approx(-receiver_result.pv, rel=1e-12)

    def test_near_par_contract_rate_gives_pv_near_zero(self):
        fra = _fra()
        curve = _curve_for_fra(fra, rate=0.08)
        par_rate = price_fra(fra, curve).forward_rate
        par_fra = _fra(contract_rate=par_rate)
        result = price_fra(par_fra, curve)
        assert abs(result.pv) < 1e-8

    def test_notional_scales_linearly(self):
        fra_small = _fra(notional=1_000_000.0, contract_rate=0.07)
        fra_large = _fra(notional=5_000_000.0, contract_rate=0.07)
        curve = _curve_for_fra(fra_small, rate=0.08)
        pv_small = price_fra(fra_small, curve).pv
        pv_large = price_fra(fra_large, curve).pv
        assert pv_large == pytest.approx(5.0 * pv_small, rel=1e-12)

    def test_deterministic_canonical_case(self):
        fra = _fra(contract_rate=0.075)
        curve = _curve_for_fra(fra, rate=0.08)
        tau = accrual_fraction(fra.start_date, fra.end_date, fra.day_count)
        df_start = curve.df(fra.start_date)
        df_end = curve.df(fra.end_date)
        expected_forward = (df_start / df_end - 1.0) / tau
        expected_payoff = fra.notional * (expected_forward - fra.contract_rate) * tau
        expected_pv = expected_payoff * df_end

        result = price_fra(fra, curve)

        assert result.forward_rate == pytest.approx(expected_forward, rel=1e-12)
        assert result.year_fraction == pytest.approx(tau, rel=1e-12)
        assert result.discount_factor_to_payment == pytest.approx(df_end, rel=1e-12)
        assert result.payoff_undiscounted == pytest.approx(expected_payoff, rel=1e-12)
        assert result.pv == pytest.approx(expected_pv, rel=1e-12)

    def test_zero_accrual_fraction_fails_clearly(self):
        fra = _fra(
            start_date=date(2024, 1, 30),
            end_date=date(2024, 1, 31),
            day_count=DayCount.THIRTY_360,
        )
        curve = DiscountCurve(
            fra.valuation_date,
            [fra.start_date, fra.end_date],
            [0.99, 0.98],
        )
        with pytest.raises(ValueError, match="year fraction"):
            price_fra(fra, curve)

    def test_curve_domain_error_surfaces(self):
        fra = _fra()
        curve = flat_curve(fra.valuation_date, 0.08, 1, "annual", fra.day_count)
        with pytest.raises(ValueError, match="before the first pillar"):
            price_fra(fra, curve)