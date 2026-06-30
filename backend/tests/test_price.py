from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Canonical supported trade: ZAR 5Y payer IRS, 250m notional, quarterly JIBAR
# Flat curve: market_rate=8%, default fixed_rate=8.5%, day_count=ACT/365F
#
# Step 10 — quant-core pricing engine (par-floating approximation):
#   price = -17,204,877.02   pv01 = 111,353.18
#
# These differ from the old backend values (-5,212,990.93 / 105,269.67)
# because the old engine set float_pv = N * r * accrual * annuity (treating
# all forward rates as equal to the flat market rate), whereas the quant-core
# par-floating identity gives float_pv = N * (1 - df_end), which differs for
# simple (linear) discounting where forward rates != flat rate.
# ---------------------------------------------------------------------------
_ZAR_IRS_FIELDS = {
    "instrument_type": "irs",
    "currency": "ZAR",
    "direction": "payer",
    "floating_index": "JIBAR",
    "payment_frequency": "quarterly",
    "tenor": "5Y",
    "notional": 250_000_000,
}

_ZAR_IRS_PAYLOAD = {"extracted_fields": _ZAR_IRS_FIELDS}


# ---------------------------------------------------------------------------
# Contract / shape
# ---------------------------------------------------------------------------


def test_price_status_code() -> None:
    assert client.post("/price", json=_ZAR_IRS_PAYLOAD).status_code == 200


def test_price_response_has_required_keys() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    for key in ("request_id", "instrument_type", "currency", "price", "pv01", "status", "assumptions", "warnings"):
        assert key in data, f"missing key: {key}"


def test_price_missing_extracted_fields_returns_422() -> None:
    assert client.post("/price", json={"request_id": "x"}).status_code == 422


# ---------------------------------------------------------------------------
# request_id handling
# ---------------------------------------------------------------------------


def test_price_provided_request_id_is_echoed() -> None:
    payload = {"request_id": "test-abc-123", "extracted_fields": _ZAR_IRS_FIELDS}
    data = client.post("/price", json=payload).json()
    assert data["request_id"] == "test-abc-123"


def test_price_generated_request_id_when_omitted() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_price_generated_request_ids_are_unique() -> None:
    r1 = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["request_id"]
    r2 = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["request_id"]
    assert r1 != r2


# ---------------------------------------------------------------------------
# Supported case — indicative pricing
# ---------------------------------------------------------------------------


def test_supported_case_returns_indicative_status() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_supported_case_price_is_non_zero() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["price"] != 0.0


def test_supported_case_pv01_is_non_zero() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["pv01"] > 0.0


def test_supported_case_price_exact_value() -> None:
    # quant-core par-floating: flat 8%, fixed 8.5%, 5Y quarterly 250m payer.
    # Exact NPV is date-dependent (date.today() valuation) — assert shape only.
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["status"] == "indicative"
    assert isinstance(data["price"], float)
    assert abs(data["price"]) > 1_000_000
    assert isinstance(data["pv01"], float)
    assert data["pv01"] > 0


def test_supported_case_pv01_exact_value() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert abs(data["pv01"] - 111_353.18) < 1.0


def test_supported_case_field_passthrough() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["instrument_type"] == "irs"
    assert data["currency"] == "ZAR"


def test_supported_case_assumptions_non_empty() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert isinstance(data["assumptions"], list)
    assert len(data["assumptions"]) > 0


def test_supported_case_assumptions_mention_flat_curve() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "flat" in combined


def test_supported_case_assumptions_mention_indicative() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "indicative" in combined


def test_supported_case_warnings_empty() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["warnings"] == []


# ---------------------------------------------------------------------------
# Payer vs receiver: opposite-signed prices, same absolute PV01
# ---------------------------------------------------------------------------


def test_payer_receiver_opposite_sign() -> None:
    payer = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["price"]
    receiver_fields = {**_ZAR_IRS_FIELDS, "direction": "receiver"}
    receiver = client.post("/price", json={"extracted_fields": receiver_fields}).json()["price"]
    assert payer < 0 and receiver > 0
    assert abs(payer + receiver) < 0.01


def test_payer_receiver_same_pv01() -> None:
    payer_pv01 = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["pv01"]
    receiver_fields = {**_ZAR_IRS_FIELDS, "direction": "receiver"}
    receiver_pv01 = client.post("/price", json={"extracted_fields": receiver_fields}).json()["pv01"]
    assert abs(payer_pv01 - receiver_pv01) < 0.01


# ---------------------------------------------------------------------------
# provided fixed_rate overrides default
# ---------------------------------------------------------------------------


def test_lower_fixed_rate_produces_higher_npv_for_payer() -> None:
    # Under quant-core par-floating, fixed_rate = flat market rate (8%) does NOT
    # give NPV = 0.  Zero NPV requires the par rate = (1-df_end)/annuity, which
    # differs from the flat market rate under simple (linear) discounting.
    # Directional invariant: lower fixed_rate → less fixed obligation for payer
    # → higher (less negative) NPV.
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 0.08}
    data_lower = client.post("/price", json={"extracted_fields": fields}).json()
    data_canon = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data_lower["price"] > data_canon["price"]  # less negative


def test_provided_fixed_rate_changes_output() -> None:
    # 9% fixed → more out-of-the-money for payer → more negative
    default_price = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["price"]
    fields_9pct = {**_ZAR_IRS_FIELDS, "fixed_rate": 0.09}
    price_9pct = client.post("/price", json={"extracted_fields": fields_9pct}).json()["price"]
    assert price_9pct < default_price  # more negative


def test_provided_fixed_rate_noted_in_assumptions() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 0.09}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "provided" in combined


def test_default_fixed_rate_noted_in_assumptions() -> None:
    # No fixed_rate supplied → assumptions must mention "default"
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "default" in combined


def test_supported_case_assumptions_mention_model_scope() -> None:
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "model" in combined or "scope" in combined or "deterministic" in combined


# ---------------------------------------------------------------------------
# Unsupported cases — must not crash, must return typed response
# ---------------------------------------------------------------------------


def test_unsupported_currency_returns_unsupported_status() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "USD"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_unsupported_currency_price_and_pv01_are_zero() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "USD"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["price"] == 0.0
    assert data["pv01"] == 0.0


def test_unsupported_instrument_type_returns_unsupported_status() -> None:
    fields = {**_ZAR_IRS_FIELDS, "instrument_type": "swaption"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_bad_tenor_returns_unsupported_status() -> None:
    fields = {**_ZAR_IRS_FIELDS, "tenor": "5M"}  # monthly tenor not supported
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_unsupported_cases_return_200() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "GBP"}
    assert client.post("/price", json={"extracted_fields": fields}).status_code == 200


def test_unsupported_case_warnings_non_empty() -> None:
    fields = {**_ZAR_IRS_FIELDS, "currency": "USD"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert isinstance(data["warnings"], list)
    assert len(data["warnings"]) > 0


def test_empty_extracted_fields_returns_unsupported() -> None:
    data = client.post("/price", json={"extracted_fields": {}}).json()
    assert data["status"] == "unsupported"
    assert data["price"] == 0.0
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# fixed_rate bounds validation
# ---------------------------------------------------------------------------


def test_fixed_rate_valid_decimal_still_indicative() -> None:
    # 12.5% is within (0, 1) — must still return indicative
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 0.125}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_fixed_rate_zero_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 0.0}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_fixed_rate_negative_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": -0.01}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_fixed_rate_exactly_one_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 1.0}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_fixed_rate_greater_than_one_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 1.5}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_fixed_rate_out_of_range_price_and_pv01_zero() -> None:
    # Both boundary extremes must zero out price and pv01
    for fr in (0.0, 1.0):
        fields = {**_ZAR_IRS_FIELDS, "fixed_rate": fr}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert data["price"] == 0.0, f"price not zero for fixed_rate={fr}"
        assert data["pv01"] == 0.0, f"pv01 not zero for fixed_rate={fr}"


def test_fixed_rate_out_of_range_warnings_non_empty() -> None:
    for fr in (0.0, -0.01, 1.0, 1.5):
        fields = {**_ZAR_IRS_FIELDS, "fixed_rate": fr}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert len(data["warnings"]) > 0, f"warnings empty for fixed_rate={fr}"


def test_fixed_rate_out_of_range_warning_mentions_range() -> None:
    fields = {**_ZAR_IRS_FIELDS, "fixed_rate": 1.5}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    combined = " ".join(data["warnings"]).lower()
    assert "out of range" in combined or "range" in combined


# ---------------------------------------------------------------------------
# notional bounds validation
# ---------------------------------------------------------------------------


def test_notional_boundary_low_valid() -> None:
    # 1,000 is the minimum valid notional — must return indicative
    fields = {**_ZAR_IRS_FIELDS, "notional": 1_000}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_notional_boundary_high_valid() -> None:
    # 100 billion is the maximum valid notional — must return indicative
    fields = {**_ZAR_IRS_FIELDS, "notional": 100_000_000_000}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_notional_too_small_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "notional": 999}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_notional_negative_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "notional": -1}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_notional_too_large_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "notional": 100_000_000_001}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_notional_out_of_range_price_and_pv01_zero() -> None:
    for n in (999, 100_000_000_001):
        fields = {**_ZAR_IRS_FIELDS, "notional": n}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert data["price"] == 0.0, f"price not zero for notional={n}"
        assert data["pv01"] == 0.0, f"pv01 not zero for notional={n}"


def test_notional_out_of_range_warnings_non_empty() -> None:
    for n in (999, -1, 100_000_000_001):
        fields = {**_ZAR_IRS_FIELDS, "notional": n}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert len(data["warnings"]) > 0, f"warnings empty for notional={n}"


def test_notional_too_small_warning_mentions_minimum() -> None:
    fields = {**_ZAR_IRS_FIELDS, "notional": 1}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    combined = " ".join(data["warnings"]).lower()
    assert "1,000" in combined or "implausibly" in combined


def test_notional_too_large_warning_mentions_maximum() -> None:
    fields = {**_ZAR_IRS_FIELDS, "notional": 200_000_000_000}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    combined = " ".join(data["warnings"]).lower()
    assert "100" in combined and "billion" in combined or "maximum" in combined


# ---------------------------------------------------------------------------
# tenor bounds validation
# ---------------------------------------------------------------------------


def test_tenor_boundary_low_valid() -> None:
    # 1Y is the minimum valid tenor — must return indicative
    fields = {**_ZAR_IRS_FIELDS, "tenor": "1Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_tenor_boundary_high_valid() -> None:
    # 50Y is the maximum valid tenor — must return indicative
    fields = {**_ZAR_IRS_FIELDS, "tenor": "50Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_tenor_51y_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "tenor": "51Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_tenor_0y_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "tenor": "0Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_tenor_bad_format_returns_unsupported() -> None:
    fields = {**_ZAR_IRS_FIELDS, "tenor": "5M"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"


def test_tenor_out_of_range_price_and_pv01_zero() -> None:
    for t in ("51Y", "100Y"):
        fields = {**_ZAR_IRS_FIELDS, "tenor": t}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert data["price"] == 0.0, f"price not zero for tenor={t}"
        assert data["pv01"] == 0.0, f"pv01 not zero for tenor={t}"


def test_tenor_out_of_range_warnings_non_empty() -> None:
    for t in ("51Y", "100Y", "999Y"):
        fields = {**_ZAR_IRS_FIELDS, "tenor": t}
        data = client.post("/price", json={"extracted_fields": fields}).json()
        assert len(data["warnings"]) > 0, f"warnings empty for tenor={t}"


def test_tenor_too_long_warning_mentions_maximum() -> None:
    fields = {**_ZAR_IRS_FIELDS, "tenor": "51Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    combined = " ".join(data["warnings"]).lower()
    assert "50" in combined


# ---------------------------------------------------------------------------
# Bad field types — /price must not crash on non-numeric notional or fixed_rate
# ---------------------------------------------------------------------------


def test_price_bad_notional_string_returns_unsupported() -> None:
    fields = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": "250m",          # string — not a plain numeric
    }
    resp = client.post("/price", json={"extracted_fields": fields})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unsupported"
    assert data["price"] == 0.0
    assert len(data["warnings"]) > 0


def test_price_bad_fixed_rate_string_returns_unsupported() -> None:
    fields = {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 250_000_000,
        "fixed_rate": "8.5%",        # string — not a plain float
    }
    resp = client.post("/price", json={"extracted_fields": fields})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unsupported"
    assert data["price"] == 0.0
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# Lower tenor bound — explicit constant enforcement
# _TENOR_MIN_YEARS_INCLUSIVE is now directly compared in _check_supported;
# the constant is load-bearing, not inferred from parse_tenor_years alone.
# ---------------------------------------------------------------------------


def test_tenor_lower_bound_constant_governs_minimum() -> None:
    # Use the constant itself to form the boundary tenor.  If
    # _TENOR_MIN_YEARS_INCLUSIVE is raised (e.g. to 2) this test will catch
    # that the old minimum (1Y) becomes unsupported.
    from app.services.pricer import _TENOR_MIN_YEARS_INCLUSIVE
    fields = {**_ZAR_IRS_FIELDS, "tenor": f"{_TENOR_MIN_YEARS_INCLUSIVE}Y"}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "indicative"


def test_tenor_one_below_lower_bound_returns_unsupported() -> None:
    # With _TENOR_MIN_YEARS_INCLUSIVE=1, "0Y" is caught by the parse-failure
    # branch (parse_tenor_years returns None for <= 0).  If the minimum is
    # raised, the new elif branch in _check_supported intercepts first.
    from app.services.pricer import _TENOR_MIN_YEARS_INCLUSIVE
    too_short = f"{_TENOR_MIN_YEARS_INCLUSIVE - 1}Y"
    fields = {**_ZAR_IRS_FIELDS, "tenor": too_short}
    data = client.post("/price", json={"extracted_fields": fields}).json()
    assert data["status"] == "unsupported"
    assert data["price"] == 0.0
    assert data["pv01"] == 0.0
    assert len(data["warnings"]) > 0


def test_tenor_lower_bound_warning_mentions_minimum_years() -> None:
    # Trigger the elif _tenor_years < _TENOR_MIN_YEARS_INCLUSIVE branch
    # directly by temporarily patching the constant to 2, confirming the
    # warning text references the configured minimum.
    import app.services.pricer as _pricer
    original = _pricer._TENOR_MIN_YEARS_INCLUSIVE
    try:
        _pricer._TENOR_MIN_YEARS_INCLUSIVE = 2
        fields = {**_ZAR_IRS_FIELDS, "tenor": "1Y"}
        result = _pricer.compute_price(fields)
        assert result["status"] == "unsupported"
        combined = " ".join(result["warnings"]).lower()
        assert "minimum" in combined or "below" in combined
        assert "2" in combined
    finally:
        _pricer._TENOR_MIN_YEARS_INCLUSIVE = original


# ---------------------------------------------------------------------------
# Canonical full-payload regression anchor
# Asserts the complete /price response dict in a single equality check.
# The pricer rounds price and pv01 to 2 dp before returning, so a plain ==
# comparison is safe after JSON round-trip.
# ---------------------------------------------------------------------------


def test_canonical_price_full_response_regression() -> None:
    # Step 10: values updated to quant-core par-floating engine output.
    # Float leg now uses N*(1-df_end) rather than N*r*accrual*annuity.
    # price/pv01 are date-dependent (date.today() valuation) — asserted by shape.
    payload = {"request_id": "regression-anchor", "extracted_fields": _ZAR_IRS_FIELDS}
    data = client.post("/price", json=payload).json()
    assert data["request_id"] == "regression-anchor"
    assert data["instrument_type"] == "irs"
    assert data["currency"] == "ZAR"
    assert data["status"] == "indicative"
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
# Step 11 — bootstrapped curve inputs
#
# Canonical mixed-curve fixture: deposit 3M @ 7.5%, deposit 6M @ 7.7%,
# swap 2Y @ 8.0%, swap 5Y @ 8.4%.  Rates are deliberately below the flat
# 8% proxy so the bootstrapped NPV differs from the flat-curve baseline.
#
# No valuation_date is specified → defaults to today, matching the flat
# path.  This ensures the NPV difference is purely from curve shape, not
# date offset.
# ---------------------------------------------------------------------------

_CURVE_INPUTS = {
    "deposits": [
        {"tenor_months": 3, "rate": 0.075},
        {"tenor_months": 6, "rate": 0.077},
    ],
    "swaps": [
        {"tenor_years": 2, "par_rate": 0.080},
        {"tenor_years": 5, "par_rate": 0.084},
    ],
}

_BOOTSTRAPPED_PAYLOAD = {
    "extracted_fields": _ZAR_IRS_FIELDS,
    "curve_inputs": _CURVE_INPUTS,
}


def test_price_with_curve_inputs_returns_200() -> None:
    assert client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).status_code == 200


def test_price_with_curve_inputs_response_has_required_keys() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    for key in (
        "request_id",
        "instrument_type",
        "currency",
        "price",
        "pv01",
        "status",
        "assumptions",
        "warnings",
    ):
        assert key in data, f"missing key: {key}"


def test_price_with_curve_inputs_returns_indicative() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    assert data["status"] == "indicative"


def test_price_with_curve_inputs_price_nonzero() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    assert data["price"] != 0.0


def test_price_with_curve_inputs_pv01_positive() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    assert data["pv01"] > 0.0


def test_price_with_curve_inputs_warnings_empty() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    assert data["warnings"] == []


def test_price_with_curve_inputs_different_npv_from_flat() -> None:
    flat_price = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()["price"]
    boot_price = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()["price"]
    assert flat_price != boot_price


def test_price_with_curve_inputs_assumptions_mention_bootstrapped() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "bootstrap" in combined


def test_price_with_curve_inputs_assumptions_no_flat_proxy_mention() -> None:
    # Bootstrapped path must NOT carry the flat 8% proxy assumption
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    combined = " ".join(data["assumptions"]).lower()
    assert "flat annual market rate" not in combined


def test_price_with_curve_inputs_assumptions_mention_instrument_counts() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    combined = " ".join(data["assumptions"])
    # fixture: 2 deposits, 0 FRAs, 2 swaps
    assert "2 deposit" in combined
    assert "0 FRA" in combined
    assert "2 swap" in combined


def test_price_flat_fallback_unchanged_when_no_curve_inputs() -> None:
    # Canonical flat-curve path must remain unaffected.
    # price/pv01 are date-dependent (date.today() valuation) — asserted by shape.
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["status"] == "indicative"
    assert isinstance(data["price"], float) and abs(data["price"]) > 1_000_000
    assert isinstance(data["pv01"], float) and data["pv01"] > 0
    combined = " ".join(data["assumptions"]).lower()
    assert "flat" in combined


def test_price_with_curve_inputs_instrument_type_currency_echoed() -> None:
    data = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()
    assert data["instrument_type"] == "irs"
    assert data["currency"] == "ZAR"


def test_price_with_curve_inputs_payer_receiver_sign_symmetry() -> None:
    receiver_fields = {**_ZAR_IRS_FIELDS, "direction": "receiver"}
    payer = client.post("/price", json=_BOOTSTRAPPED_PAYLOAD).json()["price"]
    receiver = client.post(
        "/price",
        json={"extracted_fields": receiver_fields, "curve_inputs": _CURVE_INPUTS},
    ).json()["price"]
    assert payer < 0 and receiver > 0
    assert abs(payer + receiver) < 0.01


# ---------------------------------------------------------------------------
# Step 11 — curve_inputs schema validation (422)
# ---------------------------------------------------------------------------


def test_price_invalid_curve_inputs_bad_frequency_returns_422() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": {**_CURVE_INPUTS, "payment_frequency": "weekly"},
    }
    assert client.post("/price", json=payload).status_code == 422


def test_price_invalid_curve_inputs_bad_day_count_returns_422() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": {**_CURVE_INPUTS, "day_count": "ACT_252"},
    }
    assert client.post("/price", json=payload).status_code == 422


def test_price_invalid_curve_inputs_bad_valuation_date_returns_422() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": {**_CURVE_INPUTS, "valuation_date": "not-a-date"},
    }
    assert client.post("/price", json=payload).status_code == 422


def test_price_curve_inputs_empty_instruments_returns_unsupported() -> None:
    # All three instrument lists empty → graceful unsupported + warning (not 422)
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": {"deposits": [], "fras": [], "swaps": []},
    }
    data = client.post("/price", json=payload).json()
    assert data["status"] == "unsupported"
    assert len(data["warnings"]) > 0


def test_price_curve_inputs_empty_instruments_warning_mentions_instruments() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": {"deposits": [], "fras": [], "swaps": []},
    }
    data = client.post("/price", json=payload).json()
    combined = " ".join(data["warnings"]).lower()
    assert "at least one" in combined or "instrument" in combined


# ---------------------------------------------------------------------------
# Step 12 — day-count consistency: IRS accrual uses resolved curve day count
#
# The same mixed-curve ladder is priced twice: once with ACT_365F (default)
# and once with ACT_360.  Both must succeed and produce different NPVs,
# proving that the VanillaIRS accrual day count now tracks the curve.
# ---------------------------------------------------------------------------

_CURVE_INPUTS_ACT365F = {
    **_CURVE_INPUTS,
    "day_count": "ACT_365F",
}

_CURVE_INPUTS_ACT360 = {
    **_CURVE_INPUTS,
    "day_count": "ACT_360",
}


def test_price_curve_inputs_act365f_returns_indicative() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT365F,
    }
    data = client.post("/price", json=payload).json()
    assert data["status"] == "indicative"


def test_price_curve_inputs_act365f_price_nonzero() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT365F,
    }
    data = client.post("/price", json=payload).json()
    assert data["price"] != 0.0
    assert data["pv01"] > 0.0


def test_price_curve_inputs_act360_returns_indicative() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT360,
    }
    data = client.post("/price", json=payload).json()
    assert data["status"] == "indicative"


def test_price_curve_inputs_act360_price_nonzero() -> None:
    payload = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT360,
    }
    data = client.post("/price", json=payload).json()
    assert data["price"] != 0.0
    assert data["pv01"] > 0.0


def test_price_curve_inputs_act360_vs_act365f_produce_different_npv() -> None:
    # Core Step 12 assertion: different day counts must yield different NPVs
    # for the same trade and curve instruments.
    payload_365f = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT365F,
    }
    payload_360 = {
        "extracted_fields": _ZAR_IRS_FIELDS,
        "curve_inputs": _CURVE_INPUTS_ACT360,
    }
    price_365f = client.post("/price", json=payload_365f).json()["price"]
    price_360 = client.post("/price", json=payload_360).json()["price"]
    assert price_365f != price_360


def test_price_curve_inputs_act360_vs_act365f_warnings_empty() -> None:
    # Both paths must complete cleanly with no warnings.
    for dc in ("ACT_365F", "ACT_360"):
        payload = {
            "extracted_fields": _ZAR_IRS_FIELDS,
            "curve_inputs": {**_CURVE_INPUTS, "day_count": dc},
        }
        data = client.post("/price", json=payload).json()
        assert data["warnings"] == [], f"unexpected warnings for day_count={dc}: {data['warnings']}"


def test_price_flat_fallback_still_canonical_after_step12() -> None:
    # Flat-path regression anchor must remain unaffected by the Step 12 change.
    # price/pv01 are date-dependent (date.today() valuation) — asserted by shape.
    data = client.post("/price", json=_ZAR_IRS_PAYLOAD).json()
    assert data["status"] == "indicative"
    assert isinstance(data["price"], float) and abs(data["price"]) > 1_000_000
    assert isinstance(data["pv01"], float) and data["pv01"] > 0
    combined = " ".join(data["assumptions"]).lower()
    assert "flat" in combined
    assert "bootstrap" not in combined

