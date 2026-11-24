# CredResolve SmartDialer

A runnable Python prototype of a progressive and predictive outbound dialer. It separates pacing decisions from a mandatory safety gate, transactional agent/borrower allocation, and telecom-provider adapters.

## What is implemented

| Area | Implementation |
|---|---|
| Progressive dialing | Limits attempts to available agents, queued borrowers, and the configured batch size |
| Predictive pacing | Uses answer rate, average talk time, ringing calls, connected calls, and target utilization to estimate demand |
| Independent safety gate | Every requested batch passes through the Safety Controller before any provider call is initiated |
| State management | Agent and call lifecycle states with guarded provider-event transitions |
| Concurrency | Conditional database updates protect agent and borrower reservations |
| Idempotency | Client batch keys and unique provider event IDs prevent duplicate processing |
| Provider abstraction | Two mock providers with different latency and failure behaviour |
| Provider failure handling | In-process circuit breaker stops new attempts when a provider is unhealthy |
| Recovery | Releases stale reservations only when provider initiation has not started |
| Evaluation | Predictive scenario matrix, automated tests, and a lightweight API load smoke test |

## Requirements

- Python 3.11 or later
- SQLite for local development
- PostgreSQL 14 or later for concurrency integration tests

## Setup

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/saidattaputta/credresolve-smartdialer.git
cd credresolve-smartdialer

python -m venv .venv
source .venv/bin/activate
# Windows: .venv\\Scripts\\activate

pip install -r requirements.txt
cp .env.example .env
# Windows: copy .env.example .env
```

SQLite is used by default, so no database setup is needed for a local run.

To use PostgreSQL, create a database and set `DATABASE_URL` in `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/smartdialer
```

Start the API:

```bash
uvicorn app.main:app --reload
```

- Health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

Database tables are initialized when the application starts. This is suitable for the prototype; a production deployment should use a migration tool such as Alembic.

## Quick API walkthrough

You can use the interactive Swagger UI at `/docs`, or follow these steps.

**1. Create demo data**

Send `POST /api/v1/demo/seed`:

```json
{
  "agents": 5,
  "borrowers": 20,
  "campaign_name": "Demo Campaign"
}
```

Keep the returned `campaign_id` for the following requests.

**2. Start progressive dialing**

Send `POST /api/v1/campaigns/{campaign_id}/dial`:

```json
{
  "mode": "progressive",
  "provider": "provider_a",
  "idempotency_key": "demo-batch-0001"
}
```

**3. Try predictive dialing**

```json
{
  "mode": "predictive",
  "provider": "provider_b",
  "answer_rate": 0.5,
  "average_talk_time_seconds": 120,
  "max_batch": 20
}
```

**4. Inspect calls and metrics**

- `GET /api/v1/campaigns/{campaign_id}/calls`
- `GET /api/v1/metrics`

**5. Send provider lifecycle events**

Send `POST /api/v1/calls/{call_id}/events`:

```json
{
  "event_id": "provider-event-001",
  "event_type": "RINGING"
}
```

Supported event types: `RINGING`, `ANSWERED`, `CONNECTED`, `COMPLETED`, `FAILED`, and `CANCELLED`. Use a unique event ID for each provider event. Duplicate IDs and invalid or stale state transitions are ignored.

**6. Recover abandoned pre-initiation reservations**

```text
POST /api/v1/maintenance/recover-stale-reservations?stale_after_seconds=120
```

## Design and safety

The pacing engine recommends a batch size; it does not initiate calls or control the safety policy. The Safety Controller independently checks the available agent capacity, queued borrower count, and provider health. Only approved attempts proceed to allocation.

For each attempt, the allocator conditionally claims an available agent and a queued borrower in the database and persists the call record before contacting the provider. Provider events are checked against the call state machine. Duplicate events are recorded once, and late events cannot move terminal calls back into an active state.

This prototype is intentionally conservative: every outbound attempt is backed by a reserved agent. It does not use aggressive over-dialing.

### Idempotency and crash recovery

Pass the same `idempotency_key` when retrying a dial request to avoid creating another batch. Use a new key for a genuinely new batch.

A reservation is first stored with `provider_started=false`. Immediately before the external provider request, the application commits `provider_started=true`. Recovery releases only stale `RESERVED` calls that are still marked `false`.

A call marked `provider_started=true` is not automatically retried. If a worker crashes during or after the provider request, the outcome may be unknown; provider lookup and reconciliation are needed before retrying to avoid duplicate calls.

## Predictive scenario evaluation

Run the deterministic scenario matrix:

```bash
python -m app.simulation
```

It evaluates answer rates of 20%, 50%, and 70% against average talk times of 120, 90, and 180 seconds. The output estimates expected answers per 100 attempts and agent occupancy.

These figures are model estimates, not live telecom measurements. The API simulation endpoint is a small demonstration and is separate from the scenario matrix.

## Tests and load smoke test

Run the local test suite:

```bash
pytest -q
```

The PostgreSQL concurrency tests require a dedicated test database named `credresolve_test`. Configure `DATABASE_URL` to point to that database before running them:

```bash
createdb credresolve_test
export DATABASE_URL='postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/credresolve_test'
pytest -q tests/test_postgres_concurrency.py
```

Do not use a production database for tests. The integration tests create and modify test records.

For a lightweight HTTP smoke test, start the application in one terminal and run this in another:

```bash
python scripts/load_test.py --requests 100 --concurrency 10
```

The script measures throughput and latency for the health endpoint. It is not a database, allocation, or telecom-provider load benchmark.

## Project documentation

- `docs/architecture.md` — component boundaries, state transitions, and scaling considerations
- `docs/architecture.mmd` — Mermaid architecture diagram
- `docs/adr.md` — architecture decision records
- `docs/simulation/scenarios.md` — scenario assumptions and interpretation

## Limitations

- Both telecom providers are mocks; no real calls are placed.
- Authentication, authorization, borrower PII encryption, consent/DND checks, and production regulatory controls are not implemented. Do not use this prototype with real borrower data or live collections.
- Provider circuit-breaker state is held in process memory. Multi-worker production deployments need shared state.
- A timeout after a provider request has been transmitted can have an ambiguous outcome and requires provider-side idempotency and reconciliation.
- Predictive pacing remains bounded by available agent slots; it demonstrates workload-aware pacing inputs rather than aggressive over-dialing.
- Production PostgreSQL deployments should use indexed queue claims and consider `SELECT ... FOR UPDATE SKIP LOCKED`, while retaining conditional updates as a correctness guard.
