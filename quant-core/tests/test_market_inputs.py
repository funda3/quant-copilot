"""
Tests for Step 7 — market-input schemas and normalization layer.

Canon ladder used throughout:
  Deposits : 1M @ 7.8 %, 3M @ 7.9 %, 6M @ 8.0 %
  FRAs     : 6x9 @ 8.1 %, 9x12 @ 8.15 %
  Swaps    : 2Y @ 8.2 %, 3Y @ 8.3 %, 5Y @ 8.5 %
"""
from __future__ import annotations

import pytest

from quant_core.schemas.market_inputs import (
    DepositQuote,
    FRAQuote,
    NormalizedRateRecord,
    ParSwapQuote,
)
from quant_core.marketdata.normalize_rates import (
    describe_market_span,
    normalize_deposit_quote,
    normalize_fra_quote,
    normalize_market_quotes,
    normalize_swap_quote,
)


# ===========================================================================
# DepositQuote — construction & validation
# ===========================================================================


class TestDepositQuote:
    def test_canonical_1m(self):
        q = DepositQuote(tenor_months=1, rate=0.078)
        assert q.tenor_months == 1
        assert q.rate == pytest.approx(0.078)

    def test_canonical_3m(self):
        q = DepositQuote(tenor_months=3, rate=0.079)
        assert q.tenor_months == 3
        assert q.rate == pytest.approx(0.079)

    def test_canonical_6m(self):
        q = DepositQuote(tenor_months=6, rate=0.080)
        assert q.tenor_months == 6
        assert q.rate == pytest.approx(0.080)

    # --- invalid tenor_months ---

    def test_zero_tenor_raises(self):
        with pytest.raises(ValueError, match="tenor_months"):
            DepositQuote(tenor_months=0, rate=0.05)

    def test_negative_tenor_raises(self):
        with pytest.raises(ValueError, match="tenor_months"):
            DepositQuote(tenor_months=-1, rate=0.05)

    # --- invalid rate ---

    def test_zero_rate_raises(self):
        with pytest.raises(ValueError, match="rate"):
            DepositQuote(tenor_months=3, rate=0.0)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError, match="rate"):
            DepositQuote(tenor_months=3, rate=-0.01)

    def test_rate_one_raises(self):
        with pytest.raises(ValueError, match="rate"):
            DepositQuote(tenor_months=3, rate=1.0)

    def test_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="rate"):
            DepositQuote(tenor_months=3, rate=1.5)

    def test_small_positive_rate_accepted(self):
        q = DepositQuote(tenor_months=1, rate=1e-6)
        assert q.rate == pytest.approx(1e-6)

    def test_rate_just_below_one_accepted(self):
        q = DepositQuote(tenor_months=12, rate=0.9999)
        assert q.rate == pytest.approx(0.9999)

    def test_large_tenor_accepted(self):
        q = DepositQuote(tenor_months=120, rate=0.05)
        assert q.tenor_months == 120


# ===========================================================================
# FRAQuote — construction & validation
# ===========================================================================


class TestFRAQuote:
    def test_canonical_6x9(self):
        q = FRAQuote(start_months=6, end_months=9, rate=0.081)
        assert q.start_months == 6
        assert q.end_months == 9
        assert q.rate == pytest.approx(0.081)

    def test_canonical_9x12(self):
        q = FRAQuote(start_months=9, end_months=12, rate=0.0815)
        assert q.start_months == 9
        assert q.end_months == 12
        assert q.rate == pytest.approx(0.0815)

    def test_zero_start_months_accepted(self):
        q = FRAQuote(start_months=0, end_months=3, rate=0.05)
        assert q.start_months == 0

    # --- invalid start_months ---

    def test_negative_start_months_raises(self):
        with pytest.raises(ValueError, match="start_months"):
            FRAQuote(start_months=-1, end_months=3, rate=0.05)

    # --- invalid end_months ---

    def test_end_equals_start_raises(self):
        with pytest.raises(ValueError, match="end_months"):
            FRAQuote(start_months=6, end_months=6, rate=0.05)

    def test_end_less_than_start_raises(self):
        with pytest.raises(ValueError, match="end_months"):
            FRAQuote(start_months=9, end_months=6, rate=0.05)

    # --- invalid rate ---

    def test_zero_rate_raises(self):
        with pytest.raises(ValueError, match="rate"):
            FRAQuote(start_months=6, end_months=9, rate=0.0)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError, match="rate"):
            FRAQuote(start_months=6, end_months=9, rate=-0.05)

    def test_rate_one_raises(self):
        with pytest.raises(ValueError, match="rate"):
            FRAQuote(start_months=6, end_months=9, rate=1.0)

    def test_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="rate"):
            FRAQuote(start_months=6, end_months=9, rate=2.0)

    def test_wide_fra_accepted(self):
        """FRA spanning several years should be accepted."""
        q = FRAQuote(start_months=12, end_months=24, rate=0.09)
        assert q.end_months - q.start_months == 12


# ===========================================================================
# ParSwapQuote — construction & validation (regression / unchanged behaviour)
# ===========================================================================


class TestParSwapQuote:
    def test_canonical_2y(self):
        q = ParSwapQuote(tenor_years=2, par_rate=0.082)
        assert q.tenor_years == 2
        assert q.par_rate == pytest.approx(0.082)

    def test_canonical_3y(self):
        q = ParSwapQuote(tenor_years=3, par_rate=0.083)
        assert q.tenor_years == 3

    def test_canonical_5y(self):
        q = ParSwapQuote(tenor_years=5, par_rate=0.085)
        assert q.tenor_years == 5

    def test_tenor_zero_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            ParSwapQuote(tenor_years=0, par_rate=0.05)

    def test_negative_tenor_raises(self):
        with pytest.raises(ValueError, match="tenor_years"):
            ParSwapQuote(tenor_years=-1, par_rate=0.05)

    def test_zero_rate_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(tenor_years=5, par_rate=0.0)

    def test_rate_one_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(tenor_years=5, par_rate=1.0)

    def test_rate_above_one_raises(self):
        with pytest.raises(ValueError, match="par_rate"):
            ParSwapQuote(tenor_years=5, par_rate=1.01)


# ===========================================================================
# NormalizedRateRecord — construction & validation
# ===========================================================================


class TestNormalizedRateRecord:
    def test_deposit_record(self):
        r = NormalizedRateRecord(
            instrument_type="deposit",
            start_months=0,
            end_months=3,
            quote_rate=0.079,
        )
        assert r.instrument_type == "deposit"
        assert r.start_months == 0
        assert r.end_months == 3
        assert r.quote_rate == pytest.approx(0.079)

    def test_fra_record(self):
        r = NormalizedRateRecord(
            instrument_type="fra",
            start_months=6,
            end_months=9,
            quote_rate=0.081,
        )
        assert r.instrument_type == "fra"

    def test_swap_record(self):
        r = NormalizedRateRecord(
            instrument_type="swap",
            start_months=0,
            end_months=24,
            quote_rate=0.082,
        )
        assert r.instrument_type == "swap"

    def test_frozen_immutability(self):
        r = NormalizedRateRecord(
            instrument_type="deposit",
            start_months=0,
            end_months=6,
            quote_rate=0.08,
        )
        with pytest.raises((AttributeError, TypeError)):
            r.quote_rate = 0.09  # type: ignore[misc]

    def test_invalid_instrument_type_raises(self):
        with pytest.raises(ValueError, match="instrument_type"):
            NormalizedRateRecord(
                instrument_type="future",
                start_months=0,
                end_months=3,
                quote_rate=0.05,
            )

    def test_end_equals_start_raises(self):
        with pytest.raises(ValueError, match="end_months"):
            NormalizedRateRecord(
                instrument_type="deposit",
                start_months=3,
                end_months=3,
                quote_rate=0.05,
            )

    def test_end_less_than_start_raises(self):
        with pytest.raises(ValueError, match="end_months"):
            NormalizedRateRecord(
                instrument_type="fra",
                start_months=9,
                end_months=6,
                quote_rate=0.05,
            )

    def test_zero_quote_rate_raises(self):
        with pytest.raises(ValueError, match="quote_rate"):
            NormalizedRateRecord(
                instrument_type="swap",
                start_months=0,
                end_months=24,
                quote_rate=0.0,
            )

    def test_rate_one_raises(self):
        with pytest.raises(ValueError, match="quote_rate"):
            NormalizedRateRecord(
                instrument_type="deposit",
                start_months=0,
                end_months=6,
                quote_rate=1.0,
            )

    def test_records_are_hashable(self):
        """frozen=True dataclasses must be hashable."""
        r1 = NormalizedRateRecord("deposit", 0, 3, 0.079)
        r2 = NormalizedRateRecord("deposit", 0, 3, 0.079)
        assert r1 == r2
        assert hash(r1) == hash(r2)
        s = {r1, r2}
        assert len(s) == 1


# ===========================================================================
# normalize_deposit_quote
# ===========================================================================


class TestNormalizeDepositQuote:
    def test_1m(self):
        rec = normalize_deposit_quote(DepositQuote(tenor_months=1, rate=0.078))
        assert rec.instrument_type == "deposit"
        assert rec.start_months == 0
        assert rec.end_months == 1
        assert rec.quote_rate == pytest.approx(0.078)

    def test_3m(self):
        rec = normalize_deposit_quote(DepositQuote(tenor_months=3, rate=0.079))
        assert rec.end_months == 3

    def test_6m(self):
        rec = normalize_deposit_quote(DepositQuote(tenor_months=6, rate=0.080))
        assert rec.end_months == 6
        assert rec.start_months == 0

    def test_returns_normalized_rate_record(self):
        rec = normalize_deposit_quote(DepositQuote(tenor_months=3, rate=0.05))
        assert isinstance(rec, NormalizedRateRecord)


# ===========================================================================
# normalize_fra_quote
# ===========================================================================


class TestNormalizeFRAQuote:
    def test_6x9(self):
        rec = normalize_fra_quote(FRAQuote(start_months=6, end_months=9, rate=0.081))
        assert rec.instrument_type == "fra"
        assert rec.start_months == 6
        assert rec.end_months == 9
        assert rec.quote_rate == pytest.approx(0.081)

    def test_9x12(self):
        rec = normalize_fra_quote(FRAQuote(start_months=9, end_months=12, rate=0.0815))
        assert rec.start_months == 9
        assert rec.end_months == 12

    def test_returns_normalized_rate_record(self):
        rec = normalize_fra_quote(FRAQuote(start_months=3, end_months=6, rate=0.05))
        assert isinstance(rec, NormalizedRateRecord)


# ===========================================================================
# normalize_swap_quote
# ===========================================================================


class TestNormalizeSwapQuote:
    def test_2y(self):
        rec = normalize_swap_quote(ParSwapQuote(tenor_years=2, par_rate=0.082))
        assert rec.instrument_type == "swap"
        assert rec.start_months == 0
        assert rec.end_months == 24
        assert rec.quote_rate == pytest.approx(0.082)

    def test_3y(self):
        rec = normalize_swap_quote(ParSwapQuote(tenor_years=3, par_rate=0.083))
        assert rec.end_months == 36

    def test_5y(self):
        rec = normalize_swap_quote(ParSwapQuote(tenor_years=5, par_rate=0.085))
        assert rec.end_months == 60
        assert rec.start_months == 0

    def test_10y(self):
        rec = normalize_swap_quote(ParSwapQuote(tenor_years=10, par_rate=0.09))
        assert rec.end_months == 120

    def test_returns_normalized_rate_record(self):
        rec = normalize_swap_quote(ParSwapQuote(tenor_years=1, par_rate=0.05))
        assert isinstance(rec, NormalizedRateRecord)


# ===========================================================================
# normalize_market_quotes — full canonical ladder
# ===========================================================================


def _canon_deposits() -> list[DepositQuote]:
    return [
        DepositQuote(tenor_months=1, rate=0.078),
        DepositQuote(tenor_months=3, rate=0.079),
        DepositQuote(tenor_months=6, rate=0.080),
    ]


def _canon_fras() -> list[FRAQuote]:
    return [
        FRAQuote(start_months=6, end_months=9, rate=0.081),
        FRAQuote(start_months=9, end_months=12, rate=0.0815),
    ]


def _canon_swaps() -> list[ParSwapQuote]:
    return [
        ParSwapQuote(tenor_years=2, par_rate=0.082),
        ParSwapQuote(tenor_years=3, par_rate=0.083),
        ParSwapQuote(tenor_years=5, par_rate=0.085),
    ]


class TestNormalizeMarketQuotes:
    def test_returns_list(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        assert isinstance(result, list)

    def test_total_count(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        # 3 deposits + 2 FRAs + 3 swaps = 8 records
        assert len(result) == 8

    def test_all_items_are_normalized_rate_records(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        assert all(isinstance(r, NormalizedRateRecord) for r in result)

    def test_sorted_by_start_then_end(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        keys = [(r.start_months, r.end_months) for r in result]
        assert keys == sorted(keys)

    def test_first_record_is_1m_deposit(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        first = result[0]
        assert first.instrument_type == "deposit"
        assert first.end_months == 1

    def test_last_record_is_9x12_fra(self):
        """
        The sort key is (start_months, end_months, type_priority).
        FRAs have non-zero start_months (6 and 9) so they sort *after* all
        deposits and swaps (which have start_months=0).  For the canon
        ladder the last record is therefore the 9×12 FRA.
        """
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        last = result[-1]
        assert last.instrument_type == "fra"
        assert last.start_months == 9
        assert last.end_months == 12

    def test_fras_appear_after_short_end_deposits(self):
        """FRAs start at month 6, so they appear after the 1M and 3M deposits."""
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        fra_indices = [i for i, r in enumerate(result) if r.instrument_type == "fra"]
        deposit_indices = [i for i, r in enumerate(result) if r.instrument_type == "deposit"]
        # The earliest FRA index should be after the 1M and 3M deposit indices
        assert min(fra_indices) > min(deposit_indices)

    def test_deposits_only(self):
        result = normalize_market_quotes(deposits=_canon_deposits())
        assert len(result) == 3
        assert all(r.instrument_type == "deposit" for r in result)

    def test_fras_only(self):
        result = normalize_market_quotes(fras=_canon_fras())
        assert len(result) == 2
        assert all(r.instrument_type == "fra" for r in result)

    def test_swaps_only(self):
        result = normalize_market_quotes(swaps=_canon_swaps())
        assert len(result) == 3
        assert all(r.instrument_type == "swap" for r in result)

    def test_empty_call_returns_empty(self):
        result = normalize_market_quotes()
        assert result == []

    def test_none_args_treated_as_empty(self):
        result = normalize_market_quotes(deposits=None, fras=None, swaps=None)
        assert result == []

    def test_input_order_independent(self):
        """Reversed input order should produce the same sorted output."""
        fwd = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        rev = normalize_market_quotes(
            deposits=list(reversed(_canon_deposits())),
            fras=list(reversed(_canon_fras())),
            swaps=list(reversed(_canon_swaps())),
        )
        assert fwd == rev

    # --- sort tie-breaking: deposit before FRA before swap at same (start, end) ---

    def test_type_sort_priority_deposit_before_swap(self):
        """
        When a deposit and a swap share the same (start=0, end=12),
        the deposit record must sort first.
        """
        deps = [DepositQuote(tenor_months=12, rate=0.08)]
        swps = [ParSwapQuote(tenor_years=1, par_rate=0.082)]
        result = normalize_market_quotes(deposits=deps, swaps=swps)
        assert result[0].instrument_type == "deposit"
        assert result[1].instrument_type == "swap"

    # --- duplicate rejection ---

    def test_duplicate_deposit_tenor_raises(self):
        dupes = [
            DepositQuote(tenor_months=3, rate=0.079),
            DepositQuote(tenor_months=3, rate=0.080),  # same tenor → duplicate
        ]
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            normalize_market_quotes(deposits=dupes)

    def test_duplicate_fra_raises(self):
        dupes = [
            FRAQuote(start_months=6, end_months=9, rate=0.081),
            FRAQuote(start_months=6, end_months=9, rate=0.082),
        ]
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            normalize_market_quotes(fras=dupes)

    def test_duplicate_swap_tenor_raises(self):
        dupes = [
            ParSwapQuote(tenor_years=5, par_rate=0.085),
            ParSwapQuote(tenor_years=5, par_rate=0.086),
        ]
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            normalize_market_quotes(swaps=dupes)

    def test_same_end_months_different_types_not_duplicate(self):
        """
        A 12M deposit and a 1Y swap both end at month 12 but are different
        instrument types.  Each has key (deposit, 0, 12) vs (swap, 0, 12),
        so they must NOT be treated as duplicates.
        """
        deps = [DepositQuote(tenor_months=12, rate=0.08)]
        swps = [ParSwapQuote(tenor_years=1, par_rate=0.082)]
        result = normalize_market_quotes(deposits=deps, swaps=swps)
        assert len(result) == 2

    def test_rates_preserved_correctly(self):
        result = normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )
        rate_map = {(r.instrument_type, r.end_months): r.quote_rate for r in result}
        assert rate_map[("deposit", 1)] == pytest.approx(0.078)
        assert rate_map[("deposit", 3)] == pytest.approx(0.079)
        assert rate_map[("deposit", 6)] == pytest.approx(0.080)
        assert rate_map[("fra", 9)] == pytest.approx(0.081)
        assert rate_map[("fra", 12)] == pytest.approx(0.0815)
        assert rate_map[("swap", 24)] == pytest.approx(0.082)
        assert rate_map[("swap", 36)] == pytest.approx(0.083)
        assert rate_map[("swap", 60)] == pytest.approx(0.085)


# ===========================================================================
# describe_market_span
# ===========================================================================


class TestDescribeMarketSpan:
    def _full_records(self) -> list[NormalizedRateRecord]:
        return normalize_market_quotes(
            deposits=_canon_deposits(),
            fras=_canon_fras(),
            swaps=_canon_swaps(),
        )

    def test_span_of_canon_ladder(self):
        records = self._full_records()
        min_start, max_end = describe_market_span(records)
        assert min_start == 0
        assert max_end == 60  # 5Y swap

    def test_deposits_only_span(self):
        records = normalize_market_quotes(deposits=_canon_deposits())
        min_start, max_end = describe_market_span(records)
        assert min_start == 0
        assert max_end == 6  # 6M deposit

    def test_fras_only_span(self):
        records = normalize_market_quotes(fras=_canon_fras())
        min_start, max_end = describe_market_span(records)
        assert min_start == 6
        assert max_end == 12

    def test_single_record_span(self):
        rec = NormalizedRateRecord("swap", 0, 36, 0.083)
        min_start, max_end = describe_market_span([rec])
        assert min_start == 0
        assert max_end == 36

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            describe_market_span([])

    def test_returns_tuple_of_two_ints(self):
        records = self._full_records()
        result = describe_market_span(records)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(v, int) for v in result)

    def test_span_with_only_swaps(self):
        records = normalize_market_quotes(swaps=_canon_swaps())
        min_start, max_end = describe_market_span(records)
        assert min_start == 0
        assert max_end == 60

    def test_span_fras_start_is_non_zero(self):
        """If only FRAs are provided, min_start should reflect their non-zero start."""
        fras = [FRAQuote(start_months=3, end_months=6, rate=0.05)]
        records = normalize_market_quotes(fras=fras)
        min_start, max_end = describe_market_span(records)
        assert min_start == 3
        assert max_end == 6
