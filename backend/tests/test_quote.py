from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Canonical prompt: fully-specified ZAR 5Y payer IRS — extraction ready,
# pricing indicative.
# ---------------------------------------------------------------------------
_CANONICAL_PROMPT = (
    "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"
)
_CANONICAL_PAYLOAD = {"prompt": _CANONICAL_PROMPT}

# Prompt missing direction and floating index — should need clarification.
_INCOMPLETE_PROMPT = "Price a 5Y ZAR swap, 250m notional, quarterly"
_INCOMPLETE_PAYLOAD = {"prompt": _INCOMPLETE_PROMPT}

# Fully-specified but unsupported currency/index combination.
_UNSUPPORTED_PROMPT = (
    "Price a 5Y USD payer swap, 250m notional, quarterly SOFR"
)
_UNSUPPORTED_PAYLOAD = {"prompt": _UNSUPPORTED_PROMPT}


# ---------------------------------------------------------------------------
# 1. Canonical prompt — HTTP 200
# ---------------------------------------------------------------------------


def test_quote_canonical_status_code() -> None:
    assert client.post("/quote", json=_CANONICAL_PAYLOAD).status_code == 200


# ---------------------------------------------------------------------------
# 2. Canonical prompt — extraction_status = "ready"
# ---------------------------------------------------------------------------


def test_quote_canonical_extraction_status_ready() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["extraction_status"] == "ready"


# ---------------------------------------------------------------------------
# 3. Canonical prompt — pricing_attempted = true
# ---------------------------------------------------------------------------


def test_quote_canonical_pricing_attempted() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["pricing_attempted"] is True


# ---------------------------------------------------------------------------
# 4. Canonical prompt — price_status = "indicative"
# ---------------------------------------------------------------------------


def test_quote_canonical_price_status_indicative() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["price_status"] == "indicative"


# ---------------------------------------------------------------------------
# 5. Canonical prompt — non-zero price and pv01
# ---------------------------------------------------------------------------


def test_quote_canonical_price_non_zero() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["price"] != 0.0


def test_quote_canonical_pv01_positive() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["pv01"] > 0.0


# ---------------------------------------------------------------------------
# 6. Incomplete prompt — extraction_status = "needs_clarification"
# ---------------------------------------------------------------------------


def test_quote_incomplete_extraction_status_needs_clarification() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["extraction_status"] == "needs_clarification"


# ---------------------------------------------------------------------------
# 7. Incomplete prompt — pricing_attempted = false
# ---------------------------------------------------------------------------


def test_quote_incomplete_pricing_not_attempted() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["pricing_attempted"] is False


# ---------------------------------------------------------------------------
# 8. Incomplete prompt — non-empty missing_fields
# ---------------------------------------------------------------------------


def test_quote_incomplete_missing_fields_non_empty() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert isinstance(data["missing_fields"], list)
    assert len(data["missing_fields"]) > 0


# ---------------------------------------------------------------------------
# ready path — missing_fields must always be empty (no misleading effective_date)
# ---------------------------------------------------------------------------


def test_quote_canonical_missing_fields_empty() -> None:
    # extraction_status="ready" + price_status="indicative" → missing_fields=[]
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["extraction_status"] == "ready"
    assert data["missing_fields"] == []


def test_quote_unsupported_missing_fields_empty() -> None:
    # extraction_status="ready" + price_status="unsupported" → missing_fields=[]
    data = client.post("/quote", json=_UNSUPPORTED_PAYLOAD).json()
    assert data["extraction_status"] == "ready"
    assert data["missing_fields"] == []


def test_quote_clarification_missing_fields_preserved() -> None:
    # needs_clarification path must still report the true missing fields
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["extraction_status"] == "needs_clarification"
    assert len(data["missing_fields"]) > 0


# ---------------------------------------------------------------------------
# 9. Unsupported prompt — pricing_attempted=true, price_status="unsupported"
# ---------------------------------------------------------------------------


def test_quote_unsupported_pricing_attempted() -> None:
    data = client.post("/quote", json=_UNSUPPORTED_PAYLOAD).json()
    assert data["pricing_attempted"] is True


def test_quote_unsupported_price_status() -> None:
    data = client.post("/quote", json=_UNSUPPORTED_PAYLOAD).json()
    assert data["price_status"] == "unsupported"


# ---------------------------------------------------------------------------
# 10. request_id is present and consistent throughout the response
# ---------------------------------------------------------------------------


def test_quote_request_id_present() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert "request_id" in data
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_quote_request_id_unique_across_calls() -> None:
    r1 = client.post("/quote", json=_CANONICAL_PAYLOAD).json()["request_id"]
    r2 = client.post("/quote", json=_CANONICAL_PAYLOAD).json()["request_id"]
    assert r1 != r2


# ---------------------------------------------------------------------------
# Shape invariants — all required keys present in every response
# ---------------------------------------------------------------------------


def test_quote_response_has_all_required_keys() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    for key in (
        "request_id",
        "raw_prompt",
        "extracted_fields",
        "missing_fields",
        "extraction_status",
        "pricing_attempted",
        "price_status",
        "price",
        "pv01",
        "assumptions",
        "warnings",
    ):
        assert key in data, f"missing key: {key}"


def test_quote_clarification_response_has_all_required_keys() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    for key in (
        "request_id",
        "raw_prompt",
        "extracted_fields",
        "missing_fields",
        "extraction_status",
        "pricing_attempted",
        "price_status",
        "price",
        "pv01",
        "assumptions",
        "warnings",
    ):
        assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# Clarification case — price_status null, price and pv01 zero
# ---------------------------------------------------------------------------


def test_quote_incomplete_price_status_null() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["price_status"] is None


def test_quote_incomplete_price_is_zero() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["price"] == 0.0


def test_quote_incomplete_pv01_is_zero() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["pv01"] == 0.0


# ---------------------------------------------------------------------------
# Clarification case — warnings contain a useful message
# ---------------------------------------------------------------------------


def test_quote_incomplete_warnings_non_empty() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# raw_prompt is echoed back unchanged
# ---------------------------------------------------------------------------


def test_quote_canonical_raw_prompt_echoed() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["raw_prompt"] == _CANONICAL_PROMPT


# ---------------------------------------------------------------------------
# fixed_rate extracted from prompt flows through /quote into pricing
# ---------------------------------------------------------------------------


_RATE_PROMPT = "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR, paying 8.75%"
_RATE_PAYLOAD = {"prompt": _RATE_PROMPT}


def test_quote_with_fixed_rate_returns_indicative() -> None:
    data = client.post("/quote", json=_RATE_PAYLOAD).json()
    assert data["price_status"] == "indicative"


def test_quote_with_fixed_rate_produces_different_price() -> None:
    # 8.75% fixed rate should produce a different NPV from the default 8.5%
    default_price = client.post("/quote", json=_CANONICAL_PAYLOAD).json()["price"]
    rate_price = client.post("/quote", json=_RATE_PAYLOAD).json()["price"]
    assert rate_price != default_price


def test_quote_with_fixed_rate_extracted_field_present() -> None:
    # Confirm the extractor populated fixed_rate before pricing
    data = client.post("/quote", json=_RATE_PAYLOAD).json()
    assert abs(data["extracted_fields"].get("fixed_rate", -1) - 0.0875) < 1e-9


def test_quote_with_fixed_rate_assumptions_mention_provided() -> None:
    # Pricer should note that the fixed rate was provided by the caller
    data = client.post("/quote", json=_RATE_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "provided" in combined


# ---------------------------------------------------------------------------
# assumptions propagation from compute_price into /quote
# ---------------------------------------------------------------------------


def test_quote_indicative_assumptions_non_empty() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["price_status"] == "indicative"
    assert isinstance(data["assumptions"], list)
    assert len(data["assumptions"]) > 0


def test_quote_indicative_assumptions_mention_flat_rate() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "flat" in combined


def test_quote_clarification_assumptions_empty() -> None:
    data = client.post("/quote", json=_INCOMPLETE_PAYLOAD).json()
    assert data["pricing_attempted"] is False
    assert data["assumptions"] == []


def test_quote_unsupported_priced_assumptions_non_empty() -> None:
    data = client.post("/quote", json=_UNSUPPORTED_PAYLOAD).json()
    assert data["pricing_attempted"] is True
    assert data["price_status"] == "unsupported"
    assert isinstance(data["assumptions"], list)
    assert len(data["assumptions"]) > 0


def test_quote_unsupported_priced_warnings_non_empty() -> None:
    data = client.post("/quote", json=_UNSUPPORTED_PAYLOAD).json()
    assert data["pricing_attempted"] is True
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# Canonical full-payload regression anchor
# Pins the complete POST /quote response for the canonical supported prompt.
# request_id is generated dynamically so it is checked separately.
# All other fields are asserted in one equality check.
# ---------------------------------------------------------------------------


def test_canonical_quote_full_response_regression() -> None:
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()

    # request_id is a dynamic UUID — check shape only
    assert isinstance(data["request_id"], str) and len(data["request_id"]) > 0

    # Full equality over every other field; price/pv01 are date-dependent
    # (date.today() valuation) — asserted by shape, not exact value.
    assert data["raw_prompt"] == "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"
    assert data["extracted_fields"] == {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 250_000_000,
    }
    assert data["missing_fields"] == []
    assert data["extraction_status"] == "ready"
    assert data["pricing_attempted"] is True
    assert data["price_status"] == "indicative"
    assert isinstance(data["price"], float) and abs(data["price"]) > 1_000_000
    assert isinstance(data["pv01"], float) and data["pv01"] > 0
    assert data["assumptions"] == [
        "Flat annual market rate: 8.0000% (ZAR JIBAR proxy).",
        "Fixed coupon rate: 8.5000% (default assumption; not provided in prompt).",
        "Par-floating approximation: floating leg PV = notional \u00d7 (1 \u2212 df_end).",
        "Discount factors from flat simple-rate curve (ACT/365F).",
        "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
        "Indicative only. Not suitable for production pricing or hedging decisions.",
        "Model scope: ZAR IRS with JIBAR floating leg, quant-core flat-curve engine.",
    ]
    assert data["warnings"] == []


# ---------------------------------------------------------------------------
# Step 11 — bootstrapped curve inputs in /quote
#
# The same mixed-curve fixture used in test_price.py: 2 deposits + 2 swaps
# with rates below the flat 8% proxy → different NPV from flat baseline.
# ---------------------------------------------------------------------------

_QUOTE_CURVE_INPUTS = {
    "deposits": [
        {"tenor_months": 3, "rate": 0.075},
        {"tenor_months": 6, "rate": 0.077},
    ],
    "swaps": [
        {"tenor_years": 2, "par_rate": 0.080},
        {"tenor_years": 5, "par_rate": 0.084},
    ],
}

_CANONICAL_CURVE_PAYLOAD = {
    "prompt": _CANONICAL_PROMPT,
    "curve_inputs": _QUOTE_CURVE_INPUTS,
}


def test_quote_with_curve_inputs_returns_200() -> None:
    assert client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).status_code == 200


def test_quote_with_curve_inputs_extraction_status_ready() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["extraction_status"] == "ready"


def test_quote_with_curve_inputs_pricing_attempted() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["pricing_attempted"] is True


def test_quote_with_curve_inputs_is_indicative() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["price_status"] == "indicative"


def test_quote_with_curve_inputs_price_nonzero() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["price"] != 0.0


def test_quote_with_curve_inputs_pv01_positive() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["pv01"] > 0.0


def test_quote_with_curve_inputs_different_npv_from_flat() -> None:
    flat_price = client.post("/quote", json=_CANONICAL_PAYLOAD).json()["price"]
    boot_price = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()["price"]
    assert flat_price != boot_price


def test_quote_with_curve_inputs_assumptions_mention_bootstrapped() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "bootstrap" in combined


def test_quote_with_curve_inputs_assumptions_no_flat_proxy_mention() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "flat annual market rate" not in combined


def test_quote_with_curve_inputs_warnings_empty() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    assert data["warnings"] == []


def test_quote_canonical_flat_fallback_unaffected_by_step11() -> None:
    # Original canonical prompt without curve_inputs must still return the
    # flat-curve result unchanged.
    data = client.post("/quote", json=_CANONICAL_PAYLOAD).json()
    assert data["price_status"] == "indicative"
    combined = " ".join(data["assumptions"]).lower()
    assert "flat" in combined
    assert "bootstrap" not in combined


def test_quote_with_curve_inputs_response_has_all_required_keys() -> None:
    data = client.post("/quote", json=_CANONICAL_CURVE_PAYLOAD).json()
    for key in (
        "request_id",
        "raw_prompt",
        "extracted_fields",
        "missing_fields",
        "extraction_status",
        "pricing_attempted",
        "price_status",
        "price",
        "pv01",
        "assumptions",
        "warnings",
    ):
        assert key in data, f"missing key: {key}"


def test_quote_with_curve_inputs_invalid_frequency_returns_422() -> None:
    payload = {
        "prompt": _CANONICAL_PROMPT,
        "curve_inputs": {**_QUOTE_CURVE_INPUTS, "payment_frequency": "weekly"},
    }
    assert client.post("/quote", json=payload).status_code == 422


def test_quote_with_curve_inputs_invalid_day_count_returns_422() -> None:
    payload = {
        "prompt": _CANONICAL_PROMPT,
        "curve_inputs": {**_QUOTE_CURVE_INPUTS, "day_count": "ACT_252"},
    }
    assert client.post("/quote", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# Step 12 — day-count consistency regression check for /quote
#
# ACT_360 vs ACT_365F bootstrapped pricing must produce different NPVs,
# confirming that the resolved day count flows through /quote → compute_price
# → VanillaIRS correctly.
# ---------------------------------------------------------------------------


def test_quote_curve_inputs_act360_vs_act365f_produce_different_npv() -> None:
    payload_365f = {
        "prompt": _CANONICAL_PROMPT,
        "curve_inputs": {**_QUOTE_CURVE_INPUTS, "day_count": "ACT_365F"},
    }
    payload_360 = {
        "prompt": _CANONICAL_PROMPT,
        "curve_inputs": {**_QUOTE_CURVE_INPUTS, "day_count": "ACT_360"},
    }
    price_365f = client.post("/quote", json=payload_365f).json()["price"]
    price_360 = client.post("/quote", json=payload_360).json()["price"]
    assert price_365f != price_360


def test_quote_curve_inputs_act360_returns_indicative() -> None:
    payload = {
        "prompt": _CANONICAL_PROMPT,
        "curve_inputs": {**_QUOTE_CURVE_INPUTS, "day_count": "ACT_360"},
    }
    data = client.post("/quote", json=payload).json()
    assert data["price_status"] == "indicative"
    assert data["warnings"] == []

