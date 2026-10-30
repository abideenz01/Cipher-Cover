# Contributing to Cipher Cover

Thanks for helping. This guide covers setup, the workflow and what a good pull request looks like.

## Setup

```bash
uv sync
npm install        # also installs the lefthook pre-commit hook and Playwright's Chromium
cp .env.example .env
```

## Workflow

1. Open an issue first for anything larger than a small fix, so the approach can be agreed.
2. Branch from `main`: `feat/<short-name>`, `fix/<short-name>` or `docs/<short-name>`.
3. Follow [docs/CODE_STANDARDS.md](docs/CODE_STANDARDS.md) and add tests with the change.
4. Run `npm run check` before pushing. It must pass.
5. Open a pull request and fill in the template.

## Commit messages

Use the [Conventional Commits](https://www.conventionalcommits.org/) style:

```text
feat(agent): add a tool to fetch prior claims
fix(payout): apply the excess once per claim
docs: explain the sign-off SLA
```

## Standards at a glance

- Python: ruff formatting and linting, pyright types, pytest with at least 80% coverage.
- TypeScript: Prettier, ESLint, strict `tsc`, vitest with at least 80% coverage.
- Every API operation has an `operation_id`, a one-line docstring and no optional inputs.
- Never return a customer's email, phone, date of birth or address from the API.
- Never commit secrets. `.env` is ignored; add new settings to `.env.example`.

## Reporting bugs

Use the bug report template and include steps to reproduce, what you expected and what happened.
