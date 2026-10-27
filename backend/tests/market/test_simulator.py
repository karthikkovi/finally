"""GBMSimulator math/correlation/events and SimulatorDataSource lifecycle."""

import asyncio
import math

import numpy as np
import pytest

from app.market import GBMSimulator, MarketDataSource, PriceCache, SimulatorDataSource
from app.market.seed_prices import (
    CROSS_GROUP_CORR,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
)
from app.market.simulator import DEFAULT_DT


class TestGBMSimulator:
    def test_seed_prices(self):
        sim = GBMSimulator(tickers=["AAPL", "NVDA"], seed=1)
        assert sim.get_price("AAPL") == SEED_PRICES["AAPL"]
        assert sim.get_price("NVDA") == SEED_PRICES["NVDA"]

    def test_unknown_ticker_gets_random_seed_in_range(self):
        sim = GBMSimulator(tickers=["ZZZZ"], seed=1)
        assert 50 <= sim.get_price("ZZZZ") <= 300

    def test_step_returns_positive_rounded_prices(self):
        sim = GBMSimulator(tickers=list(SEED_PRICES), seed=42)
        for _ in range(200):
            prices = sim.step()
            assert set(prices) == set(SEED_PRICES)
            for p in prices.values():
                assert p > 0
                assert round(p, 2) == p

    def test_empty_step(self):
        assert GBMSimulator(seed=1).step() == {}

    def test_dt_is_half_second_of_trading_year(self):
        assert DEFAULT_DT == pytest.approx(0.5 / (252 * 6.5 * 3600))

    def test_single_step_matches_gbm_formula(self):
        """With one ticker (no Cholesky), the step must equal S*exp(drift + sigma*sqrt(dt)*Z)."""
        dt = 0.01
        sim = GBMSimulator(tickers=["AAPL"], dt=dt, event_probability=0.0, seed=7)
        z = np.random.default_rng(7).standard_normal(1)[0]
        mu, sigma = 0.05, 0.22
        expected = 190.0 * math.exp((mu - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * z)
        assert sim.step()["AAPL"] == round(expected, 2)

    def test_log_returns_have_expected_volatility(self):
        dt = 1e-4
        sim = GBMSimulator(tickers=["AAPL"], dt=dt, event_probability=0.0, seed=3)
        prev = sim._prices["AAPL"]
        returns = []
        for _ in range(5000):
            sim.step()
            cur = sim._prices["AAPL"]
            returns.append(math.log(cur / prev))
            prev = cur
        assert np.std(returns) / math.sqrt(dt) == pytest.approx(0.22, rel=0.05)

    def test_correlation_values(self):
        assert GBMSimulator.correlation("AAPL", "MSFT") == INTRA_TECH_CORR
        assert GBMSimulator.correlation("JPM", "V") == INTRA_FINANCE_CORR
        assert GBMSimulator.correlation("AAPL", "JPM") == CROSS_GROUP_CORR
        assert GBMSimulator.correlation("TSLA", "AAPL") == CROSS_GROUP_CORR
        assert GBMSimulator.correlation("ZZZ", "YYY") == CROSS_GROUP_CORR

    def test_realized_correlation(self):
        dt = 1e-4
        sim = GBMSimulator(tickers=["AAPL", "MSFT", "JPM"], dt=dt, event_probability=0.0, seed=11)
        rets = {t: [] for t in sim.get_tickers()}
        prev = dict(sim._prices)
        for _ in range(5000):
            sim.step()
            for t in rets:
                rets[t].append(math.log(sim._prices[t] / prev[t]))
            prev = dict(sim._prices)
        tech = np.corrcoef(rets["AAPL"], rets["MSFT"])[0, 1]
        cross = np.corrcoef(rets["AAPL"], rets["JPM"])[0, 1]
        assert tech == pytest.approx(INTRA_TECH_CORR, abs=0.05)
        assert cross == pytest.approx(CROSS_GROUP_CORR, abs=0.05)

    def test_cholesky_built_and_valid(self):
        sim = GBMSimulator(tickers=list(SEED_PRICES), seed=1)
        lower = sim._cholesky
        assert lower is not None
        corr = lower @ lower.T
        assert np.allclose(np.diag(corr), 1.0)
        assert GBMSimulator(tickers=["AAPL"], seed=1)._cholesky is None

    def test_events_cause_large_moves(self):
        sim = GBMSimulator(tickers=["AAPL"], dt=1e-12, event_probability=1.0, seed=5)
        before = sim._prices["AAPL"]
        sim.step()
        move = abs(sim._prices["AAPL"] / before - 1)
        assert 0.0199 <= move <= 0.0501

    def test_add_remove_ticker(self):
        sim = GBMSimulator(tickers=["AAPL"], seed=1)
        sim.add_ticker("MSFT")
        sim.add_ticker("MSFT")
        assert sim.get_tickers() == ["AAPL", "MSFT"]
        assert sim._cholesky.shape == (2, 2)
        sim.remove_ticker("AAPL")
        sim.remove_ticker("AAPL")
        assert sim.get_tickers() == ["MSFT"]
        assert sim.get_price("AAPL") is None
        assert set(sim.step()) == {"MSFT"}

    def test_deterministic_with_seed(self):
        a = GBMSimulator(tickers=["AAPL", "TSLA"], seed=9)
        b = GBMSimulator(tickers=["AAPL", "TSLA"], seed=9)
        for _ in range(20):
            assert a.step() == b.step()


class TestSimulatorDataSource:
    def test_is_market_data_source(self):
        assert isinstance(SimulatorDataSource(PriceCache()), MarketDataSource)

    async def test_start_seeds_cache_immediately(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=10)
        await source.start(["AAPL", "GOOGL"])
        try:
            assert cache.get_price("AAPL") == SEED_PRICES["AAPL"]
            assert cache.get_price("GOOGL") == SEED_PRICES["GOOGL"]
            assert source.get_tickers() == ["AAPL", "GOOGL"]
        finally:
            await source.stop()

    async def test_loop_updates_cache(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=0.01)
        await source.start(["AAPL"])
        v = cache.version
        await asyncio.sleep(0.1)
        await source.stop()
        assert cache.version > v

    async def test_stop_is_idempotent_and_halts_updates(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=0.01)
        await source.start(["AAPL"])
        await source.stop()
        await source.stop()
        v = cache.version
        await asyncio.sleep(0.05)
        assert cache.version == v

    async def test_add_and_remove_ticker(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=10)
        await source.start(["AAPL"])
        try:
            await source.add_ticker("PYPL")
            assert "PYPL" in source.get_tickers()
            assert cache.get_price("PYPL") is not None
            await source.add_ticker("PYPL")
            assert source.get_tickers().count("PYPL") == 1
            await source.remove_ticker("PYPL")
            assert "PYPL" not in source.get_tickers()
            assert "PYPL" not in cache
        finally:
            await source.stop()

    async def test_add_before_start(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache)
        assert source.get_tickers() == []
        await source.add_ticker("AAPL")
        assert cache.get_price("AAPL") == SEED_PRICES["AAPL"]
