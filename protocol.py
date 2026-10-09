"""Explicit binary wire protocol. No pickle, JSON, RPC or object serialization."""
import struct
from enum import IntEnum

MAGIC = b'FL'
VERSION = 2
MAX_PACKET = 60000
HEADER = struct.Struct('!2sBBBB16sQ')


class Kind(IntEnum):
    REQUEST = 1
    REPLY = 2
    CALLBACK = 3


class Mode(IntEnum):
    ALO = 1
    AMO = 2


class Op(IntEnum):
    SEARCH = 1
    DETAILS = 2
    RESERVE = 3
    MONITOR = 4
    UPDATE_STATUS = 5
    ADD_BAGGAGE = 6


class FlightStatus(IntEnum):
    ON_TIME = 0
    MAINTENANCE = 1
    WEATHER_DELAY = 2


TIME_FIELDS = ('year', 'month', 'day', 'hour', 'minute')


def status_code(value):
    names = {'on-time': 0, 'maintenance': 1, 'weather-delay': 2,
             '准点': 0, '检修': 1, '天气延误': 2}
    name = str(value).strip().lower()
    return names[name] if name in names else int(value)


class Writer:
    def __init__(self):
        self.data = bytearray()

    def u32(self, value):
        self.data.extend(struct.pack('!I', value))
        return self

    def i64(self, value):
        self.data.extend(struct.pack('!q', value))
        return self

    def f64(self, value):
        self.data.extend(struct.pack('!d', value))
        return self

    def string(self, value):
        raw = value.encode('utf-8')
        self.u32(len(raw))
        self.data.extend(raw)
        return self


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        if size < 0 or self.offset + size > len(self.data):
            raise ValueError('Truncated payload')
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def u32(self):
        return struct.unpack('!I', self.take(4))[0]

    def i64(self):
        return struct.unpack('!q', self.take(8))[0]

    def f64(self):
        return struct.unpack('!d', self.take(8))[0]

    def string(self):
        return self.take(self.u32()).decode('utf-8')

    def end(self):
        if self.offset != len(self.data):
            raise ValueError('Unexpected trailing payload')


def pack(kind, mode, op, client_id, request_id, body=b''):
    data = HEADER.pack(MAGIC, VERSION, kind, mode, op, client_id, request_id) + bytes(body)
    if len(data) > MAX_PACKET:
        raise ValueError('Packet too large')
    return data


def unpack(data):
    if not HEADER.size <= len(data) <= MAX_PACKET:
        raise ValueError('Invalid packet length')
    magic, version, kind, mode, op, client_id, request_id = HEADER.unpack(data[:HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise ValueError('Invalid protocol or version')
    return Kind(kind), Mode(mode), Op(op), client_id, request_id, data[HEADER.size:]


def arguments(op, values):
    w = Writer()
    if op == Op.SEARCH:
        w.string(str(values[0])).string(str(values[1]))
    else:
        w.u32(int(values[0]))
        if op == Op.RESERVE:
            w.u32(int(values[1]))
        elif op == Op.UPDATE_STATUS:
            w.u32(status_code(values[1])).u32(int(values[2]))
        elif op in (Op.MONITOR, Op.ADD_BAGGAGE):
            w.f64(float(values[1]))
    return bytes(w.data)


def read_arguments(op, body):
    r = Reader(body)
    if op == Op.SEARCH:
        values = (r.string(), r.string())
    else:
        values = (r.u32(),)
        if op == Op.RESERVE:
            values += (r.u32(),)
        elif op == Op.UPDATE_STATUS:
            values += (r.u32(), r.u32())
        elif op in (Op.MONITOR, Op.ADD_BAGGAGE):
            values += (r.f64(),)
    r.end()
    return values


def reply_body(op, status, message, result=None):
    w = Writer().u32(status).string(message)
    if status == 0:
        if op == Op.SEARCH:
            w.u32(len(result))
            for flight_id in result:
                w.u32(flight_id)
        elif op == Op.DETAILS:
            w.u32(result['id']).string(result['source']).string(result['destination'])
            for field in TIME_FIELDS:
                w.u32(result['departure'][field])
            w.f64(result['fare']).u32(result['seats'])
            w.u32(result['flight_status']).u32(result['delay_minutes'])
            w.f64(result['total_baggage_kg']).f64(result['total_baggage_cost'])
        elif op == Op.RESERVE:
            w.u32(result)
        elif op == Op.UPDATE_STATUS:
            w.u32(result['flight_status']).u32(result['delay_minutes'])
        elif op == Op.ADD_BAGGAGE:
            w.f64(result['total_baggage_kg']).f64(result['total_baggage_cost'])
        else:
            w.f64(result)
    return w.data


def read_reply(op, body):
    r = Reader(body)
    status, message = r.u32(), r.string()
    result = None
    if status == 0:
        if op == Op.SEARCH:
            count = r.u32()
            if count > (len(body) - r.offset) // 4:
                raise ValueError('Invalid result count')
            result = [r.u32() for _ in range(count)]
        elif op == Op.DETAILS:
            result = dict(id=r.u32(), source=r.string(), destination=r.string())
            result['departure'] = {field: r.u32() for field in TIME_FIELDS}
            result.update(fare=r.f64(), seats=r.u32(), flight_status=r.u32(),
                          delay_minutes=r.u32(), total_baggage_kg=r.f64(), total_baggage_cost=r.f64())
        elif op == Op.RESERVE:
            result = r.u32()
        elif op == Op.UPDATE_STATUS:
            result = dict(flight_status=r.u32(), delay_minutes=r.u32())
        elif op == Op.ADD_BAGGAGE:
            result = dict(total_baggage_kg=r.f64(), total_baggage_cost=r.f64())
        else:
            result = r.f64()
    r.end()
    return dict(status=status, message=message, result=result)
