import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Point app.db at a fresh temporary database file."""
    path = tmp_path / "nested" / "finally.db"
    monkeypatch.setenv("DB_PATH", str(path))
    return path
