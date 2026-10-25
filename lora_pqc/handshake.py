from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import xwing
from .arq import receive_message, send_message
from .radio import Radio

NONCE_LEN = 32
COMMIT_LEN = 32
TAG_LEN = 16


class HandshakeFailed(Exception):
    pass


@dataclass
class Session:
    code: str
    send_key: bytes
    recv_key: bytes


def h(*parts: bytes) -> bytes:
    return hashlib.sha3_256(b"".join(parts)).digest()


def make_session(ss: bytes, transcript: bytes, nonce: bytes, is_alice: bool) -> Session:
    code = f"{int.from_bytes(h(b'code', ss, transcript, nonce), 'big') % 1_000_000:06d}"
    alice_to_bob = h(b"alice->bob", ss, transcript)
    bob_to_alice = h(b"bob->alice", ss, transcript)
    if is_alice:
        return Session(code=code, send_key=alice_to_bob, recv_key=bob_to_alice)
    return Session(code=code, send_key=bob_to_alice, recv_key=alice_to_bob)


def alice_start() -> tuple[object, bytes]:
    sk, pk = xwing.generate_key_pair()
    nonce = secrets.token_bytes(NONCE_LEN)
    msg1 = pk + h(nonce)
    return (sk, msg1, nonce), msg1


def bob_respond(msg1: bytes) -> tuple[object, bytes]:
    if len(msg1) != 1216 + COMMIT_LEN:
        raise HandshakeFailed("Invalid msg1 length")
    pk = msg1[:1216]
    commit = msg1[1216:]
    ss, ct = xwing.encapsulate(pk)
    transcript = msg1 + ct
    msg2 = ct + h(b"bob", ss, transcript)[:TAG_LEN]
    return (ss, transcript, commit), msg2


def alice_finish(state: object, msg2: bytes) -> tuple[Session, bytes]:
    sk, msg1, nonce = state
    if len(msg2) != 1120 + TAG_LEN:
        raise HandshakeFailed("Invalid msg2 length")
    ct = msg2[:1120]
    bob_tag = msg2[1120:]
    ss = xwing.decapsulate(ct, sk)
    transcript = msg1 + ct
    if not hmac.compare_digest(bob_tag, h(b"bob", ss, transcript)[:TAG_LEN]):
        raise HandshakeFailed("Invalid tag from Bob")
    msg3 = nonce + h(b"alice", ss, transcript)[:TAG_LEN]
    session = make_session(ss, transcript, nonce, is_alice=True)
    return session, msg3


def bob_finish(state: object, msg3: bytes) -> Session:
    ss, transcript, commit = state
    if len(msg3) != NONCE_LEN + TAG_LEN:
        raise HandshakeFailed("Invalid msg3 length")
    nonce = msg3[:NONCE_LEN]
    alice_tag = msg3[NONCE_LEN:]
    if not hmac.compare_digest(h(nonce), commit):
        raise HandshakeFailed("Nonce does not match Alice's commitment")
    if not hmac.compare_digest(alice_tag, h(b"alice", ss, transcript)[:TAG_LEN]):
        raise HandshakeFailed("Invalid tag from Alice")
    session = make_session(ss, transcript, nonce, is_alice=False)
    return session


def run_alice(
    radio: Radio,
    session_id: int,
    max_packet: int,
    *,
    ack_timeout: float = 0.05,
    quiet_gap: float = 0.01,
    linger: float = 0.5,
    timeout: float = 10.0,
) -> Session:
    state, msg1 = alice_start()
    send_message(radio, msg1, session_id, 1, max_packet, ack_timeout=ack_timeout)
    msg2 = receive_message(radio, session_id, 2, quiet_gap=quiet_gap, linger=linger, timeout=timeout)
    session, msg3 = alice_finish(state, msg2)
    send_message(radio, msg3, session_id, 3, max_packet, ack_timeout=ack_timeout)
    return session


def run_bob(
    radio: Radio,
    session_id: int,
    max_packet: int,
    *,
    ack_timeout: float = 0.05,
    quiet_gap: float = 0.01,
    linger: float = 0.5,
    timeout: float = 10.0,
) -> Session:
    msg1 = receive_message(radio, session_id, 1, quiet_gap=quiet_gap, linger=linger, timeout=timeout)
    state, msg2 = bob_respond(msg1)
    send_message(radio, msg2, session_id, 2, max_packet, ack_timeout=ack_timeout)
    msg3 = receive_message(radio, session_id, 3, quiet_gap=quiet_gap, linger=linger, timeout=timeout)
    session = bob_finish(state, msg3)
    return session


class SecureChannel:
    def __init__(self, session: Session):
        self.sender = AESGCM(session.send_key)
        self.receiver = AESGCM(session.recv_key)
        self.send_counter = 0
        self.last_received = -1

    def seal(self, plaintext: bytes) -> bytes:
        counter = self.send_counter
        self.send_counter += 1
        encrypted = self.sender.encrypt(counter.to_bytes(12, "big"), plaintext, None)
        return counter.to_bytes(4, "big") + encrypted

    def open(self, packet: bytes) -> bytes:
        if len(packet) < 4 + 16:
            raise ValueError("packet too short")
        counter = int.from_bytes(packet[:4], "big")
        if counter <= self.last_received:
            raise ValueError("replayed or out-of-order message")
        try:
            plaintext = self.receiver.decrypt(counter.to_bytes(12, "big"), packet[4:], None)
        except InvalidTag:
            raise ValueError("message was tampered with") from None
        self.last_received = counter
        return plaintext
