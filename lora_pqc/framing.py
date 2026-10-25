
from __future__ import annotations

HEADER_LEN = 6
ACK_HEADER_LEN = 5
TYPE_DATA = 0
TYPE_ACK = 1


def split(message: bytes, session_id: int, msg_id: int, max_packet: int) -> list[bytes]:
 
    if not message:
        raise ValueError("message is empty")
    if max_packet <= HEADER_LEN:
        raise ValueError("max_packet leaves no room for data after the header")
    chunk_size = max_packet - HEADER_LEN
    if len(message) > 255 * chunk_size:
        raise ValueError("message would need more than 255 packets")

    packets = []
    total = (len(message) + chunk_size - 1) // chunk_size
    for seq, start in enumerate(range(0, len(message), chunk_size)):
        end = start + chunk_size
        chunk = message[start:end]
        header = (
            TYPE_DATA.to_bytes(1, "big") +
            session_id.to_bytes(2, "big") +
            msg_id.to_bytes(1, "big") +
            seq.to_bytes(1, "big") +
            total.to_bytes(1, "big")
        )
        packets.append(header + chunk)

    return packets


class Reassembler:

    def __init__(self, session_id: int | None, msg_id: int):
        self.session_id = session_id
        self.msg_id = msg_id
        self.total = None   
        self.chunks = {}     

    def add(self, packet: bytes) -> bool:
       
        if len(packet) <= HEADER_LEN:
            return False

        ptype = packet[0]
        session_id = int.from_bytes(packet[1:3], "big")
        msg_id = packet[3]
        seq = packet[4]
        total = packet[5]

        if ptype != TYPE_DATA or msg_id != self.msg_id:
            return False
        if total == 0 or seq >= total:
            return False
        if self.session_id is None:
            self.session_id = session_id
        if session_id != self.session_id:
            return False
        if self.total is not None and total != self.total:
            return False

        self.total = total
        self.chunks.setdefault(seq, packet[HEADER_LEN:])
        return True

    def complete(self) -> bool:
        return self.total is not None and len(self.chunks) == self.total

    def missing(self) -> list[int]:
        if self.total is None:
            return []
        return [seq for seq in range(self.total) if seq not in self.chunks]

    def message(self) -> bytes:
        if not self.complete():
            raise ValueError(f"message incomplete, missing packets {self.missing()}")
        return b"".join(self.chunks[seq] for seq in range(self.total))



def make_ack(session_id: int, msg_id: int, total: int, missing: list[int]) -> bytes:
    header = (
        TYPE_ACK.to_bytes(1, "big") +
        session_id.to_bytes(2, "big") +
        msg_id.to_bytes(1, "big") +
        total.to_bytes(1, "big")
    )

    temp = bytearray(total//8 + (1 if total % 8 else 0))
    for seq in missing:
        temp[seq // 8] |= 1 << (seq % 8)

    return header + bytes(temp)

    


def parse_ack(packet: bytes, session_id: int, msg_id: int) -> list[int] | None:
    

    if len(packet) < ACK_HEADER_LEN:
        return None

    ptype = packet[0]
    session = int.from_bytes(packet[1:3], "big")
    msg = packet[3]
    total = packet[4]

    if ptype != TYPE_ACK or session != session_id or msg != msg_id:
           return None
    if total == 0 or len(packet) < ACK_HEADER_LEN + (total//8 + (1 if total % 8 else 0)):
           return None

    temp = packet[ACK_HEADER_LEN:]
    missing = []
    for seq in range(total):
        if temp[seq // 8] & (1 << (seq % 8)):
            missing.append(seq)

    return missing