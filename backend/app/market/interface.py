"""Abstract interface implemented by every market data source."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Produces price updates for a set of tickers and writes them into a PriceCache.

    Lifecycle: ``start(tickers)`` -> ``add_ticker`` / ``remove_ticker`` -> ``stop()``.
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop producing updates and release resources. Safe to call twice."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set (no-op if already present)."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and drop it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the currently active tickers."""
