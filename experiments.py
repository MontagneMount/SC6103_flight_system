"""Reproducible lost-reply experiment; writes measured results as Markdown."""
import threading
from pathlib import Path

from client import FlightClient
from protocol import Mode, Op
from server import FlightServer


def run_case(mode, op, amount, drop):
    server = FlightServer(port=0, mode=mode, drop_first_reply=drop)
    server.log = lambda message: None
    worker = threading.Thread(target=server.serve, daemon=True)
    worker.start()
    client = FlightClient(*server.address, mode=mode, timeout=.1, retries=2)
    try:
        reply = client.call(op, 101, amount)
        attempts = client.last_attempts
        state = client.call(Op.DETAILS, 101)['result']
        actual = state['seats'] if op == Op.RESERVE else state['fare']
        expected = {Op.RESERVE: 98, Op.SET_FARE: 600, Op.ADD_FARE: 510}[op]
        assert reply['status'] == 0
        return f'| {mode.name} | {op.name} | {"first reply" if drop else "none"} | {attempts} | {expected:g} | {actual:g} | {"PASS" if actual == expected else "DUPLICATE EFFECT"} |'
    finally:
        client.close()
        server.running = False
        worker.join(2)


if __name__ == '__main__':
    rows = ['# Measured UDP experiment results', '',
            'Fresh server for each case: flight 101 starts with 100 seats and fare 500. '
            'The first reply is deliberately discarded AFTER execution; the client retries the same request ID. '
            'Expected means the effect of exactly one execution. Results use real loopback UDP sockets.', '',
            '| Mode | Operation | Loss | Sends | Expected | Actual | Outcome |',
            '|---|---|---|---:|---:|---:|---|']
    for mode in [Mode.ALO, Mode.AMO]:
        for op, amount in [(Op.RESERVE, 2), (Op.SET_FARE, 600), (Op.ADD_FARE, 10)]:
            for drop in [False, True]:
                rows.append(run_case(mode, op, amount, drop))
    rows += ['', 'ALO repeats non-idempotent operations when replies are lost. '
             'AMO replays the cached response without executing again. SET_FARE stays correct in both modes because it is idempotent.', '',
             'Scope: same server process, no crash recovery. Finite retries can end with an unknown outcome. '
             'This is a correctness experiment, not a throughput benchmark or a cross-computer demonstration.']
    output = '\n'.join(rows) + '\n'
    Path(__file__).with_name('EXPERIMENT_RESULTS.md').write_text(output, encoding='utf-8')
    print(output)
