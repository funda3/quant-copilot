# Quant Copilot V2 — Repository Map

_Last updated: 2026-03-31_

---

## Single source of truth

| Layer | Responsibility |
|---|---|
| `quant-core/` | **All financial mathematics.** Curves, instruments, pricing engines, risk analytics. No HTTP, no FastAPI. |
| `backend/` | **HTTP orchestration only.** Parse requests, validate, call `quant_core`, serialise responses. No quant maths lives here. |
| `streamlit-app/` | **Analyst workbench UI.** Calls the backend over HTTP. No maths, no direct `quant_core` import. |

The direction `backend → quant_core` is correct.  
The direction `quant_core → backend` must never exist.

---

## Top-level layout

```
C:\quant-copilot\
  backend\            FastAPI backend — HTTP API surface and thin orchestration
  quant-core\         Quantitative engine library — all financial maths
  streamlit-app\      Interactive quant workbench (analyst UI)
  docs\
    architecture\     repo_map.md, migration_audit.md, build_sequence.md
```

---

## `backend/`

**Role:** HTTP API surface. Validates inputs, builds instruments, calls `quant_core`,
returns typed JSON responses. Contains zero curve maths or pricing logic.

### API routes (all currently live — 27 routes)

```
GET   /healthz                         — → HealthResponse                                             (health.py)
POST  /extract                         ExtractRequest → ExtractResponse                              (extract.py)
GET   /assumptions                     AssumptionsRequest → AssumptionsResponse                     (assumptions.py)
POST  /quote                           QuoteRequest → QuoteResponse                                  (quote.py)
POST  /price                           PricingRequest → PricingResponse                             (price.py)
POST  /price/irs                       IRSDirectPriceRequest → IRSDirectPriceResponse               (price.py)
POST  /price/irs/cashflows             IRSCashflowRequest → IRSCashflowResponse                     (price.py)
POST  /price/irs/cashflows/direct      IRSDirectCashflowRequest → IRSDirectCashflowResponse         (price.py)
POST  /price/irs/breakdown             IRSBreakdownRequest → IRSBreakdownResponse                   (price.py)
POST  /price/irs/breakdown/direct      IRSDirectBreakdownRequest → IRSDirectBreakdownResponse       (price.py)
POST  /price/irs/fair-rate             IRSFairRateRequest → IRSFairRateResponse                     (price.py)
POST  /price/irs/fair-rate/direct      IRSDirectFairRateRequest → IRSDirectFairRateResponse         (price.py)
POST  /price/fra                       FRAPriceRequest → FRAPriceResponse                           (price.py)
POST  /price/fx-forward                FXForwardPriceRequest → FXForwardPriceResponse               (price.py)
POST  /price/fx-swap                   FXSwapPriceRequest → FXSwapPriceResponse                    (price.py)
POST  /price/fx-option                 FXOptionPriceRequest → FXOptionPriceResponse                (price.py)
POST  /price/equity-option             EquityOptionPriceRequest → EquityOptionPriceResponse         (price.py)
POST  /price/bond                      BondPricingRequest → BondPricingResponse                    (price.py)
POST  /price/bond/ytm                  BondYTMRequest → BondYTMResponse                            (price.py)
POST  /price/bond/cashflows            BondCashflowRequest → BondCashflowResponse                  (price.py)
POST  /api/curve/swap                  CurveRequest → CurveResponse                                (curve.py)
POST  /api/curve                       MixedCurveRequest → MixedCurveResponse                      (curve.py)
POST  /risk/ladder                     LadderRequest → LadderResponse                              (risk.py)
POST  /risk/ladder/direct              IRSDirectLadderRequest → IRSDirectLadderResponse             (risk.py)
POST  /risk/scenario                   ScenarioRequest → ScenarioResponse                          (risk.py)
POST  /risk/scenario/direct            IRSDirectScenarioRequest → IRSDirectScenarioResponse         (risk.py)
POST  /risk/bond                       BondRiskRequest → BondRiskResponse                          (risk.py)
```

### Module structure

```
backend/
  app/
    api/
      health.py         GET /healthz
      extract.py        POST /extract
      assumptions.py    GET /assumptions
      quote.py          POST /quote
      price.py          POST /price, POST /price/irs (+/cashflows, /breakdown, /fair-rate, each ±/direct),
                        POST /price/fra, POST /price/fx-forward, POST /price/fx-swap,
                        POST /price/fx-option, POST /price/equity-option,
                        POST /price/bond, POST /price/bond/ytm, POST /price/bond/cashflows
      curve.py          POST /api/curve/swap, POST /api/curve
      risk.py           POST /risk/ladder (+/direct), POST /risk/scenario (+/direct), POST /risk/bond
    schemas/
      health.py         HealthResponse
      extract.py        ExtractRequest, ExtractResponse
      assumptions.py    AssumptionsRequest, AssumptionsResponse
      quote.py          QuoteRequest, QuoteResponse
      price.py          PricingRequest, PricingResponse,
                        IRSDirectPriceRequest, IRSDirectPriceResponse,
                        IRSCashflowRequest, IRSCashflowResponse, IRSCashflowRow,
                        IRSDirectCashflowRequest, IRSDirectCashflowResponse,
                        IRSBreakdownRequest, IRSBreakdownResponse,
                        IRSDirectBreakdownRequest, IRSDirectBreakdownResponse,
                        IRSFairRateRequest, IRSFairRateResponse,
                        IRSDirectFairRateRequest, IRSDirectFairRateResponse,
                        FRAPriceRequest, FRAPriceResponse,
                        FXForwardPriceRequest, FXForwardPriceResponse,
                        FXSwapPriceRequest, FXSwapPriceResponse,
                        FXOptionPriceRequest, FXOptionPriceResponse,
                        EquityOptionPriceRequest, EquityOptionPriceResponse,
                        BondPricingRequest, BondPricingResponse,
                        BondYTMRequest, BondYTMResponse,
                        BondCashflowRequest, BondCashflowResponse, BondCashflowRow
      curve.py          CurveRequest, CurveResponse, MixedCurveRequest, MixedCurveResponse
      risk.py           LadderRequest, LadderResponse,
                        IRSDirectLadderRequest, IRSDirectLadderResponse,
                        ScenarioRequest, ScenarioResponse,
                        IRSDirectScenarioRequest, IRSDirectScenarioResponse,
                        BondRiskRequest, BondRiskResponse
    services/
      extractor.py      Regex-based NLP field extractor
      pricer.py         Shared curve-build helpers, flat-rate constants, _build_curve()
    main.py             FastAPI app factory, CORS middleware, router registration
  tests/
    test_health.py            5 tests
    test_extract.py          32 tests
    test_assumptions.py      21 tests
    test_quote.py            49 tests
    test_price.py            86 tests
    test_bond_price.py       41 tests
    test_bond_ytm.py         15 tests
    test_curve_endpoint.py   34 tests
    test_mixed_curve.py      56 tests
    test_risk_ladder.py      27 tests
    test_risk_scenario.py    26 tests
    test_bond_risk.py        58 tests
                             ──────
                      total: 902 tests (897 passing, 5 failing — regression date-drift tests under active remediation)
  requirements.txt      fastapi, uvicorn[standard], pydantic, httpx, pytest, pytest-asyncio, -e ../quant-core
  pytest.ini            pythonpath=., testpaths=tests
```

---

## `quant-core/`

**Role:** The quantitative engine. All curve construction, instrument definitions,
pricing logic, and risk analytics. Framework-agnostic Python — no FastAPI, no HTTP,
no Streamlit.

**Status:** Fully implemented. Production logic in every module.

### Module structure

```
quant-core/
  quant_core/
    conventions/
      day_count.py      DayCount enum, accrual_fraction() — ACT_365F, ACT_360, THIRTY_360
      business_day.py   Business-day adjustment conventions
      calendar.py       Holiday calendars (ZAR)
      schedule.py       Coupon/payment schedule generation

    curves/
      discount_curve.py DiscountCurve — pillar dates + discount factors, df(date)
      build_flat.py     flat_curve() — flat-rate proxy curve for quick pricing
      bootstrap_swap.py bootstrap_discount_curve_from_swaps() — vanilla IRS par-rate bootstrap
      bootstrap_mixed.py bootstrap_discount_curve_from_market_records() — deposit/FRA/swap mixed bootstrap

    instruments/
      irs.py            VanillaIRS — fixed-for-floating interest rate swap
      bond.py           FixedRateBond — fixed coupon bond (annual/semi/quarterly)

    pricing/
      irs_pricer.py     price_irs() — fixed leg vs floating leg NPV
      bond_pricer.py    price_bond() — full DCF pricer; BondResult (dirty, clean, accrued)
                        solve_bond_ytm() — bisection YTM solver (tol 1e-10)

    risk/
      ladder.py         pv01_ladder_irs() — bucketed key-rate PV01 for VanillaIRS
      scenario.py       run_parallel_curve_scenarios_irs() — parallel shift NPV table
      bond_risk.py      bond_dv01() — parallel +1bp bump-and-reprice
                        modified_duration() — DV01 / dirty_price × 10,000
                        macaulay_duration() — Σ(t_i × PV_i) / Σ(PV_i), analytical
                        bond_convexity() — central finite-difference (P- + P+ - 2P0) / (P0·dy²)

    marketdata/
      normalize_rates.py  Rate normalisation helpers for curve inputs

    schemas/
      market_inputs.py  MarketCurveInputs — typed deposit/FRA/swap rate input schema

    utils/
      date_utils.py     add_months(), date arithmetic helpers

  tests/
    test_conventions.py       86 tests — day-count, schedule, calendar
    test_market_inputs.py     80 tests — curve input validation
    test_bond_pricer.py       70 tests — DCF pricing, ZCB, accrued, schedule
    test_irs_pricer.py        51 tests — IRS NPV, payer/receiver, par-rate
    test_bootstrap_mixed.py   47 tests — mixed deposit/FRA/swap bootstrap
    test_bootstrap_swap.py    43 tests — vanilla swap bootstrap
    test_bond_risk.py         48 tests — DV01, modified duration, Macaulay, convexity
    test_curves.py            56 tests — DiscountCurve, flat_curve
    test_risk_ladder.py       36 tests — PV01 ladder
    test_risk_scenario.py     30 tests — scenario NPV
                              ─────
                       total: 678 tests (all passing)

  pyproject.toml        installed as editable package (pip install -e ../quant-core)
  README.md
```

---

## `streamlit-app/`

**Role:** Analyst workbench. Calls the FastAPI backend over HTTP. Provides interactive
forms, result panels, and assumption expanders for every implemented backend capability.

**Status:** Fully implemented. Five live pages with sidebar navigation.

### Navigation (sidebar radio selector)

#### Implemented pages

| Page | Backend calls | Capabilities |
|---|---|---|
| **IRS Pricing** | `POST /quote` | NLP prompt → extract fields → price ZAR IRS; shows NPV, PV01, assumptions |
| **Curve Builder** | `POST /curve` | Mixed deposit/FRA/swap bootstrap; shows pillar dates and discount factors |
| **Risk Ladder** | `POST /quote` → `POST /risk/ladder` | Bucketed key-rate PV01 for ZAR IRS; pillar-by-pillar signed PV01 table |
| **Scenario Analysis** | `POST /quote` → `POST /risk/scenario` | Parallel curve-shift NPV table; user-defined shift list in basis points |
| **Bond Pricing** | `POST /price/bond`, `POST /risk/bond`, `POST /price/bond/ytm` | DCF bond pricing; DV01, modified duration, Macaulay duration, convexity; flat YTM solver |

#### Planned pages (sidebar placeholders — not yet implemented)

- FRA Pricing
- Black-Scholes Options
- Greeks
- Monte Carlo Lab

### Bond Pricing page — metric display

The Bond Risk result panel shows 8 tiles across 2 rows:

- Row 1: Status | Dirty Price | DV01 | Modified Duration
- Row 2: Macaulay Duration | Convexity | Request ID | Instrument

```
streamlit-app/
  app.py           Main workbench (~955 lines)
  requirements.txt streamlit, requests
  README.md        Full usage guide and API reference
  tests/           9 tests (all passing) — live integration against running backend
```

---

## `docs/architecture/`

```
docs/architecture/
  repo_map.md          This file — structure, routes, capabilities, separation of concerns
  migration_audit.md   File-by-file classification (KEEP / MOVE / REFACTOR / RETIRE)
  build_sequence.md    Ordered build phases with exit criteria
```

---

## Live capabilities (as of 2026-03-25)

### Implemented — quant_core + backend + Streamlit

| Capability | quant_core module | Backend route |
|---|---|---|
| Flat discount curve | `curves/build_flat.py` | used internally |
| Vanilla swap bootstrap | `curves/bootstrap_swap.py` | `POST /curve/swap` |
| Mixed deposit/FRA/swap bootstrap | `curves/bootstrap_mixed.py` | `POST /curve` |
| IRS pricing (NPV, fixed/floating legs) | `pricing/irs_pricer.py` | `POST /price`, `POST /quote` |
| IRS key-rate PV01 ladder | `risk/ladder.py` | `POST /risk/ladder` |
| IRS parallel scenario analysis | `risk/scenario.py` | `POST /risk/scenario` |
| Fixed-rate bond DCF pricing | `pricing/bond_pricer.py` | `POST /price/bond` |
| Bond YTM (bisection) | `pricing/bond_pricer.py` | `POST /price/bond/ytm` |
| Bond DV01 | `risk/bond_risk.py` | `POST /risk/bond` |
| Bond modified duration | `risk/bond_risk.py` | `POST /risk/bond` |
| Bond Macaulay duration | `risk/bond_risk.py` | `POST /risk/bond` |
| Bond convexity | `risk/bond_risk.py` | `POST /risk/bond` |
| NLP field extraction | `services/extractor.py` | `POST /extract`, `POST /quote` |

### Planned / not yet implemented

| Capability | Notes |
|---|---|
| FRA pricing | quant_core stub only |
| Black-Scholes options | Not started |
| Greeks (delta, gamma, vega, theta) | Not started |
| Monte Carlo simulation | Not started |
| Swaption / cap / floor pricing | Not started |
| Credit risk analytics | Not started |
| Multi-currency curves | Not started |

---

## Dependency graph (current)

```
streamlit-app/app.py
    └── requests → backend API (all routes)

backend/app/api/*.py
    └── app/services/pricer.py      (_build_curve, helpers)
    └── app/services/extractor.py   (NLP field extraction)
    └── quant_core.curves           (DiscountCurve, bootstrap)
    └── quant_core.instruments      (VanillaIRS, FixedRateBond)
    └── quant_core.conventions      (DayCount, accrual_fraction)
    └── quant_core.pricing          (price_irs, price_bond, solve_bond_ytm)
    └── quant_core.risk             (pv01_ladder_irs, bond_dv01, macaulay_duration, …)
    └── quant_core.schemas          (MarketCurveInputs)

quant_core.*
    └── no imports from backend or streamlit-app
```
