# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain's `create_agent` on OpenRouter, in two parts with entry points that take ids: the queue agent, `run_queue(queue_run_id)` in `agent/queue.py`, which plans the run as a to-do list and hands each claim to a fresh claim agent, and the claim agent, `run(claim_id, thread_id)` in `agent/main.py`, which works one claim. The thread id is the claim run's id. Both reach claims, the wording and the manual (one section at a time) and their instructions only through the backend's API. They use LangChain's own middleware: `ModelRetryMiddleware` for provider errors and `ModelCallLimitMiddleware` for step limits. No other agent framework. They use `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
