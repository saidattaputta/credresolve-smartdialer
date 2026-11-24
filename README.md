# CredResolve SmartDialer

A runnable, modular-monolith prototype implementing progressive and predictive outbound dialing with a mandatory Safety Controller.

## Features
- FastAPI REST API and interactive Swagger docs
- SQLAlchemy persistence (SQLite by default; PostgreSQL supported)
- Agent, borrower, campaign and call lifecycles
- Progressive and conservative predictive pacing
- Safety Controller between pacing and provider execution
- Conditional database updates for race-safe reservations
- Idempotent call creation and provider-event deduplication
- Two mock telecom providers with different reliability/latency/event behaviour
- Provider outage circuit breaker, simulation endpoint and tests

## Quick start
Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs and use the API.

SQLite is used by default so the project runs immediately. To use PostgreSQL, set
`DATABASE_URL` in `.env`, for example:
`postgresql+psycopg://postgres:postgres@localhost:5432/smartdialer`

Tables are created automatically on startup for this prototype. For a production
deployment, use Alembic migrations rather than `create_all`.

## Suggested demo
1. `POST /api/v1/demo/seed` to create a campaign, borrowers and agents.
2. `POST /api/v1/campaigns/{campaign_id}/dial` with `{"mode":"progressive"}`.
3. Inspect `GET /api/v1/campaigns/{campaign_id}/calls`.
4. Simulate provider events using `POST /api/v1/calls/{call_id}/events`.
5. Try predictive mode and inspect the pacing explanation.
6. `POST /api/v1/simulation/run` to run a deterministic scenario.

## Safety design
The pacing engine only returns a requested count and explanation. It has no provider
reference. The orchestrator passes that request to the Safety Controller, which caps
it against fresh database capacity and provider health. The allocator then reserves
an agent and borrower using conditional database updates inside a transaction.
Only after the reservation is committed does the provider adapter initiate the call.

This prototype deliberately uses a conservative predictive policy: every outbound
attempt is backed by a reserved agent slot. It therefore prioritizes the assignment's
no-unhandled-answer safety property over aggressive over-dialing. A future production
design could increase utilization using provider-side answer detection/bridging,
guaranteed standby capacity and a separately proven overflow policy.

## Concurrency and consistency
- Allocation uses conditional `UPDATE ... WHERE state = AVAILABLE/QUEUED`; only one
  concurrent transaction can change a given row from the expected prior state.
- PostgreSQL deployments should use short transactions and `SELECT ... FOR UPDATE
  SKIP LOCKED` for efficient multi-worker queue claiming. The conditional updates
  remain the final correctness guard.
- `idempotency_key` is unique for call creation.
- Provider event IDs are unique per provider and duplicate deliveries are ignored.
- Call transitions are validated; terminal states cannot be resurrected by stale events.
- Database state is authoritative; there is no correctness-critical cache.

## Limitations (intentional prototype scope)
- Mock providers simulate initiation and events; no real telecom calls are placed.
- No real authentication, borrower PII encryption, consent/DND enforcement, regulatory
  policy engine, or production observability is included. These are mandatory before
  handling real borrowers or live collections.
- In-process circuit-breaker state is suitable for a single-process demo; production
  multi-worker deployments need shared health state.
- A provider timeout after request transmission is ambiguous. Production integration
  must use provider idempotency/client references and reconciliation before retrying,
  to avoid duplicate outbound calls.

## Tests
```bash
pytest -q
```

## Architecture
See `docs/architecture.md`, `docs/adr.md`, and `docs/architecture.mmd`.
