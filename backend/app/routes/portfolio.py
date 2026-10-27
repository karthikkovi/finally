from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import TradeError, execute_trade, get_history, get_portfolio

from .deps import PriceCacheDep

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: str  # validated by execute_trade so bad values get a 400 with a readable message


@router.get("")
def portfolio(cache: PriceCacheDep) -> dict:
    return get_portfolio(cache)


@router.post("/trade")
def trade(req: TradeRequest, cache: PriceCacheDep) -> dict:
    try:
        executed = execute_trade(req.ticker, req.side, req.quantity, cache)
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"trade": executed, "portfolio": get_portfolio(cache)}


@router.get("/history")
def history() -> dict:
    return {"snapshots": get_history()}
