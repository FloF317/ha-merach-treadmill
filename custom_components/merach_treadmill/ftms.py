"""Auswertung der FTMS Treadmill Data (0x2ACD)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TreadmillData:
    """Felder aus einer Treadmill-Data-Notification, None wenn nicht enthalten."""

    speed: float | None = None
    distance: int | None = None
    calories: int | None = None
    elapsed: int | None = None


# (Flag-Bit, Feldlänge in Byte) in Reihenfolge laut FTMS-Spezifikation
_FIELDS = (
    (0x0002, 2),  # Average Speed
    (0x0004, 3),  # Total Distance
    (0x0008, 4),  # Inclination + Ramp Angle
    (0x0010, 4),  # Elevation Gain
    (0x0020, 1),  # Instantaneous Pace
    (0x0040, 1),  # Average Pace
    (0x0080, 5),  # Expended Energy (total, per hour, per minute)
    (0x0100, 1),  # Heart Rate
    (0x0200, 1),  # Metabolic Equivalent
    (0x0400, 2),  # Elapsed Time
)


def parse_treadmill_data(data: bytes) -> TreadmillData:
    """Treadmill Data dekodieren. Unvollständige Felder am Ende werden ignoriert."""
    result = TreadmillData()
    if len(data) < 2:
        return result
    flags = data[0] | data[1] << 8
    pos = 2

    # Bit 0 = "More Data": wenn NICHT gesetzt, ist die Geschwindigkeit enthalten
    if not flags & 0x0001:
        if len(data) < pos + 2:
            return result
        result.speed = (data[pos] | data[pos + 1] << 8) / 100
        pos += 2

    for bit, size in _FIELDS:
        if not flags & bit:
            continue
        if len(data) < pos + size:
            break
        if bit == 0x0004:
            result.distance = data[pos] | data[pos + 1] << 8 | data[pos + 2] << 16
        elif bit == 0x0080:
            result.calories = data[pos] | data[pos + 1] << 8
        elif bit == 0x0400:
            result.elapsed = data[pos] | data[pos + 1] << 8
        pos += size
    return result
