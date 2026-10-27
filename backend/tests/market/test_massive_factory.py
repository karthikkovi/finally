"""MassiveDataSource (with a mocked REST client) and the source factory."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.market import (
    MarketDataSource,
    MassiveDataSource,
    PriceCache,
    SimulatorDataSource,
    create_market_data_source,
)


def snap(ticker, price, ts_ms=1_700_000_000_000):
    return SimpleNamespace(ticker=ticker, last_trade=SimpleNamespace(price=price, timestamp=ts_ms))


def make_source(snapshots=None, side_effect=None):
    cache = PriceCache()
    client = MagicMock()
    client.get_snapshot_all.return_value = snapshots or []
    if side_effect is not None:
        client.get_snapshot_all.side_effect = side_effect
    source = MassiveDataSource(api_key="key", price_cache=cache, poll_interval=60)
    return source, cache, client


class TestMassiveParsing:
    def test_process_snapshots_updates_cache(self):
        source, cache, _ = make_source()
        source._tickers = ["AAPL", "MSFT"]
        source._process_snapshots([snap("AAPL", 190.5), snap("MSFT", "420.25")])
        assert cache.get_price("AAPL") == 190.5
        assert cache.get_price("MSFT") == 420.25
        assert cache.get("AAPL").timestamp == 1_700_000_000.0

    def test_ignores_inactive_tickers(self):
        source, cache, _ = make_source()
        source._tickers = ["AAPL"]
        source._process_snapshots([snap("TSLA", 250.0)])
        assert "TSLA" not in cache

    def test_skips_malformed(self):
        source, cache, _ = make_source()
        source._tickers = ["AAPL", "MSFT", "GOOGL"]
        source._process_snapshots(
            [
                SimpleNamespace(ticker="AAPL", last_trade=None),
                snap("MSFT", "not-a-number"),
                snap("GOOGL", 175.0),
            ]
        )
        assert "AAPL" not in cache
        assert "MSFT" not in cache
        assert cache.get_price("GOOGL") == 175.0

    def test_missing_timestamp_uses_now(self):
        source, cache, _ = make_source()
        source._tickers = ["AAPL"]
        source._process_snapshots([snap("AAPL", 1.0, ts_ms=None)])
        assert cache.get("AAPL").timestamp > 1_700_000_000

    def test_none_snapshots(self):
        source, cache, _ = make_source()
        source._process_snapshots(None)
        assert len(cache) == 0


class TestMassiveLifecycle:
    async def test_start_polls_immediately(self):
        source, cache, client = make_source([snap("AAPL", 190.0)])
        with patch("app.market.massive_client.RESTClient", return_value=client):
            await source.start(["AAPL", "AAPL"])
        try:
            assert source.get_tickers() == ["AAPL"]
            assert cache.get_price("AAPL") == 190.0
            kwargs = client.get_snapshot_all.call_args.kwargs
            assert kwargs["tickers"] == ["AAPL"]
        finally:
            await source.stop()
        await source.stop()

    async def test_poll_failure_is_swallowed(self):
        source, cache, client = make_source(side_effect=RuntimeError("429"))
        with patch("app.market.massive_client.RESTClient", return_value=client):
            await source.start(["AAPL"])
        await source.stop()
        assert len(cache) == 0

    async def test_add_ticker_fetches_immediately(self):
        source, cache, client = make_source([snap("PYPL", 60.0)])
        with patch("app.market.massive_client.RESTClient", return_value=client):
            await source.start([])
            await source.add_ticker("PYPL")
            await source.add_ticker("PYPL")
        await source.stop()
        assert source.get_tickers() == ["PYPL"]
        assert cache.get_price("PYPL") == 60.0
        assert client.get_snapshot_all.call_count == 1  # empty start doesn't poll

    async def test_remove_ticker_drops_from_cache(self):
        source, cache, _ = make_source()
        source._tickers = ["AAPL"]
        cache.update("AAPL", 1.0)
        await source.remove_ticker("AAPL")
        assert source.get_tickers() == []
        assert "AAPL" not in cache


class TestFactory:
    def test_simulator_without_key(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)

    def test_simulator_with_blank_key(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "   ")
        assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)

    def test_massive_with_key(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "abc")
        source = create_market_data_source(PriceCache())
        assert isinstance(source, MassiveDataSource)
        assert isinstance(source, MarketDataSource)
