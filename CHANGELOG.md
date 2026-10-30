# Changelog

All notable changes are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-30

### Added

- Claims API on FastAPI and SQLite, seeded from `data/`.
- Deterministic payout engine for section 10 of the policy wording.
- Claim agent on LangChain and OpenRouter with six API tools and a scripted stub.
- Handler sign-off for payouts over $1,000.00, with SLA tracking and send-back.
- Background agent runs with a stored, live-streamed trace.
- The Cipher Cover operations console in React and Vite, in dark and light themes.
- Optional voice mode with a voice agent, captions and rate limiting.
- Playwright end-to-end tests and CI.
