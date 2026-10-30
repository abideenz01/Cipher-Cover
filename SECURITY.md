# Security Policy

## Supported versions

Only the latest code on `main` receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue. Report it privately through [GitHub's private vulnerability reporting](https://github.com/abideenz01/Cipher-Cover/security/advisories/new).

Include what you found, how to reproduce it and the impact you expect. You'll get an acknowledgement within 72 hours.

## Security design

- Payouts over $1,000.00 cannot be made by the agent; they need a handler's sign-off.
- The API never returns customers' contact details, dates of birth or addresses.
- The agent reaches data only through the same API as the dashboard.
- Secrets live in `.env`, which is never committed.
- Claim documents are untrusted input to the model; treat any change to how they reach the agent as security-sensitive.
