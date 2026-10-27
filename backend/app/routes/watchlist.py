from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.services import (
    add_watchlist_ticker,
    get_watchlist_with_prices,
    normalize_ticker,
    remove_watchlist_ticker,
)

from .deps import MarketSourceDep, PriceCacheDep

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerRequest(BaseModel):
    ticker: str


@router.get("")
def list_watchlist(cache: PriceCacheDep) -> dict:
    return {"tickers": get_watchlist_with_prices(cache)}


@router.post("", status_code=201)
async def add_ticker(req: AddTickerRequest, source: MarketSourceDep) -> dict:
    try:
        ticker = normalize_ticker(req.ticker)
        added = await add_watchlist_ticker(ticker, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not added:
        raise HTTPException(status_code=409, detail=f"{ticker} is already on the watchlist")
    return {"ticker": ticker}


@router.delete("/{ticker}", status_code=204)
async def remove_ticker(ticker: str, source: MarketSourceDep) -> Response:
    try:
        normalized = normalize_ticker(ticker)
        removed = await remove_watchlist_ticker(normalized, source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"{normalized} is not on the watchlist")
    return Response(status_code=204)
