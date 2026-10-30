# Architecture

Cipher Cover has three parts: a FastAPI backend that owns the data and every business rule, a claim agent that decides claims through the backend's API, and a React console for claims handlers.

## Components

```mermaid
flowchart TB
    subgraph Browser
        D[Dashboard<br/>React + Vite]
        VP[Speech provider<br/>browser or stub]
    end

    subgraph Backend [Backend, FastAPI]
        API[REST API /api]
        P[payout.py<br/>section 10 rules]
        SO[signoff.py]
        RN[runs.py + runner.py<br/>background threads]
        VR[voice/routes.py]
    end

    DB[(SQLite)]
    A[Claim agent<br/>agent/main.py]
    VA[Voice agent<br/>agent/voice.py]
    LLM[(OpenRouter)]

    D --> API
    VP --> D
    D --> VR
    API --> DB
    API --> P
    API --> SO
    API --> RN
    RN --> A
    VR --> VA
    A -->|HTTP tools| API
    VA -->|tools| API
    A --> LLM
    VA --> LLM
```

| Part | Path | Responsibility |
|---|---|---|
| Backend | `backend/` | Data, business rules, permissions and PII filtering. Seeds SQLite from `data/` on startup. |
| Claim agent | `agent/main.py` | `run(claim_id, thread_id, llm=None, on_step=None)`: reads the claim, decides, calculates and pays through six tools. |
| Voice agent | `agent/voice.py` | `run_turn(session_id, handler_id, text, llm=None)`: answers spoken questions with nine tools. |
| Dashboard | `dashboard/` | The handlers' console: queue, sign-off, instructions, trace and voice. |
| Context | `context/` | Policy wording, claim rules, glossary and data dictionary. |

## The life of a claim

```mermaid
sequenceDiagram
    actor H as Handler
    participant D as Dashboard
    participant B as Backend
    participant A as Claim agent
    participant M as Model

    H->>D: Run claim
    D->>B: POST /claims/{id}/runs
    B->>A: run(claim_id) in a background thread
    A->>B: get_claim, get_policy, get_customer_history
    A->>M: Decide which items to approve
    A->>B: calculate_payout (deterministic)
    A->>B: record_decision
    alt payout up to $1,000.00
        A->>B: pay_claim
        B-->>A: paid
    else payout over $1,000.00
        A->>B: pay_claim
        B-->>A: refused, waits for sign-off
        H->>D: Sign off
        D->>B: POST /claims/{id}/sign-off
    end
    loop every second while live
        D->>B: GET /runs/{id}/events
    end
```

## Agent tools

| Tool | API operation | Purpose |
|---|---|---|
| `get_claim` | `GET /claims/{claim_id}` | The claim, its items and documents |
| `get_policy` | `GET /policies/{policy_id}` | The plan, limits and excess |
| `get_customer_history` | `GET /customers/{customer_id}/history` | Earlier claims, without personal data |
| `calculate_payout` | `POST /claims/{claim_id}/calculate` | Applies section 10 of the wording |
| `record_decision` | `POST /claims/{claim_id}/decision` | Approve, decline or refer, with the payout, reason and policy section |
| `pay_claim` | `POST /claims/{claim_id}/pay` | Pays up to $1,000.00; larger amounts wait for sign-off |

## Design decisions

- **One API for people and agents.** The agent has no database access. Permissions, PII filtering and payout limits are enforced once, in the backend.
- **The model decides, code calculates.** Money is computed by `backend/payout.py` in integer cents, never by the model.
- **A hard limit, not a prompt.** The $1,000.00 sign-off limit is enforced by `pay_claim`, so no instruction or prompt injection can bypass it.
- **Fail safe.** A run that raises or ends without a decision is marked failed and the claim returns to `waiting`.
- **Testable without a model.** `AGENT_STUB=1` and the voice stub make every test deterministic and free.
- **Voice can't pay.** `request_signoff` only highlights a claim for 10 minutes; the handler's click is the sign-off.
