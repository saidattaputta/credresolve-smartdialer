# Predictive pacing scenarios

Run the deterministic scenario matrix:

```bash
python -m app.simulation
```

The matrix covers the required answer-rate and average-talk-time combinations:

| Answer rate | Average talk times |
|---:|---|
| 20% | 120s, 90s, 180s |
| 50% | 120s, 90s, 180s |
| 70% | 120s, 90s, 180s |

## Estimation model

Each scenario assumes 100 attempts, 20 agents and a 300-second observation
window.

- Expected answers = attempts × answer rate.
- Estimated agent occupancy = expected answers × average talk time ÷
  (agent count × observation window), capped at 100%.

This is a deterministic aggregate estimate. It does not model individual call
timelines, provider behavior or live call execution. The runtime Pacing Engine
uses answer rate, average talk time, ringing calls, connected calls and current
agent availability to recommend a batch. The independent Safety Controller
applies the final cap based on available agents, queued borrowers and provider
health.

## HTTP smoke test

With the API running, execute:

```bash
python scripts/load_test.py --requests 100 --concurrency 10
```

The script sends requests to `/health` and prints elapsed time, throughput,
mean latency and p95 latency. It is a small HTTP smoke test, not a benchmark of
database allocation, provider initiation or end-to-end dialing capacity. Results
depend on the machine and environment used to run it.
