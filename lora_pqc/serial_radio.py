from __future__ import annotations

import queue
import threading
import time

from .airtime import time_on_air
from .radio import MAX_PACKET, RadioStats

FRAME_START = 0xAA
CMD_TRANSMIT = ord("T")
CMD_PING = ord("P")
CMD_SET_SF = ord("S")
EVT_READY = ord("B")
EVT_RECEIVED = ord("R")
EVT_SENT = ord("D")
EVT_RX_ERROR = ord("E")
KNOWN_TYPES = {CMD_TRANSMIT, CMD_PING, CMD_SET_SF, EVT_READY, EVT_RECEIVED, EVT_SENT, EVT_RX_ERROR}
MAX_FRAME_DATA = MAX_PACKET + 4
SEND_TIMEOUT = 4.0


class RadioError(Exception):
    pass


def encode_frame(frame_type: int, data: bytes = b"") -> bytes: 
    hi = len(data) >> 8
    lo = len(data) & 0xFF
    check = frame_type ^ hi ^ lo
    for b in data:
        check ^= b
    return bytes([FRAME_START, frame_type, hi, lo]) + bytes(data) + bytes([check])


class FrameParser:
    def __init__(self):
        self.buff = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self.buff += data
        frames = []
        while len(self.buff) >= 4:
            start = self.buff.find(FRAME_START)
            if start == -1:
                self.buff.clear()
                break
            del self.buff[:start]
            if len(self.buff) < 4:
                break
            frame_type = self.buff[1]
            length = (self.buff[2] << 8) | self.buff[3]
            if frame_type not in KNOWN_TYPES:
                self.buff.pop(0)
                continue
            if length > MAX_FRAME_DATA:
                self.buff.pop(0)
                continue
            if len(self.buff) < 5 + length:
                return frames
            data_temp = bytes(self.buff[4:4 + length])
            frame_temp = encode_frame(frame_type, data_temp)
            if self.buff[:5 + length] == frame_temp:
                frames.append((frame_type, data_temp))
                del self.buff[:5 + length]
            else:
                self.buff.pop(0)
        return frames


class SerialRadio:
    def __init__(self, ser, sf: int = 7):
        self.ser = ser
        self.sf = sf
        self.frame_parser = FrameParser()
        self.inbox = queue.Queue()
        self.sent = queue.Queue()
        self.ready = queue.Queue()
        self.stats = RadioStats()
        self.last_rssi = None
        self.last_snr = None
        self.rx_errors = 0
        self._stop = False
        self._thread = threading.Thread(target=self._reader_thread, daemon=True)
        self._thread.start()

    def _reader_thread(self) -> None:
        while not self._stop:
            chunk = self.ser.read(512)
            for frame_type, data in self.frame_parser.feed(chunk):
                if frame_type == EVT_RECEIVED and len(data) >= 4:
                    self.last_rssi = int.from_bytes(data[0:2], "big", signed=True) / 10
                    self.last_snr = int.from_bytes(data[2:4], "big", signed=True) / 10
                    self.inbox.put(data[4:])
                elif frame_type == EVT_SENT and len(data) == 2:
                    self.sent.put(int.from_bytes(data, "big", signed=True))
                elif frame_type == EVT_READY and len(data) == 3:
                    self.ready.put((int.from_bytes(data[0:2], "big", signed=True), data[2]))
                elif frame_type == EVT_RX_ERROR:
                    self.rx_errors += 1

    def _drain(self, q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def wait_ready(self, timeout: float = 3.0) -> int:
        self._drain(self.ready)
        self.ser.write(encode_frame(CMD_PING))
        try:
            status, sf = self.ready.get(timeout=timeout)
        except queue.Empty:
            raise RadioError("board did not answer the ping") from None
        self.sf = sf
        return status

    def set_sf(self, sf: int, timeout: float = 3.0) -> None:
        self._drain(self.ready)
        self.ser.write(encode_frame(CMD_SET_SF, bytes([sf])))
        try:
            status, new_sf = self.ready.get(timeout=timeout)
        except queue.Empty:
            raise RadioError("board did not answer set_sf") from None
        if status != 0:
            raise RadioError(f"board rejected SF{sf} (status {status})")
        self.sf = new_sf

    def send(self, packet: bytes) -> None:
        if not 0 < len(packet) <= MAX_PACKET:
            raise ValueError(f"packet is {len(packet)} bytes; must be 1 to {MAX_PACKET}")
        self._drain(self.sent)
        self.ser.write(encode_frame(CMD_TRANSMIT, packet))
        try:
            status = self.sent.get(timeout=SEND_TIMEOUT)
        except queue.Empty:
            raise RadioError("board never reported the transmit finishing") from None
        if status != 0:
            raise RadioError(f"transmit failed (status {status})")
        self.stats.sent += 1
        self.stats.airtime_s += time_on_air(len(packet), self.sf)

    def recv(self, timeout: float) -> bytes | None:
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop = True
        self._thread.join(timeout=1)
        self.ser.close()


def open_serial_radio(port: str, baud: int = 115200, sf: int = 7) -> SerialRadio:
    import serial

    radio = SerialRadio(serial.Serial(port, baud, timeout=0.05))
    try:
        status = radio.wait_ready()
        if status != 0:
            raise RadioError(f"radio on {port} failed to start (status {status})")
        if sf != radio.sf:
            radio.set_sf(sf)
    except Exception:
        radio.close()
        raise
    return radio
