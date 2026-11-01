"""The UnderCover backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import claims, decisions, documents, runs, seed, signoff
from backend.voice import routes as voice


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed an empty database on startup."""
    seed.seed()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.include_router(voice.config_router)
app.include_router(voice.router)
app.include_router(claims.router)
app.include_router(decisions.router)
app.include_router(signoff.router)
app.include_router(runs.router)
app.include_router(documents.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
