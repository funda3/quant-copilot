
# Quant Copilot — Streamlit Workbench

Sidebar-navigation workbench for ZAR IRS pricing, risk analytics, fixed-rate bond pricing, deterministic FX forward pricing, deterministic FX swap pricing, European FX option pricing, European equity option pricing, and a dedicated Portfolio / Scenario basket workflow.
Connects to the local FastAPI backend at `http://127.0.0.1:8001` for local live testing in this workspace.

---

## Prerequisites

- Python 3.11+
- The FastAPI backend must be running (see below)

---

## Install

```bash
cd streamlit-app
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Start the backend first

In a separate terminal:

```bash
cd backend
.venv\Scripts\activate          # or source .venv/bin/activate
uvicorn app.main:app --reload --port 8001
```

The backend target used by the Streamlit app in [streamlit-app/app.py](c:/quant-copilot/streamlit-app/app.py#L38)
is `http://127.0.0.1:8001` for local live testing in this workspace. Start the
backend on port `8001` when using the app live, or update that single client
target intentionally if you want to run the backend elsewhere.

---

## Run the Streamlit app

```bash
cd streamlit-app
.venv\Scripts\activate
streamlit run app.py
```

Opens at `http://localhost:8501` by default.

---

## Run the FRA smoke test

This smoke test exercises the Streamlit FRA pricing page in-process using
Streamlit's testing API and mocked deterministic FRA backend responses.
It proves both the flat and optional bootstrapped-curve FRA UI paths are
reachable, accept required inputs, trigger pricing, and render the expected
result block and key output fields.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_fra_smoke -v
```

## Run the Portfolio / Scenario smoke test

This smoke test exercises the dedicated Portfolio / Scenario page with mocked
backend responses. It verifies that the page is reachable from navigation,
supports JSON and pasted-table import flows, blocks malformed rows before
backend calls, posts to `POST /portfolio/value`, `POST /portfolio/scenario`,
and `POST /portfolio/risk`, and renders base/shocked/risk portfolio output
blocks with JSON and CSV export controls.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_portfolio_scenario_smoke -v
```

## Portfolio / Scenario import-export quick guide

- Position input mode supports `JSON`, `CSV upload`, and `Pasted CSV/Table`.
- Validation is row-level and runs before backend pricing calls. Errors are
    shown as a table with row number, position id, instrument type, and message.
- CSV or pasted tables must include `instrument_type` in the header and should
    provide instrument-specific columns that map to backend `fields`.
- Successful runs expose both JSON and CSV summary downloads for Value and
    Scenario outputs.

## Run the FX forward smoke test

This smoke test exercises the Streamlit FX Forward pricing page in-process
using Streamlit's testing API and a mocked deterministic backend response.
It proves the dedicated page is reachable, sends the expected structured
payload to `POST /price/fx-forward`, and renders the key output metrics.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_fx_forward_smoke -v
```

## Run the FX swap smoke test

This smoke test exercises the Streamlit FX Swap pricing page in-process using
Streamlit's testing API and a mocked deterministic backend response. It proves
the dedicated page is reachable, sends the expected structured payload to
`POST /price/fx-swap`, and renders the key output metrics.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_fx_swap_smoke -v
```

## Run the European FX option smoke test

This smoke test exercises the dedicated European FX Option page in-process
using Streamlit's testing API and a mocked deterministic backend response. It
proves the page is distinct in the navigation, sends the expected structured
payload to `POST /price/fx-option`, and renders the key output metrics.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_fx_option_smoke -v
```

## Run the European equity option smoke test

This smoke test exercises the dedicated European Equity Option page in-process
using Streamlit's testing API and a mocked deterministic backend response. It
proves the page is distinct in the navigation, sends the expected structured
payload to `POST /price/equity-option`, and renders the key output metrics.

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_equity_option_smoke -v
```

## Run a live European equity option backend proof

This is a direct backend proof for the implemented European Equity Option
contract. Use the backend schema fields exactly as shown below, including
`quantity_shares`, `option_type`, and `position`. Do not replace
`quantity_shares` with `quantity`, which is not part of the implemented
backend request contract.

Start the backend first on the port you intend to prove against:

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8001
```

Then, in a second terminal, run:

```powershell
cd backend
$body = @{
    valuation_date = "2026-03-26"
    expiry_date    = "2026-09-26"
    spot_price     = 100.0
    strike_price   = 105.0
    risk_free_rate = 0.05
    dividend_yield = 0.02
    volatility     = 0.25
    quantity_shares = 1000
    option_type    = "call"
    position       = "long"
    currency       = "USD"
    day_count      = "ACT_365F"
    underlying_name = "ACME"
} | ConvertTo-Json

Invoke-RestMethod \
    -Uri "http://127.0.0.1:8001/price/equity-option" \
    -Method Post \
    -ContentType "application/json" \
    -Body $body
```

Use the port where the current backend instance is actually running. In this
workspace the Streamlit app targets `http://127.0.0.1:8001` for local live
testing, so the example above uses that same backend target. If `8001`
returns `404 Not Found`, you are likely proving against a different backend
process than the one you intended to start.

## Run a live European FX option backend proof

This is a direct backend proof for the implemented European FX Option
contract. Use the backend schema fields exactly as shown below, including
`notional_foreign`, `option_type`, and `position`.

Start the backend first on the port you intend to prove against:

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8001
```

Then, in a second terminal, run:

```powershell
cd backend
$body = @{
    valuation_date    = "2026-03-26"
    expiry_date       = "2026-09-26"
    settlement_date   = "2026-09-26"
    spot_rate         = 18.25
    strike_rate       = 18.40
    domestic_rate     = 0.082
    foreign_rate      = 0.051
    volatility        = 0.18
    notional_foreign  = 1000000
    option_type       = "call"
    position          = "long"
    domestic_currency = "ZAR"
    foreign_currency  = "USD"
    day_count         = "ACT_365F"
} | ConvertTo-Json

Invoke-RestMethod \
    -Uri "http://127.0.0.1:8001/price/fx-option" \
    -Method Post \
    -ContentType "application/json" \
    -Body $body
```

Use the port where the current backend instance is actually running. In this
workspace the Streamlit app targets `http://127.0.0.1:8001` for local live
testing, so the example above uses that same backend target.

## Run a live FX forward backend proof

This is a direct backend proof for the implemented FX Forward contract. Use
the backend schema field `notional_foreign` exactly as shown below.

Start the backend first on the port you intend to prove against:

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8001
```

Then, in a second terminal, run:

```powershell
cd backend
$body = @{
    valuation_date        = "2026-03-26"
    maturity_date         = "2026-09-26"
    spot_rate             = 18.25
    domestic_rate         = 0.082
    foreign_rate          = 0.051
    notional_foreign      = 1000000
    contract_forward_rate = 18.40
    position              = "long_foreign"
    domestic_currency     = "ZAR"
    foreign_currency      = "USD"
    day_count             = "ACT_365F"
} | ConvertTo-Json

Invoke-RestMethod \
    -Uri "http://127.0.0.1:8001/price/fx-forward" \
    -Method Post \
    -ContentType "application/json" \
    -Body $body
```

Do not replace `notional_foreign` with `notional`. Do not switch this command
to a different port unless that is where the current backend instance is
actually running.

## Run the live FRA integration proof

Start the backend first, then run this Streamlit-side integration proof. It
drives the FRA page against the real local backend, verifies the backend call
succeeds, and checks that the Streamlit result block exposes meaningful FRA
output.

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8001
```

In a second terminal:

```bash
cd streamlit-app
.venv\Scripts\python.exe -m unittest tests.test_fra_live_integration -v
```

---

## Navigation

The left sidebar contains a radio selector with the eleven implemented pages.
Selecting a page replaces the main panel content — only controls relevant to
that workflow are shown.  Below the implemented pages the sidebar lists two
future placeholders (not yet implemented).

### Implemented pages

| Page | Status | Backend calls |
|---|---|---|
| **IRS Pricing** | ✅ Implemented | `POST /quote`, `POST /price/irs`, `POST /price/irs/cashflows`, `POST /price/irs/cashflows/direct`, `POST /price/irs/breakdown`, `POST /price/irs/breakdown/direct`, `POST /price/irs/fair-rate` |
| **FRA Pricing** | ✅ Implemented | `POST /price/fra` |
| **FX Forward Pricing** | ✅ Implemented | `POST /price/fx-forward` |
| **FX Swap Pricing** | ✅ Implemented | `POST /price/fx-swap` |
| **European FX Option** | ✅ Implemented | `POST /price/fx-option` |
| **European Equity Option** | ✅ Implemented | `POST /price/equity-option` |
| **Curve Builder** | ✅ Implemented | `POST /api/curve` |
| **Risk Ladder** | ✅ Implemented | `POST /quote` → `POST /risk/ladder` |
| **Scenario Analysis** | ✅ Implemented | `POST /quote` → `POST /risk/scenario` |
| **Portfolio / Scenario** | ✅ Implemented | `POST /portfolio/value`, `POST /portfolio/scenario`, `POST /portfolio/risk`, `POST /portfolio/scenario-compare` |
| **Bond Pricing** | ✅ Implemented | `POST /price/bond`, `POST /risk/bond`, `POST /price/bond/ytm` |

### Planned pages (sidebar placeholders only)

| Page | Status |
|---|---|
| Greeks | Coming soon |
| Monte Carlo Lab | Coming soon |

---

## Page reference

### IRS Pricing

Enter a natural-language trade description and click **Run Quote**.

Supported example:
```
Price a 5Y ZAR payer swap, 250m notional, quarterly JIBAR
```

The backend extractor parses the prompt and prices the trade. Results show:
- Extraction status and price status
- NPV (price) and PV01
- Extracted fields, assumptions, warnings, and missing fields

An **Optional Bootstrapped Curve Inputs** expander is available on this page.
When expanded and the checkbox is enabled, the quote is priced off a
bootstrapped mixed deposit/FRA/swap curve instead of the flat 8% proxy.

After running a quote, two additional buttons become available:

#### Show IRS Cashflows

Calls `POST /price/irs/cashflows` using the trade fields extracted from the
last quote.  Displays a full 12-column fixed-leg payment schedule: payment
date, accrual start/end, year fraction, fixed rate, notional, fixed cashflow,
total cashflow, discount factor, PV, and time-to-payment (years).

#### Show IRS Breakdown

Calls `POST /price/irs/breakdown` using the same cached trade fields.  Displays
a desk-level NPV decomposition:

| Field | Description |
|---|---|
| **Fixed Leg PV** | Present value of the fixed leg (same formula as `price_irs`) |
| **Floating Leg PV** | PV under the par-floating approximation |
| **NPV** | Net present value (payer = float − fixed; receiver = fixed − float) |
| **Payments** | Number of fixed-leg payment periods |
| **Curve source** | `flat_fallback` or `bootstrapped_mixed_curve` |
| **Floating leg method** | Always `par_floating_approximation` in this release |

#### Solve Fair Rate

Calls `POST /price/irs/fair-rate` using the same cached trade fields.  Solves
for the par swap rate analytically:

    fair_rate = PV_float / (notional × fixed_leg_annuity)

| Field | Description |
|---|---|
| **Fair Rate** | Par fixed rate displayed as a percentage (e.g. 7.9823%) |
| **Fixed-Leg Annuity** | Σ τ_i × df(t_i) — the denominator of the fair-rate formula |
| **Curve source** | `flat_fallback` or `bootstrapped_mixed_curve` |

#### Price Structured IRS (Direct)

Calls `POST /price/irs` directly from explicit UI inputs — no natural-language
prompt or previous quote required.

All fields are visible and editable on the page:

| Field | Description |
|---|---|
| **Direction** | `payer` or `receiver` |
| **Payment frequency** | `quarterly`, `semiannual`, or `annual` |
| **Tenor** | e.g. `5Y`, `10Y` |
| **Notional** | Numeric notional in ZAR |
| **Fixed rate** | Optional decimal (e.g. `0.085`); defaults to 8.5% if blank |

An **Optional Bootstrapped Curve Inputs** expander is available on this
section with its own independent widget keys.

Results show:
- **NPV (Price)** — net present value in ZAR
- **PV01** — sensitivity to +1bp parallel curve shift
- **Curve source** — `flat_fallback` or `bootstrapped_mixed_curve`
- Assumptions and warnings

#### Show Structured IRS Cashflows

Calls `POST /price/irs/cashflows/direct` using the same Section G widget
inputs.  Displays a full 11-column fixed-leg payment schedule without
requiring a prior quote.

#### Show Structured IRS Breakdown

Calls `POST /price/irs/breakdown/direct` using the same Section G widget
inputs.  Displays a desk-level NPV decomposition without requiring a prior
quote:

| Field | Description |
|---|---|
| **Fixed Leg PV** | Present value of the fixed leg |
| **Float Leg PV** | PV under the par-floating approximation |
| **NPV** | Net present value (payer = float − fixed; receiver = fixed − float) |
| **Payments** | Number of fixed-leg payment periods |
| **Curve** | `flat_fallback` or `bootstrapped_mixed_curve` |
| **Float Method** | Always `par_floating_approximation` in this release |

#### Solve Structured Fair Rate

Calls `POST /price/irs/fair-rate/direct` using the same Section G widget
inputs.  Solves for the par swap rate without requiring a prior quote.

| Field | Description |
|---|---|
| **Fair Rate** | Fixed rate at which swap NPV = 0 (displayed as %) |
| **Fixed Leg Annuity** | Σ τ_i × df(t_i) — denominator of the fair-rate formula |
| **Curve** | `flat_fallback` or `bootstrapped_mixed_curve` |

If `fixed_rate` was supplied in the structured IRS fields, it is accepted but
ignored during solving, and a warning is shown confirming this.

#### Run Structured Ladder

Calls `POST /risk/ladder/direct` using the same Section G widget inputs and a
comma-separated bucket list.  Returns the signed key-rate PV01 ladder without
requiring a prior quote.

| Field | Description |
|---|---|
| **Request ID** | Echoed caller id or generated UUID |
| **Status** | `indicative` on success |
| **Total \|PV01\|** | Sum of absolute bucket PV01 values |
| **Bucket ladder table** | Signed PV01 per requested tenor bucket |

The bucket list defaults to `1,2,3,5,7,10`, matching the quote-style ladder page.

#### Run Structured Scenarios

Calls `POST /risk/scenario/direct` using the same Section G widget inputs and a
comma-separated shift list.  Returns parallel curve-shift NPVs without
requiring a prior quote.

| Field | Description |
|---|---|
| **Request ID** | Echoed caller id or generated UUID |
| **Status** | `indicative` on success |
| **Base NPV** | NPV at `0bp` shift |
| **Scenario table** | Shift, NPV, and change vs base |

The shift list defaults to `-200,-100,-50,0,50,100,200`, matching the quote-style scenario page.

#### Curve input format


**Deposits** — `NM rate`
```
1M 0.078
3M 0.079
6M 0.080
```

**FRAs** — `SxE rate`
```
6x9 0.081
9x12 0.0815
```

**Swaps** — `NY rate`
```
2Y 0.082
3Y 0.083
5Y 0.085
```

Rates can be expressed as decimals (`0.078`) or percentages (`7.8%`).

---

### Curve Builder

Build and inspect a bootstrapped discount curve directly. Fill in the
deposit/FRA/swap market ladder and click **Build Curve** to call
`POST /api/curve`.

Results show:
- Valuation date and pillar count
- A table of pillar dates with corresponding discount factors

---

### FRA Pricing

Price a deterministic forward rate agreement directly from explicit trade
inputs. The page exposes:

| Field | Description |
|---|---|
| **Valuation date** | FRA pricing as-of date |
| **Start date** | FRA accrual start date |
| **End date** | FRA accrual end and payment date |
| **Notional** | FRA contract notional |
| **Contract rate** | Fixed FRA rate as a decimal |
| **Day count** | FRA accrual day-count convention |
| **Position** | `payer` = pay fixed / receive floating, `receiver` = receive fixed / pay floating |

An **Optional Bootstrapped Curve Inputs** expander is available on the page.
When enabled, the request is priced off the existing mixed deposit/FRA/swap
bootstrapped curve path. Otherwise, the backend uses the flat 8% fallback
curve with exact FRA start and end pillars.

Click **Price FRA** to call `POST /price/fra`. The page displays:

- Forward rate
- Year fraction
- Discount factor to payment
- Undiscounted payoff
- Present value
- Curve source
- Assumptions
- Warnings

---

### FX Forward Pricing

Price a deterministic FX forward directly from explicit trade and market-rate
inputs. The page exposes:

| Field | Description |
|---|---|
| **Valuation date** | FX forward pricing as-of date |
| **Maturity date** | Forward settlement date |
| **Foreign notional** | Contract notional in the foreign currency |
| **Spot rate** | Domestic-currency units per 1 foreign currency unit |
| **Contract forward rate** | Forward delivery rate under the same quote convention |
| **Domestic rate** | Flat annualized simple rate for the domestic currency |
| **Foreign rate** | Flat annualized simple rate for the foreign currency |
| **Domestic currency** | 3-letter ISO code for PV/reporting currency |
| **Foreign currency** | 3-letter ISO code for underlying notional currency |
| **Day count** | Year-fraction convention between valuation and maturity |
| **Position** | `long_foreign` = buy foreign / sell domestic; `short_foreign` = opposite |

Click **Price FX Forward** to call `POST /price/fx-forward`. The page displays:

- Implied forward rate
- Present value in domestic currency
- Year fraction
- Domestic and foreign discount factors
- Forward points
- Undiscounted payoff
- Rate source
- Assumptions
- Warnings

For manual backend proofs of this page contract, use the request field
`notional_foreign` and target the same backend URL the app is configured to
use when it is pointed at the current backend instance. In this workspace,
that local live-test target is `http://127.0.0.1:8001/price/fx-forward`.

---

### FX Swap Pricing

Price a deterministic deliverable FX swap directly from explicit trade and
market-rate inputs. The page exposes:

| Field | Description |
|---|---|
| **Valuation date** | FX swap pricing as-of date |
| **Near settlement date** | Near-leg settlement date |
| **Far settlement date** | Far-leg settlement date |
| **Foreign notional** | Contract notional in the foreign currency |
| **Spot rate** | Domestic-currency units per 1 foreign currency unit |
| **Near rate** | Near-leg exchange rate under the same quote convention |
| **Far rate** | Far-leg exchange rate under the same quote convention |
| **Domestic discount rate** | Flat annualized simple domestic discount rate |
| **Domestic currency** | 3-letter ISO code for PV/reporting currency |
| **Foreign currency** | 3-letter ISO code for underlying notional currency |
| **Day count** | Year-fraction convention between valuation and settlement dates |
| **Position** | `long_foreign` = receive foreign / pay domestic on the near leg, then reverse on the far leg; `short_foreign` = opposite |

Click **Price FX Swap** to call `POST /price/fx-swap`. The page displays:

- Near year fraction
- Far year fraction
- Near and far domestic discount factors
- Near and far leg domestic values
- Swap points
- Present value in domestic currency
- Rate source
- Assumptions
- Warnings

---

### European FX Option

Price a vanilla European deliverable FX option directly from explicit trade
and market inputs. The page exposes:

| Field | Description |
|---|---|
| **Valuation date** | FX option pricing as-of date |
| **Expiry date** | European exercise date |
| **Settlement date** | Optional delivery date; if omitted or cleared, the backend defaults it to expiry |
| **Foreign notional** | Contract notional in the foreign currency |
| **Spot rate** | Domestic-currency units per 1 foreign currency unit |
| **Strike rate** | Option strike under the same quote convention |
| **Domestic rate** | Flat annualized domestic interest rate input |
| **Foreign rate** | Flat annualized foreign interest rate input |
| **Volatility** | Flat Black/Garman-Kohlhagen volatility input |
| **Option type** | `call` = right to buy foreign / sell domestic; `put` = opposite |
| **Position** | `long` = own the option; `short` = written option |
| **Domestic currency** | 3-letter ISO code for PV/reporting currency |
| **Foreign currency** | 3-letter ISO code for underlying notional currency |
| **Day count** | Year-fraction convention between valuation, expiry, and settlement dates |

Click **Price European FX Option** to call `POST /price/fx-option`. The page displays:

- Premium in domestic currency
- Premium converted to foreign currency at current spot
- Delta, gamma, and vega
- Expiry and settlement year fractions
- Forward rate
- Domestic and foreign discount factors
- Model source
- Assumptions
- Warnings

For manual backend proofs of this page contract, use the same local live-test
backend target as the app when applicable: `http://127.0.0.1:8001/price/fx-option`.

---

### Risk Ladder

Compute a bucketed key-rate PV01 ladder for an IRS described by a
natural-language prompt.

1. Fill in a trade prompt.
2. Optionally adjust **Bucket years** (default `1,2,3,5,7,10`).
3. Optionally enable the bootstrapped curve inputs expander.
4. Click **Run Ladder**.

Internally: `POST /quote` (extract fields) → `POST /risk/ladder` (compute ladder).

Results show:
- Status, total |PV01|, and request ID
- **Bucket | Signed PV01 | % of Total Abs PV01** table
- Backend warnings and assumptions

> Bucket years beyond the curve domain return `0.0` PV01.

---

### Scenario Analysis

Compute parallel curve-shift NPVs for an IRS.

1. Fill in a trade prompt.
2. Optionally adjust **Scenario shifts (bps)** (default `-200,-100,-50,0,50,100,200`).
3. Optionally enable the bootstrapped curve inputs expander.
4. Click **Run Scenarios**.

Internally: `POST /quote` (extract fields) → `POST /risk/scenario` (compute scenarios).

Results show:
- Status, base NPV (at 0 bp), and request ID
- **Shift | NPV | Change vs Base** table
- Backend warnings and assumptions

---

### Portfolio / Scenario

Dedicated basket workflow for base valuation, shocked revaluation,
multi-scenario comparison, and finite-difference risk decomposition.

Contract notes for manual JSON entry:
- Position entries use `fields` for instrument-specific request fields.
- Scenario requests use `shocks` (not `scenario`).
- Route paths are `POST /portfolio/value`, `POST /portfolio/scenario`,
  `POST /portfolio/risk`, and `POST /portfolio/scenario-compare`.

1. Enter **Portfolio name** and **Valuation date**.
2. Edit **Positions JSON (list)** as needed.
3. Click **Value Portfolio** for base valuation.
4. Edit **Scenario shocks JSON** and click **Run Portfolio Scenario** for shocked results.
5. Choose **Scenario pack** and click **Run Scenario Pack** for side-by-side
   multi-scenario comparison.
6. Click **Run Portfolio Risk** for first-order portfolio sensitivities.

Results show:
- Position-level base/shocked PV with warnings
- Total portfolio PV and shocked total
- Delta vs base at position and portfolio level
- Grouped totals by instrument type and asset class
- Grouped delta by asset class for scenario runs
- Largest positive contributors and largest negative contributors by position
- A warning summary for ignored shocks, unsupported rows, and valuation warnings
- Grounded scenario interpretation derived from returned contribution and warning data
- Scenario pack comparison with summary, grouped delta by instrument type and
  asset class, position deltas by scenario, contributor/loser rows, warnings,
  and JSON/CSV exports
- Portfolio risk decomposition with rates, FX spot, equity spot, and volatility sensitivities
- Grouped sensitivities by instrument type and asset class
- Position-level sensitivities and largest risk contributors by dimension

Default scenario pack:
- `Core Market Moves`: Rates Up/Down (+/-100bp), FX Up/Down (+/-5%), Equity
  Up/Down (+/-5%), Vol Up (+5%), and Combined Stress (rates +100bp, FX +5%,
  equity -5%, vol +5%).

Risk sensitivity conventions:
- `rates_sensitivity`: PV change for a parallel +1bp rate move.
- `fx_spot_sensitivity`: PV change for a +1% FX spot move.
- `equity_spot_sensitivity`: PV change for a +1% equity spot move.
- `vol_sensitivity`: PV change for a +1 vol point move (`volatility + 0.01`).

---

### Bond Pricing

DCF pricing, risk, and YTM solving for a plain fixed-rate bond. All three
actions — **Price Bond**, **Run Bond Risk**, and **Solve YTM** — share the
same input fields on a single page.

**Inputs:**

| Field | Description | Default |
|---|---|---|
| Valuation date | ISO-8601 date (YYYY-MM-DD) | `2024-01-01` |
| Issue date | Bond issuance date | `2024-01-01` |
| Maturity date | Final redemption date | `2029-01-01` |
| Face value | Par / notional amount | `1,000,000` |
| Coupon rate | Annual coupon rate as a decimal | `0.085` |
| Coupon frequency | `annual`, `semiannual`, or `quarterly` | `annual` |
| Day count | `ACT_365F`, `ACT_360`, `30_360`, `ACT_ACT_ISDA` | `ACT_365F` |
| Market Dirty Price | Observed full (dirty) market price — used only by **Solve YTM** | `1,000,000` |

An **Optional Bootstrapped Curve Inputs** expander is available on this page.
When enabled, the **Price Bond** and **Run Bond Risk** buttons use the
bootstrapped curve; the **Solve YTM** button always uses the flat simple-rate
convention regardless.

#### Price Bond

Calls `POST /price/bond`. Results show:
- Status, clean price, dirty price, accrued interest
- Remaining coupon count, request ID
- Backend assumptions and warnings

#### Run Bond Risk

Calls `POST /risk/bond`. Results show:
- Status, dirty price, DV01 (per +1 bp), modified duration (years), Macaulay duration (years), convexity (years²)
- Request ID, instrument type
- Backend assumptions and warnings

> **DV01** is the decrease in dirty price for a parallel +1 bp upward shift in
> continuously-compounded zero rates.  
> **Modified duration** = DV01 / dirty_price × 10,000.  
> **Macaulay duration** = Σ(t_i × PV_i) / Σ(PV_i) — weighted-average time to cashflows
> measured using the bond's own day-count convention.  
> **Convexity** = (P_minus + P_plus − 2 × P0) / (P0 × dy²) — central finite-difference
> using the same ±1 bp parallel CC zero-rate bump.

#### Solve YTM

Calls `POST /price/bond/ytm`. Solves for the flat annual yield *y* that
satisfies `df(t) = 1 / (1 + y × τ)` (simple-rate convention) and reproduces
the supplied **Market Dirty Price**.  A deterministic bisection method is used
(tolerance 1e-10 price units).

Results show:
- Status (`solved` or `error`), market dirty price (echoed), YTM (as %)
- Backend assumptions and warnings

---

## What each button does

| Button | Backend call | Purpose |
|---|---|---|
| **Run Quote** | `POST /quote` | NLP extraction + IRS pricing |
| **Build Curve** | `POST /api/curve` | Bootstrap discount curve from market inputs |
| **Run Ladder** | `POST /quote` → `POST /risk/ladder` | Bucketed PV01 ladder for IRS |
| **Run Scenarios** | `POST /quote` → `POST /risk/scenario` | Parallel curve-shift scenario NPV table |
| **Value Portfolio** | `POST /portfolio/value` | Base basket valuation with position-level PV and grouped totals |
| **Run Portfolio Scenario** | `POST /portfolio/scenario` | Shocked basket valuation and delta-to-base report |
| **Run Scenario Pack** | `POST /portfolio/scenario-compare` | Predefined multi-scenario comparison with grouped and position deltas |
| **Run Portfolio Risk** | `POST /portfolio/risk` | Finite-difference portfolio sensitivities by position, instrument type, and asset class |
| **Price Bond** | `POST /price/bond` | Fixed-rate bond: clean price, dirty price, accrued interest |
| **Run Bond Risk** | `POST /risk/bond` | Fixed-rate bond: DV01, modified duration, Macaulay duration, and convexity |
| **Solve YTM** | `POST /price/bond/ytm` | Flat annual yield-to-maturity from observed dirty price |
| **Show IRS Cashflows** | `POST /price/irs/cashflows` | Fixed-leg payment schedule (requires a prior Run Quote) |
| **Show IRS Breakdown** | `POST /price/irs/breakdown` | Desk-level NPV decomposition: fixed PV, floating PV, NPV, curve source, method label (requires a prior Run Quote) |
| **Solve Fair Rate** | `POST /price/irs/fair-rate` | Par swap rate: fair_rate and fixed_leg_annuity (requires a prior Run Quote) |
| **Show Structured IRS Cashflows** | `POST /price/irs/cashflows/direct` | Fixed-leg cashflow schedule from structured inputs — no prior quote needed |
| **Show Structured IRS Breakdown** | `POST /price/irs/breakdown/direct` | Desk-level NPV decomposition from structured inputs — no prior quote needed |
| **Solve Structured Fair Rate** | `POST /price/irs/fair-rate/direct` | Par swap rate from structured inputs — no prior quote needed |
| **Run Structured Ladder** | `POST /risk/ladder/direct` | Key-rate PV01 ladder from structured inputs — no prior quote needed |
| **Run Structured Scenarios** | `POST /risk/scenario/direct` | Parallel curve-shift NPV table from structured inputs — no prior quote needed |

---

## Why separate from the backend

The Streamlit workbench is a developer and quant desk tool for model validation,
exploratory analysis, and rapid prototyping of new pricing logic before it is
promoted into `quant-core`.

---

## Dependencies

- `streamlit >= 1.32`
- `requests`

