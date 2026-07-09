"""ISDU register encode/decode — transport via ``IsduPort`` Protocol."""

from __future__ import annotations

from typing import Any, Protocol

import bitstruct

from .schema import RegisterSpec, SensorDescriptor


class IsduPort(Protocol):
    def read_isdu(self, index: int, subindex: int = 0, *, size: int | None = None) -> bytes: ...

    def write_isdu(self, index: int, data: bytes, subindex: int = 0) -> None: ...


# Backward-compatible alias
IsduReader = IsduPort


def _bitstruct_format(fmt: str) -> str:
    if len(fmt) > 1 and fmt[0] == "<" and not fmt.endswith("<"):
        return fmt[1:] + "<"
    return fmt


def register_byte_size(reg: RegisterSpec) -> int:
    bits = bitstruct.calcsize(_bitstruct_format(reg.format))
    if bits % 8:
        raise ValueError(f"Register {reg.index:#x} format {reg.format!r} is not byte-aligned")
    return bits // 8


def _require_writable(reg: RegisterSpec, name: str) -> None:
    if reg.access not in ("w", "rw"):
        raise ValueError(f"Register {name!r} is {reg.access!r}, cannot write")


def read_register(
    port: IsduPort, descriptor: SensorDescriptor, name: str, *, size: int | None = None,
) -> bytes:
    reg = descriptor.registers[name]
    n = register_byte_size(reg) if size is None else size
    return port.read_isdu(reg.index, reg.subindex, size=n)


def read_text_register(
    port: IsduPort,
    descriptor: SensorDescriptor,
    name: str,
    *,
    max_bytes: int = 32,
) -> str:
    """Read IO-Link string register; cap length for EL6224 single ISDU frame."""
    reg = descriptor.registers[name]
    if not reg.format.startswith("t"):
        raise ValueError(f"{name!r} is not a text register")
    n = min(register_byte_size(reg), max_bytes)
    raw = read_register(port, descriptor, name, size=n)
    return decode_register_value(reg, raw.ljust(register_byte_size(reg), b"\x00"))


def decode_register_value(reg: RegisterSpec, raw: bytes) -> Any:
    if reg.format.startswith("t"):
        end = raw.find(b"\x00")
        payload = raw if end < 0 else raw[:end]
        return payload.decode("utf-8", errors="replace").strip()
    values = bitstruct.unpack(_bitstruct_format(reg.format), raw)
    if len(values) == 1:
        return values[0]
    return values


def encode_register_value(reg: RegisterSpec, value: Any) -> bytes:
    if reg.format.startswith("t"):
        size = register_byte_size(reg)
        if not isinstance(value, (bytes, bytearray)):
            value = str(value).encode("utf-8")
        else:
            value = bytes(value)
        if len(value) > size:
            raise ValueError(f"Text value too long for {reg.format!r} ({len(value)} > {size})")
        return value.ljust(size, b"\x00")
    packed = bitstruct.pack(_bitstruct_format(reg.format), value)
    expected = register_byte_size(reg)
    if len(packed) != expected:
        raise ValueError(f"Encoded {len(packed)} bytes, expected {expected}")
    return packed


def read_decoded_register(port: IsduPort, descriptor: SensorDescriptor, name: str) -> Any:
    reg = descriptor.registers[name]
    return decode_register_value(reg, read_register(port, descriptor, name))


def write_decoded_register(
    port: IsduPort, descriptor: SensorDescriptor, name: str, value: Any,
) -> None:
    reg = descriptor.registers[name]
    _require_writable(reg, name)
    port.write_isdu(reg.index, encode_register_value(reg, value), reg.subindex)


def apply_isdu_writes(
    port: IsduPort, descriptor: SensorDescriptor, writes: dict[str, Any],
) -> None:
    for name, value in writes.items():
        write_decoded_register(port, descriptor, name, value)


def read_identity(
    port: IsduPort, descriptor: SensorDescriptor, *, max_text_bytes: int = 32,
) -> tuple[str, str]:
    """Product name first (validation); vendor best-effort."""
    product = read_text_register(port, descriptor, "product_name", max_bytes=max_text_bytes)
    try:
        vendor = read_text_register(port, descriptor, "vendor_name", max_bytes=max_text_bytes)
    except Exception:
        vendor = "?"
    return vendor, product


def assert_product_matches(descriptor: SensorDescriptor, product_name: str) -> None:
    needles: list[str] = []
    for key in ("product_name_match", "id"):
        value = descriptor.meta.get(key)
        if value:
            needles.append(str(value).lower().replace("-", "").replace("_", ""))
    if not needles:
        return
    normalized = product_name.lower().replace("-", "").replace("_", "")
    if any(needle in normalized for needle in needles):
        return
    expected = descriptor.meta.get("product_name_match") or descriptor.meta.get("id")
    raise ValueError(
        f"Unexpected product {product_name!r} (expected {expected!r} in product name)"
    )
