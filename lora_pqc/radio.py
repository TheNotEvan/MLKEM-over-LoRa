
from __future__ import annotations

import queue
import random
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .airtime import US_DWELL_LIMIT_S, max_payload, time_on_air

MAX_PACKET = 255  # LoRa's hard limit on one packet


class Radio(Protocol):
    def send(self, packet: bytes) -> None: ...
    def recv(self, timeout: float) -> bytes | None: ...


@dataclass
class RadioStats:
    sent: int = 0        
    dropped: int = 0     
    corrupted: int = 0 
    airtime_s: float = 0.0


class SimulatedRadio:

    def __init__(self, link: SimulatedLink, inbox: queue.Queue, peer_inbox: queue.Queue):
        self._link = link
        self._inbox = inbox
        self._peer_inbox = peer_inbox
        self.stats = RadioStats()

    def send(self, packet: bytes) -> None:
        self._link._transmit(self, packet)

    def recv(self, timeout: float) -> bytes | None:
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None


class SimulatedLink:


    def __init__(
        self,
        sf: int = 7,
        bw_hz: int = 125_000,
        loss: float = 0.0,
        corrupt: float = 0.0,
        dwell_limit_s: float | None = US_DWELL_LIMIT_S,
        time_scale: float = 0.0,
        seed: int | None = None,
    ):
        self.sf = sf
        self.bw_hz = bw_hz
        self.loss = loss
        self.corrupt = corrupt
        self.dwell_limit_s = dwell_limit_s
        self.time_scale = time_scale
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        a_inbox, b_inbox = queue.Queue(), queue.Queue()
        self.a = SimulatedRadio(self, a_inbox, b_inbox)
        self.b = SimulatedRadio(self, b_inbox, a_inbox)

    @property
    def max_packet(self) -> int:
        if self.dwell_limit_s is None:
            return MAX_PACKET
        return max_payload(self.sf, self.dwell_limit_s, bw_hz=self.bw_hz) or 0

    def _transmit(self, sender: SimulatedRadio, packet: bytes) -> None:
        packet = bytes(packet)
        if len(packet) > MAX_PACKET:
            raise ValueError(f"packet is {len(packet)} bytes; LoRa allows at most {MAX_PACKET}")
        toa = time_on_air(len(packet), self.sf, self.bw_hz)
        if self.dwell_limit_s is not None and toa > self.dwell_limit_s:
            raise ValueError(
                f"a {len(packet)}-byte packet takes {toa * 1000:.0f} ms at SF{self.sf}; "
                f"the limit is {self.dwell_limit_s * 1000:.0f} ms (max {self.max_packet} bytes)"
            )

        with self._lock:
            sender.stats.sent += 1
            sender.stats.airtime_s += toa
            lost = self._rng.random() < self.loss
            flip_at = None
            if not lost and packet and self._rng.random() < self.corrupt:
                flip_at = (self._rng.randrange(len(packet)), 1 << self._rng.randrange(8))

        if self.time_scale:
            time.sleep(toa * self.time_scale)

        if lost:
            sender.stats.dropped += 1
            return
        if flip_at is not None:
            pos, bit = flip_at
            damaged = bytearray(packet)
            damaged[pos] ^= bit
            packet = bytes(damaged)
            sender.stats.corrupted += 1
        sender._peer_inbox.put(packet)
