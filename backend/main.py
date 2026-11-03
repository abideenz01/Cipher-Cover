"""The UnderCover backend."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from backend import (
    accounts,
    auth,
    claims,
    decisions,
    documents,
    queue_runs,
    runs,
    seed,
    signoff,
)
from backend.voice import routes as voice


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed an empty database on startup and free what a stopped backend left."""
    seed.seed()
    queue_runs.recover()
    yield


# The interactive docs and schema are served only with API_DOCS=1: they sit
# outside the routes, so the sign-in check on every operation would not cover them.
DOCS = os.getenv("API_DOCS") == "1"

app = FastAPI(
    title="UnderCover",
    lifespan=lifespan,
    dependencies=[Depends(auth.guard)],
    openapi_url="/openapi.json" if DOCS else None,
)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(voice.config_router)
app.include_router(voice.router)
app.include_router(claims.router)
app.include_router(decisions.router)
app.include_router(signoff.router)
app.include_router(queue_runs.router)
app.include_router(runs.router)
app.include_router(documents.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
