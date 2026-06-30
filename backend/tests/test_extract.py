from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_FULL_PROMPT = "Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR"
_PARTIAL_PROMPT = "Price a ZAR payer swap"

# ---------------------------------------------------------------------------
# Contract tests — shape and HTTP semantics
# ---------------------------------------------------------------------------


def test_extract_status_code() -> None:
    response = client.post("/extract", json={"prompt": _FULL_PROMPT})
    assert response.status_code == 200


def test_extract_response_has_required_keys() -> None:
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    for key in ("request_id", "raw_prompt", "extracted_fields", "missing_fields", "status"):
        assert key in data


def test_extract_raw_prompt_echoed() -> None:
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert data["raw_prompt"] == _FULL_PROMPT


def test_extract_request_id_is_string() -> None:
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert isinstance(data["request_id"], str)
    assert len(data["request_id"]) > 0


def test_extract_unique_request_ids() -> None:
    r1 = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    r2 = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert r1["request_id"] != r2["request_id"]


def test_extract_rejects_missing_prompt() -> None:
    assert client.post("/extract", json={}).status_code == 422


# ---------------------------------------------------------------------------
# Extraction behaviour — full prompt
# ---------------------------------------------------------------------------


def test_full_prompt_extracts_instrument_type() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("instrument_type") == "irs"


def test_full_prompt_extracts_currency() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("currency") == "ZAR"


def test_full_prompt_extracts_direction_payer() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("direction") == "payer"


def test_full_prompt_extracts_floating_index() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("floating_index") == "JIBAR"


def test_full_prompt_extracts_payment_frequency() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("payment_frequency") == "quarterly"


def test_full_prompt_extracts_tenor() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("tenor") == "5Y"


def test_full_prompt_extracts_notional() -> None:
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert fields.get("notional") == 250_000_000


def test_full_prompt_tenor_and_notional_not_in_missing() -> None:
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert "tenor" not in data["missing_fields"]
    assert "notional" not in data["missing_fields"]


def test_full_prompt_status_is_ready() -> None:
    # All core fields present — only effective_date missing, which does not block ready
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert data["status"] == "ready"


def test_effective_date_always_in_missing() -> None:
    # Rule-based extractor never infers effective_date
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert "effective_date" in data["missing_fields"]


# ---------------------------------------------------------------------------
# Extraction behaviour — partial prompt
# ---------------------------------------------------------------------------


def test_partial_prompt_missing_fields() -> None:
    data = client.post("/extract", json={"prompt": _PARTIAL_PROMPT}).json()
    missing = data["missing_fields"]
    assert "tenor" in missing
    assert "notional" in missing
    assert "floating_index" in missing
    assert "payment_frequency" in missing


def test_partial_prompt_status_is_needs_clarification() -> None:
    data = client.post("/extract", json={"prompt": _PARTIAL_PROMPT}).json()
    assert data["status"] == "needs_clarification"


# ---------------------------------------------------------------------------
# Extraction behaviour — direction and currency variations
# ---------------------------------------------------------------------------


def test_receiver_direction_extracted() -> None:
    prompt = "Price a 3Y USD receiver swap, 10m notional, monthly SOFR"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert fields.get("direction") == "receiver"


def test_usd_currency_extracted() -> None:
    prompt = "Price a 3Y USD receiver swap, 10m notional, monthly SOFR"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert fields.get("currency") == "USD"


def test_sofr_index_extracted() -> None:
    prompt = "Price a 3Y USD receiver swap, 10m notional, monthly SOFR"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert fields.get("floating_index") == "SOFR"


# ---------------------------------------------------------------------------
# Notional parsing variants
# ---------------------------------------------------------------------------


def test_notional_k_suffix() -> None:
    prompt = "ZAR payer swap 500k notional 2Y quarterly JIBAR"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert fields.get("notional") == 500_000


def test_notional_large_integer() -> None:
    prompt = "ZAR payer swap 250000000 notional 5Y quarterly JIBAR"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert fields.get("notional") == 250_000_000


# ---------------------------------------------------------------------------
# Regression: currency must not false-match as substring of an index name
# ---------------------------------------------------------------------------


def test_euribor_does_not_falsely_extract_eur_currency() -> None:
    # 'EUR' is a substring of 'EURIBOR'; without word-boundary guards the
    # currency extractor would silently return 'EUR' for any EURIBOR prompt.
    data = client.post("/extract", json={"prompt": "payer swap 5Y 100m quarterly EURIBOR"}).json()
    assert data["extracted_fields"].get("currency") is None
    assert "currency" in data["missing_fields"]


# ---------------------------------------------------------------------------
# fixed_rate extraction
# ---------------------------------------------------------------------------


def test_fixed_rate_percent_suffix_extracted() -> None:
    # "8.75%" -> decimal 0.0875
    prompt = "Price a 5Y ZAR payer swap 250m notional quarterly JIBAR paying 8.75%"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert abs(fields.get("fixed_rate", -1) - 0.0875) < 1e-9


def test_fixed_rate_percent_word_extracted() -> None:
    # "8.5 percent" -> decimal 0.085
    prompt = "Price a 5Y ZAR payer swap 250m notional quarterly JIBAR at 8.5 percent"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert abs(fields.get("fixed_rate", -1) - 0.085) < 1e-9


def test_fixed_rate_absent_when_not_in_prompt() -> None:
    # Canonical prompt has no percentage — fixed_rate should not appear
    fields = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()["extracted_fields"]
    assert "fixed_rate" not in fields


def test_fixed_rate_not_in_missing_fields() -> None:
    # fixed_rate is optional — absence must never be reported as a missing field
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert "fixed_rate" not in data["missing_fields"]


def test_fixed_rate_integer_percent_extracted() -> None:
    # "9%" -> 0.09
    prompt = "5Y ZAR payer swap 250m notional quarterly JIBAR fixed rate 9%"
    fields = client.post("/extract", json={"prompt": prompt}).json()["extracted_fields"]
    assert abs(fields.get("fixed_rate", -1) - 0.09) < 1e-9


def test_fixed_rate_does_not_affect_status_when_other_fields_present() -> None:
    # Adding a rate to a ready prompt must not change extraction status
    prompt = "Price a 5Y ZAR payer swap 250m notional quarterly JIBAR paying 8.75%"
    data = client.post("/extract", json={"prompt": prompt}).json()
    assert data["status"] == "ready"


def test_fixed_rate_does_not_affect_status_when_fields_missing() -> None:
    # Adding a rate to an incomplete prompt must not suddenly flip status to ready
    prompt = "Price a ZAR payer swap 250m notional at 8.75%"
    data = client.post("/extract", json={"prompt": prompt}).json()
    assert data["status"] == "needs_clarification"


# ---------------------------------------------------------------------------
# Canonical full-payload regression anchor
# Asserts the complete extracted_fields dict in a single equality check.
# If the extractor's output for the canonical prompt ever drifts, this test
# will catch it before any per-field test has a chance to miss the interaction.
# ---------------------------------------------------------------------------


def test_canonical_prompt_full_extracted_fields_regression() -> None:
    data = client.post("/extract", json={"prompt": _FULL_PROMPT}).json()
    assert data["extracted_fields"] == {
        "instrument_type": "irs",
        "currency": "ZAR",
        "direction": "payer",
        "floating_index": "JIBAR",
        "payment_frequency": "quarterly",
        "tenor": "5Y",
        "notional": 250_000_000,
    }
    assert data["status"] == "ready"
    assert data["missing_fields"] == ["effective_date"]
    assert data["raw_prompt"] == _FULL_PROMPT
    assert isinstance(data["request_id"], str) and len(data["request_id"]) > 0

