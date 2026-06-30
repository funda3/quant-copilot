from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assumptions, curve, extract, health, portfolio, price, quote, risk

app = FastAPI(
    title="Quant Copilot API",
    description="Backend for the Quant Copilot MVP.",
    version="0.1.0",
)

# Minimal CORS for local browser-based development surfaces.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://localhost:3000",
        "http://localhost:3000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(extract.router)
app.include_router(price.router)
app.include_router(portfolio.router)
app.include_router(quote.router)
app.include_router(assumptions.router)
app.include_router(curve.router, prefix="/api")
app.include_router(risk.router)
