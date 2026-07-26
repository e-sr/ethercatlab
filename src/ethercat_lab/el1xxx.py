from __future__ import annotations

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True)
class EL1xx4:
    """EL10x4 digital inputs — Beckhoff PDO bit0 = channel 1."""

    in1: bool
    in2: bool
    in3: bool
    in4: bool

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        raw = data[0] & 0x0F
        return cls(
            bool(raw & 0x01),
            bool(raw & 0x02),
            bool(raw & 0x04),
            bool(raw & 0x08),
        )

    def to_list(self) -> list[bool]:
        return [self.in1, self.in2, self.in3, self.in4]

    def to_hex(self) -> int:
        return sum(v << i for i, v in enumerate(self.to_list()))
