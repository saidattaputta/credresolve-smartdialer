# Predictive pacing scenario matrix

Run `python -m app.simulation` to print the deterministic 3 x 3 matrix.

| Answer rate | Average talk time |
|---:|---:|
| 20% | 120s, 90s, 180s |
| 50% | 120s, 90s, 180s |
| 70% | 120s, 90s, 180s |

The aggregate model assumes 100 attempts, 20 agents, and a 60-second observation window. Expected answers are attempts multiplied by answer rate. Estimated occupancy is expected answered talk-time divided by the available agent-seconds, capped at 100%.

These are transparent planning estimates, not measured provider outcomes or a discrete-event simulation. The runtime pacing engine separately consumes answer rate, talk time, ringing calls, connected calls, and the current available-agent count. The Safety Controller caps all actual attempts at available agent slots.

For a reproducible local HTTP smoke test, start the API and run `python scripts/load_test.py --requests 100 --concurrency 10`. Record the printed throughput and latency from the machine used for evaluation; no benchmark result is hard-coded in this repository.
