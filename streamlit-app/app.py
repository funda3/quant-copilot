"""
Quant Copilot Streamlit Workbench

Sidebar-navigation workbench that connects to the local FastAPI backend
configured by BACKEND:
    POST /quote           — NLP prompt → IRS price
    POST /price/irs       — structured IRS pricing (no NLP)
    POST /price/fra       — deterministic FRA pricing
    POST /price/fx-forward — deterministic FX forward pricing
    POST /price/fx-swap   — deterministic FX swap pricing
    POST /price/fx-option — European FX option pricing under Garman-Kohlhagen
    POST /price/equity-option — European equity option pricing under Black-Scholes-Merton
    POST /api/curve       — mixed deposit/FRA/swap bootstrap
    POST /risk/ladder     — bucketed PV01 ladder for IRS
    POST /risk/scenario   — parallel curve-shift scenario NPV
    POST /price/bond      — deterministic fixed-rate bond pricing
    POST /risk/bond       — bond DV01 and modified duration
    POST /price/bond/ytm  — flat YTM solver from market dirty price

Pages (sidebar navigation):
  IRS Pricing       — NLP prompt → extract → price IRS (quote endpoint)
                                        + structured pricing via POST /price/irs
    FRA Pricing       — deterministic single-period forward rate agreement pricing
    FX Forward Pricing — deterministic FX forward pricing from flat domestic/foreign rates
        FX Swap Pricing   — deterministic deliverable FX swap pricing from flat domestic discounting
        European FX Option — vanilla European deliverable FX option pricing
          European Equity Option — vanilla European equity option pricing with continuous dividend yield
  Curve Builder     — build and inspect a bootstrapped discount curve
  Risk Ladder       — bucketed key-rate PV01 for an IRS
  Scenario Analysis — parallel curve-shift NPV table for an IRS
  Bond Pricing      — DCF pricing + DV01/modified duration + YTM solver for a fixed-rate bond
"""

from __future__ import annotations

import re

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND = "http://127.0.0.1:8001"

_DEFAULT_PROMPT = "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"

_DEFAULT_DEPOSITS = """1M 0.078
3M 0.079
6M 0.080"""

_DEFAULT_FRAS = """6x9 0.081
9x12 0.0815"""

_DEFAULT_SWAPS = """2Y 0.082
3Y 0.083
5Y 0.085"""

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_deposit_lines(text: str) -> list[dict]:
    """
    Parse lines like:
        1M 0.078
        3M 7.8%   (percent notation also accepted)
    Returns list of {"tenor_months": int, "rate": float}.
    Raises ValueError on any malformed line.
    """
    results = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.fullmatch(r"(\d+)[Mm]\s+([\d.]+)(%?)", line)
        if not m:
            raise ValueError(f"Cannot parse deposit line: {raw!r}  (expected e.g. '3M 0.079')")
        months = int(m.group(1))
        rate = float(m.group(2))
        if m.group(3) == "%":
            rate /= 100.0
        results.append({"tenor_months": months, "rate": rate})
    return results


def parse_fra_lines(text: str) -> list[dict]:
    """
    Parse lines like:
        6x9 0.081
        9x12 8.15%
    Returns list of {"start_months": int, "end_months": int, "rate": float}.
    Raises ValueError on any malformed line.
    """
    results = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.fullmatch(r"(\d+)[xX](\d+)\s+([\d.]+)(%?)", line)
        if not m:
            raise ValueError(f"Cannot parse FRA line: {raw!r}  (expected e.g. '6x9 0.081')")
        start = int(m.group(1))
        end = int(m.group(2))
        rate = float(m.group(3))
        if m.group(4) == "%":
            rate /= 100.0
        results.append({"start_months": start, "end_months": end, "rate": rate})
    return results


def parse_swap_lines(text: str) -> list[dict]:
    """
    Parse lines like:
        2Y 0.082
        5Y 8.5%
    Returns list of {"tenor_years": int, "par_rate": float}.
    Raises ValueError on any malformed line.
    """
    results = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.fullmatch(r"(\d+)[Yy]\s+([\d.]+)(%?)", line)
        if not m:
            raise ValueError(f"Cannot parse swap line: {raw!r}  (expected e.g. '5Y 0.085')")
        years = int(m.group(1))
        rate = float(m.group(2))
        if m.group(3) == "%":
            rate /= 100.0
        results.append({"tenor_years": years, "par_rate": rate})
    return results


def build_curve_inputs_payload(
    val_date: str,
    freq: str,
    day_count: str,
    deposits_text: str,
    fras_text: str,
    swaps_text: str,
) -> dict:
    """
    Parse all three text areas and assemble the curve_inputs dict.
    Raises ValueError if any parse fails.
    """
    payload: dict = {
        "payment_frequency": freq,
        "day_count": day_count,
    }
    if val_date.strip():
        payload["valuation_date"] = val_date.strip()
    deposits = parse_deposit_lines(deposits_text)
    fras = parse_fra_lines(fras_text)
    swaps = parse_swap_lines(swaps_text)
    if deposits:
        payload["deposits"] = deposits
    if fras:
        payload["fras"] = fras
    if swaps:
        payload["swaps"] = swaps
    return payload


# ---------------------------------------------------------------------------
# Parsing helpers — bucket years and scenario shifts
# ---------------------------------------------------------------------------


def parse_bucket_years(text: str) -> list[int]:
    """
    Parse a comma-separated string of positive integers into list[int].

    Accepts:  "1,2,3,5,7,10"  or  " 1, 2, 3, 5, 7, 10 "
    Raises ValueError on any non-positive or non-integer token.
    """
    parts = [t.strip() for t in text.split(",") if t.strip()]
    if not parts:
        raise ValueError("Bucket years must not be empty (e.g. '1,2,3,5,7,10').")
    result: list[int] = []
    for p in parts:
        try:
            val = int(p)
        except ValueError:
            raise ValueError(
                f"Cannot parse bucket year {p!r} — expected a positive integer."
            )
        if val <= 0:
            raise ValueError(
                f"Bucket year {val} is not valid — all values must be positive."
            )
        result.append(val)
    return result


def parse_shift_bps(text: str) -> list[int]:
    """
    Parse a comma-separated string of integers (positive, negative, or zero)
    into list[int].

    Accepts:  "-200,-100,-50,0,50,100,200"  or  " -200, -100, 0, 100 "
    Raises ValueError on any non-integer token, or if the list is empty.
    """
    parts = [t.strip() for t in text.split(",") if t.strip()]
    if not parts:
        raise ValueError(
            "Scenario shifts must not be empty (e.g. '-200,-100,0,100,200')."
        )
    result: list[int] = []
    for p in parts:
        try:
            val = int(p)
        except ValueError:
            raise ValueError(
                f"Cannot parse shift {p!r} — expected an integer in basis points."
            )
        result.append(val)
    return result


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------


def call_quote(prompt: str, curve_inputs: dict | None) -> dict:
    body: dict = {"prompt": prompt}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/quote", json=body, timeout=10)
    return resp


def call_build_curve(payload: dict) -> dict:
    resp = requests.post(f"{BACKEND}/api/curve", json=payload, timeout=10)
    return resp


def call_ladder(
    extracted_fields: dict,
    curve_inputs: dict | None,
    bucket_years: list[int],
) -> requests.Response:
    body: dict = {"extracted_fields": extracted_fields, "bucket_years": bucket_years}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/risk/ladder", json=body, timeout=10)
    return resp


def call_scenario(
    extracted_fields: dict,
    curve_inputs: dict | None,
    shift_bps: list[int],
) -> requests.Response:
    body: dict = {"extracted_fields": extracted_fields, "shift_bps": shift_bps}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/risk/scenario", json=body, timeout=10)
    return resp


def call_bond(
    valuation_date: str,
    issue_date: str,
    maturity_date: str,
    face_value: float,
    coupon_rate: float,
    coupon_frequency: str,
    day_count: str,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "issue_date": issue_date,
        "maturity_date": maturity_date,
        "face_value": face_value,
        "coupon_rate": coupon_rate,
        "coupon_frequency": coupon_frequency,
        "day_count": day_count,
    }
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/bond", json=body, timeout=10)
    return resp


def call_fra(
    valuation_date: str,
    start_date: str,
    end_date: str,
    notional: float,
    contract_rate: float,
    day_count: str,
    position: str,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "start_date": start_date,
        "end_date": end_date,
        "notional": notional,
        "contract_rate": contract_rate,
        "day_count": day_count,
        "position": position,
    }
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/fra", json=body, timeout=10)
    return resp


def call_fx_forward(
    valuation_date: str,
    maturity_date: str,
    notional_foreign: float,
    spot_rate: float,
    contract_forward_rate: float,
    domestic_rate: float,
    foreign_rate: float,
    domestic_currency: str,
    foreign_currency: str,
    day_count: str,
    position: str,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "maturity_date": maturity_date,
        "notional_foreign": notional_foreign,
        "spot_rate": spot_rate,
        "contract_forward_rate": contract_forward_rate,
        "domestic_rate": domestic_rate,
        "foreign_rate": foreign_rate,
        "domestic_currency": domestic_currency,
        "foreign_currency": foreign_currency,
        "day_count": day_count,
        "position": position,
    }
    resp = requests.post(f"{BACKEND}/price/fx-forward", json=body, timeout=10)
    return resp


def call_fx_swap(
    valuation_date: str,
    near_settlement_date: str,
    far_settlement_date: str,
    spot_rate: float,
    near_rate: float,
    far_rate: float,
    notional_foreign: float,
    domestic_currency: str,
    foreign_currency: str,
    domestic_rate: float,
    day_count: str,
    position: str,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "near_settlement_date": near_settlement_date,
        "far_settlement_date": far_settlement_date,
        "spot_rate": spot_rate,
        "near_rate": near_rate,
        "far_rate": far_rate,
        "notional_foreign": notional_foreign,
        "domestic_currency": domestic_currency,
        "foreign_currency": foreign_currency,
        "domestic_rate": domestic_rate,
        "day_count": day_count,
        "position": position,
    }
    resp = requests.post(f"{BACKEND}/price/fx-swap", json=body, timeout=10)
    return resp


def call_fx_option(
    valuation_date: str,
    expiry_date: str,
    settlement_date: str | None,
    spot_rate: float,
    strike_rate: float,
    domestic_rate: float,
    foreign_rate: float,
    volatility: float,
    notional_foreign: float,
    option_type: str,
    position: str,
    domestic_currency: str,
    foreign_currency: str,
    day_count: str,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "expiry_date": expiry_date,
        "spot_rate": spot_rate,
        "strike_rate": strike_rate,
        "domestic_rate": domestic_rate,
        "foreign_rate": foreign_rate,
        "volatility": volatility,
        "notional_foreign": notional_foreign,
        "option_type": option_type,
        "position": position,
        "domestic_currency": domestic_currency,
        "foreign_currency": foreign_currency,
        "day_count": day_count,
    }
    if settlement_date:
        body["settlement_date"] = settlement_date
    resp = requests.post(f"{BACKEND}/price/fx-option", json=body, timeout=10)
    return resp


def call_equity_option(
    valuation_date: str,
    expiry_date: str,
    spot_price: float,
    strike_price: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    quantity_shares: float,
    option_type: str,
    position: str,
    currency: str,
    day_count: str,
    underlying_name: str | None,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "expiry_date": expiry_date,
        "spot_price": spot_price,
        "strike_price": strike_price,
        "risk_free_rate": risk_free_rate,
        "dividend_yield": dividend_yield,
        "volatility": volatility,
        "quantity_shares": quantity_shares,
        "option_type": option_type,
        "position": position,
        "currency": currency,
        "day_count": day_count,
    }
    if underlying_name:
        body["underlying_name"] = underlying_name
    resp = requests.post(f"{BACKEND}/price/equity-option", json=body, timeout=10)
    return resp


def call_bond_risk(
    valuation_date: str,
    issue_date: str,
    maturity_date: str,
    face_value: float,
    coupon_rate: float,
    coupon_frequency: str,
    day_count: str,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "issue_date": issue_date,
        "maturity_date": maturity_date,
        "face_value": face_value,
        "coupon_rate": coupon_rate,
        "coupon_frequency": coupon_frequency,
        "day_count": day_count,
    }
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/risk/bond", json=body, timeout=10)
    return resp


def call_bond_ytm(
    valuation_date: str,
    issue_date: str,
    maturity_date: str,
    face_value: float,
    coupon_rate: float,
    coupon_frequency: str,
    day_count: str,
    market_dirty_price: float,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "issue_date": issue_date,
        "maturity_date": maturity_date,
        "face_value": face_value,
        "coupon_rate": coupon_rate,
        "coupon_frequency": coupon_frequency,
        "day_count": day_count,
        "market_dirty_price": market_dirty_price,
    }
    resp = requests.post(f"{BACKEND}/price/bond/ytm", json=body, timeout=10)
    return resp


def call_bond_cashflows(
    valuation_date: str,
    issue_date: str,
    maturity_date: str,
    face_value: float,
    coupon_rate: float,
    coupon_frequency: str,
    day_count: str,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "valuation_date": valuation_date,
        "issue_date": issue_date,
        "maturity_date": maturity_date,
        "face_value": face_value,
        "coupon_rate": coupon_rate,
        "coupon_frequency": coupon_frequency,
        "day_count": day_count,
    }
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/bond/cashflows", json=body, timeout=10)
    return resp


def call_irs_cashflows(
    extracted_fields: dict,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {"extracted_fields": extracted_fields}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/irs/cashflows", json=body, timeout=10)
    return resp


def call_irs_breakdown(
    extracted_fields: dict,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {"extracted_fields": extracted_fields}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/irs/breakdown", json=body, timeout=10)
    return resp


def call_irs_fair_rate(
    extracted_fields: dict,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {"extracted_fields": extracted_fields}
    if curve_inputs:
        body["curve_inputs"] = curve_inputs
    resp = requests.post(f"{BACKEND}/price/irs/fair-rate", json=body, timeout=10)
    return resp


def call_irs_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/price/irs", json=body, timeout=10)


def call_irs_cashflows_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/price/irs/cashflows/direct", json=body, timeout=10)


def call_irs_breakdown_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/price/irs/breakdown/direct", json=body, timeout=10)


def call_irs_fair_rate_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/price/irs/fair-rate/direct", json=body, timeout=10)


def call_irs_ladder_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    bucket_years: list[int] | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if bucket_years is not None:
        body["bucket_years"] = bucket_years
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/risk/ladder/direct", json=body, timeout=10)


def call_irs_scenario_direct(
    direction: str,
    payment_frequency: str,
    tenor: str,
    notional: float,
    fixed_rate: float | None,
    shift_bps: list[int] | None,
    curve_inputs: dict | None,
) -> requests.Response:
    body: dict = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": direction,
        "floating_index": "JIBAR",
        "payment_frequency": payment_frequency,
        "tenor": tenor,
        "notional": notional,
    }
    if fixed_rate is not None:
        body["fixed_rate"] = fixed_rate
    if shift_bps is not None:
        body["shift_bps"] = shift_bps
    if curve_inputs is not None:
        body["curve_inputs"] = curve_inputs
    return requests.post(f"{BACKEND}/risk/scenario/direct", json=body, timeout=10)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def _show_error(label: str, detail: str) -> None:
    st.error(f"**{label}:**  {detail}")


def _show_response_error(label: str, resp: requests.Response) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    _show_error(f"{label} (HTTP {resp.status_code})", str(detail))


# ---------------------------------------------------------------------------
# App config and sidebar navigation
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Quant Copilot", layout="wide")

# Sidebar — navigation
with st.sidebar:
    st.title("Quant Copilot")
    st.caption("ZAR quant workbench")
    st.divider()

    _NAV_IMPLEMENTED = [
        "IRS Pricing",
        "FRA Pricing",
        "FX Forward Pricing",
        "FX Swap Pricing",
        "European FX Option",
        "European Equity Option",
        "Curve Builder",
        "Risk Ladder",
        "Scenario Analysis",
        "Bond Pricing",
    ]
    _NAV_PLACEHOLDER = [
        "— Greeks (coming soon)",
        "— Monte Carlo Lab (coming soon)",
    ]

    page = st.radio(
        "Navigate to",
        options=_NAV_IMPLEMENTED,
        index=0,
        key="nav_page",
    )

    st.divider()
    st.markdown("**Planned**")
    for _ph in _NAV_PLACEHOLDER:
        st.caption(_ph)

    st.divider()
    st.caption(f"Backend: `{BACKEND}`")

# ===========================================================================
# Helper: reusable curve inputs block
# ===========================================================================

def _render_curve_inputs_expander(key_prefix: str) -> tuple[str, str, str, str, str, str, bool]:
    """
    Render the bootstrapped curve inputs expander.

    Returns (val_date, freq, day_count, deposits_text, fras_text, swaps_text, use_curve)
    so the caller can decide whether to include the curve.  All widget keys are
    namespaced with *key_prefix* to avoid collisions across pages.
    """
    with st.expander("Optional Bootstrapped Curve Inputs", expanded=False):
        st.caption(
            "When supplied, the request is priced off a bootstrapped mixed "
            "deposit/FRA/swap curve instead of the flat 8% ZAR JIBAR proxy."
        )
        _c1, _c2 = st.columns(2)
        with _c1:
            _vd = st.text_input(
                "Valuation date (YYYY-MM-DD, leave blank for today)",
                value="",
                key=f"{key_prefix}_val_date",
            )
            _fr = st.selectbox(
                "Payment frequency",
                options=["annual", "semiannual", "quarterly", "monthly"],
                index=0,
                key=f"{key_prefix}_freq",
            )
            _dc = st.selectbox(
                "Day count",
                options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
                index=0,
                key=f"{key_prefix}_day_count",
            )
        with _c2:
            st.markdown("**Format:** `tenor rate` — e.g. `3M 0.079` or `3M 7.9%`")
        _dep = st.text_area(
            'Deposits (one per line: "NM rate")',
            value=_DEFAULT_DEPOSITS,
            height=110,
            key=f"{key_prefix}_deposits_text",
        )
        _fra = st.text_area(
            'FRAs (one per line: "SxE rate")',
            value=_DEFAULT_FRAS,
            height=90,
            key=f"{key_prefix}_fras_text",
        )
        _swp = st.text_area(
            'Swaps (one per line: "NY rate")',
            value=_DEFAULT_SWAPS,
            height=110,
            key=f"{key_prefix}_swaps_text",
        )
        _use = st.checkbox(
            "Include these curve inputs in the request",
            value=False,
            key=f"{key_prefix}_use_curve",
        )
    return _vd, _fr, _dc, _dep, _fra, _swp, _use


# ===========================================================================
# PAGE: IRS Pricing
# ===========================================================================

if page == "IRS Pricing":
    st.title("IRS Pricing")
    st.caption("Natural-language trade description → field extraction → IRS NPV and PV01")

    # A. Prompt
    prompt = st.text_area(
        label="Describe the trade you want to price:",
        value=_DEFAULT_PROMPT,
        height=80,
        key="irs_prompt",
    )

    # B. Optional curve inputs
    val_date, freq, day_count, deposits_text, fras_text, swaps_text, use_curve_inputs = (
        _render_curve_inputs_expander("irs")
    )

    run_quote_btn = st.button("Run Quote", type="primary", key="run_quote_btn")

    # C. Quote result
    if run_quote_btn:
        if not prompt.strip():
            st.warning("Please enter a pricing prompt before running a quote.")
        else:
            curve_inputs_payload: dict | None = None
            if use_curve_inputs:
                try:
                    curve_inputs_payload = build_curve_inputs_payload(
                        val_date, freq, day_count, deposits_text, fras_text, swaps_text
                    )
                except ValueError as exc:
                    _show_error("Curve input parse error", str(exc))
                    st.stop()

            st.subheader("Quote Result")
            try:
                resp = call_quote(prompt.strip(), curve_inputs_payload)
            except requests.exceptions.ConnectionError:
                _show_error(
                    "Backend unreachable",
                    f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                )
            else:
                if resp.status_code == 200:
                    data = resp.json()

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Extraction", data.get("extraction_status", "—"))
                    c2.metric("Price status", data.get("price_status") or "—")
                    price_val = data.get("price", 0.0)
                    pv01_val = data.get("pv01", 0.0)
                    c3.metric("Price (NPV)", f"{price_val:,.2f}")
                    c4.metric("PV01", f"{pv01_val:,.2f}")

                    st.markdown(f"**Prompt:** {data.get('raw_prompt', prompt)}")

                    for w in data.get("warnings", []):
                        st.warning(w)

                    st.subheader("Details")

                    missing = data.get("missing_fields", [])
                    if missing:
                        st.info(f"**Missing fields:** {', '.join(missing)}")

                    extracted = data.get("extracted_fields", {})
                    if extracted:
                        # Cache extracted fields for the cashflow button
                        st.session_state["irs_extracted_fields"] = extracted
                        st.session_state["irs_curve_inputs_payload"] = curve_inputs_payload
                        st.markdown("**Extracted fields:**")
                        field_rows = "".join(
                            f"| `{k}` | {v} |\n" for k, v in extracted.items()
                        )
                        st.markdown(
                            "| Field | Value |\n"
                            "|---|---|\n" + field_rows
                        )

                    assumptions = data.get("assumptions", [])
                    if assumptions:
                        with st.expander("Assumptions", expanded=False):
                            for a in assumptions:
                                st.markdown(f"- {a}")
                else:
                    _show_response_error("Quote request failed", resp)

    # D. Show IRS cashflows button (uses cached extracted_fields from last quote)
    st.divider()
    show_irs_cf_btn = st.button(
        "Show IRS Cashflows", key="show_irs_cf_btn"
    )

    if show_irs_cf_btn:
        cached_fields = st.session_state.get("irs_extracted_fields")
        if not cached_fields:
            st.warning("Run a quote first to extract trade fields, then click Show IRS Cashflows.")
        else:
            cached_ci = st.session_state.get("irs_curve_inputs_payload")
            st.subheader("IRS Fixed-Leg Cashflow Schedule")
            try:
                cf_resp = call_irs_cashflows(cached_fields, cached_ci)
            except requests.exceptions.ConnectionError:
                _show_error(
                    "Backend unreachable",
                    f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                )
            else:
                if cf_resp.status_code == 200:
                    cf_data = cf_resp.json()
                    if cf_data.get("status") == "indicative":
                        _cf1, _cf2 = st.columns(2)
                        _cf1.metric("Fixed Leg PV", f"{cf_data['fixed_leg_pv']:,.2f}")
                        _cf2.metric("Payments", cf_data["n_payments"])

                        for w in cf_data.get("warnings", []):
                            st.warning(w)

                        rows = cf_data.get("cashflows", [])
                        if rows:
                            # Backend IRSCashflowRow fields: payment_date,
                            # accrual_start, accrual_end, year_fraction,
                            # fixed_rate, notional, fixed_cashflow,
                            # discount_factor, pv_cashflow, time_to_payment_years.
                            # NB: IRS fixed leg has no principal exchange, so
                            # fixed_cashflow == total_cashflow; displayed in
                            # both "Fixed CF" and "Total CF" columns.
                            header = (
                                "| # | Payment date | Accrual start | Accrual end"
                                " | Year frac | Fixed rate | Notional"
                                " | Fixed CF | Total CF | DF | PV | Time (yrs) |\n"
                                "|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                            )
                            body = "".join(
                                f"| {i + 1}"
                                f" | {r['payment_date']}"
                                f" | {r['accrual_start']}"
                                f" | {r['accrual_end']}"
                                f" | {r['year_fraction']:.4f}"
                                f" | {r['fixed_rate']:.4%}"
                                f" | {r['notional']:,.0f}"
                                f" | {r['fixed_cashflow']:,.0f}"
                                f" | {r['fixed_cashflow']:,.0f}"
                                f" | {r['discount_factor']:.6f}"
                                f" | {r['pv_cashflow']:,.0f}"
                                f" | {r['time_to_payment_years']:.4f} |\n"
                                for i, r in enumerate(rows)
                            )
                            st.markdown(header + body)

                        with st.expander("Assumptions", expanded=False):
                            for a in cf_data.get("assumptions", []):
                                st.markdown(f"- {a}")
                    else:
                        for w in cf_data.get("warnings", []):
                            st.warning(w)
                        st.error(f"Cashflow schedule status: {cf_data.get('status')}")
                else:
                    _show_response_error("IRS cashflows request failed", cf_resp)

    # E. Show IRS Breakdown button (uses cached extracted_fields from last quote)
    st.divider()
    show_irs_bd_btn = st.button(
        "Show IRS Breakdown", key="show_irs_bd_btn"
    )

    if show_irs_bd_btn:
        cached_fields = st.session_state.get("irs_extracted_fields")
        if not cached_fields:
            st.warning("Run a quote first to extract trade fields, then click Show IRS Breakdown.")
        else:
            cached_ci = st.session_state.get("irs_curve_inputs_payload")
            st.subheader("IRS Valuation Breakdown")
            try:
                bd_resp = call_irs_breakdown(cached_fields, cached_ci)
            except requests.exceptions.ConnectionError:
                _show_error(
                    "Backend unreachable",
                    f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                )
            else:
                if bd_resp.status_code == 200:
                    bd_data = bd_resp.json()
                    if bd_data.get("status") == "indicative":
                        # Metrics row
                        _bd1, _bd2, _bd3, _bd4 = st.columns(4)
                        _bd1.metric("Fixed Leg PV", f"{bd_data['fixed_leg_pv']:,.2f}")
                        _bd2.metric("Floating Leg PV", f"{bd_data['floating_leg_pv']:,.2f}")
                        _bd3.metric("NPV", f"{bd_data['npv']:,.2f}")
                        _bd4.metric("Payments", bd_data["n_payments"])

                        for w in bd_data.get("warnings", []):
                            st.warning(w)

                        # Breakdown detail block
                        st.markdown(
                            f"**Curve source:** `{bd_data['curve_source']}`  \n"
                            f"**Floating leg method:** `{bd_data['floating_leg_method']}`"
                        )

                        with st.expander("Assumptions", expanded=False):
                            for a in bd_data.get("assumptions", []):
                                st.markdown(f"- {a}")
                    else:
                        for w in bd_data.get("warnings", []):
                            st.warning(w)
                        st.error(f"Breakdown status: {bd_data.get('status')}")
                else:
                    _show_response_error("IRS breakdown request failed", bd_resp)

    # F. Solve Fair Rate button (uses cached extracted_fields from last quote)
    st.divider()
    solve_fair_rate_btn = st.button(
        "Solve Fair Rate", key="solve_fair_rate_btn"
    )

    if solve_fair_rate_btn:
        cached_fields = st.session_state.get("irs_extracted_fields")
        if not cached_fields:
            st.warning("Run a quote first to extract trade fields, then click Solve Fair Rate.")
        else:
            cached_ci = st.session_state.get("irs_curve_inputs_payload")
            st.subheader("IRS Fair Rate (Par Swap Rate)")
            try:
                fr_resp = call_irs_fair_rate(cached_fields, cached_ci)
            except requests.exceptions.ConnectionError:
                _show_error(
                    "Backend unreachable",
                    f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                )
            else:
                if fr_resp.status_code == 200:
                    fr_data = fr_resp.json()
                    if fr_data.get("status") == "indicative":
                        # Primary metric — fair rate as a percentage
                        _fr1, _fr2 = st.columns(2)
                        _fr1.metric(
                            "Fair Rate",
                            f"{fr_data['fair_rate']:.4%}",
                        )
                        _fr2.metric(
                            "Fixed-Leg Annuity",
                            f"{fr_data['fixed_leg_annuity']:.6f}",
                        )

                        for w in fr_data.get("warnings", []):
                            st.warning(w)

                        st.markdown(
                            f"**Curve source:** `{fr_data['curve_source']}`"
                        )

                        with st.expander("Assumptions", expanded=False):
                            for a in fr_data.get("assumptions", []):
                                st.markdown(f"- {a}")
                    else:
                        for w in fr_data.get("warnings", []):
                            st.warning(w)
                        st.error(f"Fair-rate solver status: {fr_data.get('status')}")
                else:
                    _show_response_error("IRS fair-rate request failed", fr_resp)

    # G. Price Structured IRS (direct route — no NLP required)
    st.divider()
    st.subheader("Price Structured IRS (Direct)")
    st.caption(
        "Build a structured IRS request and call POST /price/irs directly. "
        "No natural-language prompt required — all fields are explicit."
    )

    _g_c1, _g_c2, _g_c3 = st.columns(3)
    with _g_c1:
        g_direction = st.selectbox(
            "Direction",
            options=["payer", "receiver"],
            index=0,
            key="irs_direct_direction",
        )
        g_payment_freq = st.selectbox(
            "Payment frequency",
            options=["quarterly", "semiannual", "annual"],
            index=0,
            key="irs_direct_freq",
        )
    with _g_c2:
        g_tenor = st.text_input(
            "Tenor (e.g. 5Y, 10Y)",
            value="5Y",
            key="irs_direct_tenor",
        )
        g_notional = st.number_input(
            "Notional (ZAR)",
            min_value=1_000.0,
            max_value=100_000_000_000.0,
            value=100_000_000.0,
            step=1_000_000.0,
            format="%.0f",
            key="irs_direct_notional",
        )
    with _g_c3:
        g_fixed_rate_str = st.text_input(
            "Fixed rate decimal (e.g. 0.085 — leave blank for default 8.5%)",
            value="",
            key="irs_direct_fixed_rate",
        )

    # NOTE: prefix must be "irs_direct_curve" (not "irs_direct") to avoid
    # colliding with the explicit "irs_direct_freq" selectbox above.
    # Rule: any widget-producing helper must receive a prefix that does NOT
    # match the leading segment of any explicit key in the same render pass.
    (
        g_val_date, g_ci_freq, g_day_count,
        g_deposits_text, g_fras_text, g_swaps_text, g_use_curve,
    ) = _render_curve_inputs_expander("irs_direct_curve")

    price_irs_direct_btn = st.button(
        "Price Structured IRS", type="primary", key="price_irs_direct_btn"
    )

    if price_irs_direct_btn:
        g_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                g_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        g_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                g_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Pricing Result")
        try:
            direct_resp = call_irs_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=g_fixed_rate,
                curve_inputs=g_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if direct_resp.status_code == 200:
                d_data = direct_resp.json()
                if d_data.get("status") == "indicative":
                    d_c1, d_c2, d_c3 = st.columns(3)
                    d_c1.metric("NPV (Price)", f"{d_data['price']:,.2f}")
                    d_c2.metric("PV01", f"{d_data['pv01']:,.2f}")
                    d_c3.metric("Curve", d_data.get("curve_source", "—"))

                    for w in d_data.get("warnings", []):
                        st.warning(w)

                    st.markdown(
                        f"**Curve source:** `{d_data.get('curve_source', '—')}`"
                    )

                    with st.expander("Assumptions", expanded=False):
                        for a in d_data.get("assumptions", []):
                            st.markdown(f"- {a}")
                else:
                    for w in d_data.get("warnings", []):
                        st.warning(w)
                    st.error(f"Pricing status: {d_data.get('status')}")
            else:
                _show_response_error("Structured IRS pricing request failed", direct_resp)

    # H. Show Structured IRS Cashflows (direct route — uses Section G inputs)
    st.divider()
    show_irs_direct_cf_btn = st.button(
        "Show Structured IRS Cashflows", key="show_irs_direct_cf_btn"
    )

    if show_irs_direct_cf_btn:
        h_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                h_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        h_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                h_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Cashflow Schedule")
        try:
            h_resp = call_irs_cashflows_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=h_fixed_rate,
                curve_inputs=h_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if h_resp.status_code == 200:
                h_data = h_resp.json()
                if h_data.get("status") == "indicative":
                    h_c1, h_c2, h_c3 = st.columns(3)
                    h_c1.metric("Fixed Leg PV", f"{h_data['fixed_leg_pv']:,.2f}")
                    h_c2.metric("Payments", h_data["n_payments"])
                    h_c3.metric("Curve", h_data.get("curve_source", "\u2014"))

                    for w in h_data.get("warnings", []):
                        st.warning(w)

                    rows = h_data.get("cashflows", [])
                    if rows:
                        header = (
                            "| # | Payment date | Accrual start | Accrual end"
                            " | Year frac | Fixed rate | Notional"
                            " | Fixed CF | DF | PV | Time (yrs) |\n"
                            "|---|---|---|---|---|---|---|---|---|---|---|\n"
                        )
                        body_md = "".join(
                            f"| {i + 1}"
                            f" | {r['payment_date']}"
                            f" | {r['accrual_start']}"
                            f" | {r['accrual_end']}"
                            f" | {r['year_fraction']:.4f}"
                            f" | {r['fixed_rate']:.4%}"
                            f" | {r['notional']:,.0f}"
                            f" | {r['fixed_cashflow']:,.0f}"
                            f" | {r['discount_factor']:.6f}"
                            f" | {r['pv_cashflow']:,.0f}"
                            f" | {r['time_to_payment_years']:.4f} |\n"
                            for i, r in enumerate(rows)
                        )
                        st.markdown(header + body_md)

                    with st.expander("Assumptions", expanded=False):
                        for a in h_data.get("assumptions", []):
                            st.markdown(f"- {a}")
                else:
                    for w in h_data.get("warnings", []):
                        st.warning(w)
                    st.error(f"Cashflow status: {h_data.get('status')}")
            else:
                _show_response_error("Structured IRS cashflows request failed", h_resp)

    # I. Show Structured IRS Breakdown (direct route — uses Section G inputs)
    st.divider()
    show_irs_direct_bd_btn = st.button(
        "Show Structured IRS Breakdown", key="show_irs_direct_bd_btn"
    )

    if show_irs_direct_bd_btn:
        i_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                i_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        i_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                i_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Valuation Breakdown")
        try:
            i_resp = call_irs_breakdown_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=i_fixed_rate,
                curve_inputs=i_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if i_resp.status_code == 200:
                i_data = i_resp.json()
                if i_data.get("status") == "indicative":
                    i_c1, i_c2, i_c3 = st.columns(3)
                    i_c1.metric("Fixed Leg PV", f"{i_data['fixed_leg_pv']:,.2f}")
                    i_c2.metric("Float Leg PV", f"{i_data['floating_leg_pv']:,.2f}")
                    i_c3.metric("NPV", f"{i_data['npv']:,.2f}")

                    i_c4, i_c5, i_c6 = st.columns(3)
                    i_c4.metric("Payments", i_data["n_payments"])
                    i_c5.metric("Curve", i_data.get("curve_source", "\u2014"))
                    i_c6.metric("Float Method", i_data.get("floating_leg_method", "\u2014"))

                    for w in i_data.get("warnings", []):
                        st.warning(w)

                    with st.expander("Assumptions", expanded=False):
                        for a in i_data.get("assumptions", []):
                            st.markdown(f"- {a}")
                else:
                    for w in i_data.get("warnings", []):
                        st.warning(w)
                    st.error(f"Breakdown status: {i_data.get('status')}")
            else:
                _show_response_error("Structured IRS breakdown request failed", i_resp)

    # J. Solve Structured Fair Rate (direct route — uses Section G inputs)
    st.divider()
    show_irs_direct_fr_btn = st.button(
        "Solve Structured Fair Rate", key="show_irs_direct_fr_btn"
    )

    if show_irs_direct_fr_btn:
        j_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                j_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        j_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                j_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Fair Rate")
        try:
            j_resp = call_irs_fair_rate_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=j_fixed_rate,
                curve_inputs=j_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if j_resp.status_code == 200:
                j_data = j_resp.json()
                if j_data.get("status") == "indicative":
                    j_c1, j_c2, j_c3 = st.columns(3)
                    j_c1.metric("Fair Rate", f"{j_data['fair_rate']:.4%}")
                    j_c2.metric("Fixed Leg Annuity", f"{j_data['fixed_leg_annuity']:.6f}")
                    j_c3.metric("Curve", j_data.get("curve_source", "\u2014"))

                    for w in j_data.get("warnings", []):
                        st.warning(w)

                    with st.expander("Assumptions", expanded=False):
                        for a in j_data.get("assumptions", []):
                            st.markdown(f"- {a}")
                else:
                    for w in j_data.get("warnings", []):
                        st.warning(w)
                    st.error(f"Fair rate status: {j_data.get('status')}")
            else:
                _show_response_error("Structured IRS fair-rate request failed", j_resp)

    # K. Run Structured Ladder (direct route — uses Section G inputs)
    st.divider()
    k_bucket_years_text = st.text_input(
        "Structured ladder buckets (comma-separated years)",
        value="1,2,3,5,7,10",
        key="irs_direct_ladder_buckets",
        help="Defaults match the quote-style ladder page.",
    )
    run_irs_direct_ladder_btn = st.button(
        "Run Structured Ladder", key="run_irs_direct_ladder_btn"
    )

    if run_irs_direct_ladder_btn:
        k_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                k_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        try:
            k_bucket_years = parse_bucket_years(k_bucket_years_text)
        except ValueError as exc:
            _show_error("Bucket years parse error", str(exc))
            st.stop()

        k_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                k_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Ladder")
        try:
            k_resp = call_irs_ladder_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=k_fixed_rate,
                bucket_years=k_bucket_years,
                curve_inputs=k_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if k_resp.status_code == 200:
                k_data = k_resp.json()
                k_c1, k_c2, k_c3 = st.columns(3)
                k_c1.metric("Request ID", k_data.get("request_id", "—"))
                k_c2.metric("Status", k_data.get("status", "—"))
                k_c3.metric("Total |PV01|", f"{k_data.get('total_abs_pv01', 0.0):,.2f}")

                k_bp = k_data.get("bucket_pv01", {})
                k_total = k_data.get("total_abs_pv01", 0.0)
                if k_bp:
                    st.markdown("**Bucketed PV01 (signed, per +1 bp):**")
                    k_rows = "".join(
                        f"| {bucket} | {pv01:,.2f} | "
                        + (f"{abs(pv01) / k_total * 100:.1f}%" if k_total > 0 else "0.0%")
                        + " |\n"
                        for bucket, pv01 in k_bp.items()
                    )
                    st.markdown(
                        "| Bucket | Signed PV01 | % of Total Abs PV01 |\n"
                        "|---|---:|---:|\n" + k_rows
                    )

                for w in k_data.get("warnings", []):
                    st.warning(w)

                with st.expander("Assumptions", expanded=False):
                    for a in k_data.get("assumptions", []):
                        st.markdown(f"- {a}")
            else:
                _show_response_error("Structured IRS ladder request failed", k_resp)

    # L. Run Structured Scenarios (direct route — uses Section G inputs)
    st.divider()
    l_shift_bps_text = st.text_input(
        "Structured scenario shifts (bps, comma-separated)",
        value="-200,-100,-50,0,50,100,200",
        key="irs_direct_scenario_shifts",
        help="Defaults match the quote-style scenario page.",
    )
    run_irs_direct_scenario_btn = st.button(
        "Run Structured Scenarios", key="run_irs_direct_scenario_btn"
    )

    if run_irs_direct_scenario_btn:
        l_fixed_rate: float | None = None
        if g_fixed_rate_str.strip():
            try:
                l_fixed_rate = float(g_fixed_rate_str.strip())
            except ValueError:
                _show_error(
                    "Fixed rate parse error",
                    f"Cannot parse '{g_fixed_rate_str}' as a decimal number.",
                )
                st.stop()

        try:
            l_shift_bps = parse_shift_bps(l_shift_bps_text)
        except ValueError as exc:
            _show_error("Scenario shifts parse error", str(exc))
            st.stop()

        l_curve_inputs_payload: dict | None = None
        if g_use_curve:
            try:
                l_curve_inputs_payload = build_curve_inputs_payload(
                    g_val_date, g_ci_freq, g_day_count,
                    g_deposits_text, g_fras_text, g_swaps_text,
                )
            except ValueError as exc:
                _show_error("Curve input parse error", str(exc))
                st.stop()

        st.subheader("Structured IRS Scenarios")
        try:
            l_resp = call_irs_scenario_direct(
                direction=g_direction,
                payment_frequency=g_payment_freq,
                tenor=g_tenor,
                notional=g_notional,
                fixed_rate=l_fixed_rate,
                shift_bps=l_shift_bps,
                curve_inputs=l_curve_inputs_payload,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if l_resp.status_code == 200:
                l_data = l_resp.json()
                l_c1, l_c2, l_c3 = st.columns(3)
                l_c1.metric("Request ID", l_data.get("request_id", "—"))
                l_c2.metric("Status", l_data.get("status", "—"))
                l_c3.metric("Base NPV", f"{l_data.get('base_npv', 0.0):,.2f}")

                l_snpv = l_data.get("scenario_npv", {})
                l_base = l_data.get("base_npv", 0.0)
                if l_snpv:
                    st.markdown("**Scenario NPV (parallel curve shift):**")
                    l_rows = "".join(
                        f"| {shift} | {npv:,.2f} | {npv - l_base:+,.2f} |\n"
                        for shift, npv in l_snpv.items()
                    )
                    st.markdown(
                        "| Shift | NPV | Change vs Base |\n"
                        "|---|---:|---:|\n" + l_rows
                    )

                for w in l_data.get("warnings", []):
                    st.warning(w)

                with st.expander("Assumptions", expanded=False):
                    for a in l_data.get("assumptions", []):
                        st.markdown(f"- {a}")
            else:
                _show_response_error("Structured IRS scenario request failed", l_resp)


elif page == "Curve Builder":
    st.title("Curve Builder")
    st.caption("Bootstrap a mixed deposit/FRA/swap discount curve and inspect the pillar table.")

    # Curve inputs (always visible on this page)
    _cb_col1, _cb_col2 = st.columns(2)
    with _cb_col1:
        cb_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD, leave blank for today)",
            value="",
            key="cb_val_date",
        )
        cb_freq = st.selectbox(
            "Payment frequency",
            options=["annual", "semiannual", "quarterly", "monthly"],
            index=0,
            key="cb_freq",
        )
        cb_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="cb_day_count",
        )
    with _cb_col2:
        st.markdown("**Format:** `tenor rate` — e.g. `3M 0.079` or `3M 7.9%`")

    cb_deposits = st.text_area(
        'Deposits (one per line: "NM rate")',
        value=_DEFAULT_DEPOSITS,
        height=110,
        key="cb_deposits",
    )
    cb_fras = st.text_area(
        'FRAs (one per line: "SxE rate")',
        value=_DEFAULT_FRAS,
        height=90,
        key="cb_fras",
    )
    cb_swaps = st.text_area(
        'Swaps (one per line: "NY rate")',
        value=_DEFAULT_SWAPS,
        height=110,
        key="cb_swaps",
    )

    build_curve_btn = st.button("Build Curve", type="primary", key="build_curve_btn")

    if build_curve_btn:
        try:
            ci = build_curve_inputs_payload(
                cb_val_date, cb_freq, cb_day_count, cb_deposits, cb_fras, cb_swaps
            )
        except ValueError as exc:
            _show_error("Curve input parse error", str(exc))
        else:
            st.subheader("Curve Result")
            try:
                resp = call_build_curve(ci)
            except requests.exceptions.ConnectionError:
                _show_error(
                    "Backend unreachable",
                    f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                )
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    c1, c2 = st.columns(2)
                    c1.metric("Valuation date", data.get("valuation_date", "—"))
                    c2.metric("Pillars", data.get("n_pillars", len(data.get("pillar_dates", []))))

                    pillars = data.get("pillar_dates", [])
                    dfs = data.get("discount_factors", [])
                    if pillars:
                        st.markdown("**Pillar dates and discount factors:**")
                        rows = "".join(
                            f"| {d} | {f:.8f} |\n"
                            for d, f in zip(pillars, dfs)
                        )
                        st.markdown(
                            "| Date | Discount factor |\n"
                            "|---|---|\n" + rows
                        )
                    if data.get("warnings"):
                        for w in data["warnings"]:
                            st.warning(w)
                else:
                    _show_response_error("Curve build failed", resp)


# ===========================================================================
# PAGE: Risk Ladder
# ===========================================================================

elif page == "Risk Ladder":
    st.title("Risk Ladder")
    st.caption("Bucketed key-rate PV01 ladder for a ZAR vanilla IRS.")

    # A. Prompt
    prompt = st.text_area(
        label="Describe the trade:",
        value=_DEFAULT_PROMPT,
        height=80,
        key="ladder_prompt",
    )

    bucket_years_text = st.text_input(
        label="Bucket years (comma-separated positive integers)",
        value="1,2,3,5,7,10",
        key="bucket_years_text",
        help="Buckets beyond the curve domain return 0.0",
    )

    # B. Optional curve inputs
    val_date, freq, day_count, deposits_text, fras_text, swaps_text, use_curve_inputs = (
        _render_curve_inputs_expander("ladder")
    )

    run_ladder_btn = st.button("Run Ladder", type="primary", key="run_ladder_btn")

    # C. Ladder result
    if run_ladder_btn:
        if not prompt.strip():
            st.warning("Please enter a trade description before running the ladder.")
        else:
            try:
                _bucket_years = parse_bucket_years(bucket_years_text)
            except ValueError as exc:
                _show_error("Bucket years parse error", str(exc))
            else:
                _ci_for_ladder: dict | None = None
                if use_curve_inputs:
                    try:
                        _ci_for_ladder = build_curve_inputs_payload(
                            val_date, freq, day_count, deposits_text, fras_text, swaps_text
                        )
                    except ValueError as exc:
                        _show_error("Curve input parse error", str(exc))
                        st.stop()

                st.subheader("Ladder Result")
                try:
                    _qresp = call_quote(prompt.strip(), _ci_for_ladder)
                except requests.exceptions.ConnectionError:
                    _show_error(
                        "Backend unreachable",
                        f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                    )
                else:
                    if _qresp.status_code != 200:
                        _show_response_error("Prompt extraction failed (quote step)", _qresp)
                    else:
                        _qdata = _qresp.json()
                        _extracted = _qdata.get("extracted_fields", {})

                        try:
                            _lresp = call_ladder(_extracted, _ci_for_ladder, _bucket_years)
                        except requests.exceptions.ConnectionError:
                            _show_error(
                                "Backend unreachable",
                                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                            )
                        else:
                            if _lresp.status_code == 200:
                                _ldata = _lresp.json()

                                _lc1, _lc2, _lc3 = st.columns(3)
                                _lc1.metric("Status", _ldata.get("status", "—"))
                                _lc2.metric("Total |PV01|", f"{_ldata.get('total_abs_pv01', 0.0):,.2f}")
                                _lc3.metric("Request ID", _ldata.get("request_id", "—"))

                                _bp = _ldata.get("bucket_pv01", {})
                                _total = _ldata.get("total_abs_pv01", 0.0)
                                if _bp:
                                    st.markdown("**Bucketed PV01 (signed, per +1 bp):**")
                                    _rows = "".join(
                                        f"| {k} | {v:,.2f} | "
                                        + (f"{abs(v) / _total * 100:.1f}%" if _total > 0 else "0.0%")
                                        + " |\n"
                                        for k, v in _bp.items()
                                    )
                                    st.markdown(
                                        "| Bucket | Signed PV01 | % of Total Abs PV01 |\n"
                                        "|---|---:|---:|\n" + _rows
                                    )

                                for _w in _ldata.get("warnings", []):
                                    st.warning(_w)

                                _lassumptions = _ldata.get("assumptions", [])
                                if _lassumptions:
                                    with st.expander("Ladder Assumptions", expanded=False):
                                        for _a in _lassumptions:
                                            st.markdown(f"- {_a}")
                            else:
                                _show_response_error("Ladder request failed", _lresp)


# ===========================================================================
# PAGE: Scenario Analysis
# ===========================================================================

elif page == "Scenario Analysis":
    st.title("Scenario Analysis")
    st.caption("Parallel curve-shift NPV table for a ZAR vanilla IRS.")

    # A. Prompt
    prompt = st.text_area(
        label="Describe the trade:",
        value=_DEFAULT_PROMPT,
        height=80,
        key="scenario_prompt",
    )

    shifts_text = st.text_input(
        label="Scenario shifts (bps, comma-separated integers)",
        value="-200,-100,-50,0,50,100,200",
        key="shifts_text",
        help="Negative = rate fall.  Zero = base NPV.",
    )

    # B. Optional curve inputs
    val_date, freq, day_count, deposits_text, fras_text, swaps_text, use_curve_inputs = (
        _render_curve_inputs_expander("scenario")
    )

    run_scenario_btn = st.button("Run Scenarios", type="primary", key="run_scenario_btn")

    # C. Scenario result
    if run_scenario_btn:
        if not prompt.strip():
            st.warning("Please enter a trade description before running scenarios.")
        else:
            try:
                _shift_bps = parse_shift_bps(shifts_text)
            except ValueError as exc:
                _show_error("Scenario shifts parse error", str(exc))
            else:
                _ci_for_scenario: dict | None = None
                if use_curve_inputs:
                    try:
                        _ci_for_scenario = build_curve_inputs_payload(
                            val_date, freq, day_count, deposits_text, fras_text, swaps_text
                        )
                    except ValueError as exc:
                        _show_error("Curve input parse error", str(exc))
                        st.stop()

                st.subheader("Scenario Result")
                try:
                    _qresp_s = call_quote(prompt.strip(), _ci_for_scenario)
                except requests.exceptions.ConnectionError:
                    _show_error(
                        "Backend unreachable",
                        f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                    )
                else:
                    if _qresp_s.status_code != 200:
                        _show_response_error("Prompt extraction failed (quote step)", _qresp_s)
                    else:
                        _qdata_s = _qresp_s.json()
                        _extracted_s = _qdata_s.get("extracted_fields", {})

                        try:
                            _sresp = call_scenario(_extracted_s, _ci_for_scenario, _shift_bps)
                        except requests.exceptions.ConnectionError:
                            _show_error(
                                "Backend unreachable",
                                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
                            )
                        else:
                            if _sresp.status_code == 200:
                                _sdata = _sresp.json()

                                _sc1, _sc2, _sc3 = st.columns(3)
                                _sc1.metric("Status", _sdata.get("status", "—"))
                                _sc2.metric("Base NPV", f"{_sdata.get('base_npv', 0.0):,.2f}")
                                _sc3.metric("Request ID", _sdata.get("request_id", "—"))

                                _snpv = _sdata.get("scenario_npv", {})
                                _base = _sdata.get("base_npv", 0.0)
                                if _snpv:
                                    st.markdown("**Scenario NPV (parallel curve shift):**")
                                    _srows = "".join(
                                        f"| {k} | {v:,.2f} | {v - _base:+,.2f} |\n"
                                        for k, v in _snpv.items()
                                    )
                                    st.markdown(
                                        "| Shift | NPV | Change vs Base |\n"
                                        "|---|---:|---:|\n" + _srows
                                    )

                                for _w in _sdata.get("warnings", []):
                                    st.warning(_w)

                                _sassumptions = _sdata.get("assumptions", [])
                                if _sassumptions:
                                    with st.expander("Scenario Assumptions", expanded=False):
                                        for _a in _sassumptions:
                                            st.markdown(f"- {_a}")
                            else:
                                _show_response_error("Scenario request failed", _sresp)


# ===========================================================================
# PAGE: FRA Pricing
# ===========================================================================

elif page == "FRA Pricing":
    st.title("FRA Pricing")
    st.caption("Deterministic forward rate agreement pricing.")

    _frac1, _frac2 = st.columns(2)
    with _frac1:
        _fra_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="fra_val_date",
        )
        _fra_start_date = st.text_input(
            "Start date (YYYY-MM-DD)",
            value="2024-07-01",
            key="fra_start_date",
        )
        _fra_end_date = st.text_input(
            "End date (YYYY-MM-DD)",
            value="2025-01-01",
            key="fra_end_date",
        )
        _fra_notional = st.number_input(
            "Notional",
            min_value=1.0,
            value=1_000_000.0,
            step=100_000.0,
            format="%0.2f",
            key="fra_notional",
        )
    with _frac2:
        _fra_contract_rate = st.number_input(
            "Contract rate (decimal, e.g. 0.0810)",
            min_value=0.0,
            max_value=0.9999,
            value=0.08,
            step=0.0005,
            format="%0.4f",
            key="fra_contract_rate",
        )
        _fra_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="fra_day_count",
        )
        _fra_position = st.selectbox(
            "Position",
            options=["payer", "receiver"],
            index=0,
            key="fra_position",
            help="payer = pay fixed / receive floating; receiver = receive fixed / pay floating.",
        )

    _fra_curve_val, _fra_curve_freq, _fra_curve_day_count, _fra_dep_text, _fra_fra_text, _fra_swap_text, _fra_use_curve = _render_curve_inputs_expander("fra_curve")

    def _fra_curve_inputs() -> dict | None:
        if not _fra_use_curve:
            return None
        try:
            return build_curve_inputs_payload(
                _fra_curve_val,
                _fra_curve_freq,
                _fra_curve_day_count,
                _fra_dep_text,
                _fra_fra_text,
                _fra_swap_text,
            )
        except ValueError as exc:
            _show_error("Curve input parse error", str(exc))
            st.stop()

    _fra_price_btn = st.button(
        "Price FRA",
        type="primary",
        key="price_fra_btn",
        use_container_width=True,
    )

    if _fra_price_btn:
        _fra_ci = _fra_curve_inputs()
        st.subheader("FRA Pricing Result")
        try:
            _fra_resp = call_fra(
                valuation_date=_fra_val_date.strip(),
                start_date=_fra_start_date.strip(),
                end_date=_fra_end_date.strip(),
                notional=float(_fra_notional),
                contract_rate=float(_fra_contract_rate),
                day_count=_fra_day_count,
                position=_fra_position,
                curve_inputs=_fra_ci,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _fra_resp.status_code == 200:
                _fra_data = _fra_resp.json()
                _frc1, _frc2, _frc3 = st.columns(3)
                _frc1.metric("Status", _fra_data.get("status", "—"))
                _frc2.metric("Forward Rate", f"{_fra_data.get('forward_rate', 0.0) * 100:.4f}%")
                _frc3.metric("PV", f"{_fra_data.get('pv', 0.0):,.2f}")

                _frc4, _frc5, _frc6 = st.columns(3)
                _frc4.metric("Year Fraction", f"{_fra_data.get('year_fraction', 0.0):.6f}")
                _frc5.metric(
                    "Discount Factor to Payment",
                    f"{_fra_data.get('discount_factor_to_payment', 0.0):.6f}",
                )
                _frc6.metric(
                    "Payoff Undiscounted",
                    f"{_fra_data.get('payoff_undiscounted', 0.0):,.2f}",
                )

                _frc7, _frc8 = st.columns(2)
                _frc7.metric("Curve Source", _fra_data.get("curve_source", "—"))
                _frc8.metric("Request ID", _fra_data.get("request_id", "—"))

                for _fra_warning in _fra_data.get("warnings", []):
                    st.warning(_fra_warning)

                _fra_assumptions = _fra_data.get("assumptions", [])
                if _fra_assumptions:
                    with st.expander("FRA Assumptions", expanded=False):
                        for _fra_assumption in _fra_assumptions:
                            st.markdown(f"- {_fra_assumption}")
            else:
                _show_response_error("FRA pricing failed", _fra_resp)


# ===========================================================================
# PAGE: FX Forward Pricing
# ===========================================================================

elif page == "FX Forward Pricing":
    st.title("FX Forward Pricing")
    st.caption(
        "Deterministic FX forward pricing from spot and flat simple domestic/foreign rates."
    )

    _fxc1, _fxc2 = st.columns(2)
    with _fxc1:
        _fx_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="fxfwd_val_date",
        )
        _fx_maturity_date = st.text_input(
            "Maturity date (YYYY-MM-DD)",
            value="2024-07-01",
            key="fxfwd_maturity_date",
        )
        _fx_notional_foreign = st.number_input(
            "Foreign notional",
            min_value=1.0,
            value=1_000_000.0,
            step=100_000.0,
            format="%0.2f",
            key="fxfwd_notional_foreign",
        )
        _fx_spot_rate = st.number_input(
            "Spot rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.25,
            step=0.0001,
            format="%0.4f",
            key="fxfwd_spot_rate",
        )
        _fx_contract_forward_rate = st.number_input(
            "Contract forward rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.60,
            step=0.0001,
            format="%0.4f",
            key="fxfwd_contract_forward_rate",
        )
    with _fxc2:
        _fx_domestic_rate = st.number_input(
            "Domestic rate (decimal)",
            value=0.08,
            step=0.0005,
            format="%0.4f",
            key="fxfwd_domestic_rate",
        )
        _fx_foreign_rate = st.number_input(
            "Foreign rate (decimal)",
            value=0.05,
            step=0.0005,
            format="%0.4f",
            key="fxfwd_foreign_rate",
        )
        _fx_domestic_currency = st.text_input(
            "Domestic currency",
            value="ZAR",
            key="fxfwd_domestic_currency",
        )
        _fx_foreign_currency = st.text_input(
            "Foreign currency",
            value="USD",
            key="fxfwd_foreign_currency",
        )
        _fx_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="fxfwd_day_count",
        )
        _fx_position = st.selectbox(
            "Position",
            options=["long_foreign", "short_foreign"],
            index=0,
            key="fxfwd_position",
            help="long_foreign = buy foreign / sell domestic at maturity; short_foreign = opposite.",
        )

    st.caption(
        "Convention: rates are quoted as domestic-currency units per 1 unit of foreign currency."
    )

    _fx_price_btn = st.button(
        "Price FX Forward",
        type="primary",
        key="price_fxfwd_btn",
        use_container_width=True,
    )

    if _fx_price_btn:
        st.subheader("FX Forward Pricing Result")
        try:
            _fx_resp = call_fx_forward(
                valuation_date=_fx_val_date.strip(),
                maturity_date=_fx_maturity_date.strip(),
                notional_foreign=float(_fx_notional_foreign),
                spot_rate=float(_fx_spot_rate),
                contract_forward_rate=float(_fx_contract_forward_rate),
                domestic_rate=float(_fx_domestic_rate),
                foreign_rate=float(_fx_foreign_rate),
                domestic_currency=_fx_domestic_currency.strip().upper(),
                foreign_currency=_fx_foreign_currency.strip().upper(),
                day_count=_fx_day_count,
                position=_fx_position,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _fx_resp.status_code == 200:
                _fx_data = _fx_resp.json()

                _fxm1, _fxm2, _fxm3 = st.columns(3)
                _fxm1.metric("Status", _fx_data.get("status", "—"))
                _fxm2.metric(
                    "Implied Forward",
                    f"{_fx_data.get('implied_forward_rate', 0.0):.4f}",
                )
                _fxm3.metric(
                    f"PV ({_fx_data.get('pv_currency', _fx_domestic_currency.strip().upper())})",
                    f"{_fx_data.get('present_value_domestic', 0.0):,.2f}",
                )

                _fxm4, _fxm5, _fxm6 = st.columns(3)
                _fxm4.metric("Year Fraction", f"{_fx_data.get('year_fraction', 0.0):.6f}")
                _fxm5.metric(
                    "Domestic Discount Factor",
                    f"{_fx_data.get('domestic_discount_factor', 0.0):.6f}",
                )
                _fxm6.metric(
                    "Foreign Discount Factor",
                    f"{_fx_data.get('foreign_discount_factor', 0.0):.6f}",
                )

                _fxm7, _fxm8, _fxm9 = st.columns(3)
                _fxm7.metric(
                    "Forward Points",
                    f"{_fx_data.get('forward_points', 0.0):.4f}",
                )
                _fxm8.metric(
                    "Payoff Undiscounted",
                    f"{_fx_data.get('payoff_undiscounted_domestic', 0.0):,.2f}",
                )
                _fxm9.metric("Rate Source", _fx_data.get("rate_source", "—"))

                _fxm10, _fxm11, _fxm12 = st.columns(3)
                _fxm10.metric(
                    "Domestic Currency",
                    _fx_data.get("domestic_currency", "—"),
                )
                _fxm11.metric(
                    "Foreign Currency",
                    _fx_data.get("foreign_currency", "—"),
                )
                _fxm12.metric("Request ID", _fx_data.get("request_id", "—"))

                for _fx_warning in _fx_data.get("warnings", []):
                    st.warning(_fx_warning)

                _fx_assumptions = _fx_data.get("assumptions", [])
                if _fx_assumptions:
                    with st.expander("FX Forward Assumptions", expanded=False):
                        for _fx_assumption in _fx_assumptions:
                            st.markdown(f"- {_fx_assumption}")
            else:
                _show_response_error("FX forward pricing failed", _fx_resp)


# ===========================================================================
# PAGE: FX Swap Pricing
# ===========================================================================

elif page == "FX Swap Pricing":
    st.title("FX Swap Pricing")
    st.caption(
        "Deterministic deliverable FX swap pricing from near/far exchange rates and flat domestic discounting."
    )

    _fxs1, _fxs2 = st.columns(2)
    with _fxs1:
        _fxs_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="fxswap_val_date",
        )
        _fxs_near_date = st.text_input(
            "Near settlement date (YYYY-MM-DD)",
            value="2024-01-03",
            key="fxswap_near_date",
        )
        _fxs_far_date = st.text_input(
            "Far settlement date (YYYY-MM-DD)",
            value="2024-07-01",
            key="fxswap_far_date",
        )
        _fxs_notional_foreign = st.number_input(
            "Foreign notional",
            min_value=1.0,
            value=1_000_000.0,
            step=100_000.0,
            format="%0.2f",
            key="fxswap_notional_foreign",
        )
        _fxs_spot_rate = st.number_input(
            "Spot rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.25,
            step=0.0001,
            format="%0.4f",
            key="fxswap_spot_rate",
        )
    with _fxs2:
        _fxs_near_rate = st.number_input(
            "Near rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.27,
            step=0.0001,
            format="%0.4f",
            key="fxswap_near_rate",
        )
        _fxs_far_rate = st.number_input(
            "Far rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.65,
            step=0.0001,
            format="%0.4f",
            key="fxswap_far_rate",
        )
        _fxs_domestic_rate = st.number_input(
            "Domestic discount rate (decimal)",
            value=0.08,
            step=0.0005,
            format="%0.4f",
            key="fxswap_domestic_rate",
        )
        _fxs_domestic_currency = st.text_input(
            "Domestic currency",
            value="ZAR",
            key="fxswap_domestic_currency",
        )
        _fxs_foreign_currency = st.text_input(
            "Foreign currency",
            value="USD",
            key="fxswap_foreign_currency",
        )
        _fxs_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="fxswap_day_count",
        )
        _fxs_position = st.selectbox(
            "Position",
            options=["long_foreign", "short_foreign"],
            index=0,
            key="fxswap_position",
            help="long_foreign = receive foreign / pay domestic on the near leg, then reverse on the far leg; short_foreign = opposite.",
        )

    st.caption(
        "Convention: rates are quoted as domestic-currency units per 1 unit of foreign currency."
    )

    _fxs_price_btn = st.button(
        "Price FX Swap",
        type="primary",
        key="price_fxswap_btn",
        use_container_width=True,
    )

    if _fxs_price_btn:
        st.subheader("FX Swap Pricing Result")
        try:
            _fxs_resp = call_fx_swap(
                valuation_date=_fxs_val_date.strip(),
                near_settlement_date=_fxs_near_date.strip(),
                far_settlement_date=_fxs_far_date.strip(),
                spot_rate=float(_fxs_spot_rate),
                near_rate=float(_fxs_near_rate),
                far_rate=float(_fxs_far_rate),
                notional_foreign=float(_fxs_notional_foreign),
                domestic_currency=_fxs_domestic_currency.strip().upper(),
                foreign_currency=_fxs_foreign_currency.strip().upper(),
                domestic_rate=float(_fxs_domestic_rate),
                day_count=_fxs_day_count,
                position=_fxs_position,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _fxs_resp.status_code == 200:
                _fxs_data = _fxs_resp.json()

                _fxs_m1, _fxs_m2, _fxs_m3 = st.columns(3)
                _fxs_m1.metric("Status", _fxs_data.get("status", "-"))
                _fxs_m2.metric("Swap Points", f"{_fxs_data.get('swap_points', 0.0):.4f}")
                _fxs_m3.metric(
                    f"PV ({_fxs_data.get('pv_currency', _fxs_domestic_currency.strip().upper())})",
                    f"{_fxs_data.get('present_value_domestic', 0.0):,.2f}",
                )

                _fxs_m4, _fxs_m5, _fxs_m6 = st.columns(3)
                _fxs_m4.metric("Near Year Fraction", f"{_fxs_data.get('year_fraction_near', 0.0):.6f}")
                _fxs_m5.metric("Far Year Fraction", f"{_fxs_data.get('year_fraction_far', 0.0):.6f}")
                _fxs_m6.metric("Rate Source", _fxs_data.get("rate_source", "-"))

                _fxs_m7, _fxs_m8 = st.columns(2)
                _fxs_m7.metric(
                    "Near Domestic Discount Factor",
                    f"{_fxs_data.get('domestic_discount_factor_near', 0.0):.6f}",
                )
                _fxs_m8.metric(
                    "Far Domestic Discount Factor",
                    f"{_fxs_data.get('domestic_discount_factor_far', 0.0):.6f}",
                )

                _fxs_m9, _fxs_m10 = st.columns(2)
                _fxs_m9.metric(
                    "Near Leg Value Domestic",
                    f"{_fxs_data.get('near_leg_value_domestic', 0.0):,.2f}",
                )
                _fxs_m10.metric(
                    "Far Leg Value Domestic",
                    f"{_fxs_data.get('far_leg_value_domestic', 0.0):,.2f}",
                )

                _fxs_m11, _fxs_m12 = st.columns(2)
                _fxs_m11.metric("Domestic Currency", _fxs_data.get("domestic_currency", "-"))
                _fxs_m12.metric("Foreign Currency", _fxs_data.get("foreign_currency", "-"))

                for _fxs_warning in _fxs_data.get("warnings", []):
                    st.warning(_fxs_warning)

                _fxs_assumptions = _fxs_data.get("assumptions", [])
                if _fxs_assumptions:
                    with st.expander("FX Swap Assumptions", expanded=False):
                        for _fxs_assumption in _fxs_assumptions:
                            st.markdown(f"- {_fxs_assumption}")
            else:
                _show_response_error("FX swap pricing failed", _fxs_resp)


# ===========================================================================
# PAGE: European FX Option
# ===========================================================================

elif page == "European FX Option":
    st.title("European FX Option")
    st.caption(
        "Vanilla European deliverable FX option pricing under Garman-Kohlhagen with flat domestic and foreign rates."
    )

    _fxo1, _fxo2 = st.columns(2)
    with _fxo1:
        _fxo_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="fxopt_val_date",
        )
        _fxo_expiry_date = st.text_input(
            "Expiry date (YYYY-MM-DD)",
            value="2024-07-01",
            key="fxopt_expiry_date",
        )
        _fxo_settlement_date = st.text_input(
            "Settlement date (YYYY-MM-DD, optional)",
            value="2024-07-01",
            key="fxopt_settlement_date",
        )
        _fxo_notional_foreign = st.number_input(
            "Foreign notional",
            min_value=1.0,
            value=1_000_000.0,
            step=100_000.0,
            format="%0.2f",
            key="fxopt_notional_foreign",
        )
        _fxo_spot_rate = st.number_input(
            "Spot rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.25,
            step=0.0001,
            format="%0.4f",
            key="fxopt_spot_rate",
        )
        _fxo_strike_rate = st.number_input(
            "Strike rate (domestic per 1 foreign)",
            min_value=0.0001,
            value=18.40,
            step=0.0001,
            format="%0.4f",
            key="fxopt_strike_rate",
        )
    with _fxo2:
        _fxo_domestic_rate = st.number_input(
            "Domestic rate (decimal)",
            value=0.08,
            step=0.0005,
            format="%0.4f",
            key="fxopt_domestic_rate",
        )
        _fxo_foreign_rate = st.number_input(
            "Foreign rate (decimal)",
            value=0.05,
            step=0.0005,
            format="%0.4f",
            key="fxopt_foreign_rate",
        )
        _fxo_volatility = st.number_input(
            "Volatility (decimal)",
            min_value=0.0001,
            value=0.18,
            step=0.005,
            format="%0.4f",
            key="fxopt_volatility",
        )
        _fxo_domestic_currency = st.text_input(
            "Domestic currency",
            value="ZAR",
            key="fxopt_domestic_currency",
        )
        _fxo_foreign_currency = st.text_input(
            "Foreign currency",
            value="USD",
            key="fxopt_foreign_currency",
        )
        _fxo_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="fxopt_day_count",
        )
        _fxo_option_type = st.selectbox(
            "Option type",
            options=["call", "put"],
            index=0,
            key="fxopt_option_type",
            help="call = right to buy foreign / sell domestic at the strike; put = opposite.",
        )
        _fxo_position = st.selectbox(
            "Position",
            options=["long", "short"],
            index=0,
            key="fxopt_position",
            help="long = own the option; short = written option with opposite premium and Greeks.",
        )

    st.caption(
        "Convention: rates are quoted as domestic-currency units per 1 unit of foreign currency. If settlement date is cleared, the backend defaults it to expiry date."
    )

    _fxo_price_btn = st.button(
        "Price European FX Option",
        type="primary",
        key="price_fxoption_btn",
        use_container_width=True,
    )

    if _fxo_price_btn:
        st.subheader("European FX Option Result")
        try:
            _fxo_resp = call_fx_option(
                valuation_date=_fxo_val_date.strip(),
                expiry_date=_fxo_expiry_date.strip(),
                settlement_date=_fxo_settlement_date.strip() or None,
                spot_rate=float(_fxo_spot_rate),
                strike_rate=float(_fxo_strike_rate),
                domestic_rate=float(_fxo_domestic_rate),
                foreign_rate=float(_fxo_foreign_rate),
                volatility=float(_fxo_volatility),
                notional_foreign=float(_fxo_notional_foreign),
                option_type=_fxo_option_type,
                position=_fxo_position,
                domestic_currency=_fxo_domestic_currency.strip().upper(),
                foreign_currency=_fxo_foreign_currency.strip().upper(),
                day_count=_fxo_day_count,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _fxo_resp.status_code == 200:
                _fxo_data = _fxo_resp.json()

                _fxo_m1, _fxo_m2, _fxo_m3 = st.columns(3)
                _fxo_m1.metric("Status", _fxo_data.get("status", "-"))
                _fxo_m2.metric(
                    f"Premium ({_fxo_data.get('pv_currency', _fxo_domestic_currency.strip().upper())})",
                    f"{_fxo_data.get('premium_domestic', 0.0):,.2f}",
                )
                _fxo_m3.metric(
                    "Premium (Foreign)",
                    f"{_fxo_data.get('premium_foreign', 0.0):,.4f}",
                )

                _fxo_m4, _fxo_m5, _fxo_m6 = st.columns(3)
                _fxo_m4.metric("Delta", f"{_fxo_data.get('delta', 0.0):,.4f}")
                _fxo_m5.metric("Gamma", f"{_fxo_data.get('gamma', 0.0):,.6f}")
                _fxo_m6.metric("Vega", f"{_fxo_data.get('vega', 0.0):,.2f}")

                _fxo_m7, _fxo_m8, _fxo_m9 = st.columns(3)
                _fxo_m7.metric("Expiry Year Fraction", f"{_fxo_data.get('year_fraction', 0.0):.6f}")
                _fxo_m8.metric(
                    "Settlement Year Fraction",
                    f"{_fxo_data.get('settlement_year_fraction', 0.0):.6f}",
                )
                _fxo_m9.metric("Forward Rate", f"{_fxo_data.get('forward_rate', 0.0):.4f}")

                _fxo_m10, _fxo_m11, _fxo_m12 = st.columns(3)
                _fxo_m10.metric(
                    "Domestic Discount Factor",
                    f"{_fxo_data.get('domestic_discount_factor', 0.0):.6f}",
                )
                _fxo_m11.metric(
                    "Foreign Discount Factor",
                    f"{_fxo_data.get('foreign_discount_factor', 0.0):.6f}",
                )
                _fxo_m12.metric("Model Source", _fxo_data.get("model_source", "-"))

                _fxo_m13, _fxo_m14, _fxo_m15 = st.columns(3)
                _fxo_m13.metric("Domestic Currency", _fxo_data.get("domestic_currency", "-"))
                _fxo_m14.metric("Foreign Currency", _fxo_data.get("foreign_currency", "-"))
                _fxo_m15.metric("Request ID", _fxo_data.get("request_id", "-"))

                for _fxo_warning in _fxo_data.get("warnings", []):
                    st.warning(_fxo_warning)

                _fxo_assumptions = _fxo_data.get("assumptions", [])
                if _fxo_assumptions:
                    with st.expander("European FX Option Assumptions", expanded=False):
                        for _fxo_assumption in _fxo_assumptions:
                            st.markdown(f"- {_fxo_assumption}")
            else:
                _show_response_error("European FX option pricing failed", _fxo_resp)


# ===========================================================================
# PAGE: European Equity Option
# ===========================================================================

elif page == "European Equity Option":
    st.title("European Equity Option")
    st.caption(
        "Vanilla European equity option pricing under Black-Scholes-Merton with a flat risk-free rate and continuous dividend yield."
    )

    _eqo1, _eqo2 = st.columns(2)
    with _eqo1:
        _eqo_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="eqopt_val_date",
        )
        _eqo_expiry_date = st.text_input(
            "Expiry date (YYYY-MM-DD)",
            value="2024-07-01",
            key="eqopt_expiry_date",
        )
        _eqo_underlying_name = st.text_input(
            "Underlying name or ticker (optional)",
            value="ACME",
            key="eqopt_underlying_name",
        )
        _eqo_quantity_shares = st.number_input(
            "Quantity (shares)",
            min_value=1.0,
            value=1_000.0,
            step=100.0,
            format="%0.2f",
            key="eqopt_quantity_shares",
        )
        _eqo_spot_price = st.number_input(
            "Spot price",
            min_value=0.0001,
            value=100.0,
            step=0.01,
            format="%0.4f",
            key="eqopt_spot_price",
        )
        _eqo_strike_price = st.number_input(
            "Strike price",
            min_value=0.0001,
            value=105.0,
            step=0.01,
            format="%0.4f",
            key="eqopt_strike_price",
        )
    with _eqo2:
        _eqo_risk_free_rate = st.number_input(
            "Risk-free rate (decimal)",
            value=0.05,
            step=0.0005,
            format="%0.4f",
            key="eqopt_risk_free_rate",
        )
        _eqo_dividend_yield = st.number_input(
            "Dividend yield (decimal)",
            value=0.02,
            step=0.0005,
            format="%0.4f",
            key="eqopt_dividend_yield",
        )
        _eqo_volatility = st.number_input(
            "Volatility (decimal)",
            min_value=0.0001,
            value=0.25,
            step=0.005,
            format="%0.4f",
            key="eqopt_volatility",
        )
        _eqo_currency = st.text_input(
            "Pricing currency",
            value="USD",
            key="eqopt_currency",
        )
        _eqo_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="eqopt_day_count",
        )
        _eqo_option_type = st.selectbox(
            "Option type",
            options=["call", "put"],
            index=0,
            key="eqopt_option_type",
            help="call = right to buy the underlying at strike on expiry; put = right to sell.",
        )
        _eqo_position = st.selectbox(
            "Position",
            options=["long", "short"],
            index=0,
            key="eqopt_position",
            help="long = own the option; short = written option with opposite premium and Greeks.",
        )

    st.caption(
        "Convention: enter quantity in underlying shares. The backend request field is quantity_shares. Premium and Greeks are scaled by quantity_shares and reported in the selected pricing currency."
    )

    _eqo_price_btn = st.button(
        "Price European Equity Option",
        type="primary",
        key="price_eqoption_btn",
        use_container_width=True,
    )

    if _eqo_price_btn:
        st.subheader("European Equity Option Result")
        try:
            _eqo_resp = call_equity_option(
                valuation_date=_eqo_val_date.strip(),
                expiry_date=_eqo_expiry_date.strip(),
                spot_price=float(_eqo_spot_price),
                strike_price=float(_eqo_strike_price),
                risk_free_rate=float(_eqo_risk_free_rate),
                dividend_yield=float(_eqo_dividend_yield),
                volatility=float(_eqo_volatility),
                quantity_shares=float(_eqo_quantity_shares),
                option_type=_eqo_option_type,
                position=_eqo_position,
                currency=_eqo_currency.strip().upper(),
                day_count=_eqo_day_count,
                underlying_name=_eqo_underlying_name.strip() or None,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _eqo_resp.status_code == 200:
                _eqo_data = _eqo_resp.json()

                _eqo_m1, _eqo_m2, _eqo_m3 = st.columns(3)
                _eqo_m1.metric("Status", _eqo_data.get("status", "-"))
                _eqo_m2.metric(
                    f"Premium ({_eqo_data.get('pv_currency', _eqo_currency.strip().upper())})",
                    f"{_eqo_data.get('premium', 0.0):,.2f}",
                )
                _eqo_m3.metric("Delta", f"{_eqo_data.get('delta', 0.0):,.4f}")

                _eqo_m4, _eqo_m5, _eqo_m6 = st.columns(3)
                _eqo_m4.metric("Gamma", f"{_eqo_data.get('gamma', 0.0):,.6f}")
                _eqo_m5.metric("Vega", f"{_eqo_data.get('vega', 0.0):,.2f}")
                _eqo_m6.metric("Year Fraction", f"{_eqo_data.get('year_fraction', 0.0):.6f}")

                _eqo_m7, _eqo_m8, _eqo_m9 = st.columns(3)
                _eqo_m7.metric("Forward Price", f"{_eqo_data.get('forward_price', 0.0):,.4f}")
                _eqo_m8.metric(
                    "Risk-Free Discount Factor",
                    f"{_eqo_data.get('discount_factor', 0.0):.6f}",
                )
                _eqo_m9.metric(
                    "Dividend Discount Factor",
                    f"{_eqo_data.get('dividend_discount_factor', 0.0):.6f}",
                )

                _eqo_m10, _eqo_m11, _eqo_m12 = st.columns(3)
                _eqo_m10.metric("Currency", _eqo_data.get("currency", "-"))
                _eqo_m11.metric("Model Source", _eqo_data.get("model_source", "-"))
                _eqo_m12.metric("Request ID", _eqo_data.get("request_id", "-"))

                _eqo_underlying_display = _eqo_data.get("underlying_name") or "-"
                st.metric("Underlying", _eqo_underlying_display)

                for _eqo_warning in _eqo_data.get("warnings", []):
                    st.warning(_eqo_warning)

                _eqo_assumptions = _eqo_data.get("assumptions", [])
                if _eqo_assumptions:
                    with st.expander("European Equity Option Assumptions", expanded=False):
                        for _eqo_assumption in _eqo_assumptions:
                            st.markdown(f"- {_eqo_assumption}")
            else:
                _show_response_error("European equity option pricing failed", _eqo_resp)


# ===========================================================================
# PAGE: Bond Pricing  (pricing + risk on one page, shared inputs)
# ===========================================================================

elif page == "Bond Pricing":
    st.title("Bond Pricing")
    st.caption("DCF pricing and DV01 / modified duration for a fixed-rate bond.")

    # -----------------------------------------------------------------------
    # Bond input fields
    # -----------------------------------------------------------------------
    _bcol1, _bcol2 = st.columns(2)
    with _bcol1:
        _bond_val_date = st.text_input(
            "Valuation date (YYYY-MM-DD)",
            value="2024-01-01",
            key="bond_val_date",
        )
        _bond_issue_date = st.text_input(
            "Issue date (YYYY-MM-DD)",
            value="2024-01-01",
            key="bond_issue_date",
        )
        _bond_maturity_date = st.text_input(
            "Maturity date (YYYY-MM-DD)",
            value="2029-01-01",
            key="bond_maturity_date",
        )
        _bond_face_value = st.number_input(
            "Face value",
            min_value=1.0,
            value=1_000_000.0,
            step=100_000.0,
            format="%0.2f",
            key="bond_face_value",
        )
    with _bcol2:
        _bond_coupon_rate = st.number_input(
            "Coupon rate (decimal, e.g. 0.085 for 8.5%)",
            min_value=0.0,
            max_value=0.9999,
            value=0.085,
            step=0.001,
            format="%0.4f",
            key="bond_coupon_rate",
        )
        _bond_coupon_freq = st.selectbox(
            "Coupon frequency",
            options=["annual", "semiannual", "quarterly"],
            index=0,
            key="bond_coupon_freq",
        )
        _bond_day_count = st.selectbox(
            "Day count",
            options=["ACT_365F", "ACT_360", "30_360", "ACT_ACT_ISDA"],
            index=0,
            key="bond_day_count",
        )

    _bond_market_dirty_price = st.number_input(
        "Market Dirty Price  (used by Solve YTM)",
        min_value=0.01,
        value=1_000_000.0,
        step=10_000.0,
        format="%0.2f",
        key="bond_market_dirty_price",
        help="Observed full (dirty) market price. Used only by the Solve YTM button.",
    )

    # Optional bootstrapped curve (shared for Price Bond, Run Bond Risk, and Solve YTM)
    val_date, freq, day_count, deposits_text, fras_text, swaps_text, _bond_use_curve = (
        _render_curve_inputs_expander("bond_curve")
    )

    # -----------------------------------------------------------------------
    # Action buttons (side by side)
    # -----------------------------------------------------------------------
    _bbtn1, _bbtn2, _bbtn3, _bbtn4 = st.columns(4)
    with _bbtn1:
        price_bond_btn = st.button("Price Bond", type="primary", key="price_bond_btn", use_container_width=True)
    with _bbtn2:
        run_bond_risk_btn = st.button("Run Bond Risk", type="secondary", key="run_bond_risk_btn", use_container_width=True)
    with _bbtn3:
        solve_ytm_btn = st.button("Solve YTM", type="secondary", key="solve_ytm_btn", use_container_width=True)
    with _bbtn4:
        show_cashflows_btn = st.button("Show Cashflows", type="secondary", key="show_cashflows_btn", use_container_width=True)

    # -----------------------------------------------------------------------
    # Helper: build optional curve inputs for bond page
    # -----------------------------------------------------------------------
    def _bond_curve_inputs() -> dict | None:
        if not _bond_use_curve:
            return None
        try:
            return build_curve_inputs_payload(
                val_date, freq, day_count, deposits_text, fras_text, swaps_text
            )
        except ValueError as exc:
            _show_error("Curve input parse error", str(exc))
            st.stop()

    # -----------------------------------------------------------------------
    # H. Bond Pricing result
    # -----------------------------------------------------------------------
    if price_bond_btn:
        _bci = _bond_curve_inputs()
        st.subheader("Bond Pricing Result")
        try:
            _bresp = call_bond(
                valuation_date=_bond_val_date.strip(),
                issue_date=_bond_issue_date.strip(),
                maturity_date=_bond_maturity_date.strip(),
                face_value=float(_bond_face_value),
                coupon_rate=float(_bond_coupon_rate),
                coupon_frequency=_bond_coupon_freq,
                day_count=_bond_day_count,
                curve_inputs=_bci,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _bresp.status_code == 200:
                _bdata = _bresp.json()

                _bc1, _bc2, _bc3, _bc4 = st.columns(4)
                _bc1.metric("Status", _bdata.get("status", "—"))
                _bc2.metric("Clean Price", f"{_bdata.get('clean_price', 0.0):,.2f}")
                _bc3.metric("Dirty Price", f"{_bdata.get('dirty_price', 0.0):,.2f}")
                _bc4.metric("Accrued Interest", f"{_bdata.get('accrued_interest', 0.0):,.2f}")

                _bc5, _bc6 = st.columns(2)
                _bc5.metric("Remaining Coupons", _bdata.get("n_remaining_coupons", "—"))
                _bc6.metric("Request ID", _bdata.get("request_id", "—"))

                for _bw in _bdata.get("warnings", []):
                    st.warning(_bw)

                _bassumptions = _bdata.get("assumptions", [])
                if _bassumptions:
                    with st.expander("Bond Pricing Assumptions", expanded=False):
                        for _ba in _bassumptions:
                            st.markdown(f"- {_ba}")
            else:
                _show_response_error("Bond pricing failed", _bresp)

    # -----------------------------------------------------------------------
    # I. Bond Risk result
    # -----------------------------------------------------------------------
    if run_bond_risk_btn:
        _brci = _bond_curve_inputs()
        st.subheader("Bond Risk Result")
        try:
            _brresp = call_bond_risk(
                valuation_date=_bond_val_date.strip(),
                issue_date=_bond_issue_date.strip(),
                maturity_date=_bond_maturity_date.strip(),
                face_value=float(_bond_face_value),
                coupon_rate=float(_bond_coupon_rate),
                coupon_frequency=_bond_coupon_freq,
                day_count=_bond_day_count,
                curve_inputs=_brci,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _brresp.status_code == 200:
                _brdata = _brresp.json()

                _brc1, _brc2, _brc3, _brc4 = st.columns(4)
                _brc1.metric("Status", _brdata.get("status", "—"))
                _brc2.metric("Dirty Price", f"{_brdata.get('dirty_price', 0.0):,.2f}")
                _brc3.metric("DV01", f"{_brdata.get('dv01', 0.0):,.4f}")
                _brc4.metric("Modified Duration", f"{_brdata.get('modified_duration', 0.0):.4f}")

                _brc5, _brc6, _brc7, _brc8 = st.columns(4)
                _brc5.metric("Macaulay Duration", f"{_brdata.get('macaulay_duration', 0.0):.4f}")
                _brc6.metric("Convexity", f"{_brdata.get('convexity', 0.0):.4f}")
                _brc7.metric("Request ID", _brdata.get("request_id", "—"))
                _brc8.metric("Instrument", _brdata.get("instrument_type", "—"))

                for _brw in _brdata.get("warnings", []):
                    st.warning(_brw)

                _brassumptions = _brdata.get("assumptions", [])
                if _brassumptions:
                    with st.expander("Bond Risk Assumptions", expanded=False):
                        for _bra in _brassumptions:
                            st.markdown(f"- {_bra}")
            else:
                _show_response_error("Bond risk failed", _brresp)

    # -----------------------------------------------------------------------
    # J. Bond YTM result
    # -----------------------------------------------------------------------
    if solve_ytm_btn:
        st.subheader("Bond YTM Result")
        try:
            _bytmresp = call_bond_ytm(
                valuation_date=_bond_val_date.strip(),
                issue_date=_bond_issue_date.strip(),
                maturity_date=_bond_maturity_date.strip(),
                face_value=float(_bond_face_value),
                coupon_rate=float(_bond_coupon_rate),
                coupon_frequency=_bond_coupon_freq,
                day_count=_bond_day_count,
                market_dirty_price=float(_bond_market_dirty_price),
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _bytmresp.status_code == 200:
                _bytmdata = _bytmresp.json()

                _ytmc1, _ytmc2, _ytmc3 = st.columns(3)
                _ytmc1.metric("Status", _bytmdata.get("status", "—"))
                _ytmc2.metric(
                    "Market Dirty Price",
                    f"{_bytmdata.get('market_dirty_price', 0.0):,.2f}",
                )
                _ytm_val = _bytmdata.get("ytm", float("nan"))
                _ytmc3.metric(
                    "YTM",
                    f"{_ytm_val * 100:.4f}%" if _ytm_val == _ytm_val else "—",
                )

                _ytm_rid = _bytmdata.get("request_id", "—")
                st.caption(f"Request ID: {_ytm_rid}")

                for _ytmw in _bytmdata.get("warnings", []):
                    st.warning(_ytmw)

                _ytmassumptions = _bytmdata.get("assumptions", [])
                if _ytmassumptions:
                    with st.expander("YTM Assumptions", expanded=False):
                        for _ytma in _ytmassumptions:
                            st.markdown(f"- {_ytma}")
            else:
                _show_response_error("Bond YTM solve failed", _bytmresp)

    # -----------------------------------------------------------------------
    # K. Bond Cashflow Schedule result
    # -----------------------------------------------------------------------
    if show_cashflows_btn:
        _cfci = _bond_curve_inputs()
        st.subheader("Bond Cashflow Schedule")
        try:
            _cfresp = call_bond_cashflows(
                valuation_date=_bond_val_date.strip(),
                issue_date=_bond_issue_date.strip(),
                maturity_date=_bond_maturity_date.strip(),
                face_value=float(_bond_face_value),
                coupon_rate=float(_bond_coupon_rate),
                coupon_frequency=_bond_coupon_freq,
                day_count=_bond_day_count,
                curve_inputs=_cfci,
            )
        except requests.exceptions.ConnectionError:
            _show_error(
                "Backend unreachable",
                f"Cannot connect to {BACKEND}. Is the FastAPI server running?",
            )
        else:
            if _cfresp.status_code == 200:
                _cfdata = _cfresp.json()

                _cfc1, _cfc2 = st.columns(2)
                _cfc1.metric("Dirty Price", f"{_cfdata.get('dirty_price', 0.0):,.2f}")
                _cfc2.metric("Remaining Coupons", _cfdata.get("n_remaining_coupons", "—"))

                _cfrows = _cfdata.get("cashflows", [])
                if _cfrows:
                    st.markdown("**Cashflow Schedule:**")
                    _cf_header = (
                        "| Payment Date | Accrual Start | Accrual End "
                        "| Year Frac | Coupon CF | Principal CF "
                        "| Total CF | DF | PV |\n"
                        "|---|---|---|---:|---:|---:|---:|---:|---:|\n"
                    )
                    _cf_rows_md = "".join(
                        f"| {r['payment_date']} "
                        f"| {r['accrual_start']} "
                        f"| {r['accrual_end']} "
                        f"| {r['year_fraction']:.4f} "
                        f"| {r['coupon_cashflow']:,.2f} "
                        f"| {r['principal_cashflow']:,.2f} "
                        f"| {r['total_cashflow']:,.2f} "
                        f"| {r['discount_factor']:.6f} "
                        f"| {r['pv_cashflow']:,.2f} |\n"
                        for r in _cfrows
                    )
                    st.markdown(_cf_header + _cf_rows_md)

                for _cfw in _cfdata.get("warnings", []):
                    st.warning(_cfw)

                _cfassumptions = _cfdata.get("assumptions", [])
                if _cfassumptions:
                    with st.expander("Cashflow Assumptions", expanded=False):
                        for _cfa in _cfassumptions:
                            st.markdown(f"- {_cfa}")
            else:
                _show_response_error("Bond cashflow schedule failed", _cfresp)
