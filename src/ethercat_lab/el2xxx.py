from __future__ import annotations

from dataclasses import dataclass
from typing import Self

_CHANNEL_WIRE_BITS = (3, 2, 1, 0)
"""Wire bit index of DO1..DO4 (verified on the bench: DO1 is the nibble MSB)."""


@dataclass(frozen=True, slots=True)
class EL2xx4:
    """EL20x4 digital outputs, addressed by channel as on the terminal block.

    Two surfaces, on purpose:

    - channels `o1..o4` — application logic, True = output requested ON
    - `raw` — the nibble as it sits in the process image

    The wire nibble is active-low, so a channel is ON when its bit is 0:
    all outputs off is `raw == 0x0F`.
    """

    o1: bool
    o2: bool
    o3: bool
    o4: bool

    @property
    def raw(self) -> int:
        """Nibble as it sits in the process image (active-low)."""
        wire = 0
        for bit, on in zip(_CHANNEL_WIRE_BITS, self.to_list()):
            if not on:
                wire |= 1 << bit
        return wire

    @classmethod
    def from_raw(cls, wire: int) -> Self:
        nibble = int(wire) & 0x0F
        return cls(*[((nibble >> bit) & 1) == 0 for bit in _CHANNEL_WIRE_BITS])

    def pack(self) -> bytes:
        return bytes([self.raw])

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        return cls.from_raw(data[0])

    def to_list(self) -> list[bool]:
        return [self.o1, self.o2, self.o3, self.o4]

    @classmethod
    def from_list(cls, values: list[bool]) -> Self:
        if len(values) != 4:
            raise ValueError(f"EL2xx4 needs 4 channel values, got {len(values)}")
        return cls(*[bool(v) for v in values])

    @classmethod
    def from_channels(cls, *channels: int) -> Self:
        """Build from 1-based channel numbers, e.g. `from_channels(1, 4)`."""
        unknown = [ch for ch in channels if ch not in (1, 2, 3, 4)]
        if unknown:
            raise ValueError(f"EL2xx4 channels are 1..4, got {unknown}")
        return cls(*[ch in channels for ch in (1, 2, 3, 4)])

    @classmethod
    def all_off(cls) -> Self:
        return cls(False, False, False, False)

    @classmethod
    def all_on(cls) -> Self:
        return cls(True, True, True, True)
