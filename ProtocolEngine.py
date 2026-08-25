import json
import struct
from collections import deque


TYPE_MAP = {
    "uint8": ("B", 1),
    "uint16": ("H", 2),
    "uint32": ("I", 4),
    "float32": ("f", 4),
}

import struct

def parse_uint16_pair(buffer: bytes, offset: int, little_endian=True):
    fmt = "<HH" if little_endian else ">HH"
    value1, value2 = struct.unpack_from(fmt, buffer, offset)

    return {
        "value_1": value1,
        "value_2": value2
    }

def pack_value(value, typ):
    if typ in TYPE_MAP:
        fmt, _ = TYPE_MAP[typ]
        return struct.pack("<" + fmt, value)

    if typ in ("bytes", "uint8[]"):
        return bytes(value)

    raise ValueError(f"Unsupported type: {typ}")

class Field:
    def __init__(self, desc):
        self.name = desc["name"]
        self.type = desc["type"]
        self.size = desc.get("size", 0)
        self.bits = desc.get("bits")
        self.enum = desc.get("enum")
        self.fields = desc.get("fields")

class PacketDefinition:
    def __init__(self, name, desc):
        self.name = name
        self.sync_byte = int(desc["sync_byte"], 16)
        self.size = desc.get("size", 0)
        self.fields = [Field(f) for f in desc["fields"]]

class ProtocolEngine:
    def __init__(self, json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            root = json.load(f)

        self.packets = {}

        for direction in ("controller_to_host",):
            for block in root.get(direction, []):
                for name, desc in block.items():
                    pkt = PacketDefinition(name, desc)
                    self.packets[pkt.sync_byte] = pkt

        self.buffer = deque()
        self.current_packet = None

        #выше - чтение из порта, ниже - запись в порт
        self.control_packet = None
        self.commands = {}
        self.eprom = {}

        for block in root.get("host_to_controller", []):
            for name, desc in block.items():

                if name == "control_packet":
                    self.control_packet = desc
                    self.commands = {
                        int(k, 16): v
                        for k, v in desc["command_definitions"].items()
                    }

                if name in ("eprom_write", "eprom_read"):
                    self.eprom[name] = desc

    def feed(self, data: bytes):
        results = []
        for b in data:
            self.buffer.append(b)
            pkt = self._try_parse()
            if pkt:
                results.append(pkt)
        return results

    def _try_parse(self):
        if not self.buffer:
            return None

        if self.current_packet is None:
            sync = self.buffer[0]
            if sync not in self.packets:
                self.buffer.popleft()
                return None

            self.current_packet = self.packets[sync]

        pkt = self.current_packet

        # --- фиксированный размер ---
        if pkt.size > 0:
            if len(self.buffer) < pkt.size:
                return None

            raw = bytes(self.buffer.popleft() for _ in range(pkt.size))
            self.current_packet = None
            return self._decode_packet(pkt, raw)

        # --- переменный размер ---
        data = []
        temp = list(self.buffer)

        offset = 0
        for field in pkt.fields:
            if field.name == "len":
                if offset + 1 > len(temp):
                    return None
                length = temp[offset]
                total = offset + 1 + length
                if len(temp) < total:
                    return None
                raw = bytes(self.buffer.popleft() for _ in range(total))
                self.current_packet = None
                return self._decode_packet(pkt, raw)

            offset += self._field_size(field)

        return None

    def _field_size(self, field):
        if field.type in TYPE_MAP:
            return TYPE_MAP[field.type][1]

        if field.type == "uint16_pair":
            return 4

        if field.type == "bitfield":
            return 1

        if field.type in ("bytes", "uint8[]"):
            return 0

        return 0

    def _decode_packet(self, pkt, raw):
        result = {"__packet__": pkt.name}
        offset = 0

        for field in pkt.fields:
            if field.type == "bitfield":
                v = raw[offset]
                offset += 1
                bf = {}
                for name, bit in field.bits.items():
                    bf[name] = bool(v & (1 << bit))
                result[field.name] = bf
                continue

            if field.type == "uint16_pair":
                v1, v2 = struct.unpack_from("<HH", raw, offset)
                offset += 4
                for sub, value in zip(field.fields, (v1, v2)):
                    result[sub["name"]] = value
                continue

            if field.type in TYPE_MAP:
                fmt, size = TYPE_MAP[field.type]
                value = struct.unpack_from("<" + fmt, raw, offset)[0]
                offset += size
                if field.enum:
                    value = field.enum.get(hex(value), value)
                result[field.name] = value
                continue

            if field.type in ("bytes", "uint8[]"):
                length = result.get("len", 0)
                result[field.name] = raw[offset:offset + length]
                offset += length

        return result

    @staticmethod
    def _pack_value(typ, value, field_desc=None):
        """
        Упаковка payload для host_to_controller control_packet.

        Групповые клапаны (DU16 / электромагнитные) НЕ упаковываются здесь
        из словаря — Engine._build_bitfield уже собирает готовый int
        (битовое поле по всей группе) до вызова build_control(), поэтому
        сюда всегда приходит обычное число (int/float), а не dict.
        """
        TYPE_PACK = {
            "uint8": ("B", 1),
            "uint16": ("H", 2),
            "uint32": ("I", 4),
            "float32": ("f", 4),
        }

        if typ in TYPE_PACK:
            fmt, _ = TYPE_PACK[typ]
            return struct.pack("<" + fmt, value)

        # --- массив байт ---
        if typ in ("bytes", "uint8[]"):
            return bytes(value)

        raise ValueError(f"Unsupported type: {typ}")

    def build_control(self, command_name: str, data):
        for cmd_id, cmd in self.commands.items():
            if cmd["name"] == command_name:
                payload_type = cmd["payload"]
                field_desc = cmd
                break
        else:
            raise ValueError(f"Unknown command: {command_name}")

        payload_bytes = self._pack_value(payload_type, data, field_desc)

        header = int(self.control_packet["fields"][0]["example"], 16)
        payload_len = len(payload_bytes)

        return bytes([
            header,
            cmd_id,
            payload_len
        ]) + payload_bytes

    def build_eprom_write(self, address: int, data: bytes):
        desc = self.eprom["eprom_write"]

        header = int(desc["header"], 16)
        cmd_id = int(desc["cmd_id"], 16)

        length = len(data)

        return (
            bytes([header, cmd_id, length]) +
            struct.pack("<H", address) +
            data
        )

    def build_eprom_read(self, address: int, num_bytes: int):
        desc = self.eprom["eprom_read"]

        header = int(desc["header"], 16)
        cmd_id = int(desc["cmd_id"], 16)

        return (
            bytes([header, cmd_id]) +
            struct.pack("<H", address) +
            bytes([num_bytes])
        )
