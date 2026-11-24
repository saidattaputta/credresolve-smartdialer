# Simulation scenarios

| Scenario | Answer rate | Average talk time | Expected focus |
|---|---:|---:|---|
| A | 20% | 120 sec | Low answer yield; avoid runaway retries |
| B | 50% | 90 sec | Baseline |
| C | 70% | 180 sec | High answer yield and longer agent occupancy |
| D | Changing | Changing | Recompute pacing from recent observations |

Additional fault injections to demonstrate:
- Provider B intermittent timeout (12% simulated initiation failure).
- Provider B latency (30 ms simulated delay).
- Duplicate provider event IDs.
- Out-of-order events (e.g. COMPLETED before ANSWERED).
- Worker restart: committed reservations remain visible in the database and can be reconciled.
