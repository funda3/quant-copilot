from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _data() -> dict:
    return client.get("/assumptions").json()


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------


def test_assumptions_status_code() -> None:
    assert client.get("/assumptions").status_code == 200


def test_assumptions_response_has_all_required_keys() -> None:
    data = _data()
    for key in (
        "pricing_model",
        "supported_instruments",
        "supported_currencies",
        "supported_floating_indices",
        "supported_payment_frequencies",
        "supported_directions",
        "flat_market_rate",
        "default_fixed_rate",
        "fixed_rate_bounds",
        "notional_bounds",
        "tenor_bounds_years",
        "notes",
    ):
        assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# pricing_model label
# ---------------------------------------------------------------------------


def test_assumptions_pricing_model() -> None:
    assert _data()["pricing_model"] == "quant_core_flat_curve_irs_indicative_v2"


# ---------------------------------------------------------------------------
# Rate constants
# ---------------------------------------------------------------------------


def test_assumptions_flat_market_rate() -> None:
    assert abs(_data()["flat_market_rate"] - 0.08) < 1e-9


def test_assumptions_default_fixed_rate() -> None:
    assert abs(_data()["default_fixed_rate"] - 0.085) < 1e-9


# ---------------------------------------------------------------------------
# Supported sets
# ---------------------------------------------------------------------------


def test_assumptions_supported_instruments() -> None:
    assert _data()["supported_instruments"] == ["irs"]


def test_assumptions_supported_currencies() -> None:
    assert _data()["supported_currencies"] == ["ZAR"]


def test_assumptions_supported_floating_indices() -> None:
    assert _data()["supported_floating_indices"] == ["JIBAR"]


def test_assumptions_supported_payment_frequencies() -> None:
    freqs = _data()["supported_payment_frequencies"]
    assert set(freqs) == {"quarterly", "semiannual", "annual"}


# ---------------------------------------------------------------------------
# Supported directions
# ---------------------------------------------------------------------------


def test_assumptions_supported_directions_present() -> None:
    assert "supported_directions" in _data()


def test_assumptions_supported_directions_exact_values() -> None:
    assert set(_data()["supported_directions"]) == {"payer", "receiver"}


def test_assumptions_supported_directions_is_list() -> None:
    assert isinstance(_data()["supported_directions"], list)


# ---------------------------------------------------------------------------
# Bounds objects
# ---------------------------------------------------------------------------


def test_assumptions_fixed_rate_bounds() -> None:
    bounds = _data()["fixed_rate_bounds"]
    assert abs(bounds["min_exclusive"] - 0.0) < 1e-9
    assert abs(bounds["max_exclusive"] - 1.0) < 1e-9


def test_assumptions_notional_bounds() -> None:
    bounds = _data()["notional_bounds"]
    assert bounds["min_inclusive"] == 1_000
    assert bounds["max_inclusive"] == 100_000_000_000


def test_assumptions_tenor_bounds_years() -> None:
    bounds = _data()["tenor_bounds_years"]
    assert bounds["min_inclusive"] == 1
    assert bounds["max_inclusive"] == 50


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def test_assumptions_notes_is_non_empty_list() -> None:
    notes = _data()["notes"]
    assert isinstance(notes, list)
    assert len(notes) > 0


def test_assumptions_notes_mention_indicative() -> None:
    combined = " ".join(_data()["notes"]).lower()
    assert "indicative" in combined


def test_assumptions_notes_mention_flat_curve() -> None:
    combined = " ".join(_data()["notes"]).lower()
    assert "flat" in combined


def test_assumptions_notes_mention_narrow_scope() -> None:
    combined = " ".join(_data()["notes"]).lower()
    assert "irs" in combined or "narrow" in combined


# ---------------------------------------------------------------------------
# Determinism — repeated calls return identical response
# ---------------------------------------------------------------------------


def test_assumptions_is_deterministic() -> None:
    r1 = client.get("/assumptions").json()
    r2 = client.get("/assumptions").json()
    assert r1 == r2


# ---------------------------------------------------------------------------
# Canonical full-payload regression anchor
# Pins the complete GET /assumptions response in one equality check.
# Values are taken from the live endpoint, not derived from app source code.
# ---------------------------------------------------------------------------


def test_canonical_assumptions_full_response_regression() -> None:
    # Step 10: pricing_model label and notes updated to reflect quant-core engine.
    data = client.get("/assumptions").json()
    assert data == {
        "pricing_model": "quant_core_flat_curve_irs_indicative_v2",
        "supported_instruments": ["irs"],
        "supported_currencies": ["ZAR"],
        "supported_floating_indices": ["JIBAR"],
        "supported_payment_frequencies": ["annual", "quarterly", "semiannual"],
        "supported_directions": ["payer", "receiver"],
        "flat_market_rate": 0.08,
        "default_fixed_rate": 0.085,
        "fixed_rate_bounds": {"min_exclusive": 0.0, "max_exclusive": 1.0},
        "notional_bounds": {"min_inclusive": 1000, "max_inclusive": 100_000_000_000},
        "tenor_bounds_years": {"min_inclusive": 1, "max_inclusive": 50},
        "notes": [
            "Indicative pricing only. Not suitable for production pricing or hedging decisions.",
            "Only a narrow ZAR IRS case with JIBAR floating index is currently supported.",
            "Flat curve: all cash flows discounted using quant_core.curves.build_flat (ACT/365F).",
            "Floating leg: par-floating approximation \u2014 PV_float = notional \u00d7 (1 \u2212 df_end).",
            "PV01: parallel +1bp shift of all continuously-compounded zero rates.",
        ],
    }
