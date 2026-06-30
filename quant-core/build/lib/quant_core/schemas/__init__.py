"""
schemas — Pydantic models for quant-core inputs and outputs.

These are internal domain schemas, distinct from the API-layer schemas in
backend/app/schemas/ which are coupled to the HTTP contract.

Planned modules:
  trade.py          — IRSwap, Swaption, CapFloor, Bond dataclasses
  market.py         — MarketData snapshot
  result.py         — PricingResult, RiskResult

Status: PLACEHOLDER — not yet implemented.
"""
