# Architecture Decision Records

This document records the main design choices made for the SmartDialer prototype,
along with the trade-offs they introduce.

## ADR-001: Modular monolith with a relational source of truth

**Status:** Accepted for the prototype.

**Context**

The assignment is time-boxed, but allocating agents and borrowers correctly requires
atomic state changes. Introducing multiple deployable services would add operational
complexity without improving the prototype's core guarantees.

**Decision**

Use FastAPI and SQLAlchemy in a modular monolith. Keep API routes, pacing, safety,
allocation, provider adapters and event handling in separate modules, with a relational
database as the source of truth. SQLite provides a simple local setup; PostgreSQL is
used for multi-worker concurrency scenarios.

**Consequences**

- A single deployable application is straightforward to run and understand.
- Relational transactions and conditional updates protect resource allocation.
- The application is not production-ready for high availability: multiple workers
  require shared provider-health state, durable background processing and operational
  monitoring.

## ADR-002: Predictive pacing is advisory; safety approval is mandatory

**Status:** Accepted for the prototype.

**Context**

Predictive pacing estimates how many outbound attempts may be needed to keep agents
occupied. Answer-rate estimates are imperfect, and an aggressive recommendation must
not result in more simultaneous attempts than the available agent capacity.

**Decision**

The Pacing Engine recommends a batch size using answer rate, average talk time,
ringing calls, connected calls and current capacity. The independent Safety Controller
then applies the final limits: available agents, queued borrowers and provider health.
The allocator only runs after this approval.

**Consequences**

- The safety gate prevents the pacing estimate from authorizing more attempts than
  available agent slots.
- The approach is deliberately conservative and may leave some potential utilization
  unrealized.
- A production predictive dialer would need reliable answer detection, real-time
  capacity signals and a validated abandonment/overflow policy before using more
  aggressive pacing.

## ADR-003: Conditional database updates for resource allocation

**Status:** Accepted.

**Context**

Concurrent dial requests can observe the same AVAILABLE agent or QUEUED borrower.
A read followed by an unconditional write could allow two workers to allocate the
same resource.

**Decision**

Claim agents and borrowers with conditional updates that require their expected
current state. Create the call record and commit the resource claims in the same
transaction. Keep a unique idempotency key on each call as an additional duplicate
request safeguard.

**Consequences**

- Only one worker can successfully change a given resource from its eligible state.
- Failed claims are rolled back and retried within a bounded number of attempts.
- PostgreSQL worker pools can use row-locking strategies such as
  `SELECT ... FOR UPDATE SKIP LOCKED` if queue contention warrants it; conditional
  updates remain the final state-transition guard.

## ADR-004: Do not blindly retry ambiguous provider initiation

**Status:** Accepted for the prototype.

**Context**

A process can fail around the time it sends a request to a telecom provider. After a
restart, the application may not know whether the provider received or accepted the
request. Retrying without reconciliation could create a duplicate outbound call.

**Decision**

Persist `provider_started=true` before invoking the provider adapter. Automatic stale
reservation recovery is limited to calls that remain RESERVED with
`provider_started=false`. Calls beyond that boundary are left for provider-side
reconciliation rather than being retried automatically.

**Consequences**

- Reservations abandoned before provider initiation can be safely released.
- A crash after the flag is committed may leave an ambiguous call requiring manual
  or provider-assisted reconciliation.
- Production deployment should integrate provider lookup/webhook reconciliation and
  an operational process for resolving ambiguous attempts.
