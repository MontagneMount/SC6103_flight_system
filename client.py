"""Console UDP client; retries preserve the original request identity."""
import argparse
import math
import socket
import struct
import time
import uuid

from protocol import Kind, Mode, Op, FlightStatus, Reader, arguments, pack, unpack, read_reply


class FlightClient:
    def __init__(self, host='127.0.0.1', port=9000, mode=Mode.AMO, timeout=1.0, retries=3):
        if not math.isfinite(timeout) or timeout <= 0 or retries < 0:
            raise ValueError('Timeout must be positive and retries nonnegative')
        self.address = (socket.gethostbyname(host), port)
        self.mode, self.timeout, self.retries = mode, timeout, retries
        self.client_id = uuid.uuid4().bytes
        self.request_id = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        self.pending = []
        self.last_attempts = 0

    def close(self):
        self.sock.close()

    def receive(self, deadline):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()
            self.sock.settimeout(remaining)
            data, address = self.sock.recvfrom(65535)
            if address != self.address:
                continue
            try:
                packet = unpack(data)
            except ValueError:
                continue
            if packet[1] == self.mode and packet[3] == self.client_id:
                return packet

    def call(self, op, *values):
        body = arguments(op, values)
        self.request_id += 1
        self.pending = []
        packet = pack(Kind.REQUEST, self.mode, op, self.client_id, self.request_id, body)
        for attempt in range(self.retries + 1):
            self.last_attempts = attempt + 1
            self.sock.sendto(packet, self.address)
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    kind, _, received_op, _, request_id, payload = self.receive(deadline)
                except socket.timeout:
                    break
                if request_id != self.request_id or received_op != op:
                    continue
                if kind == Kind.CALLBACK and op == Op.MONITOR:
                    self.pending.append(payload)
                elif kind == Kind.REPLY:
                    try:
                        return read_reply(op, payload)
                    except (ValueError, UnicodeError):
                        continue
        raise TimeoutError('No reply after retries. Outcome is UNKNOWN: the server may have executed the operation. Query state before submitting a new operation.')

    def monitor(self, flight_id, seconds, on_update=print):
        started = time.monotonic()
        reply = self.call(Op.MONITOR, flight_id, seconds)
        if reply['status']:
            return reply
        # Start at acknowledgement to avoid missing late server registrations.
        deadline = time.monotonic() + seconds
        latest = 0

        def emit(body):
            nonlocal latest
            try:
                reader = Reader(body)
                fid, seats, sequence = reader.u32(), reader.u32(), reader.u32()
                reader.end()
            except ValueError:
                return
            if fid == flight_id and sequence > latest:
                latest = sequence
                on_update(dict(flight_id=fid, seats=seats, sequence=sequence))

        for body in self.pending:
            emit(body)
        print(f'Monitor registered for flight {flight_id}; waiting up to {seconds:g}s.', flush=True)
        while time.monotonic() < deadline:
            try:
                kind, _, op, _, request_id, body = self.receive(deadline)
            except socket.timeout:
                break
            if kind == Kind.CALLBACK and op == Op.MONITOR and request_id == self.request_id:
                emit(body)
        print(f'Monitor finished ({time.monotonic()-started:.1f}s including registration).', flush=True)
        return reply


def display(reply):
    if reply['status']:
        print('ERROR:', reply['message'])
        return
    value = reply['result']
    if isinstance(value, dict):
        value = dict(value)
        if 'departure' in value:
            dt = value['departure']
            value['departure'] = (f'{dt["year"]:04d}-{dt["month"]:02d}-{dt["day"]:02d} '
                                  f'{dt["hour"]:02d}:{dt["minute"]:02d} UTC')
        if 'flight_status' in value:
            value['flight_status'] = FlightStatus(value['flight_status']).name
        if 'total_baggage_cost' in value:
            value['total_baggage_cost'] = f'${value["total_baggage_cost"]:.2f}'
    print('OK:', value)


def menu(client):
    while True:
        print('\n1 Search flights  2 Flight details  3 Reserve seats\n4 Monitor seats  5 Update flight status  6 Buy extra baggage ($15.50/kg)  0 Exit')
        choice = input('Operation: ').strip()
        if choice == '0':
            return
        try:
            op = Op(int(choice))
            if op == Op.SEARCH:
                values = (input('Source: '), input('Destination: '))
            else:
                values = (int(input('Flight ID: ')),)
                if op == Op.RESERVE:
                    values += (int(input('Seats to reserve: ')),)
                elif op == Op.UPDATE_STATUS:
                    values += (input('Status (0=on time, 1=maintenance, 2=weather delay): '),
                               int(input('Delay minutes: ')))
                elif op in (Op.MONITOR, Op.ADD_BAGGAGE):
                    values += (float(input('Seconds: ' if op == Op.MONITOR else 'Extra baggage kg: ')),)
            display(client.monitor(*values) if op == Op.MONITOR else client.call(op, *values))
        except (ValueError, OverflowError, struct.error, OSError) as exc:
            print('ERROR:', exc)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--mode', choices=['alo', 'amo'], default='amo')
    parser.add_argument('--timeout', type=float, default=1)
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('operation', nargs='?', choices=['search', 'details', 'reserve', 'monitor', 'update-status', 'add-baggage'])
    parser.add_argument('values', nargs='*')
    args = parser.parse_args()
    client = FlightClient(args.host, args.port, Mode[args.mode.upper()], args.timeout, args.retries)
    try:
        if args.operation:
            op = Op[args.operation.replace('-', '_').upper()]
            expected = 1 if op == Op.DETAILS else (3 if op == Op.UPDATE_STATUS else 2)
            if len(args.values) != expected:
                parser.error(f'{args.operation} requires {expected} arguments')
            if op == Op.MONITOR:
                display(client.monitor(int(args.values[0]), float(args.values[1])))
            else:
                display(client.call(op, *args.values))
        else:
            menu(client)
    except (ValueError, OverflowError, struct.error, OSError) as exc:
        print('ERROR:', exc)
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nClient stopped.')
    finally:
        client.close()
