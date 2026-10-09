# Binary protocol version 1

All multibyte fields use network byte order (big endian). Each UDP datagram contains exactly one message. Maximum accepted packet size: 60,000 bytes, including header. `struct` packs individual numeric primitives; no automatic object serialization is used.

## Header (30 bytes)

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 2 | magic | ASCII FL |
| 2 | 1 | version | 1 |
| 3 | 1 | kind | request=1, reply=2, callback=3 |
| 4 | 1 | mode | ALO=1, AMO=2 |
| 5 | 1 | operation | 1–6 below |
| 6 | 16 | client ID | random UUID bytes, generated once per client process |
| 22 | 8 | request ID | unsigned counter, incremented for new requests only |

The remainder is an operation-specific body. Invalid headers are ignored. Invalid bodies with valid headers produce an error reply. Truncated strings and trailing bytes are rejected.

## Primitive types

- `u32`: unsigned 32-bit integer.
- `i64`: signed 64-bit integer; departure is seconds since Unix epoch, UTC.
- `f64`: IEEE-754 binary64 floating-point value.
- `string`: u32 UTF-8 **byte count**, then that many UTF-8 bytes (not character count).

## Requests and successful response data

| ID | Operation | Request body | Success data |
|---:|---|---|---|
| 1 | SEARCH | string source, string destination | u32 count, count × u32 flight ID |
| 2 | DETAILS | u32 flight ID | u32 ID, string source, string destination, i64 departure, f64 fare, u32 seats |
| 3 | RESERVE | u32 flight ID, u32 count | u32 remaining seats |
| 4 | MONITOR | u32 flight ID, f64 seconds | f64 accepted interval |
| 5 | SET_FARE | u32 flight ID, f64 fare | f64 resulting fare |
| 6 | ADD_FARE | u32 flight ID, f64 increment | f64 resulting fare |

Every reply body begins with u32 status and string message, followed by success data only when status=0. Status 1 means invalid arguments/business error, 2 means mode mismatch, 3 means request ID reused with conflicting contents. Header request ID and operation match the original request. A mode-mismatch reply echoes the requested mode so the client can read the diagnostic.

Callback header: kind=3, operation=4, client ID and request ID copied from the monitor registration. Body: u32 flight ID, u32 remaining seats, u32 notification sequence. Sequence begins at 1 for each registration and increases on each notification. Source IP/port comes from the received registration datagram.

## Invocation semantics

Client sends the same encoded datagram after each timeout. Replies are accepted only from the configured server address and matching client ID, request ID, operation and mode. Unrelated packets do not extend the timeout.

ALO executes each received request. AMO looks up `(client ID, request ID)` before execution and replays the exact cached reply. Cache entries include the operation and request body to detect conflicting ID reuse. Both successful and error replies are cached. History remains in memory for the server lifetime; no cache eviction or crash recovery is claimed.

Default timeout: 1 second. Default retries: 3 (4 total sends). This bounded implementation can report an unknown outcome, so unconditional eventual execution is not guaranteed if losses persist.

The protocol assumes a trusted course laboratory network. It does not authenticate client IDs or datagrams.
