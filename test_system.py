"""Integration tests use real local UDP sockets; no external dependencies."""
import socket
import subprocess
import sys
import threading
import time
import unittest

from client import FlightClient
from protocol import Kind, Mode, Op, Reader, Writer, arguments, pack, unpack, read_reply, read_arguments, reply_body
from server import FlightServer


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.servers, self.clients = [], []

    def tearDown(self):
        for client in self.clients:
            client.close()
        for server, thread in self.servers:
            server.running = False
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def start(self, mode=Mode.AMO, **options):
        server = FlightServer(port=0, mode=mode, **options)
        server.log = lambda message: None
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return server

    def client(self, server, mode=None):
        client = FlightClient(*server.address, mode=mode or server.mode, timeout=.08, retries=2)
        self.clients.append(client)
        return client

    def test_binary_codec_and_malformed_payloads(self):
        w = Writer().u32(0x12345678).i64(-5).f64(12.25).string('新加坡✈Tokyo')
        self.assertEqual(bytes(w.data[:4]), b'\x12\x34\x56\x78')
        r = Reader(w.data)
        self.assertEqual((r.u32(), r.i64(), r.f64(), r.string()), (0x12345678, -5, 12.25, '新加坡✈Tokyo'))
        r.end()
        with self.assertRaises(ValueError):
            Reader(b'\x00').u32()
        with self.assertRaises(ValueError):
            unpack(b'bad')

    def test_all_business_operations_and_errors(self):
        server = self.start()
        client = self.client(server)
        self.assertEqual(client.call(Op.SEARCH, 'singapore', 'Tokyo')['result'], [101, 102])
        self.assertNotEqual(client.call(Op.SEARCH, 'Paris', 'Tokyo')['status'], 0)
        self.assertEqual(client.call(Op.DETAILS, 101)['result']['seats'], 100)
        self.assertNotEqual(client.call(Op.DETAILS, 999)['status'], 0)
        self.assertEqual(client.call(Op.RESERVE, 101, 2)['result'], 98)
        for quantity in [0, 999]:
            self.assertNotEqual(client.call(Op.RESERVE, 101, quantity)['status'], 0)
        self.assertEqual(client.call(Op.DETAILS, 101)['result']['seats'], 98)
        for _ in range(2):
            self.assertEqual(client.call(Op.UPDATE_STATUS, 101, 'weather-delay', 30)['result'],
                             dict(flight_status=2, delay_minutes=30))
        self.assertEqual(client.call(Op.ADD_BAGGAGE, 101, 2.5)['result'],
                         dict(total_baggage_kg=2.5, total_baggage_cost=38.75))
        self.assertEqual(client.call(Op.ADD_BAGGAGE, 101, 1.5)['result'],
                         dict(total_baggage_kg=4.0, total_baggage_cost=62.0))
        for value in [-1, 0, float('nan'), float('inf'), 1000001]:
            self.assertNotEqual(client.call(Op.ADD_BAGGAGE, 101, value)['status'], 0)
        for status, delay in [(3, 0), (0, 30)]:
            self.assertNotEqual(client.call(Op.UPDATE_STATUS, 101, status, delay)['status'], 0)
        state = client.call(Op.DETAILS, 101)['result']
        self.assertEqual(state['departure'], dict(year=2026, month=10, day=20, hour=2, minute=0))
        self.assertEqual(state['flight_status'], 2)
        self.assertEqual(state['total_baggage_cost'], 62)
        self.assertEqual(state['fare'], 500)
        self.assertEqual(client.call(Op.DETAILS, 103)['result']['total_baggage_kg'], 0)
        self.assertNotEqual(client.call(Op.MONITOR, 101, 0)['status'], 0)

    def test_new_operations_under_lost_replies(self):
        for mode, weight, cost in [(Mode.ALO, 4, 62), (Mode.AMO, 2, 31)]:
            server = self.start(mode, drop_first_reply=True)
            client = self.client(server)
            self.assertEqual(client.call(Op.ADD_BAGGAGE, 101, 2)['result'],
                             dict(total_baggage_kg=weight, total_baggage_cost=cost))
            self.assertEqual(client.last_attempts, 2)
            server.drop_first_reply = True
            self.assertEqual(client.call(Op.UPDATE_STATUS, 101, 'maintenance', 45)['result'],
                             dict(flight_status=1, delay_minutes=45))
            self.assertEqual(client.last_attempts, 2)
            self.assertEqual(client.call(Op.UPDATE_STATUS, 101, 'on-time', 0)['result'],
                             dict(flight_status=0, delay_minutes=0))

    def test_monitor_replay_preserves_lease_even_after_expiry(self):
        for mode in [Mode.ALO, Mode.AMO]:
            server = self.start(mode)
            client = self.client(server)
            self.assertEqual(client.call(Op.MONITOR, 101, .15)['status'], 0)
            key = (client.client_id, client.request_id)
            original_expiry = server.subscriptions[key]['expires']
            original_address = server.subscriptions[key]['address']
            self.assertEqual(original_address[1], client.sock.getsockname()[1])
            packet = pack(Kind.REQUEST, mode, Op.MONITOR, *key, arguments(Op.MONITOR, (101, .15)))
            client.sock.sendto(packet, server.address)
            client.receive(time.monotonic()+1)
            self.assertEqual(server.subscriptions[key]['expires'], original_expiry)
            time.sleep(.3)
            client.sock.sendto(packet, server.address)
            client.receive(time.monotonic()+1)
            self.assertNotIn(key, server.subscriptions)

    def test_v2_wire_layout_and_truncated_new_fields(self):
        server = self.start()
        body = reply_body(Op.DETAILS, 0, 'OK', server.flights[101])
        r = Reader(body)
        self.assertEqual((r.u32(), r.string(), r.u32(), r.string(), r.string()),
                         (0, 'OK', 101, 'Singapore', 'Tokyo'))
        self.assertEqual([r.u32() for _ in range(5)], [2026, 10, 20, 2, 0])
        self.assertEqual(r.f64(), 500)
        with self.assertRaises(ValueError):
            read_reply(Op.DETAILS, body[:-1])
        with self.assertRaises(ValueError):
            read_arguments(Op.UPDATE_STATUS, Writer().u32(101).u32(2).data)
        self.assertEqual(read_arguments(Op.UPDATE_STATUS, arguments(Op.UPDATE_STATUS, (101, '天气延误', 30))),
                         (101, 2, 30))

    def test_baggage_decimal_rounding(self):
        server = self.start()
        client = self.client(server)
        client.call(Op.ADD_BAGGAGE, 101, .1)
        self.assertEqual(client.call(Op.ADD_BAGGAGE, 101, .2)['result'],
                         dict(total_baggage_kg=.3, total_baggage_cost=4.65))
        self.assertEqual(client.call(Op.ADD_BAGGAGE, 103, .01)['result']['total_baggage_cost'], .16)

    def test_lost_reply_alo_reexecutes_amo_deduplicates(self):
        for mode, expected in [(Mode.ALO, 96), (Mode.AMO, 98)]:
            server = self.start(mode, drop_first_reply=True)
            client = self.client(server)
            self.assertEqual(client.call(Op.RESERVE, 101, 2)['result'], expected)
            self.assertEqual(client.last_attempts, 2)
            self.assertEqual(client.call(Op.DETAILS, 101)['result']['seats'], expected)

    def test_multiple_subscribers_expiry_and_other_flights(self):
        server = self.start()
        subscribers = [self.client(server), self.client(server)]
        actor = self.client(server)
        for client in subscribers:
            self.assertEqual(client.call(Op.MONITOR, 101, .25)['status'], 0)
        actor.call(Op.RESERVE, 103, 1)
        actor.call(Op.RESERVE, 101, 3)
        for client in subscribers:
            packet = client.receive(time.monotonic() + 1)
            self.assertEqual(packet[0], Kind.CALLBACK)
            r = Reader(packet[-1])
            self.assertEqual((r.u32(), r.u32(), r.u32()), (101, 97, 1))
            r.end()
        time.sleep(.35)
        actor.call(Op.RESERVE, 101, 1)
        for client in subscribers:
            with self.assertRaises(socket.timeout):
                client.receive(time.monotonic() + .1)

    def test_mode_mismatch(self):
        server = self.start(Mode.AMO)
        client = self.client(server, Mode.ALO)
        self.assertEqual(client.call(Op.RESERVE, 101, 2)['status'], 2)
        self.assertEqual(server.flights[101]['seats'], 100)

    def test_request_loss_and_exhausted_retries(self):
        server = self.start(request_loss=1)
        client = self.client(server)
        with self.assertRaisesRegex(TimeoutError, 'UNKNOWN'):
            client.call(Op.RESERVE, 101, 2)
        self.assertEqual(server.flights[101]['seats'], 100)
        self.assertEqual(server.stats['requests_dropped'], 3)

    def test_all_reply_loss_executes_once_in_amo(self):
        server = self.start(reply_loss=1)
        client = self.client(server)
        with self.assertRaises(TimeoutError):
            client.call(Op.RESERVE, 101, 2)
        self.assertEqual(server.flights[101]['seats'], 98)
        self.assertEqual(server.stats['duplicates'], 2)

    def test_request_id_collision_rejected_and_malformed_packet_survived(self):
        server = self.start()
        client = self.client(server)
        client.sock.sendto(b'garbage', server.address)
        self.assertEqual(client.call(Op.RESERVE, 101, 2)['result'], 98)
        packet = pack(Kind.REQUEST, Mode.AMO, Op.RESERVE, client.client_id,
                      client.request_id, arguments(Op.RESERVE, (101, 3)))
        client.sock.sendto(packet, server.address)
        response = client.receive(time.monotonic()+1)
        self.assertEqual(read_reply(Op.RESERVE, response[-1])['status'], 3)
        self.assertEqual(server.flights[101]['seats'], 98)

    def test_two_clients_can_use_same_counter(self):
        server = self.start()
        first, second = self.client(server), self.client(server)
        self.assertEqual(first.call(Op.RESERVE, 101, 2)['result'], 98)
        self.assertEqual(second.call(Op.RESERVE, 101, 2)['result'], 96)

    def test_request_loss_recovery(self):
        server = self.start(request_loss=.5, seed=1)
        client = self.client(server)
        self.assertEqual(client.call(Op.RESERVE, 101, 2)['result'], 98)
        self.assertEqual(client.last_attempts, 2)

    def test_cli_and_complete_monitor_flow(self):
        server = self.start()
        result = subprocess.run([sys.executable, 'client.py', '--port', str(server.address[1]),
                                 'search', 'Singapore', 'Tokyo'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[101, 102]', result.stdout)
        for args, expected in [(['update-status', '101', 'weather-delay', '30'], 'WEATHER_DELAY'),
                               (['add-baggage', '101', '2'], '$31.00'),
                               (['details', '101'], '2026-10-20 02:00 UTC')]:
            result = subprocess.run([sys.executable, 'client.py', '--port', str(server.address[1]), *args],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)
        actor = self.client(server)
        updates, failures = [], []

        def reserve_after_registration():
            deadline = time.monotonic() + 2
            while not server.subscriptions and time.monotonic() < deadline:
                time.sleep(.01)
            try:
                actor.call(Op.RESERVE, 101, 2)
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=reserve_after_registration)
        worker.start()
        try:
            subscriber = self.client(server)
            reply = subscriber.monitor(101, .4, updates.append)
            self.assertEqual(reply['status'], 0)
        finally:
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(updates, [dict(flight_id=101, seats=98, sequence=1)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
