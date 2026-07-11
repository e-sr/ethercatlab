import bitstruct
from dataclasses import dataclass
from __future__ import annotations
from typing import Self
@dataclass(frozen=True, slots=True)
class EL2xx4:
    o1: bool
    o2: bool
    o3: bool
    o4: bool
    _codec= bitstruct.compile('p4b1b1b1b1')

    def pack(self) -> bytes:
        return self._codec.pack(*[bool(v) for v in [self.o1, self.o2, self.o3, self.o4]])

    @classmethod
    def from_bytes(cls,data:bytes) -> Self: 
        out1, out2, out3, out4= cls._codec.unpack(data)
        return cls(*[bool(v) for v in [out1, out2, out3, out4]])
    @classmethod
    def from_hex(cls,value:int) -> Self:
        return cls(*[bool((value>>i)&0x01) for i in range(4)])
    
    def to_hex(self) -> int:
        return sum([v<<i for i, v in enumerate([self.o1, self.o2, self.o3, self.o4])])

    def to_list(self) -> list[bool]:
        return [self.o1, self.o2, self.o3, self.o4]
    @classmethod
    def from_list(cls,values:list[bool]) -> EL2xx4:
        return cls(*values)
