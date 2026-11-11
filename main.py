from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Literal

app = FastAPI(title="ProfitBot API", version="0.3")

class ProductScore(BaseModel):
    demand: int = Field(ge=0, le=100)
    competition: int = Field(ge=0, le=100)
    estimated_margin: float = Field(ge=-100, le=100)

class ProfitInput(BaseModel):
    sell_price: float = Field(gt=0)
    product_cost: float = Field(ge=0)
    shipping: float = Field(ge=0)
    platform_fee_percent: float = Field(ge=0, le=100)
    payment_fee_percent: float = Field(ge=0, le=100)
    returns_reserve_percent: float = Field(ge=0, le=100)
    other_costs: float = Field(ge=0, default=0)

@app.get("/health")
def health():
    return {"status": "ok", "version": "0.3", "integrations": "not_connected"}

@app.post("/product/score")
def score(p: ProductScore):
    value = p.demand * .45 + (100 - p.competition) * .35 + max(0, min(100, p.estimated_margin)) * .20
    return {"score": round(value, 1), "label": "prototype heuristic; not a verified market signal"}

@app.post("/profit/calculate")
def profit(p: ProfitInput):
    fees = p.sell_price * (p.platform_fee_percent + p.payment_fee_percent + p.returns_reserve_percent) / 100
    net = p.sell_price - p.product_cost - p.shipping - p.other_costs - fees
    return {
        "estimated_net_profit": round(net, 2),
        "estimated_margin_percent": round(net / p.sell_price * 100, 2),
        "currency": "USD",
        "warning": "Estimate only. Verify actual provider fees, taxes, duties, refunds, chargebacks and supplier terms."
    }
