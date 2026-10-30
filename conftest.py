import pytest

from backend import seed


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """Give every test a freshly seeded database."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    seed.seed()
