# Quant Copilot V2 — Build Sequence

_Last updated: Step 29 (V2 architectural restructure)_

This document defines the ordered build phases for Quant Copilot V2.
Each phase has a clear objective, the modules it touches, its dependencies on
prior phases, and explicit exit criteria that must be proven before the next
phase begins.

The existing backend (V1 flat-curve IRS pricer + FastAPI endpoints) remains
live and untouched until the relevant V2 phase explicitly supersedes it.

---

## Phase 0 — Repository structure ✅ DONE

**Objective:** Establish the clean V2 repo layout, skeleton packages, and
architectural documentation so that all future build work has an unambiguous
home and context.

**Modules touched:**
- `quant-core/` skeleton created
- `streamlit-app/` placeholder created
- `docs/architecture/` created

**Dependencies:** None.

**Exit criteria:** ✅
- `backend/` pytest 152/152 still passes
- `quant-core/quant_core/` package tree exists with `__init__.py` in all sub-packages
- `docs/architecture/repo_map.md`, `migration_audit.md`, `build_sequence.md` exist

---

## Phase 1 — Conventions engine

**Objective:** Build the day-count, calendar, and schedule-generation foundation that
every subsequent module depends on. This is the lowest layer — nothing else can be
correct without it.

**Modules touched:**
- `quant_core/conventions/day_count.py` — ACT/365, ACT/360, ACT/ACT ISDA, 30/360
- `quant_core/conventions/calendars.py` — ZAR (SARB), USD (Fed), EUR (TARGET), GBP holiday sets
- `quant_core/conventions/settlement.py` — T+2 / T+1 spot date rules per currency
- `quant_core/conventions/schedule.py` — Generate coupon dates from effective date + tenor + frequency
- `quant_core/utils/date_utils.py` — date arithmetic helpers
- `quant-core/tests/test_conventions.py` — comprehensive unit tests

**Dependencies:** Phase 0 (skeleton exists).

**Exit criteria:**
- `schedule.generate(...)` produces correct coupon date lists for 1Y–30Y tenors at
  quarterly, semiannual, and annual frequencies
- All ZAR and USD holiday adjustments are correct to test-fixture dates
- `accrual_fraction(start, end, convention)` matches ISDA published test cases
- 100% branch coverage on conventions package
- Zero regressions in `backend/` test suite

---

## Phase 2 — Curve ingestion and bootstrap

**Objective:** Build the yield-curve layer. Load market rates (deposit, futures,
swap rates), bootstrap a discount curve, interpolate discount factors at arbitrary dates.

**Modules touched:**
- `quant_core/marketdata/rates.py` — MarketRates snapshot (par swap rates, deposit rates)
- `quant_core/marketdata/fixtures.py` — Deterministic test fixtures for CI (no live data dependency)
- `quant_core/marketdata/loaders.py` — CSV loader for rate snapshots
- `quant_core/curves/discount_curve.py` — Discount factor container + log-linear interpolator
- `quant_core/curves/bootstrap.py` — Par-swap bootstrap from rate snapshot
- `quant_core/curves/flat_curve.py` — Flat-rate adapter (wraps V1 assumption as a named curve)
- `quant-core/tests/test_curves.py`

**Dependencies:**
- Phase 1 (conventions, schedule generation, ACT/365 accrual fractions needed for bootstrapping)

**Exit criteria:**
- `bootstrap_from_par_rates(rates_snapshot)` produces a monotone discount curve
- `DiscountCurve.df(date)` interpolates correctly to within 0.01 bps vs. known analytic solutions
- `FlatCurve(0.08).df(date)` replicates the current pricer's `_df(0.08, t)` exactly
- Deterministic fixtures used — no live market data dependency in CI
- Zero regressions in `backend/` test suite

---

## Phase 3 — Deterministic vanilla pricing

**Objective:** Replace the flat-curve simple-discounting pricer with a real
IRS pricer that uses the discount curve from Phase 2 and proper cash-flow schedules
from Phase 1.

**Modules touched:**
- `quant_core/instruments/irs.py` — IRSwap dataclass (fixed leg, floating leg, metadata)
- `quant_core/instruments/base.py` — Abstract `Instrument` interface
- `quant_core/pricing/irs_pricer.py` — `price_irs(swap, curve)` → `PricingResult`
- `quant_core/schemas/trade.py` — `IRSwap`, `FixedLeg`, `FloatingLeg` Pydantic models
- `quant_core/schemas/result.py` — `PricingResult` (npv, pv01, status, assumptions)
- `quant-core/tests/test_pricing_irs.py`
- `backend/app/services/pricer.py` — **REFACTORED** to delegate to `quant_core.pricing.irs_pricer`

**Dependencies:**
- Phase 1 (schedule generation + day-count)
- Phase 2 (discount curve)

**Exit criteria:**
- `price_irs(swap, FlatCurve(0.08))` matches `backend/app/services/pricer.py` results
  to within rounding (proves backward compatibility)
- `price_irs(swap, bootstrapped_curve)` produces economically correct NPV and PV01
  for a range of tenors, notionals, and fixed rates
- Existing 152 `backend/` tests still pass (backend pricer now delegates to quant_core)
- PV01 computed by deterministic bump-and-revalue on the real curve

---

## Phase 4 — Option analytics

**Objective:** Add swaption and cap/floor pricing via Black-76 and SABR.

**Modules touched:**
- `quant_core/instruments/swaption.py` — European swaption representation
- `quant_core/instruments/cap_floor.py` — Cap/floor, caplet/floorlet
- `quant_core/marketdata/vol_surface.py` — Swaption vol surface (normal / lognormal)
- `quant_core/pricing/swaption_pricer.py` — Black-76 + Bachelier
- `quant_core/pricing/cap_floor_pricer.py` — Caplet/floorlet Black-76
- `quant_core/risk/greeks.py` — Delta, vega, theta for options
- `quant-core/tests/test_pricing_swaption.py`
- `quant-core/tests/test_pricing_cap_floor.py`
- Backend: new `POST /option-quote` endpoint (additive, non-breaking)

**Dependencies:**
- Phase 3 (swap pricing; swaption annuity uses the IRS pricing engine)

**Exit criteria:**
- Black-76 swaption premium matches ISDA published reference values to within 0.1 bps
- `vega(swaption)` correct to within 0.01% of analytic delta-vega check
- SABR fit to a vol smile for at least one standard ZAR expiry/tenor bucket
- New backend endpoint tested at 100% path coverage

---

## Phase 5 — Monte Carlo

**Objective:** Implement a path-simulation framework for exotics, XVA inputs,
and scenario generation. Initial scope: LMM (LIBOR Market Model / Cheyette) for
ZAR short rate.

**Modules touched:**
- `quant_core/pricing/mc_engine.py` — Monte Carlo simulator (path generation, antithetic, Sobol)
- `quant_core/pricing/mc_irs_pricer.py` — MC-based IRS pricer (validation vs. analytic)
- `quant_core/risk/scenario.py` — Scenario runner (parallel shift, twist scenarios)
- `quant-core/tests/test_mc_engine.py`

**Dependencies:**
- Phase 3 (IRS pricer as validation benchmark for MC output)
- Phase 4 (option pricers as additional MC validation targets)

**Exit criteria:**
- MC IRS NPV converges to analytic within 0.1% at N=10,000 paths after antithetic
- MC swaption premium converges to Black-76 within 1 bps at N=50,000 paths
- Reproducible with fixed random seed (deterministic test)
- Runtime < 5s for N=10,000 paths on a standard dev machine (no GPU required)

---

## Phase 6 — Streamlit workbench

**Objective:** Build the interactive analyst UI on top of the `quant_core` library.

**Modules touched:**
- `streamlit-app/app.py` — Full implementation replacing the placeholder stub
- `streamlit-app/pages/` — Multi-page Streamlit layout
  - `pricing.py` — Live IRS pricer with user inputs
  - `risk_ladder.py` — Bucketed PV01 ladder
  - `scenario.py` — Scenario analysis runner
  - `curves.py` — Discount curve viewer
  - `mc_paths.py` — Monte Carlo path visualiser
- `streamlit-app/requirements.txt` — Pinned versions

**Dependencies:**
- Phase 3 (IRS pricing)
- Phase 4 (option analytics; used in the pricer page)
- Phase 5 (MC; used in the paths page)

**Exit criteria:**
- IRS pricer page reproduces backend `/quote` output for the canonical test case
- Risk ladder updates within 200ms on standard dev machine for a single IRS
- All Streamlit pages load without error
- No live market data required for CI smoke test (fixtures used)

---

## Phase 7 — Copilot layer

**Objective:** Replace the prototype regex extractor (`extractor.py`) with an
LLM-based structured extraction pipeline using function calling / JSON mode.
Extend copilot scope beyond ZAR IRS to any instrument in `quant_core`.

**Modules touched:**
- `backend/app/services/extractor.py` — **REPLACED** by LLM-based extractor
- `backend/app/services/llm_client.py` — NEW: OpenAI / Azure OpenAI / local LLM adapter
- `backend/app/services/prompt_builder.py` — NEW: system prompt + few-shot examples
- `backend/app/schemas/extract.py` — UPDATED: expanded field set for new instruments
- `quant_core/schemas/trade.py` — UPDATED: new instrument types
- `backend/tests/test_extract.py` — UPDATED: canonical assertions must still hold

**Dependencies:**
- Phase 3 (new instrument schemas must be priceable)
- Phase 6 (Streamlit workbench as the LLM testing harness during development)

**Exit criteria:**
- LLM extractor matches V1 regex extractor output on all 32 canonical extraction tests
- New instrument types (swaption, cap, bond) extracted correctly from natural language
- Extraction latency < 3s at p95 on standard connection to chosen LLM provider
- Fallback to regex extractor if LLM unavailable (graceful degradation)
- API contract unchanged: callers of `POST /extract` see the same response schema

---

## Phase ordering rationale

```
Phase 0  (structure)
    └── Phase 1  (conventions)         — required by everything
            └── Phase 2  (curves)      — required by real pricing
                    └── Phase 3  (vanilla pricing)  — core loop complete
                            ├── Phase 4  (options)
                            │       └── Phase 5  (MC)
                            └── Phase 6  (Streamlit)  — needs Phase 3+4+5
                                    └── Phase 7  (copilot)  — needs everything
```

Each phase is independently releasable — the backend remains alive and testable
at every stage.
