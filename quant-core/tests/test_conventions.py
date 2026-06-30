"""
Tests for quant_core conventions engine — Phase 1.

Covers:
  - quant_core.conventions.day_count  (ACT/365F, ACT/360, 30/360, ACT/ACT ISDA)
  - quant_core.conventions.schedule   (generate_unadjusted_dates, n_payments)
  - quant_core.utils.date_utils       (add_months)

Reference values for day-count fractions are computed by hand and verified
against ISDA 2006 Definitions published test cases where applicable.
"""
from __future__ import annotations

from datetime import date

import pytest

from quant_core.conventions.day_count import DayCount, accrual_fraction
from quant_core.conventions.schedule import generate_unadjusted_dates, n_payments
from quant_core.utils.date_utils import add_months


# ===========================================================================
# Helpers
# ===========================================================================

def _frac(d1: tuple, d2: tuple, convention: DayCount | str) -> float:
    return accrual_fraction(date(*d1), date(*d2), convention)


# ===========================================================================
# DayCount enum
# ===========================================================================

class TestDayCountEnum:
    def test_enum_values(self):
        assert DayCount.ACT_365F == "ACT/365F"
        assert DayCount.ACT_360 == "ACT/360"
        assert DayCount.THIRTY_360 == "30/360"
        assert DayCount.ACT_ACT_ISDA == "ACT/ACT ISDA"

    def test_string_coercion_valid(self):
        # accrual_fraction accepts a plain string and coerces it to DayCount
        result = _frac((2024, 1, 1), (2024, 7, 1), "ACT/365F")
        assert result == pytest.approx(182 / 365)

    def test_string_coercion_invalid(self):
        with pytest.raises(ValueError):
            _frac((2024, 1, 1), (2024, 7, 1), "UNKNOWN/CONVENTION")


# ===========================================================================
# ACT/365F
# ===========================================================================

class TestAct365F:
    """ACT/365 Fixed: actual_days / 365.  Leap years are irrelevant."""

    def test_half_year_leap(self):
        # 2024 is a leap year; ACT/365F still divides by 365
        result = _frac((2024, 1, 1), (2024, 7, 1), DayCount.ACT_365F)
        assert result == pytest.approx(182 / 365)

    def test_full_year_spanning_leap(self):
        # 2024 is leap → 366 actual days, still divided by 365
        result = _frac((2024, 1, 1), (2025, 1, 1), DayCount.ACT_365F)
        assert result == pytest.approx(366 / 365)

    def test_full_non_leap_year(self):
        result = _frac((2023, 1, 1), (2024, 1, 1), DayCount.ACT_365F)
        assert result == pytest.approx(365 / 365)  # == 1.0

    def test_quarterly_period(self):
        # Jan 1 → Apr 1 = 91 days (2024 leap: Jan 31, Feb 29, Mar 31 → 91)
        result = _frac((2024, 1, 1), (2024, 4, 1), DayCount.ACT_365F)
        assert result == pytest.approx(91 / 365)

    def test_zero_length(self):
        result = _frac((2024, 6, 15), (2024, 6, 15), DayCount.ACT_365F)
        assert result == pytest.approx(0.0)


# ===========================================================================
# ACT/360
# ===========================================================================

class TestAct360:
    """ACT/360: actual_days / 360."""

    def test_half_year(self):
        result = _frac((2024, 1, 1), (2024, 7, 1), DayCount.ACT_360)
        assert result == pytest.approx(182 / 360)

    def test_quarterly_period(self):
        result = _frac((2024, 1, 1), (2024, 4, 1), DayCount.ACT_360)
        assert result == pytest.approx(91 / 360)

    def test_full_leap_year(self):
        # 366 actual days / 360 > 1
        result = _frac((2024, 1, 1), (2025, 1, 1), DayCount.ACT_360)
        assert result == pytest.approx(366 / 360)

    def test_zero_length(self):
        result = _frac((2024, 3, 15), (2024, 3, 15), DayCount.ACT_360)
        assert result == pytest.approx(0.0)


# ===========================================================================
# 30/360 Bond Basis (ISDA 2006 §4.16(f))
# ===========================================================================

class TestThirty360:
    """
    30/360: each month treated as 30 days.

    D1 adjustment: D1==31 → D1=30.
    D2 adjustment: D2==31 AND D1(after adj)==30 → D2=30.
    """

    def test_start_of_month_quarter(self):
        # (360*0 + 30*3 + 0) / 360 = 90/360 = 0.25
        result = _frac((2024, 1, 1), (2024, 4, 1), DayCount.THIRTY_360)
        assert result == pytest.approx(90 / 360)

    def test_start_of_month_semi(self):
        # (360*0 + 30*6 + 0) / 360 = 180/360 = 0.5
        result = _frac((2024, 1, 1), (2024, 7, 1), DayCount.THIRTY_360)
        assert result == pytest.approx(180 / 360)

    def test_full_year(self):
        # (360*1 + 0 + 0) / 360 = 1.0
        result = _frac((2024, 1, 1), (2025, 1, 1), DayCount.THIRTY_360)
        assert result == pytest.approx(1.0)

    def test_d1_31_adjusted(self):
        # D1=31 → D1=30; D2=30 (not 31, no adj)
        # (360*0 + 30*3 + (30-30)) / 360 = 90/360
        result = _frac((2024, 1, 31), (2024, 4, 30), DayCount.THIRTY_360)
        assert result == pytest.approx(90 / 360)

    def test_d1_31_d2_31_both_adjusted(self):
        # D1=31 → D1=30; D2=31 and D1=30 → D2=30
        # (360*0 + 30*6 + 0) / 360 = 180/360 = 0.5
        result = _frac((2024, 1, 31), (2024, 7, 31), DayCount.THIRTY_360)
        assert result == pytest.approx(180 / 360)

    def test_d1_30_d2_31_adjusted(self):
        # D1=30 (no adj needed); D2=31 and D1=30 → D2=30
        # (360*0 + 30*3 + (30-30)) / 360 = 90/360
        result = _frac((2024, 4, 30), (2024, 7, 31), DayCount.THIRTY_360)
        assert result == pytest.approx(90 / 360)

    def test_d1_29_d2_31_no_d2_adjustment(self):
        # D1=29 (not 31, no adj); D2=31 but D1≠30 so no adj to D2
        # (360*0 + 30*3 + (31-29)) / 360 = 92/360
        result = _frac((2024, 4, 29), (2024, 7, 31), DayCount.THIRTY_360)
        assert result == pytest.approx(92 / 360)

    def test_zero_length(self):
        result = _frac((2024, 6, 1), (2024, 6, 1), DayCount.THIRTY_360)
        assert result == pytest.approx(0.0)


# ===========================================================================
# ACT/ACT ISDA (ISDA 2006 §4.16(b))
# ===========================================================================

class TestActActIsda:
    """
    ACT/ACT ISDA: period split at 1-Jan boundaries.
    Each year's days divided by 365 or 366 (if leap).
    """

    def test_whole_leap_year(self):
        # 2024 is leap: 366 days / 366 = 1.0
        result = _frac((2024, 1, 1), (2025, 1, 1), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(1.0)

    def test_whole_non_leap_year(self):
        # 2023 is not leap: 365 days / 365 = 1.0
        result = _frac((2023, 1, 1), (2024, 1, 1), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(1.0)

    def test_half_year_within_leap(self):
        # All in 2024 (leap): 182 days / 366
        result = _frac((2024, 1, 1), (2024, 7, 1), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(182 / 366)

    def test_cross_year_boundary(self):
        # 2023-07-01 → 2024-07-01
        # In 2023 (non-leap): (2024-01-01 - 2023-07-01).days = 184  → 184/365
        # In 2024 (leap):     (2024-07-01 - 2024-01-01).days = 182  → 182/366
        expected = 184 / 365 + 182 / 366
        result = _frac((2023, 7, 1), (2024, 7, 1), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(expected)

    def test_cross_year_boundary_non_leap_to_non_leap(self):
        # 2022-07-01 → 2023-07-01 (both non-leap)
        # In 2022: (2023-01-01 - 2022-07-01).days = 184 → 184/365
        # In 2023: (2023-07-01 - 2023-01-01).days = 181 → 181/365
        expected = 184 / 365 + 181 / 365
        result = _frac((2022, 7, 1), (2023, 7, 1), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(expected)

    def test_zero_length(self):
        result = _frac((2024, 3, 15), (2024, 3, 15), DayCount.ACT_ACT_ISDA)
        assert result == pytest.approx(0.0)


# ===========================================================================
# add_months
# ===========================================================================

class TestAddMonths:
    """Date arithmetic helpers — add_months."""

    def test_basic(self):
        assert add_months(date(2024, 3, 1), 3) == date(2024, 6, 1)

    def test_year_rollover(self):
        assert add_months(date(2024, 12, 1), 1) == date(2025, 1, 1)

    def test_end_of_month_leap_feb(self):
        # Jan 31 + 1M → Feb 29 in leap year 2024
        assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)

    def test_end_of_month_non_leap_feb(self):
        # Jan 31 + 1M → Feb 28 in non-leap year 2023
        assert add_months(date(2023, 1, 31), 1) == date(2023, 2, 28)

    def test_end_of_month_no_clamp(self):
        # Jan 31 + 2M → Mar 31 (no clamp needed)
        assert add_months(date(2024, 1, 31), 2) == date(2024, 3, 31)

    def test_year_boundary_31(self):
        # Dec 31 + 1M → Jan 31
        assert add_months(date(2024, 12, 31), 1) == date(2025, 1, 31)

    def test_zero_months(self):
        # Identity
        d = date(2024, 6, 15)
        assert add_months(d, 0) == d

    def test_twelve_months(self):
        # + 12 months = + 1 year (for non-EOM dates)
        assert add_months(date(2024, 3, 20), 12) == date(2025, 3, 20)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            add_months(date(2024, 1, 1), -1)


# ===========================================================================
# generate_unadjusted_dates
# ===========================================================================

class TestGenerateUnadjustedDates:
    """Coupon-date schedule generation — unadjusted."""

    def test_1y_annual(self):
        dates = generate_unadjusted_dates(date(2024, 1, 1), 1, "annual")
        assert dates == [date(2025, 1, 1)]

    def test_2y_semiannual(self):
        dates = generate_unadjusted_dates(date(2024, 1, 1), 2, "semiannual")
        assert dates == [
            date(2024, 7, 1),
            date(2025, 1, 1),
            date(2025, 7, 1),
            date(2026, 1, 1),
        ]

    def test_2y_quarterly(self):
        dates = generate_unadjusted_dates(date(2024, 3, 20), 2, "quarterly")
        assert len(dates) == 8
        assert dates[0] == date(2024, 6, 20)
        assert dates[-1] == date(2026, 3, 20)

    def test_maturity_is_last(self):
        dates = generate_unadjusted_dates(date(2024, 6, 15), 3, "annual")
        assert dates[-1] == date(2027, 6, 15)

    def test_case_insensitive_frequency(self):
        dates_lower = generate_unadjusted_dates(date(2024, 1, 1), 1, "quarterly")
        dates_upper = generate_unadjusted_dates(date(2024, 1, 1), 1, "QUARTERLY")
        assert dates_lower == dates_upper

    def test_monthly_1y(self):
        dates = generate_unadjusted_dates(date(2024, 1, 1), 1, "monthly")
        assert len(dates) == 12
        assert dates[0] == date(2024, 2, 1)
        assert dates[-1] == date(2025, 1, 1)

    def test_invalid_frequency(self):
        with pytest.raises(ValueError):
            generate_unadjusted_dates(date(2024, 1, 1), 2, "weekly")

    def test_invalid_tenor(self):
        with pytest.raises(ValueError):
            generate_unadjusted_dates(date(2024, 1, 1), 0, "quarterly")


# ===========================================================================
# n_payments
# ===========================================================================

class TestNPayments:
    def test_5y_quarterly(self):
        assert n_payments(5, "quarterly") == 20

    def test_5y_semiannual(self):
        assert n_payments(5, "semiannual") == 10

    def test_10y_annual(self):
        assert n_payments(10, "annual") == 10

    def test_1y_monthly(self):
        assert n_payments(1, "monthly") == 12

    def test_invalid_frequency(self):
        with pytest.raises(ValueError):
            n_payments(5, "biweekly")


# ===========================================================================
# Canonical integration — 5Y ZAR payer swap (links V1 pricer to V2 engine)
# ===========================================================================

class TestCanonical5YZarSwap:
    """
    The canonical prompt: "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"

    The V1 pricer computes 20 quarterly payment periods.
    The V2 schedule engine must agree on the period count and produce the
    correct maturity date for any given trade date.
    """

    def test_schedule_period_count(self):
        effective = date(2024, 3, 20)
        dates = generate_unadjusted_dates(effective, 5, "quarterly")
        assert len(dates) == 20

    def test_schedule_maturity(self):
        effective = date(2024, 3, 20)
        dates = generate_unadjusted_dates(effective, 5, "quarterly")
        assert dates[-1] == date(2029, 3, 20)

    def test_n_payments_matches_v1_pricer(self):
        # V1 pricer: round(tenor_years / accrual) = round(5 / 0.25) = 20
        assert n_payments(5, "quarterly") == 20

    def test_accrual_fraction_quarterly(self):
        # A calendar-exact quarter: ACT/365F for Jan-01 → Apr-01 (91 days in leap year)
        result = accrual_fraction(date(2024, 1, 1), date(2024, 4, 1), DayCount.ACT_365F)
        assert result == pytest.approx(91 / 365)


# ===========================================================================
# Calendar — WeekendsOnly
# ===========================================================================

from quant_core.conventions.calendar import WeekendsOnly  # noqa: E402


class TestWeekendsOnly:
    """WeekendsOnly calendar: Mon–Fri are business days, Sat/Sun are not."""

    def setup_method(self):
        self.cal = WeekendsOnly()

    def test_monday_is_business_day(self):
        assert self.cal.is_business_day(date(2024, 1, 1))   # Monday

    def test_friday_is_business_day(self):
        assert self.cal.is_business_day(date(2024, 1, 5))   # Friday

    def test_saturday_is_not_business_day(self):
        assert not self.cal.is_business_day(date(2024, 1, 6))  # Saturday

    def test_sunday_is_not_business_day(self):
        assert not self.cal.is_business_day(date(2024, 1, 7))  # Sunday

    def test_is_holiday_mirrors_is_business_day(self):
        sat = date(2024, 1, 6)
        assert self.cal.is_holiday(sat) is True
        assert self.cal.is_holiday(date(2024, 1, 8)) is False  # Monday

    def test_weekdays_in_a_row(self):
        # 2024-04-01 (Mon) through 2024-04-05 (Fri) — all business days
        for day in range(1, 6):
            assert self.cal.is_business_day(date(2024, 4, day))


# ===========================================================================
# BusinessDayConvention — adjust()
# ===========================================================================

from quant_core.conventions.business_day import (  # noqa: E402
    BusinessDayConvention,
    adjust,
)


class TestBusinessDayConventionEnum:
    def test_enum_values(self):
        assert BusinessDayConvention.UNADJUSTED == "UNADJUSTED"
        assert BusinessDayConvention.FOLLOWING == "FOLLOWING"
        assert BusinessDayConvention.MODIFIED_FOLLOWING == "MODIFIED FOLLOWING"
        assert BusinessDayConvention.PRECEDING == "PRECEDING"


class TestAdjustFollowing:
    """FOLLOWING: advance to the next business day."""

    def setup_method(self):
        self.cal = WeekendsOnly()
        self.bdc = BusinessDayConvention.FOLLOWING

    def test_already_business_day_unchanged(self):
        # 2024-01-08 is a Monday
        d = date(2024, 1, 8)
        assert adjust(d, self.bdc, self.cal) == d

    def test_saturday_rolls_to_monday(self):
        # 2024-01-06 Saturday → 2024-01-08 Monday
        assert adjust(date(2024, 1, 6), self.bdc, self.cal) == date(2024, 1, 8)

    def test_sunday_rolls_to_monday(self):
        # 2024-01-07 Sunday → 2024-01-08 Monday
        assert adjust(date(2024, 1, 7), self.bdc, self.cal) == date(2024, 1, 8)

    def test_follows_across_month_boundary(self):
        # 2024-03-31 is a Sunday → 2024-04-01 Monday
        assert adjust(date(2024, 3, 31), self.bdc, self.cal) == date(2024, 4, 1)


class TestAdjustModifiedFollowing:
    """MODIFIED_FOLLOWING: advance unless that crosses the month; then retreat."""

    def setup_method(self):
        self.cal = WeekendsOnly()
        self.bdc = BusinessDayConvention.MODIFIED_FOLLOWING

    def test_already_business_day_unchanged(self):
        assert adjust(date(2024, 4, 1), self.bdc, self.cal) == date(2024, 4, 1)

    def test_saturday_in_mid_month_rolls_forward(self):
        # 2024-04-06 Saturday → 2024-04-08 Monday (same month)
        assert adjust(date(2024, 4, 6), self.bdc, self.cal) == date(2024, 4, 8)

    def test_month_end_saturday_falls_back(self):
        # 2026-10-31 Saturday: FOLLOWING → 2026-11-02 Mon (crosses month)
        # MOD_FOLLOWING → fall back → 2026-10-30 Friday
        assert adjust(date(2026, 10, 31), self.bdc, self.cal) == date(2026, 10, 30)

    def test_month_end_sunday_falls_back(self):
        # 2024-03-31 Sunday: FOLLOWING → 2024-04-01 Mon (crosses month)
        # MOD_FOLLOWING → fall back → 2024-03-29 Friday
        assert adjust(date(2024, 3, 31), self.bdc, self.cal) == date(2024, 3, 29)


class TestAdjustPreceding:
    """PRECEDING: retreat to the previous business day."""

    def setup_method(self):
        self.cal = WeekendsOnly()
        self.bdc = BusinessDayConvention.PRECEDING

    def test_already_business_day_unchanged(self):
        assert adjust(date(2024, 1, 5), self.bdc, self.cal) == date(2024, 1, 5)

    def test_saturday_rolls_to_friday(self):
        # 2024-01-06 Saturday → 2024-01-05 Friday
        assert adjust(date(2024, 1, 6), self.bdc, self.cal) == date(2024, 1, 5)

    def test_sunday_rolls_to_friday(self):
        # 2024-01-07 Sunday → 2024-01-05 Friday
        assert adjust(date(2024, 1, 7), self.bdc, self.cal) == date(2024, 1, 5)

    def test_preceding_across_month_boundary(self):
        # 2024-04-01 Monday is a business day; test month boundary:
        # 2024-03-31 Sunday → 2024-03-29 Friday
        assert adjust(date(2024, 3, 31), self.bdc, self.cal) == date(2024, 3, 29)


class TestAdjustUnadjusted:
    """UNADJUSTED: always return the date unchanged."""

    def setup_method(self):
        self.cal = WeekendsOnly()
        self.bdc = BusinessDayConvention.UNADJUSTED

    def test_weekday_unchanged(self):
        d = date(2024, 1, 8)
        assert adjust(d, self.bdc, self.cal) == d

    def test_saturday_unchanged(self):
        d = date(2024, 1, 6)
        assert adjust(d, self.bdc, self.cal) == d

    def test_sunday_unchanged(self):
        d = date(2024, 1, 7)
        assert adjust(d, self.bdc, self.cal) == d


# ===========================================================================
# EOM schedule
# ===========================================================================

class TestEOMSchedule:
    """
    End-of-month rule: when eom=True and the effective date is month-end,
    every generated date is forced to the last calendar day of its month.
    """

    def test_eom_false_no_effect_on_mid_month(self):
        # effective is not month-end → eom flag has no effect
        dates = generate_unadjusted_dates(date(2024, 1, 15), 1, "monthly", eom=True)
        dates_plain = generate_unadjusted_dates(date(2024, 1, 15), 1, "monthly")
        assert dates == dates_plain

    def test_eom_monthly_from_jan31_leap(self):
        # Jan 31, 2024 (leap year) → 12 monthly EOM dates
        dates = generate_unadjusted_dates(date(2024, 1, 31), 1, "monthly", eom=True)
        assert len(dates) == 12
        # Feb should be Feb 29 (2024 is leap)
        assert dates[0] == date(2024, 2, 29)
        # Mar: month-end of March = 31
        assert dates[1] == date(2024, 3, 31)
        # Apr: month-end of April = 30
        assert dates[2] == date(2024, 4, 30)
        # Last element is maturity = Jan 31, 2025 (month-end)
        assert dates[-1] == date(2025, 1, 31)

    def test_eom_monthly_from_jan31_non_leap(self):
        # Jan 31, 2023 (non-leap year)
        dates = generate_unadjusted_dates(date(2023, 1, 31), 1, "monthly", eom=True)
        # Feb should be Feb 28
        assert dates[0] == date(2023, 2, 28)
        assert dates[-1] == date(2024, 1, 31)

    def test_eom_quarterly_from_nov30(self):
        # Nov 30 is month-end; quarterly eom=True
        # Nov 30 + 3M raw = Feb 28/29 (clamp), EOM squeeze further not needed (already EOM)
        # Nov 30 + 6M raw = May 30 (clamp from 30), EOM upgrades to May 31
        dates = generate_unadjusted_dates(date(2024, 11, 30), 1, "quarterly", eom=True)
        # Q1: Feb 28 (2025 is not leap — 2025 Feb has 28 days)
        assert dates[0] == date(2025, 2, 28)
        # Q2: May 31
        assert dates[1] == date(2025, 5, 31)
        # Q3: Aug 31
        assert dates[2] == date(2025, 8, 31)
        # Q4 = maturity: Nov 30
        assert dates[3] == date(2025, 11, 30)

    def test_eom_default_false(self):
        # Confirm default is backward-compatible (eom=False)
        d1 = generate_unadjusted_dates(date(2024, 1, 31), 1, "quarterly")
        d2 = generate_unadjusted_dates(date(2024, 1, 31), 1, "quarterly", eom=False)
        assert d1 == d2

    def test_eom_not_applied_when_not_month_end(self):
        # Jan 30 is NOT month-end → eom=True has no effect
        with_eom = generate_unadjusted_dates(date(2024, 1, 30), 1, "monthly", eom=True)
        without_eom = generate_unadjusted_dates(date(2024, 1, 30), 1, "monthly")
        assert with_eom == without_eom


# ===========================================================================
# generate_schedule — adjusted schedules
# ===========================================================================

from quant_core.conventions.schedule import generate_schedule  # noqa: E402


class TestGenerateSchedule:
    """generate_schedule: unadjusted pass-through and BDC-adjusted output."""

    def setup_method(self):
        self.cal = WeekendsOnly()

    def test_no_calendar_returns_unadjusted(self):
        dates = generate_schedule(date(2024, 1, 1), 1, "annual")
        assert dates == generate_unadjusted_dates(date(2024, 1, 1), 1, "annual")

    def test_calendar_without_bdc_returns_unadjusted(self):
        # calendar provided but bdc=None → no adjustment
        dates = generate_schedule(
            date(2024, 1, 1), 1, "annual", calendar=self.cal, bdc=None
        )
        assert dates == generate_unadjusted_dates(date(2024, 1, 1), 1, "annual")

    def test_bdc_without_calendar_returns_unadjusted(self):
        # bdc provided but calendar=None → no adjustment
        dates = generate_schedule(
            date(2024, 1, 1), 1, "annual",
            calendar=None, bdc=BusinessDayConvention.FOLLOWING
        )
        assert dates == generate_unadjusted_dates(date(2024, 1, 1), 1, "annual")

    def test_following_adjusts_weekend_dates(self):
        # quarterly from 2024-01-01 over 1 year
        # 2024-04-01 Mon ✓, 2024-07-01 Mon ✓, 2024-10-01 Tue ✓, 2025-01-01 Wed ✓
        unadj = generate_unadjusted_dates(date(2024, 1, 1), 1, "quarterly")
        adj = generate_schedule(
            date(2024, 1, 1), 1, "quarterly",
            calendar=self.cal, bdc=BusinessDayConvention.FOLLOWING
        )
        # All adjusted dates must be business days
        for d in adj:
            assert self.cal.is_business_day(d), f"{d} is not a business day"
        # Each adjusted date >= its unadjusted counterpart (FOLLOWING never goes back)
        for u, a in zip(unadj, adj):
            assert a >= u

    def test_modified_following_stays_in_same_month(self):
        # Build a schedule where a date falls on Sat month-end so MOD_FOLLOWING kicks in.
        # 2026-10-31 is Saturday; FOLLOWING → Nov 2, but MOD_FOLLOWING → Oct 30.
        # We need a 1y quarterly schedule that contains Oct 31.
        # effective = 2026-01-31 quarterly → Apr 30, Jul 31, Oct 31, Jan 31 2027
        # Oct 31 2026 is Saturday.
        adj = generate_schedule(
            date(2026, 1, 31), 1, "quarterly",
            calendar=self.cal, bdc=BusinessDayConvention.MODIFIED_FOLLOWING
        )
        # Oct 31 unadjusted is at index 2; MOD_FOLLOWING should give Oct 30 (Friday)
        assert date(2026, 10, 31) not in adj
        assert date(2026, 10, 30) in adj
        # The Nov boundary must not have been crossed
        for d in adj:
            assert self.cal.is_business_day(d)

    def test_eom_with_following_adjustment(self):
        # EOM schedule from Jan 31 quarterly; all dates month-end, then FOLLOWING applied.
        # Month-end dates: Apr 30 (Tue 2024), Jul 31 (Wed 2024), Oct 31 (Thu 2024),
        # Jan 31 (Fri 2025) — all already weekdays, so FOLLOWING leaves them unchanged.
        adj = generate_schedule(
            date(2024, 1, 31), 1, "quarterly",
            calendar=self.cal, bdc=BusinessDayConvention.FOLLOWING, eom=True
        )
        for d in adj:
            assert self.cal.is_business_day(d)
