# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.
7. The agent has four parts: the queue agent (`create_agent`), the claim agent's graph (`agent/graph.py`, whose nodes take the place of middleware), the tools that call the backend, and the agent's service (`agent/service.py`). Business rules stay in the backend; the graph never applies a limit itself.
