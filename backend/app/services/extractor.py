from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Required fields for a fully-specified IRS trade.
# effective_date is included in missing_fields reporting but is NOT required
# for status="ready" — it can be inferred from settlement conventions.
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS: list[str] = [
    "instrument_type",
    "currency",
    "direction",
    "floating_index",
    "payment_frequency",
    "tenor",
    "notional",
    "effective_date",
]

# Fields that must all be present to return status="ready".
_STATUS_REQUIRED: list[str] = [f for f in _REQUIRED_FIELDS if f != "effective_date"]

_CURRENCIES: list[str] = ["ZAR", "USD", "EUR", "GBP"]
_FLOAT_INDICES: list[str] = ["JIBAR", "SOFR", "EURIBOR", "LIBOR"]
_FREQUENCIES: dict[str, str] = {
    "quarterly": "quarterly",
    "monthly": "monthly",
    "semiannual": "semiannual",
    "annual": "annual",
}


def _extract_instrument_type(prompt_lower: str) -> str | None:
    if "swap" in prompt_lower:
        return "irs"
    return None


def _extract_currency(prompt: str) -> str | None:
    # Word-boundary regex prevents 'EUR' matching inside 'EURIBOR'.
    for ccy in _CURRENCIES:
        if re.search(rf"\b{ccy}\b", prompt):
            return ccy
    return None


def _extract_direction(prompt_lower: str) -> str | None:
    if "payer" in prompt_lower:
        return "payer"
    if "receiver" in prompt_lower:
        return "receiver"
    return None


def _extract_floating_index(prompt: str) -> str | None:
    # Word-boundary regex — defensive; no current index is a substring of another,
    # but this is safer as the index list grows.
    for idx in _FLOAT_INDICES:
        if re.search(rf"\b{idx}\b", prompt):
            return idx
    return None


def _extract_payment_frequency(prompt_lower: str) -> str | None:
    for keyword, value in _FREQUENCIES.items():
        if keyword in prompt_lower:
            return value
    return None


def _extract_tenor(prompt: str) -> str | None:
    """Match patterns like 5Y, 3Y, 10Y (case-insensitive Y suffix)."""
    match = re.search(r"\b(\d+)[Yy]\b", prompt)
    if match:
        return f"{match.group(1)}Y"
    return None


def _extract_notional(prompt_lower: str) -> int | None:
    """
    Parse shorthand notional amounts:
      250m  -> 250_000_000
      10.5m -> 10_500_000
      500k  -> 500_000
    Falls back to any plain integer >= 7 digits if no suffix found.
    """
    m_match = re.search(r"\b(\d+(?:\.\d+)?)\s*m\b", prompt_lower)
    if m_match:
        return int(float(m_match.group(1)) * 1_000_000)

    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*k\b", prompt_lower)
    if k_match:
        return int(float(k_match.group(1)) * 1_000)

    large_match = re.search(r"\b(\d{7,})\b", prompt_lower)
    if large_match:
        return int(large_match.group(1))

    return None


def _extract_fixed_rate(prompt_lower: str) -> float | None:
    """
    Extract an optional fixed coupon rate and normalise to decimal.

    Recognised patterns (case-insensitive via prompt_lower):
      8.75%        -> 0.0875
      8.5 percent  -> 0.085
      at 8%        -> 0.08
      paying 9.25% -> 0.0925

    The regex requires a % sign or the word 'percent' to avoid accidental
    matches against tenor strings (e.g. '5Y') or notional shorthand ('250m').
    """
    # Percentage-sign pattern: digits optionally followed by decimal, then '%'
    pct_match = re.search(r"\b(\d+(?:\.\d+)?)\s*%", prompt_lower)
    if pct_match:
        return float(pct_match.group(1)) / 100.0

    # Spelled-out 'percent' pattern
    word_match = re.search(r"\b(\d+(?:\.\d+)?)\s*percent\b", prompt_lower)
    if word_match:
        return float(word_match.group(1)) / 100.0

    return None


def extract_fields(prompt: str) -> tuple[dict, list[str], str]:
    """
    Rule-based field extractor for interest-rate swap prompts.

    Returns:
        extracted_fields: dict of successfully parsed fields.
        missing_fields:   list of required fields not found in the prompt.
        status:           "ready" | "needs_clarification"
    """
    prompt_lower = prompt.lower()
    extracted: dict[str, object] = {}

    v = _extract_instrument_type(prompt_lower)
    if v is not None:
        extracted["instrument_type"] = v

    v = _extract_currency(prompt)
    if v is not None:
        extracted["currency"] = v

    v = _extract_direction(prompt_lower)
    if v is not None:
        extracted["direction"] = v

    v = _extract_floating_index(prompt)
    if v is not None:
        extracted["floating_index"] = v

    v = _extract_payment_frequency(prompt_lower)
    if v is not None:
        extracted["payment_frequency"] = v

    v = _extract_tenor(prompt)
    if v is not None:
        extracted["tenor"] = v

    v = _extract_notional(prompt_lower)
    if v is not None:
        extracted["notional"] = v

    # fixed_rate is optional — not in _REQUIRED_FIELDS, never in missing_fields
    fv = _extract_fixed_rate(prompt_lower)
    if fv is not None:
        extracted["fixed_rate"] = fv

    missing = [f for f in _REQUIRED_FIELDS if f not in extracted]
    status = "ready" if all(f in extracted for f in _STATUS_REQUIRED) else "needs_clarification"

    return extracted, missing, status
