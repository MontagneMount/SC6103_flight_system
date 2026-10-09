# Measured UDP experiment results

Fresh server for each case: flight 101 starts with 100 seats and fare 500. The first reply is deliberately discarded AFTER execution; the client retries the same request ID. Expected means the effect of exactly one execution. Results use real loopback UDP sockets.

| Mode | Operation | Loss | Sends | Expected | Actual | Outcome |
|---|---|---|---:|---:|---:|---|
| ALO | RESERVE | none | 1 | 98 | 98 | PASS |
| ALO | RESERVE | first reply | 2 | 98 | 96 | DUPLICATE EFFECT |
| ALO | SET_FARE | none | 1 | 600 | 600 | PASS |
| ALO | SET_FARE | first reply | 2 | 600 | 600 | PASS |
| ALO | ADD_FARE | none | 1 | 510 | 510 | PASS |
| ALO | ADD_FARE | first reply | 2 | 510 | 520 | DUPLICATE EFFECT |
| AMO | RESERVE | none | 1 | 98 | 98 | PASS |
| AMO | RESERVE | first reply | 2 | 98 | 98 | PASS |
| AMO | SET_FARE | none | 1 | 600 | 600 | PASS |
| AMO | SET_FARE | first reply | 2 | 600 | 600 | PASS |
| AMO | ADD_FARE | none | 1 | 510 | 510 | PASS |
| AMO | ADD_FARE | first reply | 2 | 510 | 510 | PASS |

ALO repeats non-idempotent operations when replies are lost. AMO replays the cached response without executing again. SET_FARE stays correct in both modes because it is idempotent.

Scope: same server process, no crash recovery. Finite retries can end with an unknown outcome. This is a correctness experiment, not a throughput benchmark or a cross-computer demonstration.
