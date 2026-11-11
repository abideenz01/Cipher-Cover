import pytest

from agent import tracing
from backend import auth, seed
from backend.tests import sessions
from backend.voice import routes


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """Give every test a freshly seeded database with a session for each user."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    # Tests run on SQLite, even with a developer's .env loaded.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEMO_PASSWORD", sessions.PASSWORD)
    # Tests never reach Langfuse, even with a developer's .env loaded.
    for key in tracing.KEYS:
        monkeypatch.delenv(key, raising=False)
    # Full-cost scrypt for seven demo users would slow every test down.
    monkeypatch.setattr(auth, "SCRYPT_N", 2**4)
    # Tests move the clock by hours; the idle timeout has tests of its own.
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "100000000")
    routes.TURNS.clear()
    seed.seed()
    sessions.install()
