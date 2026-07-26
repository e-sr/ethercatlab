from __future__ import annotations

from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class EL2xx4:
    """EL20x4 digital outputs — Beckhoff PDO bit0 = channel 1."""

    o1: bool
    o2: bool
    o3: bool
    o4: bool

    def pack(self) -> bytes:
        return bytes([self.to_hex()])

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        return cls.from_hex(data[0])

    @classmethod
    def from_hex(cls, value: int) -> Self:
        raw = int(value) & 0x0F
        return cls(
            bool(raw & 0x01),
            bool(raw & 0x02),
            bool(raw & 0x04),
            bool(raw & 0x08),
        )

    def to_hex(self) -> int:
        return sum(v << i for i, v in enumerate(self.to_list()))

    def to_list(self) -> list[bool]:
        return [self.o1, self.o2, self.o3, self.o4]

    @classmethod
    def from_list(cls, values: list[bool]) -> EL2xx4:
        return cls(*values)
