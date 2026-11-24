# Architecture Decision Record

## ADR-001: Modular monolith with relational source of truth

**Status:** Accepted for prototype.

**Context:** The assignment timebox is 4-6 hours and correctness is more important than
technology count. Agent and borrower allocation requires atomic state changes.

**Decision:** Use FastAPI + SQLAlchemy + PostgreSQL-compatible relational persistence.
Keep pacing, safety, allocation, provider adapters and event processing as separate
modules in one deployable application. SQLite is the zero-setup local default.

**Consequences:** Easy local setup, simple transactions and clear module boundaries.
A single process is not sufficient for production availability; multi-worker deployment
requires PostgreSQL, shared provider health, durable jobs and operational monitoring.

## ADR-002: Conservative predictive pacing

**Status:** Accepted for prototype.

The predictive engine recommends a batch using answer-rate and workload signals, but
the Safety Controller caps it to actual available agent slots. This sacrifices some
potential predictive utilization in exchange for a deterministic no-overbooking property.
A more aggressive production design needs provider-side answer detection, reserved
standby capacity and a proven overflow/abandonment prevention mechanism.

## ADR-003: Conditional updates for resource claims

**Status:** Accepted.

Agent and borrower state transitions use conditional updates from AVAILABLE/QUEUED.
A transaction commits the claims and call record together. For PostgreSQL worker pools,
use `FOR UPDATE SKIP LOCKED` to avoid workers waiting on the same queue rows, retaining
conditional updates as a final guard.
