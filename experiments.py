"""Reproducible lost-reply experiment; writes measured results as Markdown."""
import threading
from pathlib import Path

from client import FlightClient
from protocol import Mode, Op
from server import FlightServer


def run_case(mode, op, values, drop):
    server = FlightServer(port=0, mode=mode, drop_first_reply=drop)
    server.log = lambda message: None
    worker = threading.Thread(target=server.serve, daemon=True)
    worker.start()
    client = FlightClient(*server.address, mode=mode, timeout=.1, retries=2)
    try:
        reply = client.call(op, 101, *values)
        attempts = client.last_attempts
        state = client.call(Op.DETAILS, 101)['result']
        if op == Op.RESERVE:
            actual, expected = str(state['seats']), '98'
        elif op == Op.UPDATE_STATUS:
            actual, expected = f'{state["flight_status"]} / {state["delay_minutes"]} min', '2 / 30 min'
        else:
            actual = f'{state["total_baggage_kg"]:g} kg / ${state["total_baggage_cost"]:.2f}'
            expected = '2 kg / $31.00'
        assert reply['status'] == 0
        return f'| {mode.name} | {op.name} | {"first reply" if drop else "none"} | {attempts} | {expected} | {actual} | {"PASS" if actual == expected else "DUPLICATE EFFECT"} |'
    finally:
        client.close()
        server.running = False
        worker.join(2)


if __name__ == '__main__':
    rows = ['# Measured UDP experiment results', '',
            'Fresh server for each case: flight 101 starts with 100 seats, on-time status and zero baggage. '
            'The first reply is deliberately discarded AFTER execution; the client retries the same request ID. '
            'Expected means the effect of exactly one execution. Results use real loopback UDP sockets.', '',
            '| Mode | Operation | Loss | Sends | Expected | Actual | Outcome |',
            '|---|---|---|---:|---:|---:|---|']
    for mode in [Mode.ALO, Mode.AMO]:
        for op, values in [(Op.RESERVE, (2,)), (Op.UPDATE_STATUS, (2, 30)), (Op.ADD_BAGGAGE, (2,))]:
            for drop in [False, True]:
                rows.append(run_case(mode, op, values, drop))
    rows += ['', 'ALO repeats non-idempotent operations when replies are lost. '
             'AMO replays the cached response without executing again. UPDATE_STATUS stays correct in both modes because it is idempotent. '
             'Baggage costs $15.50/kg; duplicate ALO execution charges $62.00 for 4 kg rather than $31.00 for 2 kg.', '',
             'Scope: same server process, no crash recovery. Finite retries can end with an unknown outcome. '
             'This is a correctness experiment, not a throughput benchmark or a cross-computer demonstration.']
    output = '\n'.join(rows) + '\n'
    Path(__file__).with_name('EXPERIMENT_RESULTS.md').write_text(output, encoding='utf-8')
    print(output)
