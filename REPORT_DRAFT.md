# Distributed Flight Information System — Technical Report Draft

Group members and contribution percentages: **TO BE COMPLETED BY THE GROUP**.

## 1. Objective and architecture

The system implements remote access to flight records using UDP sockets. A single-threaded server holds flight data in memory. Console clients send requests and display replies. During monitoring, a client waits for callback datagrams rather than accepting new commands. Several clients may subscribe concurrently.

The implementation uses Python 3 standard library modules. Numeric primitives are explicitly packed with big-endian byte order, and variable-length UTF-8 strings carry byte-length prefixes. No RMI/RPC framework or object serialization is used. Protocol version 2 represents departure as five u32 fields: year, month, day, hour and minute, interpreted in UTC. Detailed field definitions are in PROTOCOL.md.

## 2. Services

The four required services search flight identifiers by route, retrieve flight details, reserve seats and monitor seat availability. Searches return all matches and report errors when none exist. Reservations require a positive count no larger than the remaining availability. Flight identifiers are validated before use.

Two additional services are implemented. UPDATE_STATUS overwrites an operating status (0=on time, 1=maintenance, 2=weather delay) and delay minutes, so repeated identical assignments are idempotent. ADD_BAGGAGE adds a positive extra weight and charges $15.50/kg; repeated execution adds weight and fees again, so it is non-idempotent. RESERVE is also non-idempotent.

Baggage totals are per flight across all clients because the agreed request has no passenger or booking identifier. The returned bill is the cumulative extra-baggage fee, excluding airfare. Decimal arithmetic accumulates weight, and the total bill is rounded half-up to two decimal places. Status updates do not alter the scheduled departure time or seat count. Details replies also expose status, delay and baggage totals for verification.

## 3. Monitoring

A registration records the client address/port, flight ID, request identity and expiration on the server's monotonic clock. Each successful reservation triggers notifications to all unexpired subscribers for that flight. Expired entries are periodically removed and are also removed before notification dispatch. Registration identities are retained in both ALO and AMO modes: retransmitting the same registration does not extend its expiration or recreate an expired lease. A new request identity creates a new lease. Each callback includes a sequence number so clients can ignore duplicate or older notifications. Callbacks are best-effort UDP and are not acknowledged or retransmitted.

## 4. Invocation semantics and fault injection

Clients generate a random 128-bit process identity and increment a request counter for every new operation. Timeout retransmissions preserve the original request identity and bytes.

In ALO mode, each received business request is executed; MONITOR alone has registration replay protection to preserve its original lease. In AMO mode, the server caches the encoded reply and request signature by client ID and request ID. Duplicates receive the original reply without another business execution. Reusing an ID for different arguments is rejected. Cache contents and flight data last only as long as the server process.

Fault injection independently discards received requests before processing and outgoing replies after processing. A deterministic switch discards the first response, allowing a repeatable demonstration of the execute-then-lose-reply failure case. Finite retry exhaustion is reported as an unknown outcome rather than as proof the operation was not executed.

## 5. Experiment design and results

Run `python experiments.py` to generate EXPERIMENT_RESULTS.md. There are 12 cases: two invocation modes × three operations × two loss configurations. Every case begins with a new server, 100 seats, on-time status, zero delay and zero purchased baggage. The comparison is between no loss and loss of the first reply. The operations reserve 2 seats, set weather-delay status with 30 minutes delay, and buy 2 kg of extra baggage for $31.00.

Measured values are in EXPERIMENT_RESULTS.md. With a lost reply, ALO repeats the reservation and baggage purchase, whereas AMO executes each only once and replays its reply. Repeated UPDATE_STATUS yields the same final state in either mode. A duplicated 2 kg baggage purchase in ALO produces 4 kg and a $62.00 bill; AMO retains 2 kg and $31.00. An intentionally incorrect ALO business result is evidence of the required failure scenario, not an unreported implementation failure.

These are deterministic correctness experiments over local UDP, not measurements of performance or Internet loss rates. Request-loss recovery, exhausted retries, malformed packets, mode mismatch and multiple subscribers are separately covered by the automated tests.

## 6. Validation and demonstration

Run `python -m unittest -v test_system` for the automated checks. The tests use actual local UDP sockets. The group must additionally run the server and two clients on three separate computers, record their addresses/environment and demonstrate one client reserving while another receives callbacks.

**Cross-computer demonstration observations and screenshots: TO BE COMPLETED.**

## 7. Limitations

There is no persistence, authentication or crash recovery. Deduplication history grows throughout server uptime. After retry exhaustion the execution outcome may be unknown. Callbacks may be lost on a real network. Monitor client waiting starts at acknowledgement, while server expiration starts at registration processing; therefore the client may wait slightly longer than the remaining server interval. The optional different-language client/server extension is not implemented.

## 8. Contributions and sources

Fill in actual member responsibilities and percentages. The requirements source is the supplied SC6103 Course Project for 2026–2027 Trimester 1. Add lecture references and any other material actually used by the group. Check the course's AI policy and document assistance as required; this draft does not assert that AI use has been approved.
