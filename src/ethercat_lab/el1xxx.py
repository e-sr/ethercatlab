import bitstruct
from dataclasses import dataclass
from typing import Self
from __future__ import annotations

@dataclass(frozen=True,)
class EL1xx4:
    in1: bool
    in2: bool
    in3: bool
    in4: bool
    _codec= bitstruct.compile('p4b1b1b1b1')

    @classmethod
    def from_bytes(cls,data:bytes) -> Self:
        in1, in2, in3, in4= cls._codec.unpack(data)
        return cls(*[bool(v) for v in [in1, in2, in3, in4]])

    def to_list(self) -> list[bool]:
        return [self.in1, self.in2, self.in3, self.in4]

    def to_hex(self) -> int:
        return sum([v<<i for i, v in enumerate([self.in1, self.in2, self.in3, self.in4])])
