from __future__ import annotations

from dataclasses import dataclass
from typing import Self

_CHANNEL_WIRE_BITS = (0,1,2,3)
"""Wire bit index of DI1..DI4 (verified on the bench: DI1 is the nibble MSB)."""


@dataclass(frozen=True)
class EL1xx4:
    """EL10x4 digital inputs, addressed by channel as on the terminal block.

    Two surfaces, on purpose:

    - channels `in1..in4` — application logic
    - `raw` — the nibble as it sits in the process image
    """

    in1: bool
    in2: bool
    in3: bool
    in4: bool

    @property
    def raw(self) -> int:
        """Nibble as it sits in the process image."""
        wire = 0
        for bit, on in zip(_CHANNEL_WIRE_BITS, self.to_list()):
            if on:
                wire |= 1 << bit
        return wire

    @classmethod
    def from_raw(cls, wire: int) -> Self:
        nibble = int(wire) & 0x0F
        return cls(*[((nibble >> bit) & 1) == 1 for bit in _CHANNEL_WIRE_BITS])

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        return cls.from_raw(data[0])

    def to_list(self) -> list[bool]:
        return [self.in1, self.in2, self.in3, self.in4]

    @classmethod
    def from_list(cls, values: list[bool]) -> Self:
        if len(values) != 4:
            raise ValueError(f"EL1xx4 needs 4 channel values, got {len(values)}")
        return cls(*[bool(v) for v in values])
