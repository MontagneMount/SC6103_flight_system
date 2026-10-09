# Binary protocol version 2

Version 2 changes departure time and replaces operations 5 and 6. Update client and server together. Old-version packets are rejected. All multibyte fields use network byte order (big endian). Each UDP datagram contains one message, at most 60,000 bytes including header. Individual numeric primitives are explicitly packed; no object serialization is used.

## Header (30 bytes)

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 2 | magic | ASCII FL |
| 2 | 1 | version | 2 |
| 3 | 1 | kind | request=1, reply=2, callback=3 |
| 4 | 1 | mode | ALO=1, AMO=2 |
| 5 | 1 | operation | 1–6 below |
| 6 | 16 | client ID | random UUID bytes per client process |
| 22 | 8 | request ID | unsigned counter, incremented for new requests only |

Invalid headers are ignored. Invalid bodies with valid headers produce an error reply. Truncated fields and trailing bytes are rejected.

## Primitive types

- u32: unsigned 32-bit integer.
- f64: IEEE-754 binary64 floating-point value.
- string: u32 UTF-8 byte count followed by exactly that many bytes.
- departure: five consecutive u32 values: **year, month, day, hour, minute**, interpreted in UTC. Status updates do not change scheduled departure.
- flight_status: u32, 0=on time, 1=maintenance, 2=weather delay.
- delay_minutes: u32; on-time status requires zero delay.

## Requests and successful response data

| ID | Operation | Request body | Success data |
|---:|---|---|---|
| 1 | SEARCH | string source, string destination | u32 count, count × u32 flight ID |
| 2 | DETAILS | u32 flight ID | detail record below |
| 3 | RESERVE | u32 flight ID, u32 count | u32 remaining seats |
| 4 | MONITOR | u32 flight ID, f64 seconds | f64 accepted interval |
| 5 | UPDATE_STATUS | u32 flight ID, u32 flight_status, u32 delay_minutes | u32 flight_status, u32 delay_minutes |
| 6 | ADD_BAGGAGE | u32 flight ID, f64 extra kg | f64 total_baggage_kg, f64 total_baggage_cost |

Detail record, in order: u32 ID, string source, string destination, five-field departure, f64 airfare, u32 seats, u32 flight_status, u32 delay_minutes, f64 total_baggage_kg, f64 total_baggage_cost.

Every reply begins with u32 status and string message; success data follows only when status=0. Reply status 1 means invalid arguments/business error, 2 means mode mismatch, 3 means conflicting request ID reuse. Reply status is distinct from flight operating status. Header operation and request ID match the request. A mode-mismatch response echoes the requested mode so the client can read the error.

Baggage weight must be finite and positive; accumulated weight is limited to 1,000,000 kg per flight. Purchases are accumulated per flight across all clients because inputs contain no passenger or booking ID. The returned total bill includes extra baggage only, excluding airfare. Internal weights use decimal arithmetic. Total weight times $15.50/kg is rounded half-up to cents and transmitted as f64. UPDATE_STATUS overwrites values and is idempotent; ADD_BAGGAGE accumulates weight and charges and is non-idempotent.

## Monitoring and callbacks

Callback header: kind=3, operation=4, client ID and request ID copied from registration. Body: u32 flight ID, u32 remaining seats, u32 notification sequence. Sequence starts at 1 for each subscription. Client IP/port comes from the received datagram. Server expiration uses a monotonic clock.

In both ALO and AMO modes, replaying the same registration ID returns its original acknowledgement without renewing its lease or resetting its sequence. Registration history survives subscription expiry so delayed repeats cannot recreate expired leases. A new request ID creates a new subscription. Thus monitoring is idempotent for retransmissions of one registration, not arbitrary new registrations with the same relative duration. Client waiting starts at acknowledgement and may slightly exceed the remaining server lease.

## Invocation semantics

Client retries preserve the exact encoded datagram and request identity. Replies must match the configured server address, client ID, request ID, operation and mode. Unrelated datagrams do not extend the timeout.

ALO executes every received business request; MONITOR has registration replay protection. AMO replays cached replies keyed by client ID and request ID. The cache stores request signatures to detect conflicting ID reuse. Successes and errors are cached. History lasts for the server lifetime; no eviction or crash recovery is claimed.

Default timeout is 1 second with 3 retries (4 sends). Exhausted retries mean an unknown outcome; persistent loss prevents guaranteed eventual execution. Callbacks are best effort without ACK or retransmission. Clients discard duplicate/out-of-order notifications by sequence.

The protocol assumes a trusted course laboratory network and does not authenticate clients or datagrams.
