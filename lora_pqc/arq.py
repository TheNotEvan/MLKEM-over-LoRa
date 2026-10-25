
from __future__ import annotations
import time

from dataclasses import dataclass

from .framing import Reassembler, make_ack, parse_ack, split
from .radio import Radio


class TransferFailed(Exception):
    """The link is too bad, or dead: give up loudly instead of hanging."""


@dataclass
class TransferStats:
    rounds: int = 0      
    packets_sent: int = 0  
    resends: int = 0       


def send_message(
    radio: Radio,
    message: bytes,
    session_id: int,
    msg_id: int,
    max_packet: int,
    *,
    ack_timeout: float = 0.05,
    max_rounds: int = 20,
) -> TransferStats:
    
    packets = split(message, session_id, msg_id, max_packet)
    stats = TransferStats()
    to_send = list(range(len(packets)))
    for _ in range(max_rounds):
        for seq in to_send:
            radio.send(packets[seq])
            stats.packets_sent += 1
        stats.rounds += 1

        missing = None
        deadline = time.monotonic() + ack_timeout
        while (time_left := deadline - time.monotonic()) > 0:
            ack = radio.recv(timeout=time_left)
            if ack is not None:
                missing = parse_ack(ack, session_id, msg_id)
                if missing is not None:
                    break

        if missing == []:
            stats.resends = stats.packets_sent - len(packets)
            return stats
        elif missing is not None:
            to_send = missing
        else:
            to_send = [len(packets) - 1]

    stats.resends = stats.packets_sent - len(packets)
    raise TransferFailed("Max rounds reached without successful transfer")


def receive_message(
    radio: Radio,
    session_id: int,
    msg_id: int,
    *,
    quiet_gap: float = 0.01,
    linger: float = 0.5,
    timeout: float = 10.0,
) -> bytes:
    reassembler = Reassembler(session_id, msg_id)
    return _receive(radio, reassembler, quiet_gap, linger, timeout)


def receive_new_session(
    radio: Radio,
    msg_id: int,
    *,
    quiet_gap: float = 0.01,
    linger: float = 0.5,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    reassembler = Reassembler(None, msg_id)
    message = _receive(radio, reassembler, quiet_gap, linger, timeout)
    return reassembler.session_id, message


def _receive(radio: Radio, reassembler: Reassembler, quiet_gap: float, linger: float, timeout: float) -> bytes:
    msg_id = reassembler.msg_id
    acked = False
    start_time = time.monotonic()
    while not reassembler.complete():
        if time.monotonic() - start_time > timeout:
            raise TransferFailed("Timeout while waiting for message")
        packet = radio.recv(timeout=quiet_gap)
        if packet is None:
            if reassembler.total is not None and not acked:
                missing = reassembler.missing()
                ack_packet = make_ack(reassembler.session_id, msg_id, reassembler.total, missing)
                radio.send(ack_packet)
                acked = True
        elif reassembler.add(packet):
            acked = False
    ack_packet = make_ack(reassembler.session_id, msg_id, reassembler.total, [])
    radio.send(ack_packet)
    deadline = time.monotonic() + linger
    while (time_left := deadline - time.monotonic()) > 0:
        packet = radio.recv(timeout=time_left)
        if packet is not None and reassembler.add(packet):
            ack_packet = make_ack(reassembler.session_id, msg_id, reassembler.total, [])
            radio.send(ack_packet)
            deadline = time.monotonic() + linger
    return reassembler.message()


