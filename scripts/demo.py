import argparse
import secrets
import sys
import time

from lora_pqc.arq import TransferFailed, receive_message, receive_new_session, send_message
from lora_pqc.framing import split
from lora_pqc.handshake import (
    HandshakeFailed,
    SecureChannel,
    alice_finish,
    alice_start,
    bob_finish,
    bob_respond,
)
from lora_pqc.serial_radio import RadioError, open_serial_radio
from scripts.full_message import timings

FIRST_CHAT_ID = 4
LAST_MSG_ID = 255
QUIT = "/quit"
WAIT_SLICE = 30.0


class Link:
    def __init__(self, radio, sf):
        self.radio = radio
        self.max_packet, _, self.quiet_gap, self.ack_timeout, self.linger, self.timeout = timings(sf)
        self.session_id = None
        self.joined_at = None

    def send(self, msg_id, data, label):
        packets = len(split(data, self.session_id, msg_id, self.max_packet))
        start = time.monotonic()
        stats = send_message(self.radio, data, self.session_id, msg_id, self.max_packet, ack_timeout=self.ack_timeout)
        print(
            f"  -> sent {label}: {len(data)} bytes in {packets} packet{'s' if packets > 1 else ''}, "
            f"{time.monotonic() - start:.1f} s, {stats.resends} resends"
        )

    def receive(self, msg_id, label, wait_forever=False):
        timeout = WAIT_SLICE if wait_forever else self.timeout
        arq = dict(quiet_gap=self.quiet_gap, linger=self.linger, timeout=timeout)
        while True:
            try:
                if self.session_id is None:
                    self.session_id, data = receive_new_session(self.radio, msg_id, **arq)
                else:
                    data = receive_message(self.radio, self.session_id, msg_id, **arq)
                break
            except TransferFailed:
                if not wait_forever:
                    raise
        print(
            f"  <- got {label}: {len(data)} bytes, "
            f"RSSI {self.radio.last_rssi} dBm, SNR {self.radio.last_snr} dB"
        )
        return data


def alice_handshake(link):
    link.session_id = secrets.randbelow(0x10000)
    print(f"Starting session {link.session_id:04x}. Generating an X-Wing key pair...")
    state, msg1 = alice_start()
    link.send(1, msg1, "public key + nonce commitment")
    print("Waiting for Bob's reply...")
    msg2 = link.receive(2, "ciphertext + Bob's tag")
    session, msg3 = alice_finish(state, msg2)
    print("  Bob's tag checks out.")
    link.send(3, msg3, "nonce + Alice's tag")
    return session


def bob_handshake(link):
    print("Waiting for Alice to start a handshake...")
    msg1 = link.receive(1, "public key + nonce commitment", wait_forever=True)
    link.joined_at = time.monotonic()
    print(f"Joined session {link.session_id:04x}. Encapsulating a shared secret...")
    state, msg2 = bob_respond(msg1)
    link.send(2, msg2, "ciphertext + Bob's tag")
    msg3 = link.receive(3, "nonce + Alice's tag")
    session = bob_finish(state, msg3)
    print("  Alice's nonce matches her commitment, and her tag checks out.")
    return session


def ask(prompt):
    return input(prompt).lstrip("﻿").strip()


def confirm_code(session):
    code = f"{session.code[:3]} {session.code[3:]}"
    print()
    print("  +--------------------------------+")
    print(f"  |   Verification code: {code}   |")
    print("  +--------------------------------+")
    print("  Read it aloud. If someone were intercepting, the two codes would differ.")
    print()
    return ask("Does the other device show the same code? [y/n] ").lower() == "y"


def next_id(msg_id):
    return msg_id + 1 if msg_id < LAST_MSG_ID else FIRST_CHAT_ID


def chat(link, session, my_turn):
    channel = SecureChannel(session)
    msg_id = FIRST_CHAT_ID
    print(f"Encrypted chat open. Type {QUIT} to leave.")
    while True:
        if my_turn:
            text = ""
            while not text:
                text = ask("you> ")
            sealed = channel.seal(text.encode())
            print(f"  on the air: {sealed.hex()[:48]}...")
            link.send(msg_id, sealed, "encrypted message")
            if text == QUIT:
                return
        else:
            print("(waiting for the other side...)")
            sealed = link.receive(msg_id, "encrypted message", wait_forever=True)
            print(f"  on the air: {sealed.hex()[:48]}...")
            try:
                text = channel.open(sealed).decode()
            except ValueError as e:
                print(f"  REJECTED: {e}")
            else:
                if text == QUIT:
                    print("The other side left the chat.")
                    return
                print(f"them> {text}")
        my_turn = not my_turn
        msg_id = next_id(msg_id)


def main():
    parser = argparse.ArgumentParser(description="Post-quantum encrypted chat over LoRa")
    parser.add_argument("role", choices=["alice", "bob"])
    parser.add_argument("port", help="serial port of this device's board")
    parser.add_argument("--sf", type=int, default=7, help="spreading factor")
    args = parser.parse_args()

    radio = open_serial_radio(args.port, sf=args.sf)
    link = Link(radio, args.sf)
    print(f"{args.role.capitalize()} on {args.port}, SF{args.sf}.")
    try:
        start = time.monotonic()
        session = alice_handshake(link) if args.role == "alice" else bob_handshake(link)
        print(f"Handshake complete in {time.monotonic() - (link.joined_at or start):.1f} s.")
        if not confirm_code(session):
            print("Codes don't match")
            return 1
        chat(link, session, my_turn=args.role == "alice")
        return 0
    except (HandshakeFailed, TransferFailed, RadioError) as e:
        print(f"Failed: {type(e).__name__}: {e}")
        return 1
    except KeyboardInterrupt:
        print()
        return 1
    finally:
        radio.close()


if __name__ == "__main__":
    sys.exit(main())
