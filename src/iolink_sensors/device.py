from __future__ import annotations

from enum import IntEnum
from typing import Any

from .isdu import (
    IsduPort,
    apply_isdu_writes,
    assert_product_matches,
    read_decoded_register,
    read_register,
    write_register,
    read_identity,
    write_encoded_register,
)
from .pd_layout import PdWireLayout
from .schema import SensorDescriptor, PdSpec


def register_address(index: int, subindex: int = 0) -> int:
    return (index << 8) | subindex


def split_register_address(value: int) -> tuple[int, int]:
    return value >> 8, value & 0xFF


def _reg_key(name: str | IntEnum) -> str:
    if isinstance(name, IntEnum):
        return name.name
    return name


def register_enum(descriptor: SensorDescriptor) -> type[IntEnum]:
    """Runtime ``IntEnum`` of register addresses (REPL tab-completion)."""
    members = {
        name: register_address(reg.index, reg.subindex)
        for name, reg in descriptor.registers.items()
    }
    return IntEnum(  # type: ignore[call-overload]
        f"{descriptor.meta.get('id', 'sensor')}_registers",
        members,
    )


def commands_enum(descriptor: SensorDescriptor) -> type[IntEnum]:
    """Runtime ``IntEnum`` of system command codes (REPL tab-completion)."""
    return IntEnum(  # type: ignore[call-overload]
        f"{descriptor.meta.get('id', 'sensor')}_commands",
        dict(sorted(descriptor.system_commands.items())),
    )


class DeviceBase:
    """Wire-level PD parse/pack; ISDU setup via ``apply_isdu`` (SAFE-OP / OP)."""

    def __init__(self, descriptor: SensorDescriptor) -> None:
        self.descriptor = descriptor
        self.Registers = register_enum(descriptor)
        self.Commands = commands_enum(descriptor)
        pd: PdSpec = descriptor.pd
        if pd.input is not None:
            self._pd_in_layout = PdWireLayout(fields=pd.input.fields, sio=False)
        else:
            self._pd_in_layout = None
        if pd.output is not None:
            self._pd_out_layout = PdWireLayout(fields=pd.output.fields, sio=False)
        else:
            self._pd_out_layout = None

    def isdu_writes(self) -> dict[str, Any]:
        """Register values to push before ISDU sync. Empty = read-only."""
        return {}

    def read_reg(self, port: IsduPort, name: str | IntEnum,raw: bool = False) -> Any:
        name_str = _reg_key(name)
        reg = self.descriptor.registers[name_str]
        if raw:
            return read_register(port, reg, name_str)
        return read_decoded_register(port, reg, name_str)

    def write_reg(self, port: IsduPort, name: str | IntEnum, value: Any) -> None:
        name_str = _reg_key(name)
        reg = self.descriptor.registers[name_str]
        if isinstance(value, bytes):
            write_register(port, reg, name_str, value)
        else:
            write_encoded_register(port, reg, name_str, value)

    def system_command(self, port: IsduPort, name: str | IntEnum) -> None:
        if isinstance(name, IntEnum):
            code = name.value
        else:
            code = self.descriptor.system_commands[name]
        port.write_isdu(2, bytes([code]), 0)

    def check_port(self, port: IsduPort) -> tuple[str, str]:
        """Read identity and verify vendor/product match this device descriptor."""
        vendor, product = read_identity(port, self.descriptor)
        assert_product_matches(self.descriptor, product)
        expected_vendor = self.descriptor.meta.get("vendor")
        if expected_vendor and expected_vendor.lower() not in vendor.lower():
            raise ValueError(
                f"Unexpected vendor {vendor!r} (expected {expected_vendor!r})"
            )
        return vendor, product

    def sync_from_isdu(self, port: IsduPort) -> None:
        """Read ISDU registers and populate runtime state used by ``sample()``."""
        raise NotImplementedError(f"{type(self).__name__} has no ISDU sync")

    def apply_isdu(self, port: IsduPort, *, verify: bool = True) -> None:
        """Write optional setup, validate identity, sync runtime from ISDU."""
        apply_isdu_writes(port, self.descriptor, self.isdu_writes())
        if verify:
            self.check_port(port)
        else:
            _, product = read_identity(port, self.descriptor)
            assert_product_matches(self.descriptor, product)
        self.sync_from_isdu(port)

    def configure_from_isdu(self, port: IsduPort, *, verify: bool = True) -> None:
        self.apply_isdu(port, verify=verify)

    @property
    def pd_in_layout(self) -> PdWireLayout | None:
        return self._pd_in_layout

    @property
    def pd_out_layout(self) -> PdWireLayout | None:
        return self._pd_out_layout

    def _decode_pd(self, raw: bytes) -> list[Any]:
        if self._pd_in_layout is None:
            raise ValueError("PD input layout not configured")
        return self._pd_in_layout.decode(raw)

    def _decode_pd_named(self, raw: bytes) -> dict[str, Any]:
        if self._pd_in_layout is None:
            raise ValueError("PD input layout not configured")
        return self._pd_in_layout.decode_named(raw)

    def _encode_pd(self, values: list[Any]) -> bytes:
        if self._pd_out_layout is None:
            raise ValueError("PD output layout not configured")
        return self._pd_out_layout.encode(values)
