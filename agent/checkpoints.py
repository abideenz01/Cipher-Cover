"""Where the claim agent saves its progress after every step.

With DATABASE_URL set, progress goes to LangGraph's Postgres checkpointer in the
same database and schema as the backend's tables, through one connection, so a
claim stopped partway carries on from its last step in a later process. Without
it, progress is kept in memory for this process only, which is how the tests run.
"""

import os
from functools import cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

CONNECTIONS = 1
MEMORY = InMemorySaver()


def durable() -> bool:
    """Say whether progress outlives this process."""
    return bool(os.getenv("DATABASE_URL"))


def saver() -> BaseCheckpointSaver[str]:
    """Return the checkpointer for this process."""
    conninfo = os.getenv("DATABASE_URL")
    if not conninfo:
        return MEMORY
    return postgres(conninfo, os.getenv("DATABASE_SCHEMA") or "undercover")


@cache
def postgres(conninfo: str, schema: str) -> PostgresSaver:
    """Open the Postgres checkpointer once, in the schema, and make its tables."""

    def configure(conn: Connection) -> None:
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))

    pool = ConnectionPool(
        conninfo,
        min_size=CONNECTIONS,
        max_size=CONNECTIONS,
        open=True,
        configure=configure,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    checkpointer = PostgresSaver(pool)  # pyright: ignore[reportArgumentType]
    checkpointer.setup()
    return checkpointer
