"""PriceUpdate and PriceCache."""

import threading

import pytest

from app.market import PriceCache, PriceUpdate


def make(price=101.0, previous=100.0, open_price=100.0):
    return PriceUpdate(
        ticker="AAPL", price=price, previous_price=previous, timestamp=1.0, open_price=open_price
    )


class TestPriceUpdate:
    def test_up(self):
        u = make(101.0, 100.0)
        assert u.direction == "up"
        assert u.change == 1.0
        assert u.change_percent == 1.0

    def test_down(self):
        u = make(99.0, 100.0)
        assert u.direction == "down"
        assert u.change == -1.0
        assert u.change_percent == -1.0

    def test_flat(self):
        u = make(100.0, 100.0)
        assert u.direction == "flat"
        assert u.change == 0.0
        assert u.change_percent == 0.0

    def test_change_percent_open(self):
        assert make(110.0, 105.0, open_price=100.0).change_percent_open == 10.0

    def test_zero_previous_and_open_are_safe(self):
        u = make(5.0, 0.0, open_price=0.0)
        assert u.change_percent == 0.0
        assert u.change_percent_open == 0.0

    def test_to_dict_keys(self):
        d = make().to_dict()
        assert set(d) == {
            "ticker",
            "price",
            "previous_price",
            "timestamp",
            "change",
            "change_percent",
            "direction",
            "open_price",
            "change_percent_open",
        }
        assert d["direction"] == "up"

    def test_immutable(self):
        with pytest.raises(AttributeError):
            make().price = 1.0  # type: ignore[misc]


class TestPriceCache:
    def test_first_update_sets_previous_and_open_to_price(self):
        cache = PriceCache()
        u = cache.update("AAPL", 190.0, timestamp=5.0)
        assert (u.price, u.previous_price, u.open_price, u.timestamp) == (190.0, 190.0, 190.0, 5.0)
        assert u.direction == "flat"

    def test_subsequent_update_tracks_previous_and_keeps_open(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("AAPL", 191.0)
        u = cache.update("AAPL", 189.0)
        assert u.previous_price == 191.0
        assert u.open_price == 190.0
        assert u.direction == "down"

    def test_default_timestamp(self):
        assert PriceCache().update("AAPL", 1.0).timestamp > 0

    def test_get_and_get_price(self):
        cache = PriceCache()
        assert cache.get("X") is None
        assert cache.get_price("X") is None
        cache.update("X", 3.5)
        assert cache.get("X").price == 3.5
        assert cache.get_price("X") == 3.5

    def test_get_all_is_a_copy(self):
        cache = PriceCache()
        cache.update("A", 1.0)
        snapshot = cache.get_all()
        snapshot.clear()
        assert "A" in cache

    def test_remove(self):
        cache = PriceCache()
        cache.update("A", 1.0)
        cache.remove("A")
        assert "A" not in cache
        assert len(cache) == 0
        cache.remove("A")  # no error

    def test_version_increments_on_mutation_only(self):
        cache = PriceCache()
        v0 = cache.version
        cache.update("A", 1.0)
        assert cache.version == v0 + 1
        cache.remove("missing")
        assert cache.version == v0 + 1
        cache.remove("A")
        assert cache.version == v0 + 2

    def test_reremove_resets_open_price(self):
        cache = PriceCache()
        cache.update("A", 1.0)
        cache.remove("A")
        assert cache.update("A", 2.0).open_price == 2.0

    def test_thread_safety(self):
        cache = PriceCache()

        def worker(n):
            for i in range(500):
                cache.update(f"T{n}", float(i))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(cache) == 8
        assert cache.version == 8 * 500
