"""Start the agent's service: `uv run -m agent`.

It listens at UNDERCOVER_AGENT (default http://127.0.0.1:8002) and, on start,
carries on any claim that was stopped or signed off while it was away.
"""

import os
from urllib.parse import urlparse

import uvicorn

from agent import service

if __name__ == "__main__":
    address = urlparse(os.getenv("UNDERCOVER_AGENT") or service.DEFAULT_URL)
    uvicorn.run(
        service.app, host=address.hostname or "127.0.0.1", port=address.port or 8002
    )
