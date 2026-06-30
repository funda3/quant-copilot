# quant-core — Quant Copilot V2 Quantitative Engine

**Status: under construction — skeleton only.**

This package will become the authoritative quantitative library for Quant Copilot V2.
It is intentionally kept separate from the FastAPI backend so that pricing logic can be
tested, versioned, and imported independently of any web framework.

---

## What belongs here (target state)

| Sub-package | Responsibility |
|---|---|
| `conventions/` | Day-count conventions, calendar arithmetic, cash-flow schedule generation |
| `curves/` | Yield-curve construction, bootstrapping, discount-factor interpolation |
| `instruments/` | Instrument representations (IRS, swaption, cap/floor, bond, …) |
| `pricing/` | Analytical and Monte Carlo pricing engines |
| `risk/` | Greeks, PV01/DV01, bucketed sensitivities, scenario analysis |
| `marketdata/` | Market data abstractions, loaders, and deterministic test fixtures |
| `schemas/` | Internal Pydantic domain schemas (trade, market snapshot, result) |
| `utils/` | Shared math and date helpers |

---

## What does NOT belong here

- FastAPI route handlers → `backend/app/api/`
- HTTP request/response schemas → `backend/app/schemas/`
- LLM prompt extraction logic → `backend/app/services/extractor.py`
- Streamlit UI → `streamlit-app/`

---

## Current backend pricer

The production-ready quantitative logic is **not yet here**. The current backend uses
a flat-curve simple-discounting pricer in `backend/app/services/pricer.py`.
That pricer is:

- Accurate enough for the current narrow scope (ZAR IRS JIBAR, indicative only)
- Classified as **KEEP TEMPORARILY / REFACTOR** in `docs/architecture/migration_audit.md`
- The target state is for it to be replaced by `quant_core.pricing.irs_pricer` once
  Phase 2 (curve ingestion) and Phase 3 (deterministic vanilla pricing) are complete

---

## Build phases

See `docs/architecture/build_sequence.md` for the full ordered build plan.

---

## Running tests

```powershell
cd C:\quant-copilot\quant-core
python -m pytest tests/ -q
```

(No tests yet — the test suite will be added as each module is implemented.)
