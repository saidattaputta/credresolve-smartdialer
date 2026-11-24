# CredResolve SmartDialer

A runnable Python prototype for progressive and predictive outbound dialing. The design separates pacing recommendations from a mandatory Safety Controller, transactional resource allocation, and telecom-provider adapters.

## Assignment scope and implemented requirements

| Requirement | Implementation |
|---|---|
| Progressive dialer | Starts no more calls than available agents, queued borrowers, and configured batch size |
| Predictive pacing | Estimates demand using answer rate, average talk time, ringing calls, connected calls, and target utilization |
| Mandatory safety gate | Every batch passes through `SafetyController`; provider execution happens only after approval |
| Agent and call state machines | Explicit domain states and validated provider-event transitions |
| Concurrency protection | Conditional SQL updates reserve agents and borrowers atomically with the call record |
| Idempotency and event ordering | Unique call idempotency key; provider event uniqueness; duplicate and stale event handling |
| Provider abstraction | Two mock providers with different latency and failure behaviour |
| Provider outage handling | In-process circuit breaker blocks new attempts when provider health is open |
| Worker recovery | Maintenance endpoint releases stale pre-initiation reservations; ambiguous initiated calls require provider reconciliation |
| Simulation and tests | Deterministic scenario runner, unit tests, provider-event tests, and PostgreSQL concurrency tests |
| Architecture and decisions | Architecture diagram, scaling notes, and ADRs in `docs/` |

## Requirements

- Python 3.11+
- PostgreSQL 14+ for concurrency integration tests (SQLite is sufficient for local development)

## Setup

```bash
git clone <repository-url>
cd credresolve-smartdialer
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
```

The application loads values from `.env`. SQLite is the default and requires no database setup. To use PostgreSQL, set:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/smartdialer
```

Create the database before starting the application. Then run:

```bash
uvicorn app.main:app --reload
```

- API health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs

Tables are created automatically for this prototype. A production deployment should use Alembic migrations.

## Quick API demo

Use Swagger UI or the following sequence:

1. Seed a campaign, agents, and borrowers with `POST /api/v1/demo/seed`:
   ```json
   {"agents": 5, "borrowers": 20, "campaign_name": "Demo Campaign"}
   ```
2. Copy the returned `campaign_id`.
3. Start progressive dialing:
   `POST /api/v1/campaigns/{campaign_id}/dial`
   ```json
   {"mode": "progressive", "provider": "provider_a"}
   ```
4. Start predictive dialing with an answer-rate and talk-time estimate:
   ```json
   {
     "mode": "predictive",
     "provider": "provider_b",
     "answer_rate": 0.5,
     "average_talk_time_seconds": 120,
     "max_batch": 20
   }
   ```
5. Inspect calls at `GET /api/v1/campaigns/{campaign_id}/calls` and aggregate counts at `GET /api/v1/metrics`.
6. Send provider lifecycle events to `POST /api/v1/calls/{call_id}/events`:
   ```json
   {"event_id": "provider-event-001", "event_type": "RINGING"}
   ```
   Valid event types: `RINGING`, `ANSWERED`, `CONNECTED`, `COMPLETED`, `FAILED`, `CANCELLED`. Use a unique event ID per provider event.
7. Recover reservations abandoned before provider initiation:
   `POST /api/v1/maintenance/recover-stale-reservations?stale_after_seconds=120`.

## Safety and concurrency model

1. The pacing engine is advisory. It calculates a requested batch and has no provider reference.
2. The Safety Controller independently caps the request by available agents and queued borrowers, and returns zero when the provider circuit breaker is unhealthy.
3. The allocator claims an agent and borrower with conditional updates in one database transaction and persists the call before initiating it.
4. A provider event can advance only a legal state transition. Duplicate event IDs are ignored, and terminal calls cannot be resurrected by late events.
5. The prototype is intentionally conservative: every outbound attempt has a reserved agent. It does not over-dial and therefore avoids unhandled answers by construction.

### Crash recovery boundary

The recovery endpoint only resets old calls still in `RESERVED`, which indicates the worker did not progress to provider initiation. Calls already in `INITIATED` are deliberately not retried automatically: a worker may have crashed after the provider accepted the request but before the database was updated. Such calls require provider lookup/reconciliation to avoid duplicate outbound calls.

## Predictive scenario evaluation

Run the deterministic aggregate scenario matrix:

```bash
python -m app.simulation
```

The runner evaluates answer rates of 20%, 50%, and 70% against average talk times of 120s, 90s, and 180s. It reports expected answers per 100 attempts and estimated agent occupancy for each case. These are model estimates, not live telecom measurements. The live API simulation endpoint is a small single-campaign demonstration, not a substitute for this matrix.

## Tests

Run the local suite:

```bash
pytest -q
```

The PostgreSQL concurrency and provider-event integration tests are skipped unless `DATABASE_URL` points to a dedicated database named `credresolve_test`. To run them:

```bash
createdb credresolve_test
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/credresolve_test pytest -q
```

Do not point destructive integration tests at a production database. They create and remove isolated test records and temporarily pause other available agents.

A lightweight API load smoke test can be run with the server active:

```bash
python scripts/load_test.py --requests 100 --concurrency 10
```

It measures local health-endpoint throughput and latency. It is a smoke test, not a benchmark of database allocation or provider capacity.

## Architecture

See:
- `docs/architecture.md` — component boundaries, state transitions, and scaling from 100 to 10,000 agents
- `docs/architecture.mmd` — standalone Mermaid diagram
- `docs/adr.md` — key architecture decisions
- `docs/simulation/scenarios.md` — scenario assumptions and interpretation

## Limitations and production work

- Mock providers do not place real calls.
- Authentication, authorization, borrower PII encryption, consent/DND checks, regulatory policy enforcement, and production observability are not implemented. Do not use this prototype with real borrower data or live collections.
- Circuit-breaker state is in-process; multi-worker production deployments need shared health state.
- Provider timeout after request transmission is ambiguous and requires provider idempotency plus reconciliation.
- The predictive engine is deliberately bounded by currently available agents. It demonstrates workload-aware pacing inputs, not an aggressive over-dial strategy.
- Production PostgreSQL workers should use indexed queue claims and `SELECT ... FOR UPDATE SKIP LOCKED`, while retaining conditional updates as the final correctness guard.
