# Measured UDP experiment results

Fresh server for each case: flight 101 starts with 100 seats, on-time status and zero baggage. The first reply is deliberately discarded AFTER execution; the client retries the same request ID. Expected means the effect of exactly one execution. Results use real loopback UDP sockets.

| Mode | Operation | Loss | Sends | Expected | Actual | Outcome |
|---|---|---|---:|---:|---:|---|
| ALO | RESERVE | none | 1 | 98 | 98 | PASS |
| ALO | RESERVE | first reply | 2 | 98 | 96 | DUPLICATE EFFECT |
| ALO | UPDATE_STATUS | none | 1 | 2 / 30 min | 2 / 30 min | PASS |
| ALO | UPDATE_STATUS | first reply | 2 | 2 / 30 min | 2 / 30 min | PASS |
| ALO | ADD_BAGGAGE | none | 1 | 2 kg / $31.00 | 2 kg / $31.00 | PASS |
| ALO | ADD_BAGGAGE | first reply | 2 | 2 kg / $31.00 | 4 kg / $62.00 | DUPLICATE EFFECT |
| AMO | RESERVE | none | 1 | 98 | 98 | PASS |
| AMO | RESERVE | first reply | 2 | 98 | 98 | PASS |
| AMO | UPDATE_STATUS | none | 1 | 2 / 30 min | 2 / 30 min | PASS |
| AMO | UPDATE_STATUS | first reply | 2 | 2 / 30 min | 2 / 30 min | PASS |
| AMO | ADD_BAGGAGE | none | 1 | 2 kg / $31.00 | 2 kg / $31.00 | PASS |
| AMO | ADD_BAGGAGE | first reply | 2 | 2 kg / $31.00 | 2 kg / $31.00 | PASS |

ALO repeats non-idempotent operations when replies are lost. AMO replays the cached response without executing again. UPDATE_STATUS stays correct in both modes because it is idempotent. Baggage costs $15.50/kg; duplicate ALO execution charges $62.00 for 4 kg rather than $31.00 for 2 kg.

Scope: same server process, no crash recovery. Finite retries can end with an unknown outcome. This is a correctness experiment, not a throughput benchmark or a cross-computer demonstration.
