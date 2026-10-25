
from __future__ import annotations

import math

US_DWELL_LIMIT_S = 0.4  


def symbol_time(sf: int, bw_hz: int = 125_000) -> float:
    return (2 ** sf) / bw_hz


def time_on_air(
    payload_len: int,
    sf: int,
    bw_hz: int = 125_000,
    cr: int = 1,
    preamble: int = 8,
    explicit_header: bool = True,
    crc: bool = True,
    low_data_rate_opt: bool | None = None,
) -> float:
   
    if not 7 <= sf <= 12:
        raise ValueError(f"sf must be 7-12, got {sf}")
    if not 0 <= payload_len <= 255:
        raise ValueError(f"payload_len must be 0-255, got {payload_len}")

    t_sym = symbol_time(sf, bw_hz)
    if low_data_rate_opt is None:
        low_data_rate_opt = t_sym > 0.016
    de = 1 if low_data_rate_opt else 0
    ih = 0 if explicit_header else 1

    numerator = 8 * payload_len - 4 * sf + 28 + 16 * int(crc) - 20 * ih
    payload_symbols = 8 + max(math.ceil(numerator / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preamble + 4.25) * t_sym + payload_symbols * t_sym


def max_payload(sf: int, limit_s: float = US_DWELL_LIMIT_S, **settings) -> int | None:
    
    fits = [n for n in range(256) if time_on_air(n, sf, **settings) <= limit_s]
    return max(fits) if fits else None


if __name__ == "__main__":
    print("SF   max bytes under 400 ms   airtime of a 255-byte packet")
    for sf in range(7, 13):
        mp = max_payload(sf)
        print(f"{sf:>2}   {str(mp):>18}   {time_on_air(255, sf) * 1000:>10.0f} ms")
