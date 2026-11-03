# ADR: PostgreSQL with row-level security before production

Status: accepted, 2026-11-03. Not yet implemented.

## Context

Phase 1 added tenants to Cipher Cover. Every business table has a `tenant_id`, and every query the backend runs filters by the caller's tenant (`backend/store.py`, the routes, `backend/auth.py`). The tests in `backend/tests/test_tenancy.py` show that a second tenant cannot read or change the first tenant's claims, policies, customers, runs, queue runs, traces, sign-offs or voice sessions.

That is isolation in the application only, on SQLite:

- **No row-level security.** SQLite has no RLS. If one query in the code forgets `AND tenant_id = ?`, the database returns every tenant's rows. Tests check the routes we have, not routes written later.
- **A default tenant on every column.** SQLite can only add a NOT NULL column with a default, so `tenant_id` defaults to `T-UNDERCOVER`. An insert that forgets the column lands in that tenant instead of failing.
- **One file, one writer.** All tenants share one database file, one set of file permissions and one writer at a time. A backup, restore or leaked file contains every tenant.
- **Threads and file locks.** Agent runs, queue runs and voice turns are threads in the backend process, writing through `sqlite3`. Since 2026-11-03 every connection uses WAL with a 30-second busy timeout, so reads don't wait for a writer. Code opens a connection for one step and never holds it across a model call. WAL still allows only one writer at a time and only one machine, so the later background sweeps (SLA timers, fraud rules) add to the contention. That is fine for a pilot, but it does not scale out to several backend processes.

## Decision

**Production with more than one tenant's data waits on PostgreSQL with row-level security on `tenant_id`.** Until then Cipher Cover is for development and single-tenant pilots. No doc, README or sales material may describe the current isolation as enterprise-grade.

The production setup must have:

1. PostgreSQL, through `psycopg`, which is already locked in `pyproject.toml`.
2. An RLS policy on every tenant table: `USING (tenant_id = current_setting('app.tenant_id'))` and the same `WITH CHECK`, with `FORCE ROW LEVEL SECURITY`.
3. The tenant set for each request and each service token (`SET LOCAL app.tenant_id`) from the principal that `backend/auth.py` already resolves.
4. An application database role that is not the owner and does not have `BYPASSRLS`. Migrations run as a separate role.
5. `tenant_id` with no default. An insert without a tenant fails.
6. Tests that run the cross-tenant suite against Postgres with RLS on, plus a test that a query with the tenant filter removed still returns only the caller's rows.

## Consequences

- The application filters stay. They become the second layer behind RLS, not the only one.
- The SQL uses `?` placeholders and a few SQLite-only features (`INSERT OR IGNORE`, `rowid` ordering, `ALTER TABLE ... ADD COLUMN` with a default). These must be ported, so the migration to Postgres is its own phase, not part of this upgrade.
- Until that phase is done, adding a second real tenant is a deployment decision someone must sign off, knowing these limits.
