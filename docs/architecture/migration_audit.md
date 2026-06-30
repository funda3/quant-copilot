# Quant Copilot V2 — Migration Audit

_Last updated: Step 29 (V2 architectural restructure)_

This document classifies every existing file or module into one of four categories:

| Category | Meaning |
|---|---|
| **KEEP AS-IS** | Correct, well-tested, already in the right place. No action needed. |
| **KEEP TEMPORARILY** | Working code in the wrong layer or with the wrong scope. Keep until the V2 replacement is built, then migrate. |
| **MOVE LATER** | Structurally fine but belongs in a different package once that package exists. |
| **REFACTOR** | Logic is correct but the implementation is prototype-grade and needs a proper rewrite before production. |
| **RETIRE / DEPRECATE** | Will be superseded by V2 equivalents. Keep until V2 equivalent is proven, then delete. |
| **DEFERRED** | Not wrong, not urgent. Revisit in a later phase. |

---

## `backend/app/api/`

### `health.py`
**KEEP AS-IS**

A correct, minimal liveness probe (`GET /healthz → {"status":"ok","version":"…"}`).
Tested (5 tests). No coupling to business logic.
No action needed.

### `extract.py`
**KEEP AS-IS (endpoint layer) / REFACTOR (service layer)**

The route handler is correct: validates input, delegates to `extractor.py`, returns
structured response. The HTTP contract is stable.
The underlying extraction logic in `services/extractor.py` is prototype-grade (see below).
Next action: keep the route; refactor the extractor.

### `price.py`
**KEEP AS-IS (endpoint layer) / KEEP TEMPORARILY (service layer)**

The route handler is correct. The pricing logic it delegates to is temporary (flat curve).
Next action: keep route unchanged until `quant_core.pricing.irs_pricer` is ready.

### `quote.py`
**KEEP AS-IS**

Orchestrates extract → price in a single call. Well-tested (33 tests).
This is a permanent convenience endpoint — it will remain after V2, calling the
upgraded extractor and pricer.
Next action: none in this step.

### `assumptions.py`
**KEEP AS-IS**

Returns pricing assumptions without a numeric result. Useful for UI debugging and
auditability. Stable API contract.
Next action: update assumption text when flat-curve pricer is replaced.

---

## `backend/app/schemas/`

All five schema files (`health.py`, `extract.py`, `price.py`, `quote.py`,
`assumptions.py`) are:

**KEEP AS-IS**

These are the HTTP API contract. Pydantic v2, well-typed, all tested.
They are intentionally distinct from `quant_core/schemas/` (which will hold internal
domain models). The API schemas will evolve alongside the API contract, not alongside
the quant model.

Next action: none. As new instrument types are added, new fields will be appended
under additive versioning.

---

## `backend/app/services/extractor.py`

**KEEP TEMPORARILY → REFACTOR**

**What it does:** Regex + keyword matching to extract structured fields (instrument_type,
currency, tenor, notional, direction, floating_index, payment_frequency, effective_date,
fixed_rate) from a natural-language prompt string.

**Why it's temporary:**
- Regex rules are brittle; coverage is narrow (ZAR IRS JIBAR only)
- No ambiguity resolution, no partial-match confidence scoring
- Does not use an LLM; the extraction is purely deterministic pattern matching
- Will not scale to new instrument types without per-instrument rule sets

**V2 target:**
Replace with an LLM-based structured extraction layer (function calling / JSON mode)
that maps any instrument description to the internal domain schema in `quant_core.schemas`.
This is a Phase 7 (copilot layer) concern.

**Next action:** Keep as-is through Phases 1–6. Mark in tests as canonical regression
anchor so any LLM-based replacement must match or improve on the current outputs.

---

## `backend/app/services/pricer.py`

**KEEP TEMPORARILY → REFACTOR INTO `quant-core`**

**What it does:** Flat-curve, simple-discounting IRS pricer for ZAR JIBAR.
Computes NPV and PV01 via deterministic revaluation.

**Why it's temporary:**
- Flat-rate assumption (`r = 0.08` constant) is not a real market curve
- Simple (linear) discounting — not ACT/365 compound discounting
- No settlement conventions, no holiday calendars, no day-count basis
- Hard-coded to ZAR/JIBAR/IRS — does not generalise
- Lives in the API layer, which violates the separation of concerns target

**Why it's kept for now:**
- Fully tested (61 tests, canonical regression anchor)
- Correct for the narrow supported scope
- Breaking it to force an early migration would leave the backend non-functional

**V2 target:**
- `quant_core.curves` bootstraps a real discount curve from market rates
- `quant_core.instruments.irs` represents the trade with proper schedule generation
- `quant_core.pricing.irs_pricer` computes NPV by summing discounted CF on the real curve
- `pricer.py` becomes a thin adapter calling `quant_core.pricing.irs_pricer`
- Eventually `pricer.py` is deleted; the route calls `quant_core` directly

**Migration trigger:** Phase 3 exit criteria met (see `build_sequence.md`).

---

## `backend/tests/`

### All five test files
**KEEP AS-IS**

152 tests, all passing. Includes canonical regression anchors for each endpoint.
These are the correctness gate — any future refactor must not regress them.

**Next action:** As `quant_core` modules are implemented, add parallel test suites
under `quant-core/tests/`. The backend test suite tests the HTTP layer; the quant-core
test suite tests the quantitative logic in isolation.

---

## `streamlit-app/`

**PLACEHOLDER — Phase 6**

Does not yet exist as a functional application.
`app.py` is a valid stub that displays an "under construction" banner.
`requirements.txt` lists planned dependencies (all commented out).

**Target:** Interactive quant workbench for analysts. See `build_sequence.md` Phase 6.

---

## `quant-core/`

**SKELETON — ALL MODULES PLACEHOLDER**

All `__init__.py` files exist and document their intended content.
No production quantitative logic yet.
Build begins in Phase 1 (conventions engine).

---

## Repo root

No clutter at the repo root. `backend/`, `quant-core/`, and `streamlit-app/`
hold the active product surfaces. A root `.gitignore` should be added (see below).

**Recommended root `.gitignore` additions (not yet present):**
```
__pycache__/
*.pyc
*.pyo
.venv/
.pytest_cache/
node_modules/
.env
dist/
build/
*.log
.DS_Store
```

This is a minor housekeeping item; it does not block any build phase.

---

## Summary table

| Path | Category | Next action |
|---|---|---|
| `backend/app/api/*.py` | KEEP AS-IS | None |
| `backend/app/schemas/*.py` | KEEP AS-IS | None |
| `backend/app/services/extractor.py` | KEEP TEMPORARILY → REFACTOR | Replace in Phase 7 |
| `backend/app/services/pricer.py` | KEEP TEMPORARILY → REFACTOR | Migrate to `quant_core.pricing` after Phase 3 |
| `backend/app/main.py` | KEEP AS-IS | None |
| `backend/tests/*.py` | KEEP AS-IS | Add `quant-core/tests/` in parallel in Phase 1 |
| `streamlit-app/` | PLACEHOLDER | Implement in Phase 6 |
| `quant-core/` | SKELETON | Phase 1 implementation starts next |
| `docs/architecture/` | NEW — KEEP | Maintain as living documents |
