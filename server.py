"""Single-threaded UDP server with optional request/reply loss injection."""
import argparse
import math
import random
import socket
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from protocol import Kind, Mode, Op, FlightStatus, TIME_FIELDS, Writer, pack, unpack, read_arguments, reply_body, read_reply


class FlightServer:
    def __init__(self, host='127.0.0.1', port=9000, mode=Mode.AMO,
                 request_loss=0, reply_loss=0, drop_first_reply=False, seed=1):
        self.mode = mode
        self.request_loss, self.reply_loss = request_loss, reply_loss
        self.drop_first_reply = drop_first_reply
        self.random = random.Random(seed)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(0.1)
        self.address = self.sock.getsockname()
        departure = int(datetime(2026, 10, 20, 2, tzinfo=timezone.utc).timestamp())
        self.flights = {
            101: dict(id=101, source='Singapore', destination='Tokyo', departure=departure, fare=500.0, seats=100),
            102: dict(id=102, source='Singapore', destination='Tokyo', departure=departure+3600, fare=550.0, seats=50),
            103: dict(id=103, source='Singapore', destination='Shanghai', departure=departure+7200, fare=350.0, seats=80),
        }
        for flight in self.flights.values():
            dt = datetime.fromtimestamp(flight['departure'], timezone.utc)
            flight['departure'] = {field: getattr(dt, field) for field in TIME_FIELDS}
            flight.update(flight_status=FlightStatus.ON_TIME, delay_minutes=0,
                          total_baggage_kg=0.0, total_baggage_cost=0.0)
        # Exact decimal accumulation internally; wire format is explicitly f64.
        self.baggage_weights = {flight_id: Decimal('0') for flight_id in self.flights}
        # Lifetime history deliberately retained: eviction would weaken AMO guarantees.
        self.history = {}
        # Registration replay preserves the original lease even in ALO mode.
        self.monitor_history = {}
        self.subscriptions = {}
        self.running = True
        self.stats = dict(executed=0, duplicates=0, requests_dropped=0, replies_dropped=0)

    def log(self, message):
        print(message, flush=True)

    def expire(self):
        now = time.monotonic()
        for key, sub in list(self.subscriptions.items()):
            if sub['expires'] <= now:
                del self.subscriptions[key]

    def notify(self, flight_id):
        self.expire()
        for sub in self.subscriptions.values():
            if sub['flight_id'] != flight_id:
                continue
            sub['sequence'] += 1
            body = Writer().u32(flight_id).u32(self.flights[flight_id]['seats']).u32(sub['sequence']).data
            packet = pack(Kind.CALLBACK, self.mode, Op.MONITOR, sub['client_id'], sub['request_id'], body)
            try:
                self.sock.sendto(packet, sub['address'])
                self.log(f'CALLBACK to {sub["address"]}: flight={flight_id} seats={self.flights[flight_id]["seats"]}')
            except OSError as exc:
                self.log(f'Callback send failed: {exc}')

    def execute(self, op, args, client_id, request_id, address):
        if op == Op.SEARCH:
            source, destination = (value.strip().casefold() for value in args)
            matches = [f['id'] for f in self.flights.values()
                       if f['source'].casefold() == source and f['destination'].casefold() == destination]
            if not matches:
                raise ValueError('No matching flights')
            return matches
        flight_id = args[0]
        if flight_id not in self.flights:
            raise ValueError('Flight does not exist')
        flight = self.flights[flight_id]
        if op == Op.DETAILS:
            return flight
        value = args[1]
        if op == Op.UPDATE_STATUS:
            try:
                status = FlightStatus(value)
            except ValueError:
                raise ValueError('Status must be 0 (on time), 1 (maintenance), or 2 (weather delay)')
            delay = args[2]
            if status == FlightStatus.ON_TIME and delay != 0:
                raise ValueError('On-time flights must have zero delay')
            flight.update(flight_status=status, delay_minutes=delay)
            return dict(flight_status=status, delay_minutes=delay)
        if op == Op.RESERVE:
            if value <= 0 or value > flight['seats']:
                raise ValueError('Seat count must be positive and no greater than availability')
            flight['seats'] -= value
            self.notify(flight_id)
            return flight['seats']
        if not math.isfinite(value):
            raise ValueError('Value must be finite')
        if op == Op.MONITOR:
            if not 0 < value <= 3600:
                raise ValueError('Monitor interval must be in (0, 3600] seconds')
            self.subscriptions[(client_id, request_id)] = dict(
                client_id=client_id, request_id=request_id, flight_id=flight_id,
                expires=time.monotonic()+value, address=address, sequence=0)
            return value
        if value <= 0:
            raise ValueError('Extra baggage weight must be positive')
        total = self.baggage_weights[flight_id] + Decimal(str(value))
        if total > Decimal('1000000'):
            raise ValueError('Total baggage must not exceed 1000000 kg')
        cost = (total * Decimal('15.50')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.baggage_weights[flight_id] = total
        flight.update(total_baggage_kg=float(total), total_baggage_cost=float(cost))
        return dict(total_baggage_kg=float(total), total_baggage_cost=float(cost))

    def handle(self, data, address):
        try:
            kind, mode, op, client_id, request_id, body = unpack(data)
            if kind != Kind.REQUEST:
                return
        except (ValueError, UnicodeError):
            self.log('Ignored malformed datagram')
            return
        if self.random.random() < self.request_loss:
            self.stats['requests_dropped'] += 1
            self.log(f'DROP request {request_id}')
            return
        self.log(f'REQUEST {address} id={request_id} op={op.name}')
        key = (client_id, request_id)
        signature = (op, body)
        history = self.monitor_history if mode == Mode.ALO and op == Op.MONITOR else self.history
        use_history = mode == Mode.AMO or op == Op.MONITOR
        if mode != self.mode:
            response = pack(Kind.REPLY, mode, op, client_id, request_id,
                            reply_body(op, 2, 'Client/server invocation modes differ'))
        elif use_history and key in history:
            previous, response = history[key]
            if signature != previous:
                response = pack(Kind.REPLY, mode, op, client_id, request_id,
                                reply_body(op, 3, 'Request ID reused with different arguments'))
            else:
                self.stats['duplicates'] += 1
                self.log(f'DUPLICATE {request_id}: replay cached reply')
        else:
            try:
                args = read_arguments(op, body)
                self.log(f'ARGUMENTS {args}')
                self.stats['executed'] += 1
                result = self.execute(op, args, client_id, request_id, address)
                payload = reply_body(op, 0, 'OK', result)
            except (ValueError, UnicodeError, OverflowError) as exc:
                payload = reply_body(op, 1, str(exc))
            response = pack(Kind.REPLY, mode, op, client_id, request_id, payload)
            if use_history:
                history[key] = (signature, response)
        if self.drop_first_reply or self.random.random() < self.reply_loss:
            self.drop_first_reply = False
            self.stats['replies_dropped'] += 1
            self.log(f'DROP reply {request_id}')
        else:
            self.sock.sendto(response, address)
            self.log(f'REPLY id={request_id}: {read_reply(op, unpack(response)[-1])}')

    def serve(self):
        self.log(f'READY {self.address[0]}:{self.address[1]} mode={self.mode.name.lower()}')
        try:
            while self.running:
                self.expire()
                try:
                    data, address = self.sock.recvfrom(65535)
                    self.handle(data, address)
                except socket.timeout:
                    continue
        finally:
            self.sock.close()


def probability(value):
    result = float(value)
    if not 0 <= result <= 1:
        raise argparse.ArgumentTypeError('Probability must be between 0 and 1')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--mode', choices=['alo', 'amo'], default='amo')
    parser.add_argument('--request-loss', type=probability, default=0)
    parser.add_argument('--reply-loss', type=probability, default=0)
    parser.add_argument('--drop-first-reply', action='store_true')
    parser.add_argument('--seed', type=int, default=1)
    options = vars(parser.parse_args())
    options['mode'] = Mode[options['mode'].upper()]
    server = FlightServer(**options)
    try:
        server.serve()
    except KeyboardInterrupt:
        print('\nServer stopped.')
