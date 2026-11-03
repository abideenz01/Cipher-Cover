"""The offline evaluation of the claim agent against the handlers' decisions.

This package reads the answer keys in data/evals/ and data/security/, so it
lives outside backend/ and agent/: the backend never imports it and cannot
serve it, and the agent never sees it. It scores runs only after they finish.
"""
