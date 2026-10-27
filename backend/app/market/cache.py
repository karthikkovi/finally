"""Thread-safe in-memory price cache shared by producers and consumers."""

from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Latest price per ticker, with a version counter for change detection."""

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version = 0

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker and return the resulting PriceUpdate."""
        with self._lock:
            ts = timestamp if timestamp is not None else time.time()
            previous = self._prices.get(ticker)
            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=previous.price if previous else price,
                timestamp=ts,
                open_price=previous.open_price if previous else price,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        with self._lock:
            update = self._prices.get(ticker)
            return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        """Monotonic counter, incremented on every mutation."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: object) -> bool:
        with self._lock:
            return ticker in self._prices
