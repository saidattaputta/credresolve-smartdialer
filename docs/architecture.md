# Architecture

## Overview

The application is a FastAPI modular monolith. The API coordinates campaign setup,
dial requests, provider callbacks, maintenance recovery and basic metrics. SQLAlchemy
persists campaign, agent, borrower, call and provider-event records in a relational
database (SQLite for local setup; PostgreSQL for multi-worker concurrency).

The main dialing path is:

1. The API receives a campaign dial request and passes its mode, provider, pacing
   inputs, batch limit and optional idempotency key to the Dialer.
2. The Pacing Engine recommends a batch size. Progressive mode limits the recommendation
   to currently available agents, queued borrowers and the requested batch maximum.
   Predictive mode estimates demand using answer rate, average talk time, ringing calls,
   connected calls and current capacity.
3. The Safety Controller independently applies the final capacity and provider-health
   gate. It cannot approve more calls than available agents or queued borrowers.
4. The Allocator conditionally claims an AVAILABLE agent and QUEUED borrower, creates
   a RESERVED call record, and commits those changes together.
5. Before contacting the provider, the Dialer persists `provider_started=true`.
   It then invokes the selected provider adapter and records the initiation result.
6. Provider callbacks enter through the call-events API and are processed by the event
   handler, which records event IDs and applies only allowed call-state transitions.

## Component responsibilities

| Component | Responsibility |
|---|---|
| FastAPI routes | Validate requests and expose campaign, agent, borrower, dialing, event, metrics and maintenance endpoints |
| Dialer | Coordinate pacing, safety approval, allocation and provider initiation |
| Pacing Engine | Recommend a batch size; does not allocate resources or call providers |
| Safety Controller | Enforce the final agent, borrower and provider-health limits |
| Allocator | Atomically reserve agent/borrower records and create calls |
| Provider adapters | Hide provider-specific initiation behind a common interface |
| Provider event handler | Deduplicate callbacks and apply legal state transitions |
| SQLAlchemy models | Persist campaign, agent, borrower, call and provider-event state |

## Trust and control boundaries

The Pacing Engine is advisory. Its recommendation is not permission to dial.
The Safety Controller is a separate final gate before allocation. The Allocator then
uses conditional database updates to claim resources, so concurrent workers cannot
successfully claim the same AVAILABLE agent or QUEUED borrower.

Each call has a unique idempotency key derived from the campaign, client batch key
(or generated batch key) and position in the batch. This prevents a repeated batch
request from creating another call for the same key. Provider callback IDs are unique
per provider, preventing the same event from being applied twice.

Provider health is represented by an in-memory demo circuit breaker. It is suitable
for this single-process prototype only; a multi-worker or production deployment needs
shared health state.

## State and event handling

The principal agent path is:

`AVAILABLE -> RESERVED -> DIALING -> CONNECTED -> AVAILABLE`

The principal call path is:

`RESERVED -> INITIATED -> RINGING -> ANSWERED -> CONNECTED -> COMPLETED`

Calls may instead reach `FAILED` or `CANCELLED`. These are terminal states. The event
handler ignores duplicate events, events for terminal calls, and transitions that are
not allowed from the current state. The implementation also defines additional agent
states such as `OFFLINE`, `PAUSED` and `WRAP_UP`; not every state is exercised by the
prototype's current API flow.

## Failure handling and recovery boundary

A provider initiation failure marks the call as FAILED, releases the agent and returns
the borrower to the queue. Provider event IDs are persisted with a uniqueness constraint
so duplicate callbacks do not repeat state changes. Out-of-order or otherwise invalid
transitions are recorded and ignored rather than moving a call backwards.

The maintenance recovery endpoint only releases stale calls that remain RESERVED and
have `provider_started=false`. This identifies reservations abandoned before the
provider side effect was started. Once `provider_started=true` is committed, a crash
may have occurred before or after the provider accepted the request. The prototype
does not guess which happened and does not blindly retry those calls; production
handling requires provider-side lookup or reconciliation.

## Scaling considerations

- **100 agents:** A single application process and relational database are sufficient
  for the prototype.
- **1,000 agents:** Measure database lock contention, provider throughput and event
  processing lag. Use bounded worker pools, indexed queue claims and shared circuit-
  breaker state where multiple workers are deployed.
- **10,000 agents:** Consider partitioning campaigns or queues, durable event transport,
  horizontally scaled workers and carefully partitioned database ownership. Apply
  provider rate limits and use measured bottlenecks to guide service boundaries.

These are design considerations, not benchmark claims. The included load script is
an HTTP health-endpoint smoke test; it is not a database or provider capacity benchmark.
