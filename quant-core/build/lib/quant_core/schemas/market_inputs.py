"""
market_inputs — Typed schemas for market-observable inputs to quant-core.

This module defines lightweight dataclasses for market data that is fed
into the quantitative library (curve construction, pricing, etc.).  These
are *internal* domain types — they are not coupled to the HTTP/API layer.

All rates are expressed as decimals (e.g. 0.08 for 8 %).

Defined types
-------------
:class:`DepositQuote`
    A single ON/TN/cash-deposit or money-market quote (start = today,
    maturity = tenor_months from today).

:class:`FRAQuote`
    A Forward Rate Agreement quote specified by its start and end month
    offsets from the valuation date.

:class:`ParSwapQuote`
    A single (tenor, par rate) observation from the swap market.  Used as
    input to :func:`~quant_core.curves.bootstrap_swap.bootstrap_discount_curve_from_swaps`.

:class:`NormalizedRateRecord`
    Canonical, instrument-type-agnostic representation of any of the above
    quote types after normalization.  Used as the unit for mixed-instrument
    curve input processing.
"""
from __future__ import annotations

from dataclasses import dataclass

_VALID_INSTRUMENT_TYPES: frozenset[str] = frozenset({"deposit", "fra", "swap"})


# ---------------------------------------------------------------------------
# Raw quote types
# ---------------------------------------------------------------------------


@dataclass
class DepositQuote:
    """
    A single cash-deposit / money-market quote.

    The deposit is assumed to start on the valuation date and mature at
    ``tenor_months`` calendar months from the valuation date.

    Parameters
    ----------
    tenor_months : int
        Deposit tenor in whole months.  Must be >= 1.
    rate : float
        Deposit rate expressed as a decimal, e.g. 0.078 for 7.8 %.
        Must be > 0 and < 1.

    Raises
    ------
    ValueError
        On any invalid field value.
    """

    tenor_months: int
    rate: float

    def __post_init__(self) -> None:
        if self.tenor_months < 1:
            raise ValueError(
                f"tenor_months must be >= 1; got {self.tenor_months}"
            )
        if not (0.0 < self.rate < 1.0):
            raise ValueError(
                f"rate must be > 0 and < 1; got {self.rate}"
            )


@dataclass
class FRAQuote:
    """
    A Forward Rate Agreement (FRA) quote.

    Conventionally quoted as ``start_months × end_months``, e.g. a 6×9
    FRA has ``start_months=6`` and ``end_months=9``.

    Parameters
    ----------
    start_months : int
        Settlement offset from the valuation date in whole months.
        Must be >= 0.
    end_months : int
        Maturity offset from the valuation date in whole months.
        Must be strictly greater than ``start_months``.
    rate : float
        FRA rate expressed as a decimal, e.g. 0.081 for 8.1 %.
        Must be > 0 and < 1.

    Raises
    ------
    ValueError
        On any invalid field value.
    """

    start_months: int
    end_months: int
    rate: float

    def __post_init__(self) -> None:
        if self.start_months < 0:
            raise ValueError(
                f"start_months must be >= 0; got {self.start_months}"
            )
        if self.end_months <= self.start_months:
            raise ValueError(
                f"end_months ({self.end_months}) must be > start_months "
                f"({self.start_months})"
            )
        if not (0.0 < self.rate < 1.0):
            raise ValueError(
                f"rate must be > 0 and < 1; got {self.rate}"
            )


@dataclass
class ParSwapQuote:
    """
    A single par-swap market quote.

    A par swap is a vanilla fixed-for-floating interest rate swap priced such
    that its net present value is zero at inception.  The ``par_rate`` is the
    fixed coupon rate that achieves this.

    Parameters
    ----------
    tenor_years : int
        Swap tenor in whole years.  Must be >= 1.
    par_rate : float
        Par (market) fixed rate expressed as a decimal, e.g. 0.08 for 8%.
        Must be > 0 and < 1.

    Raises
    ------
    ValueError
        On any invalid field value (see ``__post_init__``).

    Examples
    --------
    >>> from quant_core.schemas.market_inputs import ParSwapQuote
    >>> q = ParSwapQuote(tenor_years=5, par_rate=0.085)
    >>> q.tenor_years
    5
    >>> q.par_rate
    0.085
    """

    tenor_years: int
    par_rate: float

    def __post_init__(self) -> None:
        if self.tenor_years < 1:
            raise ValueError(
                f"tenor_years must be >= 1; got {self.tenor_years}"
            )
        if not (0.0 < self.par_rate < 1.0):
            raise ValueError(
                f"par_rate must be > 0 and < 1; got {self.par_rate}"
            )


# ---------------------------------------------------------------------------
# Normalized (canonical) representation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedRateRecord:
    """
    Instrument-type-agnostic representation of a single market rate quote.

    All tenors are expressed in whole months from the valuation date so that
    deposits, FRAs, and swap quotes can appear in the same sorted sequence.

    Parameters
    ----------
    instrument_type : str
        One of ``"deposit"``, ``"fra"``, or ``"swap"``.
    start_months : int
        Start offset from the valuation date in whole months.  Zero for
        deposits and swaps; positive for FRAs.
    end_months : int
        End (maturity) offset from the valuation date in whole months.
        Must be strictly greater than ``start_months``.
    quote_rate : float
        Rate as a decimal.  Must be > 0 and < 1.

    Raises
    ------
    ValueError
        On any invalid field value.
    """

    instrument_type: str
    start_months: int
    end_months: int
    quote_rate: float

    def __post_init__(self) -> None:
        if self.instrument_type not in _VALID_INSTRUMENT_TYPES:
            raise ValueError(
                f"instrument_type must be one of {sorted(_VALID_INSTRUMENT_TYPES)}; "
                f"got '{self.instrument_type}'"
            )
        if self.end_months <= self.start_months:
            raise ValueError(
                f"end_months ({self.end_months}) must be > start_months "
                f"({self.start_months})"
            )
        if not (0.0 < self.quote_rate < 1.0):
            raise ValueError(
                f"quote_rate must be > 0 and < 1; got {self.quote_rate}"
            )
