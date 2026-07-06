"""CoE PDO mapping and assignment (ETG.1000)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import bitstruct

from .master import CoeTransfer


@dataclass(slots=True)
class PdoMapEntry:
    index: int
    subindex: int
    length: int
    typeprefix: str = "r"
    name: str | None = ""
    _codec = bitstruct.compile("u16u8u8")

    @property
    def typestr(self) -> str:
        return self.typeprefix + str(self.length)

    def __post_init__(self) -> None:
        if self.name == "" and self.typeprefix != "p":
            self.name = f"0x{self.index:04X}:{self.subindex:02X}"

    @property
    def map_value(self) -> bytes:
        packed: bytes = self._codec.pack(self.index, self.subindex, self.length)  # type: ignore[call-arg]
        return packed[::-1]

    @classmethod
    def from_bytes(cls, value: bytes) -> PdoMapEntry:
        index, sub_index, length = cls._codec.unpack(value[::-1])
        if not isinstance(index, int) or not isinstance(sub_index, int) or not isinstance(length, int):
            raise ValueError("Index, sub_index and length must be integers")
        typeprefix = "p" if index == 0 and sub_index == 0 else "r"
        return cls(index, sub_index, length, typeprefix)

    def __repr__(self) -> str:
        return (
            f"PdoMapEntry(index:sub=0x{self.index:04X}:0x{self.subindex}, "
            f"name={self.name}, typestr={self.typestr})"
        )


@dataclass(slots=True)
class PdoMapping:
    index: int
    entries: list[PdoMapEntry]
    name: str = ""
    writable: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            object.__setattr__(self, "name", f"0x{self.index:04X}")

    def to_coe_writes(self) -> list[CoeTransfer]:
        writes = [CoeTransfer(self.index, 0, raw=bytes([0]))]
        for slot, entry in enumerate(self.entries, 1):
            writes.append(CoeTransfer(self.index, slot, raw=entry.map_value))
        writes.append(CoeTransfer(self.index, 0, raw=bytes([len(self.entries)])))
        return writes

    @classmethod
    def from_coe_reads(cls, coe_reads: list[CoeTransfer], name: str | None = None) -> PdoMapping:
        for coe_read in coe_reads:
            if coe_read.index != coe_reads[0].index:
                raise ValueError("All coe_reads must have the same index")
            if coe_read.raw is None:
                raise ValueError("All coe_reads must have a raw value")
        entries = []
        for coe_read in coe_reads:
            assert coe_read.raw is not None
            entries.append(PdoMapEntry.from_bytes(coe_read.raw))
        map_name = name if name is not None else f"0x{coe_reads[0].index:04X}"
        return cls(index=coe_reads[0].index, entries=entries, name=map_name, writable=False)

    def __repr__(self) -> str:
        result = [f"PdoMapping: name={self.name} index=0x{self.index:04X} writable={self.writable}"]
        for entry in self.entries:
            result.append(f"    {entry}")
        return "\n".join(result)


def _pdoformat_bigendian(mappings: tuple[PdoMapping, ...]) -> str:
    tipi: list[str] = []
    for mapping in mappings:
        for entry in mapping.entries:
            tipi.append(entry.typestr)
    tipi.reverse()
    return ">" + "".join(tipi)


def _build_field_slices(
    mappings: tuple[PdoMapping, ...],
    names: tuple[str, ...],
) -> dict[str, tuple[list[str], slice]]:
    info: dict[str, tuple[list[str], slice]] = {}
    start = 0
    for map_name, mapping in zip(names, mappings):
        field_names = [entry.name for entry in mapping.entries if entry.name is not None]
        end = start + len(field_names)
        info[map_name] = (field_names, slice(start, end))
        start = end
    return info


@dataclass(slots=True)
class PdoAssignment:
    """Ordered PDO maps + logical names (process-image order)."""

    mappings: tuple[PdoMapping, ...]
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.mappings) != len(self.names):
            raise ValueError("mappings and names must have the same length")

    @property
    def assign_coe_index(self) -> int:
        raise NotImplementedError

    def pdo_indices(self) -> list[int]:
        return [mapping.index for mapping in self.mappings]

    def _assignment_coe_writes(self) -> list[CoeTransfer]:
        idx = self.assign_coe_index
        writes = [CoeTransfer(idx, 0, raw=bytes([0]))]
        for slot, mapping in enumerate(self.mappings, 1):
            writes.append(CoeTransfer(idx, slot, raw=mapping.index.to_bytes(2, "little")))
        writes.append(CoeTransfer(idx, 0, raw=bytes([len(self.mappings)])))
        return writes

    def to_coe_writes(self) -> list[CoeTransfer]:
        writes: list[CoeTransfer] = []
        for mapping in self.mappings:
            if mapping.writable:
                writes.extend(mapping.to_coe_writes())
        writes.extend(self._assignment_coe_writes())
        return writes

    @classmethod
    def from_mappings(cls, items: list[tuple[str, PdoMapping]]) -> PdoAssignment:
        if not items:
            raise ValueError("at least one PDO mapping is required")
        names = tuple(name for name, _ in items)
        mappings = tuple(mapping for _, mapping in items)
        return cls(mappings=mappings, names=names)


@dataclass(slots=True)
class TxPdoAssignment(PdoAssignment):
    _bitstruct: Any = field(init=False, repr=False, default=None)
    _field_slices: dict[str, tuple[list[str], slice]] = field(
        init=False, repr=False, default_factory=dict
    )

    @property
    def assign_coe_index(self) -> int:
        return 0x1C13

    def _ensure_codec(self) -> None:
        if self._bitstruct is not None:
            return
        if not self.mappings:
            raise RuntimeError("empty tx PDO assignment")
        self._bitstruct = bitstruct.compile(_pdoformat_bigendian(self.mappings))
        self._field_slices = _build_field_slices(self.mappings, self.names)

    @property
    def pdoformat_bigendian(self) -> str:
        self._ensure_codec()
        return _pdoformat_bigendian(self.mappings)

    def byte_len(self) -> int:
        self._ensure_codec()
        return self._bitstruct.calcsize() // 8

    def decode(self, pdo_data: bytes) -> tuple[Any, ...]:
        self._ensure_codec()
        return self._bitstruct.unpack(pdo_data[::-1])[::-1]

    def decode_named(self, pdo_data: bytes) -> dict[str, dict[str, Any]]:
        decoded = self.decode(pdo_data)
        result: dict[str, dict[str, Any]] = {}
        for map_name, (field_names, slice_map) in self._field_slices.items():
            result[map_name] = dict(zip(field_names, decoded[slice_map]))
        return result

    @classmethod
    def from_mappings(cls, items: list[tuple[str, PdoMapping]]) -> TxPdoAssignment:
        assign = PdoAssignment.from_mappings(items)
        return cls(mappings=assign.mappings, names=assign.names)


@dataclass(slots=True)
class RxPdoAssignment(PdoAssignment):
    @property
    def assign_coe_index(self) -> int:
        return 0x1C12

    @classmethod
    def from_mappings(cls, items: list[tuple[str, PdoMapping]]) -> RxPdoAssignment:
        assign = PdoAssignment.from_mappings(items)
        return cls(mappings=assign.mappings, names=assign.names)
