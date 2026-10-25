import argparse
import secrets
import sys
import textwrap
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
from lora_pqc.serial_radio import TEXT_LARGE, TEXT_MEDIUM, TEXT_SMALL, RadioError, open_serial_radio
from scripts.full_message import timings

FIRST_CHAT_ID = 4
LAST_MSG_ID = 255
QUIT = "/quit"
WAIT_SLICE = 30.0
OLED_COLUMNS = 21
OLED_MESSAGE_LINES = 4


class Link:
    def __init__(self, radio, sf):
        self.radio = radio
        self.max_packet, _, self.quiet_gap, self.ack_timeout, self.linger, self.timeout = timings(sf)
        self.session_id = None
        self.joined_at = None

    def show(self, text, size=TEXT_SMALL):
        self.radio.show_text(text, size)

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
    link.show("Alice\nHandshake 1/3\nsending public key...")
    link.send(1, msg1, "public key + nonce commitment")
    print("Waiting for Bob's reply...")
    link.show("Alice\nHandshake 2/3\nwaiting for Bob...")
    msg2 = link.receive(2, "ciphertext + Bob's tag")
    session, msg3 = alice_finish(state, msg2)
    print("  Bob's tag checks out.")
    link.show(f"Alice\nHandshake 3/3\nBob verified\nRSSI {link.radio.last_rssi} dBm")
    link.send(3, msg3, "nonce + Alice's tag")
    return session


def bob_handshake(link):
    print("Waiting for Alice to start a handshake...")
    link.show("Bob\nwaiting for Alice...")
    msg1 = link.receive(1, "public key + nonce commitment", wait_forever=True)
    link.joined_at = time.monotonic()
    print(f"Joined session {link.session_id:04x}. Encapsulating a shared secret...")
    link.show(f"Bob\nHandshake 1/3\ngot Alice's key\nRSSI {link.radio.last_rssi} dBm")
    state, msg2 = bob_respond(msg1)
    link.send(2, msg2, "ciphertext + Bob's tag")
    link.show("Bob\nHandshake 2/3\nwaiting for Alice...")
    msg3 = link.receive(3, "nonce + Alice's tag")
    session = bob_finish(state, msg3)
    print("  Alice's nonce matches her commitment, and her tag checks out.")
    link.show("Bob\nHandshake 3/3\nAlice verified")
    return session


def ask(prompt):
    return input(prompt).lstrip("﻿").strip()


def confirm_code(link, session):
    code = f"{session.code[:3]} {session.code[3:]}"
    link.show(f"Code\n{code}", TEXT_LARGE)
    print()
    print("  +--------------------------------+")
    print(f"  |   Verification code: {code}   |")
    print("  +--------------------------------+")
    print("  Read it aloud. If someone were intercepting, the two codes would differ.")
    print()
    return ask("Does the other device show the same code? [y/n] ").lower() == "y"


def next_id(msg_id):
    return msg_id + 1 if msg_id < LAST_MSG_ID else FIRST_CHAT_ID


def oled_message(sender, text):
    lines = textwrap.wrap(text, OLED_COLUMNS)[:OLED_MESSAGE_LINES] or [""]
    return f"{sender}:\n" + "\n".join(lines)


def chat(link, session, my_turn, peer):
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
            if text != QUIT:
                link.show(oled_message("You", text))
            link.send(msg_id, sealed, "encrypted message")
            if text == QUIT:
                link.show("Chat ended", TEXT_MEDIUM)
                return
        else:
            print("(waiting for the other side...)")
            sealed = link.receive(msg_id, "encrypted message", wait_forever=True)
            print(f"  on the air: {sealed.hex()[:48]}...")
            try:
                text = channel.open(sealed).decode()
            except ValueError as e:
                print(f"  REJECTED: {e}")
                link.show(f"REJECTED\n{textwrap.fill(str(e), OLED_COLUMNS)}")
            else:
                if text == QUIT:
                    print("The other side left the chat.")
                    link.show(f"Chat ended\nby {peer}", TEXT_MEDIUM)
                    return
                print(f"them> {text}")
                link.show(oled_message(peer, text))
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
    name = args.role.capitalize()
    peer = "Bob" if args.role == "alice" else "Alice"
    print(f"{name} on {args.port}, SF{args.sf}.")
    link.show(f"{name}\nSF{args.sf} ready", TEXT_MEDIUM)
    try:
        start = time.monotonic()
        session = alice_handshake(link) if args.role == "alice" else bob_handshake(link)
        print(f"Handshake complete in {time.monotonic() - (link.joined_at or start):.1f} s.")
        if not confirm_code(link, session):
            print("Codes don't match")
            link.show("CODES DIFFER\nsession closed", TEXT_MEDIUM)
            return 1
        link.show(f"Codes match\nchat with {peer}", TEXT_MEDIUM)
        chat(link, session, my_turn=args.role == "alice", peer=peer)
        return 0
    except (HandshakeFailed, TransferFailed, RadioError) as e:
        print(f"Failed: {type(e).__name__}: {e}")
        link.show(f"FAILED\n{type(e).__name__}", TEXT_MEDIUM)
        return 1
    except KeyboardInterrupt:
        print()
        return 1
    finally:
        radio.close()


if __name__ == "__main__":
    sys.exit(main())
