"""
normalize_rates — Normalization layer for mixed market-rate input data.

Converts heterogeneous market quotes (deposits, FRAs, par swaps) into a
uniform :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`
sequence suitable for mixed-instrument discount-curve construction.

Public API
----------
:func:`normalize_deposit_quote`
    Map a :class:`~quant_core.schemas.market_inputs.DepositQuote` to a
    :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`.

:func:`normalize_fra_quote`
    Map a :class:`~quant_core.schemas.market_inputs.FRAQuote` to a
    :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`.

:func:`normalize_swap_quote`
    Map a :class:`~quant_core.schemas.market_inputs.ParSwapQuote` to a
    :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`.

:func:`normalize_market_quotes`
    Accept arbitrary collections of all three quote types, normalize each
    one, enforce uniqueness, and return a sorted list.

:func:`describe_market_span`
    Return the ``(min_start_months, max_end_months)`` span covered by a
    sequence of :class:`~quant_core.schemas.market_inputs.NormalizedRateRecord`
    items.
"""
from __future__ import annotations

from typing import Sequence

from quant_core.schemas.market_inputs import (
    DepositQuote,
    FRAQuote,
    NormalizedRateRecord,
    ParSwapQuote,
)

# Sort-priority weight for instrument types so that when two records share
# the same (start_months, end_months) key, deposits sort before FRAs, which
# sort before swaps.  This is arbitrary but deterministic.
_TYPE_PRIORITY: dict[str, int] = {"deposit": 0, "fra": 1, "swap": 2}


# ---------------------------------------------------------------------------
# Per-type normalizers
# ---------------------------------------------------------------------------


def normalize_deposit_quote(quote: DepositQuote) -> NormalizedRateRecord:
    """
    Convert a :class:`DepositQuote` to a :class:`NormalizedRateRecord`.

    Deposits start at month 0 (valuation date) and mature at
    ``quote.tenor_months``.

    Parameters
    ----------
    quote : DepositQuote
        A single validated deposit quote.

    Returns
    -------
    NormalizedRateRecord
        ``instrument_type="deposit"``, ``start_months=0``,
        ``end_months=quote.tenor_months``, ``quote_rate=quote.rate``.
    """
    return NormalizedRateRecord(
        instrument_type="deposit",
        start_months=0,
        end_months=quote.tenor_months,
        quote_rate=quote.rate,
    )


def normalize_fra_quote(quote: FRAQuote) -> NormalizedRateRecord:
    """
    Convert a :class:`FRAQuote` to a :class:`NormalizedRateRecord`.

    Parameters
    ----------
    quote : FRAQuote
        A single validated FRA quote.

    Returns
    -------
    NormalizedRateRecord
        ``instrument_type="fra"``,
        ``start_months=quote.start_months``,
        ``end_months=quote.end_months``,
        ``quote_rate=quote.rate``.
    """
    return NormalizedRateRecord(
        instrument_type="fra",
        start_months=quote.start_months,
        end_months=quote.end_months,
        quote_rate=quote.rate,
    )


def normalize_swap_quote(quote: ParSwapQuote) -> NormalizedRateRecord:
    """
    Convert a :class:`ParSwapQuote` to a :class:`NormalizedRateRecord`.

    Par swaps start at month 0 and mature at ``tenor_years * 12`` months.

    Parameters
    ----------
    quote : ParSwapQuote
        A single validated par-swap quote.

    Returns
    -------
    NormalizedRateRecord
        ``instrument_type="swap"``, ``start_months=0``,
        ``end_months=quote.tenor_years * 12``, ``quote_rate=quote.par_rate``.
    """
    return NormalizedRateRecord(
        instrument_type="swap",
        start_months=0,
        end_months=quote.tenor_years * 12,
        quote_rate=quote.par_rate,
    )


# ---------------------------------------------------------------------------
# Mixed-input normalizer
# ---------------------------------------------------------------------------


def normalize_market_quotes(
    deposits: Sequence[DepositQuote] | None = None,
    fras: Sequence[FRAQuote] | None = None,
    swaps: Sequence[ParSwapQuote] | None = None,
) -> list[NormalizedRateRecord]:
    """
    Normalize and combine all market quotes into a deduplicated sorted list.

    All three input sequences are optional; omitted sequences are treated as
    empty.  The resulting list is sorted by ``(start_months, end_months,
    instrument_type_priority)`` so that the order is deterministic and
    suitable for sequential curve construction.

    Duplicate detection
    ~~~~~~~~~~~~~~~~~~~
    A duplicate is defined as two records with the same
    ``(instrument_type, start_months, end_months)`` triple.  Duplicates
    raise :exc:`ValueError` so that callers are forced to supply clean, non-
    overlapping market data.

    Parameters
    ----------
    deposits : sequence of DepositQuote, optional
    fras : sequence of FRAQuote, optional
    swaps : sequence of ParSwapQuote, optional

    Returns
    -------
    list[NormalizedRateRecord]
        Sorted, deduplicated list of normalized records.

    Raises
    ------
    ValueError
        If any two input quotes produce records with the same
        ``(instrument_type, start_months, end_months)`` key.
    """
    records: list[NormalizedRateRecord] = []

    for q in deposits or []:
        records.append(normalize_deposit_quote(q))
    for q in fras or []:
        records.append(normalize_fra_quote(q))
    for q in swaps or []:
        records.append(normalize_swap_quote(q))

    # Duplicate check — O(n) using a set of unique keys.
    seen: set[tuple[str, int, int]] = set()
    for rec in records:
        key = (rec.instrument_type, rec.start_months, rec.end_months)
        if key in seen:
            raise ValueError(
                f"Duplicate market quote detected: instrument_type="
                f"'{rec.instrument_type}', start_months={rec.start_months}, "
                f"end_months={rec.end_months}"
            )
        seen.add(key)

    # Stable sort: primary = start_months, secondary = end_months,
    # tertiary = instrument_type_priority (deposits first, then FRAs, then swaps).
    records.sort(
        key=lambda r: (
            r.start_months,
            r.end_months,
            _TYPE_PRIORITY.get(r.instrument_type, 99),
        )
    )

    return records


# ---------------------------------------------------------------------------
# Span helper
# ---------------------------------------------------------------------------


def describe_market_span(
    records: Sequence[NormalizedRateRecord],
) -> tuple[int, int]:
    """
    Return the time span covered by a collection of normalized rate records.

    Parameters
    ----------
    records : sequence of NormalizedRateRecord
        A non-empty sequence of normalized rate records.

    Returns
    -------
    tuple[int, int]
        ``(min_start_months, max_end_months)`` across all records.

    Raises
    ------
    ValueError
        If ``records`` is empty.
    """
    if not records:
        raise ValueError("records must be non-empty")

    min_start = min(r.start_months for r in records)
    max_end = max(r.end_months for r in records)
    return min_start, max_end
