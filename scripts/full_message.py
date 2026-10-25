import os
import sys
import threading
import time

from lora_pqc.airtime import max_payload, time_on_air
from lora_pqc.arq import TransferFailed, receive_message, send_message
from lora_pqc.framing import split
from lora_pqc.serial_radio import open_serial_radio

SESSION_ID = 0xBEEF
MESSAGE_LEN = 1216


def timings(sf):
    max_packet = max_payload(sf)
    packets = len(split(bytes(MESSAGE_LEN), SESSION_ID, 1, max_packet))
    big = time_on_air(max_packet, sf)
    ack = time_on_air(5 + (packets + 7) // 8, sf)
    quiet_gap = 1.5 * big
    ack_timeout = quiet_gap + 2 * ack + 0.3
    linger = ack_timeout + big + 0.5
    timeout = 3 * packets * big + 10
    return max_packet, packets, quiet_gap, ack_timeout, linger, timeout


def run_once(alice, bob, msg_id, sf):
    max_packet, packets, quiet_gap, ack_timeout, linger, timeout = timings(sf)
    message = os.urandom(MESSAGE_LEN)
    result = {}

    def bob_side():
        try:
            result["msg"] = receive_message(
                bob, SESSION_ID, msg_id, quiet_gap=quiet_gap, linger=linger, timeout=timeout
            )
        except TransferFailed as e:
            result["error"] = e

    rx = threading.Thread(target=bob_side)
    rx.start()
    start = time.monotonic()
    try:
        stats = send_message(alice, message, SESSION_ID, msg_id, max_packet, ack_timeout=ack_timeout)
    except TransferFailed as e:
        rx.join()
        return f"FAILED (sender): {e}"
    sent_in = time.monotonic() - start
    rx.join()
    if "error" in result:
        return f"FAILED (receiver): {result['error']}"
    ok = result.get("msg") == message
    return (
        f"{'OK' if ok else 'MISMATCH'}  {sent_in:.2f} s  "
        f"rounds={stats.rounds} sent={stats.packets_sent} resends={stats.resends}"
    )


def main():
    sf = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    max_packet, packets, quiet_gap, ack_timeout, linger, timeout = timings(sf)
    print(
        f"SF{sf}: {packets} packets of up to {max_packet} bytes, "
        f"quiet_gap={quiet_gap:.2f} ack_timeout={ack_timeout:.2f} linger={linger:.2f} timeout={timeout:.0f}"
    )
    alice = open_serial_radio("COM3", sf=sf)
    bob = open_serial_radio("COM4", sf=sf)
    try:
        for run in range(1, runs + 1):
            print(f"run {run}: {run_once(alice, bob, run, sf)}")
        print(f"airtime: alice {alice.stats.airtime_s:.2f} s, bob {bob.stats.airtime_s:.2f} s")
        print(f"last RSSI at bob {bob.last_rssi} dBm, SNR {bob.last_snr} dB; rx errors {alice.rx_errors + bob.rx_errors}")
    finally:
        alice.close()
        bob.close()


if __name__ == "__main__":
    main()
