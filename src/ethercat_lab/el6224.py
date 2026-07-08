"""EL6224 IO-Link master (0x18503052).

ISDU via AoE read/write works in SAFE-OP and OP, not in PRE-OP (runtime-tested).
``aoe_init`` still runs in PRE-OP during ``configure_preop``.

EtherCAT PDO layout (``TxPdoAssignment``) exposes opaque per-port blobs mapped to
``0x60n0:01``. IO-Link field semantics stay in ``iolink_sensors`` (``parse_pd``).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import TYPE_CHECKING, Any, NoReturn

import pysoem

from iolink_sensors.models import DeviceBase, PdWireLayout, SensorDescriptor

from .beckhoff_device import BeckhoffDevice
from .master import CoeTransfer, MasterState
from .pdo import PdoMapEntry, PdoMapping, TxPdoAssignment, RxPdoAssignment

from .aoe import (
    INDEX_GROUP_COE,
    iolink_ams_port,
    iolink_index_offset,
    isdu_access_hint,
    parse_aoe_error,
    parse_packet_error,
)

if TYPE_CHECKING:
    from .master import Master

PRODUCT_CODE = 0x18503052
_ISDU_SIZE = {0x0010: 2, 0x0011: 4}
_ISDU_TRANSIENT = {0x707, 0x708, 0x712, 0x11000700}

# CoE 0x80n0 — Beckhoff names vs hex subindex used in SDO writes
_SUB_SETTINGS_PD_IN = 0x24   # subindex 36: process data in length
_SUB_SETTINGS_PD_OUT = 0x25  # subindex 37: process data out length
_SUB_SETTINGS_MASTER = 0x28  # subindex 40: master control

DEVICE_STATE_DEVICE_TXPDO = 0x1A81
DEVICE_STATE_PORTS_TXPDO = 0x1A80
DEVICE_STATE_DEVICE_TXPDO_LEGACY = 0x1A05
DEVICE_STATE_PORTS_TXPDO_LEGACY = 0x1A04
DEVICE_STATE_BYTES = 6

_PD_FIELD = "iolink_pd"

# Hardcoded TxPDO specs because they are not configurable
_PDO_SPECS_RAW: dict[int, list[tuple[int, int, int, str | None, str]]] = {
    0x1A80: [
        (0xF100, 0x01, 8, "state_ch1", "u"),
        (0xF100, 0x02, 8, "state_ch2", "u"),
        (0xF100, 0x03, 8, "state_ch3", "u"),
        (0xF100, 0x04, 8, "state_ch4", "u"),
    ],
    0x1A81: [
        (0, 0, 12, None, "p"),
        (0xF101, 0x0D, 1, "device_diag", "b"),
        (0, 0, 2, None, "p"),
        (0xF101, 0x10, 1, "device_state", "b"),
    ],
}

_PDO_SPECS_HARDCODED: dict[int, list[PdoMapEntry]] = {
    idx: [PdoMapEntry(index, subindex, length, tp, name) for index, subindex, length, name, tp in entries]
    for idx, entries in _PDO_SPECS_RAW.items()
}
_PDO_SPECS_HARDCODED[DEVICE_STATE_PORTS_TXPDO_LEGACY] = _PDO_SPECS_HARDCODED[DEVICE_STATE_PORTS_TXPDO]
_PDO_SPECS_HARDCODED[DEVICE_STATE_DEVICE_TXPDO_LEGACY] = _PDO_SPECS_HARDCODED[DEVICE_STATE_DEVICE_TXPDO]
del _PDO_SPECS_RAW


class PortStatusMode(IntEnum):
    DISABLED = 0
    STD_DIG_IN = 1
    STD_DIG_OUT = 2
    COMM_OP = 3
    COMM_COMSTOP = 4


class PortStatusFlag(IntFlag):
    PD_INVALID = 0x08


class PortStatusError(IntFlag):
    WATCHDOG = 0x10
    INTERNAL = 0x20
    INVALID_DEVICE_ID = 0x30
    INVALID_VENDOR_ID = 0x40
    INVALID_IOL_VERSION = 0x50
    INVALID_FRAME_CAPABILITY = 0x60
    INVALID_CYCLE_TIME = 0x70
    INVALID_PD_IN_LENGTH = 0x80
    INVALID_PD_OUT_LENGTH = 0x90
    NO_DEVICE = 0xA0
    PREOP_STORAGE_ERROR = 0xB0


def decode_port_status_byte(
    value: int,
) -> tuple[PortStatusError, PortStatusMode, PortStatusFlag]:
    """Decode one F100 status byte into high-nibble errors, mode, and flags."""
    low = value & 0x0F
    mode = PortStatusMode(low & 0x07)
    flags = PortStatusFlag(low & PortStatusFlag.PD_INVALID)
    errors = PortStatusError(value & 0xF0)
    return errors, mode, flags

def _validate_port(port: int) -> None:
    if not 1 <= port <= 4:
        raise ValueError(f"IO-Link port must be 1..4, got {port}")


def encode_pd_settings_byte(*, bit_len: int, sio: bool) -> int:
    """Encode EL6224 CoE 0x80n0:24/:25 process-data length byte."""
    if bit_len == 0:
        return 0
    code = 0x40 if sio else 0
    if bit_len % 8 == 0 and bit_len > 16:
        nbytes = bit_len // 8
        if not 1 <= nbytes <= 32:
            raise ValueError(f"byte length out of range: {nbytes}")
        n = nbytes - 1
        if n > 0x1F:
            raise ValueError(f"byte length too large for IO-Link length code: {nbytes}")
        return code | 0x80 | n
    if not 1 <= bit_len <= 0x1F:
        raise ValueError(f"bit length out of range (1..31): {bit_len}")
    return code | bit_len


def decode_pd_settings_byte(code: int) -> tuple[int, bool]:
    """Decode EL6224 process-data length byte to (bit_len, sio)."""
    if code == 0:
        return 0, False
    sio = bool(code & 0x40)
    if code & 0x80:
        return ((code & 0x1F) + 1) * 8, sio
    return code & 0x1F, sio

@dataclass(frozen=True, slots=True)
class IoLinkChannelConfig:
    port: int
    pd_in: PdWireLayout | None = None
    pd_out: PdWireLayout | None = None
    _master_control: int = 3

    def __post_init__(self) -> None:
        _validate_port(self.port)
        if self.pd_in is None and self.pd_out is None:
            raise ValueError("pd_in or pd_out is required")

    @property
    def pdo_in_byte_len(self) -> int:
        if self.pd_in is None:
            return 0
        return self.pd_in.byte_len
    
    @property
    def settings_index(self) -> int:
        return 0x8000 + (self.port - 1) * 0x10

    @property
    def txpdo_index(self) -> int:
        return 0x1A00 + self.port - 1

    @property
    def rxpdo_index(self) -> int:
        return 0x1800 + self.port - 1

    @property
    def inputs_index(self) -> int:
        return 0x6000 + (self.port - 1) * 0x10

    @property
    def outputs_index(self) -> int:
        return 0x7000 + (self.port - 1) * 0x10

    @property
    def pd_field_name(self) -> str:
        return f"ch{self.port}_{_PD_FIELD}"

    def settings_writes(self) -> list[CoeTransfer]:
        sioin = self.pd_in.sio if self.pd_in is not None else False
        sioout = self.pd_out.sio if self.pd_out is not None else False
        bit_len_in = self.pd_in.bit_len if self.pd_in is not None else 0
        bit_len_out = self.pd_out.bit_len if self.pd_out is not None else 0
        return [
            CoeTransfer(self.settings_index, _SUB_SETTINGS_MASTER, raw=int(self._master_control).to_bytes(2, "little")),
            CoeTransfer(self.settings_index, _SUB_SETTINGS_PD_IN, raw=bytes([encode_pd_settings_byte(bit_len=bit_len_in, sio=sioin)])),
            CoeTransfer(self.settings_index, _SUB_SETTINGS_PD_OUT, raw=bytes([encode_pd_settings_byte(bit_len=bit_len_out, sio=sioout)])),
        ]

    def txpdo_mapping(self) -> PdoMapping|None:
        if self.pd_in is None:
            return None
        iolinkentry=PdoMapEntry(
            index=self.inputs_index,
            subindex=1,
            length=self.pd_in.bit_len,
            name="raw",
        )
        return PdoMapping(
            index=self.txpdo_index,
            entries=[iolinkentry],
            writable=True,
        )

    def rxpdo_mapping(self) -> PdoMapping|None:
        if self.pd_out is None:
            return None
        iolinkentry=PdoMapEntry(
            index=self.outputs_index,
            subindex=1,
            length=self.pd_out.bit_len,
            name="raw",
        )
        return PdoMapping(
            index=self.rxpdo_index,
            entries=[iolinkentry],
            writable=False,
        )


def all_channel_coe_writes(channels: list[IoLinkChannelConfig]) -> list[CoeTransfer]:
    ops: list[CoeTransfer] = []
    for cfg in sorted(channels, key=lambda c: c.port):
        ops.extend(cfg.settings_writes())
    return ops


class EL6224(BeckhoffDevice):
    def __init__(self, bus: Master, slave_idx: int, *, include_device_state: bool = True) -> None:
        super().__init__(bus, slave_idx)
        self._channels: dict[int, IoLinkChannelConfig] = {}
        self._aoe_init = True
        self.include_device_state = include_device_state

    def set_channel(self,channel: IoLinkChannelConfig) -> None:
        """Register a port recipe; optional ``device`` enables ``parse_pd`` on the channel."""
        self._channels[channel.port] = channel
        self.refresh_pdo_assignments()

    def clear_channels(self,port: int) -> None:
        self._channels.pop(port, None)
        self.refresh_pdo_assignments()

    @property
    def channels(self) -> list[IoLinkChannelConfig]:
        return list(self._channels.values())

    def preop_hook(self) -> None:
        if self._aoe_init:
            self._bus.aoe_init(self.slave_idx)

    def coe_setup_writes(self) -> list[CoeTransfer]:
        return all_channel_coe_writes(self.channels)

    def build_tx_assignment(self) -> TxPdoAssignment :
        items: list[tuple[str, PdoMapping]] = []
        if self.include_device_state:
            items.append((
                "dev_state_device",
                PdoMapping(
                    index=DEVICE_STATE_DEVICE_TXPDO,
                    entries=list(_PDO_SPECS_HARDCODED[DEVICE_STATE_DEVICE_TXPDO]),
                    writable=False,
                ),
            ))
            items.append((
                "dev_state_ports",
                PdoMapping(
                    index=DEVICE_STATE_PORTS_TXPDO,
                    entries=list(_PDO_SPECS_HARDCODED[DEVICE_STATE_PORTS_TXPDO]),
                    writable=False,
                ),
            ))

        for cfg in self.channels:
            map=cfg.txpdo_mapping()
            if map is not None:
                items.append((cfg.pd_field_name, map))

        return TxPdoAssignment.from_mappings(items)

    def build_rx_assignment(self) -> RxPdoAssignment | None:
        items: list[tuple[str, PdoMapping]] = []
        for cfg in self.channels:
            map=cfg.rxpdo_mapping()
            if map is not None:
                items.append((cfg.pd_field_name, map))
        if not items:
            return None
        return RxPdoAssignment.from_mappings(items)

    def expected_pdo_byte_len(self) -> int:
        return self.expected_tx_pdo_byte_len()

    def iolink_master_state_to_enum(self, pdo_decoded: dict[str, Any]) -> dict[str, Any]:
        state = {k: decode_port_status_byte(v) for k, v in pdo_decoded["dev_state_ports"].items()}
        return state

    def port_statuses(self, master: Master) -> dict[int, tuple[PortStatusError, PortStatusMode, PortStatusFlag]]:
        """Decode F100 port status bytes (call after ``master.cycle()``)."""
        raw = master.pdoin(self.slave_idx)
        decoded = self.decode_tx_pdo_named(raw, parse_iolink=False)
        out: dict[int, tuple[PortStatusError, PortStatusMode, PortStatusFlag]] = {}
        for key, value in decoded["dev_state_ports"].items():
            if not key.startswith("state_ch"):
                continue
            out[int(key.removeprefix("state_ch"))] = decode_port_status_byte(int(value))
        return out

    def wait_ports_ready(
        self,
        master: Master,
        ports: Sequence[int],
        *,
        timeout_s: float = 5.0,
        cycles_per_try: int = 5,
    ) -> None:
        """Exchange PDO until ports reach COMM_OP (required before ISDU on EL6224)."""
        deadline = time.monotonic() + timeout_s
        last = self.port_statuses(master)
        while time.monotonic() < deadline:
            for _ in range(cycles_per_try):
                master.cycle()
            last = self.port_statuses(master)
            if all(last.get(p, (PortStatusError(0), PortStatusMode.DISABLED, PortStatusFlag(0)))[1]
                   == PortStatusMode.COMM_OP for p in ports):
                for _ in range(20):
                    master.cycle()
                time.sleep(0.25)
                return
            time.sleep(0.05)
        lines = [
            f"  port {p}: mode={st[1].name} error={st[0].name if st[0] else 'none'}"
            for p in ports if (st := last.get(p)) is not None
        ]
        raise RuntimeError(
            "IO-Link port(s) not in COMM_OP — ISDU not available yet. "
            "Check sensor connected, powered, and matching PD layout.\n"
            + "\n".join(lines)
        )

    def configure_preop(self, *, aoe_init: bool = True) -> None:
        if not self.channels:
            raise ValueError("No IO-Link channels registered; call add_channel() first")
        self._aoe_init = aoe_init
        self.refresh_pdo_assignments()
        super().configure_preop()

    def decode_tx_pdo_named(self, raw: bytes,parse_iolink: bool = True) -> dict[str, Any]:
        decoded = super().decode_tx_pdo_named(raw)
        if parse_iolink:
            for cfg in self.channels:
                if cfg.pd_in is None:
                    continue
                decoded[cfg.pd_field_name] = cfg.pd_in.decode_named(decoded[cfg.pd_field_name]["raw"])
        return decoded

def _isdu_err(exc, offset: int, ams_port: int, *, write: bool, nbytes: int) -> NoReturn:
    idx, sub = (offset >> 16) & 0xFFFF, offset & 0xFF
    op = "write" if write else "read"
    if isinstance(exc, pysoem.AoeError):
        raise pysoem.AoeError(
            exc.slave_pos, exc.ams_error_code, exc.index_group, exc.index_offset,
            f"{parse_aoe_error(exc.ams_error_code)}{isdu_access_hint(idx, writing=write)} "
            f"(port {ams_port:#x}, ISDU 0x{idx:04x}:{sub}, {op} {nbytes} B)",
        ) from exc
    raise RuntimeError(
        f"ISDU {op}: {parse_packet_error(exc.error_code)} "
        f"(port {ams_port:#x}, ISDU 0x{idx:04x}:{sub}, {nbytes} B)"
    ) from exc


def _isdu_transient(exc: BaseException) -> bool:
    if isinstance(exc, pysoem.AoeError):
        code = exc.ams_error_code & 0xFFFFFFFF
        if code in _ISDU_TRANSIENT or (code >> 8) & 0xFF == 0x07:
            return True
    return isinstance(exc, pysoem.PacketError)


class IOLinkIsduChannel:
    """One EL6224 port: PRE-OP channel recipe, runtime ISDU and optional PDO parse."""

    def __init__(
        self,
        iolinkmaster: EL6224,
        port: int,
    ) -> None:
        self._iolinkmaster = iolinkmaster
        self.port = port
        self.iolink_channel = self._iolinkmaster._channels[port]

    def _check_master_state(self) -> None:
        if self._iolinkmaster._bus.get_slave(self._iolinkmaster.slave_idx).state != MasterState.SAFEOP:
            raise RuntimeError("Master is not in SAFE-OP state")

    def read_isdu(
        self,
        index: int,
        subindex: int = 0,
        *,
        size: int | None = None,
        retries: int = 2,
        retry_delay_s: float = 0.1,
    ) -> bytes:
        self._check_master_state()
        n = size if size is not None else _ISDU_SIZE.get(index, 64)
        off, ams = iolink_index_offset(index, subindex), iolink_ams_port(self.port)
        last_exc: BaseException | None = None
        for attempt in range(retries):
            try:
                return self._iolinkmaster._bus.aoe_read(
                    self._iolinkmaster.slave_idx, INDEX_GROUP_COE, off, n, ams,
                )
            except (pysoem.AoeError, pysoem.PacketError) as exc:
                last_exc = exc
                if attempt + 1 >= retries or not _isdu_transient(exc):
                    _isdu_err(exc, off, ams, write=False, nbytes=n)
                for _ in range(3):
                    self._iolinkmaster._bus.cycle()
                time.sleep(retry_delay_s)
        assert last_exc is not None
        _isdu_err(last_exc, off, ams, write=False, nbytes=n)  # type: ignore[arg-type]

    def write_isdu(self, index: int, data: bytes, subindex: int = 0) -> None:
        self._check_master_state()
        off, ams = iolink_index_offset(index, subindex), iolink_ams_port(self.port)
        try:
            self._iolinkmaster._bus.aoe_write(self._iolinkmaster.slave_idx, INDEX_GROUP_COE, off, data, ams)
        except (pysoem.AoeError, pysoem.PacketError) as exc:
            _isdu_err(exc, off, ams, write=True, nbytes=len(data))

