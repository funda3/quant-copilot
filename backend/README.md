# Quant Copilot V2 — Backend

FastAPI backend for the Quant Copilot V2 pricing API.

## Prerequisites

- **Python 3.11** — the venv **must** be created with Python 3.11.  All compiled
  extensions ship as `cp311` wheels; Python 3.13 cannot load them.
- Commands must be run from the `backend/` directory so that the relative
  path to `../quant-core` resolves correctly.

## Install

```bash
cd backend

# Windows — specify Python 3.11 explicitly to avoid a 3.13 system default
"C:\Users\Admin User\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# macOS / Linux
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` includes `-e ../quant-core` which installs the local
`quant-core` package in editable mode. No separate install step is required.

Verify:

```bash
python -c "import quant_core; print('ok')"
```

## Run

```powershell
# From backend/ directory
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001

# Absolute-path form (works from any directory)
& "C:\quant-copilot\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload --app-dir C:\quant-copilot\backend
```

API available at `http://127.0.0.1:8001`. Interactive docs at
`http://127.0.0.1:8001/docs`.

`8001` is the canonical local port for this repo. The Streamlit app hard-targets
`http://127.0.0.1:8001` and requires the backend to run on that port.

## Test

```bash
pytest tests\
```

## FX Forward route proof

`POST /price/fx-forward` expects the backend schema field
`notional_foreign`.

PowerShell example:

```powershell
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

`8001` is the canonical local port. Start the backend with
`.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001`
before running this proof.

## European FX Option route proof

`POST /price/fx-option` prices a vanilla European deliverable FX option under
the quote convention `domestic_currency/foreign_currency = domestic-currency
units per 1 foreign unit`.

Option convention:

- `call` = right to buy foreign / sell domestic at strike
- `put` = right to sell foreign / buy domestic at strike

PowerShell example:

```powershell
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
workspace the current live-proof target is typically `8001`, so the example
above uses `http://127.0.0.1:8001/price/fx-option`. If your local backend is
running elsewhere, change only the port and keep the route path and request
fields unchanged.

## European Equity Option route proof

`POST /price/equity-option` prices a vanilla European equity option under
Black-Scholes-Merton with a flat continuously compounded risk-free rate and
continuous dividend yield.

Use the backend schema field `quantity_shares` exactly as shown below. Do not
replace it with `quantity`, which is not part of the implemented request
contract.

Option convention:

- `call` = right to buy the underlying at strike on expiry
- `put` = right to sell the underlying at strike on expiry

Quantity convention:

- `quantity_shares` scales premium and Greeks by the number of underlying shares

PowerShell example:

```powershell
$body = @{
  valuation_date  = "2026-03-26"
  expiry_date     = "2026-09-26"
  spot_price      = 100.0
  strike_price    = 105.0
  risk_free_rate  = 0.05
  dividend_yield  = 0.02
  volatility      = 0.25
  quantity_shares = 1000
  option_type     = "call"
  position        = "long"
  currency        = "USD"
  day_count       = "ACT_365F"
  underlying_name = "ACME"
} | ConvertTo-Json

Invoke-RestMethod \
  -Uri "http://127.0.0.1:8001/price/equity-option" \
  -Method Post \
  -ContentType "application/json" \
  -Body $body
```

Use the port where the current backend instance is actually running. In this
workspace the current live-proof target is typically `8001`, so the example
above uses `http://127.0.0.1:8001/price/equity-option`. If your local backend
is running elsewhere, change only the port and keep the route path and request
fields unchanged. If `8001` returns `404 Not Found`, you are likely hitting a
different or stale backend process; rerun the same proof against the port of
the backend instance you just started.
