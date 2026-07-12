"""EL3072 2ch analog input (0x0C003052).

Process values (object 0x6000) are exposed in two alternate formats:

- **0x6000:11 Value (INT16)** — scaled process counts (Extended Range: ±30518 ≈ 100 %
  FSV). Refreshed with the input Sync Manager in SAFE-OP/OP only; SDO reads in
  PRE-OP return 0 / stale data.
- **0x6000:13 Value (Real32)** — engineering units (V or mA per ``InputInterface``).
  Usable via SDO in all states; preferred for application code.

**User scaling** (optional) applies **only to the Real32 path**:

- Enable: ``0x80n0:01``
- Offset (float): ``0x80nD:1C``
- Gain (float): ``0x80nD:1D`` — ``Y = Y_cal × gain + offset`` (V or mA)

Beckhoff also documents INT16 user scale on ``0x80n0:11/12`` (fixed-point gain
Q16). We do **not** write those objects: INT16 scaling belongs in application
code (``raw / 30518 × FSV``) if needed.

Recommended setup: ``PdoMode.DEFAULT_REAL32``, ``user_scale=None`` for direct
V/mA; set ``UserScaleConfig`` when a linear transform on Real32 is required.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .beckhoff_device import BeckhoffDevice
from .master import CoeTransfer, Master
from .pdo import PdoMapEntry, PdoMapping, TxPdoAssignment

PRODUCT_CODE = 0x0C003052

# 0x8000 — AI Settings (subindices decimal in Beckhoff table → hex below)
_SUB_0X8000_ENABLE_USER_SCALE = 0x01
_SUB_0X8000_ENABLE_FILTER1 = 0x06
_SUB_0X8000_ENABLE_LIMIT1 = 0x07
_SUB_0X8000_ENABLE_LIMIT2 = 0x08
_SUB_0X8000_FILTER_SETTINGS = 0x15  # dec 21, DOMAIN r16

# 0x800D — AI Advanced Settings
_SUB_0X800D_INPUT_INTERFACE = 0x11  # dec 17
_SUB_0X800D_USER_SCALE_OFFSET_F32 = 0x1C  # dec 28
_SUB_0X800D_USER_SCALE_GAIN_F32 = 0x1D  # dec 29
_SUB_0X800D_LOW_RANGE_ERROR_F32 = 0x27  # dec 39
_SUB_0X800D_HIGH_RANGE_ERROR_F32 = 0x28  # dec 40
_SUB_0X800D_LIMIT_1_F32 = 0x29  # dec 41
_SUB_0X800D_LIMIT_2_F32 = 0x2A  # dec 42
# 0x6000 — AI Inputs (runtime / PDO)
_SUB_0X6000_VALUE_I16 = 0x11  # dec 17
_SUB_0X6000_VALUE_F32 = 0x13  # dec 19


class InputInterface(IntEnum):
    NONE = 0
    V_PM10 = 2
    V_0_10 = 14
    I_PM20MA = 17
    I_0_20MA = 18
    I_4_20MA = 19
    I_4_20MA_NAMUR = 20


INPUT_10V = InputInterface.V_PM10
INPUT_20MA = InputInterface.I_PM20MA


class IIRFilter(IntEnum):
    """Filter type written to ``0x80n0:15`` (Filter Settings DOMAIN r16)."""
    NONE = 0
    IIR168Hz = 1
    IIR88Hz = 2
    IIR43Hz = 3
    IIR21Hz = 4
    IIR10_5Hz = 5
    IIR5_2Hz = 6
    IIR2_5Hz = 7
    IIR1_2Hz = 8


class LimitTriggerType(IntEnum):
    """TxPDO ``0x6000:03/05`` limit status (BIT2)."""
    NONE = 0
    LESS_THAN = 1
    GREATER_THAN = 2
    EQUAL = 3


class PdoMode(IntEnum):
    """Ch.1 TxPDO map index; Ch.2 = value + 2."""
    DEFAULT = 0x1A00
    COMPACT = 0x1A01
    DEFAULT_REAL32 = 0x1A10
    COMPACT_REAL32 = 0x1A11


CYCLE_COUNTER_TXPDO_BASE = 0x1A20

_PDO_SPECS_CH1: dict[int, list[tuple[int, int, int, str | None, str]]] = {
    0x1A00: [
        (0x6000, 0x01, 1, "underrange", "b"),
        (0x6000, 0x02, 1, "overrange", "b"),
        (0x6000, 0x03, 2, "limit1", "u"),
        (0x6000, 0x05, 2, "limit2", "u"),
        (0x6000, 0x07, 1, "error", "b"),
        (0, 0, 7, None, "p"),
        (0x6000, 0x0F, 1, "txpdo_state", "b"),
        (0x6000, 0x10, 1, "txpdo_toggle", "b"),
        (0x6000, 0x11, 16, "value_i16", "s"),
    ],
    0x1A01: [
        (0x6000, 0x11, 16, "value_i16", "s"),
    ],
    0x1A10: [
        (0x6000, 0x01, 1, "underrange", "b"),
        (0x6000, 0x02, 1, "overrange", "b"),
        (0x6000, 0x03, 2, "limit1", "u"),
        (0x6000, 0x05, 2, "limit2", "u"),
        (0x6000, 0x07, 1, "error", "b"),
        (0, 0, 4, None, "p"),
        (0x6000, 0x0C, 1, "tare_active", "b"),
        (0, 0, 2, None, "p"),
        (0x6000, 0x0F, 1, "txpdo_state", "b"),
        (0x6000, 0x10, 1, "txpdo_toggle", "b"),
        (0x6000, 0x13, 32, "value_f32", "f"),
    ],
    0x1A11: [
        (0x6000, 0x13, 32, "value_f32", "f"),
    ],
    0x1A20: [
        (0x6000, 0x14, 16, "cycle_counter", "u"),
    ],
}

_PDO_SPECS: dict[int, list[PdoMapEntry]] = {
    (mapindex + (channel - 1) * 2): [
        PdoMapEntry(index + (channel - 1) * 0x10, subindex, length, tp, name)
        for index, subindex, length, name, tp in entries
    ]
    for mapindex, entries in _PDO_SPECS_CH1.items()
    for channel in (1, 2)
}

del _PDO_SPECS_CH1


def decode_limit_trigger(value: int) -> LimitTriggerType:
    """Decode a TxPDO limit BIT2 field to ``LimitTriggerType``."""
    try:
        return LimitTriggerType(int(value))
    except ValueError:
        return LimitTriggerType.NONE


def txpdo_index(mode: PdoMode, port: int) -> int:
    if port not in (1, 2):
        raise ValueError(f"EL3072 channel must be 1 or 2, got {port}")
    return mode + (port - 1) * 2


def cycle_counter_txpdo_index(port: int) -> int:
    if port not in (1, 2):
        raise ValueError(f"EL3072 channel must be 1 or 2, got {port}")
    return CYCLE_COUNTER_TXPDO_BASE + (port - 1) * 2


@dataclass(frozen=True, slots=True)
class UserScaleConfig:
    """Linear user scale on the Real32 path (``0x80nD:1C`` / ``0x80nD:1D``)."""

    gain: float = 1.0
    offset: float = 0.0

    @classmethod
    def physical(cls, *, gain: float, offset: float) -> UserScaleConfig:
        return cls(gain=gain, offset=offset)


@dataclass(frozen=True, slots=True)
class LimitConfig:
    """Limit thresholds Real32 on ``0x80nD:41`` / ``0x80nD:42`` (enabled via ``0x80n0:07/08``)."""

    limit1: float = 0.0
    limit2: float = 0.0


@dataclass(frozen=True, slots=True)
class RangeErrorConfig:
    """Range-error substitution values (``0x80nD:27`` / ``0x80nD:28``)."""

    low: float = 0.0
    high: float = 0.0


# Backward alias
RangeError = RangeErrorConfig


@dataclass(frozen=True, slots=True)
class AnalogInputChannel:
    port: int
    input_interface: InputInterface = InputInterface.V_PM10
    user_scale: UserScaleConfig | None = None
    limits: LimitConfig | None = None
    range_error: RangeErrorConfig | None = None
    iir_filter: IIRFilter = IIRFilter.NONE
    pdo_mode: PdoMode | None = PdoMode.DEFAULT
    cycle_counters: bool = False

    def __post_init__(self) -> None:
        if self.port not in (1, 2):
            raise ValueError(f"EL3072 channel must be 1 or 2, got {self.port}")
        if not isinstance(self.input_interface, InputInterface):
            object.__setattr__(self, "input_interface", InputInterface(int(self.input_interface)))

    @property
    def settings_index(self) -> int:
        return 0x8000 + (self.port - 1) * 0x10

    @property
    def advanced_index(self) -> int:
        return 0x800D + (self.port - 1) * 0x10

    @property
    def inputs_index(self) -> int:
        return 0x6000 + (self.port - 1) * 0x10

    def txpdo_mappings(self) -> list[tuple[str, PdoMapping]]:
        out: list[tuple[str, PdoMapping]] = []
        if self.pdo_mode is not None:
            idx = txpdo_index(self.pdo_mode, self.port)
            name = f"ch{self.port}_{self.pdo_mode.name}"
            out.append((
                name,
                PdoMapping(
                    index=idx,
                    entries=list(_PDO_SPECS[idx]),
                    writable=False,
                ),
            ))
        if self.cycle_counters:
            idx = cycle_counter_txpdo_index(self.port)
            out.append((
                f"ch{self.port}_cycle_counter",
                PdoMapping(
                    index=idx,
                    entries=list(_PDO_SPECS[idx]),
                    writable=False,
                ),
            ))
        return out

    def settings_writes(self) -> list[CoeTransfer]:
        writes: list[CoeTransfer] = [
            CoeTransfer(
                self.advanced_index,
                _SUB_0X800D_INPUT_INTERFACE,
                raw=int(self.input_interface).to_bytes(2, "little"),
            ),
        ]
        if self.user_scale is not None:
            writes.extend([
                CoeTransfer(self.settings_index, _SUB_0X8000_ENABLE_USER_SCALE, raw=b"\x01"),
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_USER_SCALE_OFFSET_F32,
                    raw=struct.pack("<f", self.user_scale.offset),
                ),
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_USER_SCALE_GAIN_F32,
                    raw=struct.pack("<f", self.user_scale.gain),
                ),
            ])
        if self.iir_filter != IIRFilter.NONE:
            writes.extend([
                CoeTransfer(self.settings_index, _SUB_0X8000_ENABLE_FILTER1, raw=b"\x01"),
                CoeTransfer(
                    self.settings_index,
                    _SUB_0X8000_FILTER_SETTINGS,
                    raw=int(self.iir_filter).to_bytes(2, "little"),
                ),
            ])
        if self.limits is not None:
            lim = self.limits
            writes.extend([
                CoeTransfer(self.settings_index, _SUB_0X8000_ENABLE_LIMIT1, raw=b"\x01"),
                CoeTransfer(self.settings_index, _SUB_0X8000_ENABLE_LIMIT2, raw=b"\x01"),
                # Write upper threshold first: device validates min/max on each SDO.
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_LIMIT_2_F32,
                    raw=struct.pack("<f", lim.limit2),
                ),
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_LIMIT_1_F32,
                    raw=struct.pack("<f", lim.limit1),
                ),
            ])
        if self.range_error is not None:
            re = self.range_error
            writes.extend([
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_HIGH_RANGE_ERROR_F32,
                    raw=struct.pack("<f", re.high),
                ),
                CoeTransfer(
                    self.advanced_index,
                    _SUB_0X800D_LOW_RANGE_ERROR_F32,
                    raw=struct.pack("<f", re.low),
                ),
            ])
        return writes


class EL3072(BeckhoffDevice):
    def __init__(self, bus: Master, slave_idx: int) -> None:
        super().__init__(bus, slave_idx)
        self._channels: dict[int, AnalogInputChannel] = {}

    def set_channel(self, channel: AnalogInputChannel) -> None:
        self._channels[channel.port] = channel
        self.refresh_pdo_assignments()

    def clear_channel(self, port: int) -> None:
        self._channels.pop(port, None)
        self.refresh_pdo_assignments()

    @property
    def channels(self) -> list[AnalogInputChannel]:
        return [self._channels[p] for p in sorted(self._channels)]

    def build_tx_assignment(self) -> TxPdoAssignment | None:
        if not self._channels:
            return None
        items: list[tuple[str, PdoMapping]] = []
        for ch in self.channels:
            items.extend(ch.txpdo_mappings())
        if not items:
            return None
        items.sort(key=lambda item: item[1].index)
        return TxPdoAssignment.from_mappings(items)

    def coe_setup_writes(self) -> Sequence[CoeTransfer]:
        writes: list[CoeTransfer] = []
        for ch in self.channels:
            writes.extend(ch.settings_writes())
        return writes

    def expected_pdo_byte_len(self) -> int:
        return self.expected_tx_pdo_byte_len()

    def configure_preop(self) -> None:
        if not self._channels:
            raise ValueError("No channels registered; call set_channel() first")
        self.refresh_pdo_assignments()
        super().configure_preop()

    def decode_tx_pdo_named(
        self,
        raw: bytes,
        *,
        parse_limit: bool = False,
    ) -> dict[str, dict[str, Any]]:
        named = super().decode_tx_pdo_named(raw)
        if not parse_limit:
            return named
        for fields in named.values():
            for key in ("limit1", "limit2"):
                if key in fields:
                    fields[key] = decode_limit_trigger(fields[key])
        return named

    def decode_pdo_named(
        self,
        raw: bytes,
        *,
        parse_limit: bool = False,
    ) -> dict[str, dict[str, Any]]:
        return self.decode_tx_pdo_named(raw, parse_limit=parse_limit)

    def coe_read_inputs_f32(self, port: int) -> float:
        transfer = self._bus.read_coe(
            self.slave_idx, 0x6000 + (port - 1) * 0x10, _SUB_0X6000_VALUE_F32,
        )
        if transfer.error is not None or transfer.raw is None:
            raise RuntimeError(transfer.error or "empty CoE read")
        return struct.unpack("<f", transfer.raw[:4])[0]

    def coe_read_inputs_i16(self, port: int) -> int:
        transfer = self._bus.read_coe(
            self.slave_idx, 0x6000 + (port - 1) * 0x10, _SUB_0X6000_VALUE_I16,
        )
        if transfer.error is not None or transfer.raw is None:
            raise RuntimeError(transfer.error or "empty CoE read")
        return int.from_bytes(transfer.raw[:2], "little", signed=True)
