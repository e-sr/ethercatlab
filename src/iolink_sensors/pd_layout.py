"""Sensor process-data wire layout (bitstruct pack/unpack)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal
from collections.abc import Mapping, Sequence

import bitstruct
from bitstruct import CompiledFormat, CompiledFormatDict

from .schema import PdFrameFieldSpec, PdFrameSpec


@dataclass(slots=True)
class PdWireLayout:
    """One direction of IO-Link process data (sensor wire semantics)."""

    fields: list[PdFrameFieldSpec]
    sio: bool = False
    _codec: CompiledFormat | CompiledFormatDict = field(init=False, repr=False)
    _codec_reverse: CompiledFormat | CompiledFormatDict = field(init=False, repr=False)
    def __post_init__(self) -> None:
        if not self.fields:
            raise RuntimeError("empty PD wire layout")
        self._codec = bitstruct.compile(self.format)

    @property
    def format(self) -> str:
        return "".join(field.typestr for field in self.fields)

    @property
    def bit_len(self) -> int:
        if not self.fields:
            return 0
        return sum(field.length for field in self.fields)

    @property
    def byte_len(self) -> int:
        return (self.bit_len + 7) // 8


    def decode(self, raw: bytes) -> list[Any]:
        return list(self._codec.unpack(raw[::-1]))


    def decode_named(self, raw: bytes) -> dict[str, Any]:
        return {field.name: value for field, value in zip(self.fields, self.decode(raw))}
  
    def encode(self, values: list[Any]) -> bytes:
        return bytes(self._codec.pack(*values))