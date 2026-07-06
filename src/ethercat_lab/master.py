from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from sys import settrace
from typing import Any, Callable
import pysoem

from .aoe import (
    AOE_TIMEOUT_US, COE_SLAVE_NETID_INDEX, COE_SLAVE_NETID_SUB,
    DEFAULT_MASTER_NETID, INDEX_GROUP_COE, coe_index_offset,
    parse_aoe_error, parse_packet_error,
)
from .coe import CoEEntry, CoeObject

logger = logging.getLogger(__name__)


EC_SLAVE_RESET_TO_DEFAULT_INDEX = 0x1011
EC_SLAVE_RESET_TO_DEFAULT_SUB = 0x01
EC_SLAVE_RESET_TO_DEFAULT_VALUE = b'\x64\x61\x6F\x6C'

def format_coe_exc(exc: BaseException) -> str:
    """pysoem CoE exceptions store details on attributes, not Exception.args."""
    if isinstance(exc, pysoem.SdoError):
        return (
            f"SDO abort 0x{exc.abort_code:08x}: {exc.desc} "
            f"(0x{exc.index:04x}:{exc.subindex})"
        )
    if isinstance(exc, pysoem.MailboxError):
        return f"Mailbox error 0x{exc.error_code:x}: {exc.desc}"
    if isinstance(exc, pysoem.PacketError):
        return f"Packet error 0x{exc.error_code:x}: {exc.desc}"
    if isinstance(exc, pysoem.WkcError):
        if exc.message:
            return exc.message
        return f"WKC error (wkc={exc.wkc})"
    msg = str(exc)
    return msg if msg else repr(exc)


def format_coe_payload(raw: bytes | bytearray) -> str:
    return " ".join(f"{byte:02x}" for byte in bytes(raw))


@dataclass(slots=True)
class CoeTransfer:
    """CoE bus transfer: index, subindex, raw payload or error."""

    index: int
    subindex: int
    raw: bytes | None = None
    error: str | None = None

    @property
    def raw_str(self) -> str:
        if self.error is not None or self.raw is None:
            return ""
        return " ".join(f"{byte:02x}" for byte in self.raw[::-1])


class Master:

    def __init__(
        self,
        ifname: str,
        *,
        master_netid: bytes | None = None,
        aoe_timeout_us: int = AOE_TIMEOUT_US,
    ):
        self.ifname = ifname
        self.master = pysoem.Master()
        self.initialized = False
        self.master_netid = master_netid or DEFAULT_MASTER_NETID
        if len(self.master_netid) != 6:
            raise ValueError("master_netid must be 6 bytes")
        self.aoe_timeout_us = aoe_timeout_us
        self.coe_cache: dict[int, dict[int, CoeObject]] = {}
        self._aoe_slave_netids: dict[int, bytes] = {}

    def open(self, manual_state_change: bool = False) -> Master:
        try:
            if self.initialized:
                return self
            self.master.open(self.ifname)
            self.master.manual_state_change = manual_state_change
            self.master.config_init()
            if not self.master.slaves:
                raise RuntimeError(f"No EtherCAT slaves found on interface {self.ifname}")
        except Exception:
            self.initialized = False
            raise
        else:
            self.master.read_state()
            if not manual_state_change:
                state = self.master.state_check(pysoem.PREOP_STATE, 100000)
                if state != pysoem.PREOP_STATE:
                    raise RuntimeError(f"Failed to reach PRE-OP state. Current state: {state}")
            else:
                state = self.master.state_check(pysoem.INIT_STATE, 100000)
                if state != pysoem.INIT_STATE:
                    raise RuntimeError(f"Failed to reach INIT state. Current state: {state}")
            self.initialized = True
            return self

    @property
    def state(self) -> int:
        return self.master.state

    @property
    def state_str(self) -> str:
        return Master.state_to_str(self.master.state)

    def _require_initialized(self) -> None:
        if not self.initialized:
            raise RuntimeError("Master not initialized.")

    def _check_slave_index(self, slave_idx: int) -> None:
        """slave_idx is 1-based, same as pysoem (first slave = 1)."""
        n = len(self.master.slaves)
        if slave_idx < 1 or slave_idx > n:
            raise ValueError(
                f"Slave index {slave_idx} out of range. Valid: 1..{n} (pysoem convention)"
            )

    def get_slave(self, slave_idx: int):
        """Return slave by 1-based index (first slave = 1, as in pysoem)."""
        self._require_initialized()
        self._check_slave_index(slave_idx)
        return self.master.slaves[slave_idx - 1]

    def slave_coe_object_dict(self, slave_idx: int) -> dict[int, CoeObject] | None:
        """Legge e formatta l'Object Dictionary CoE di uno slave, con caching per prestazioni."""
        self._require_initialized()
        if slave_idx in self.coe_cache:
            return self.coe_cache[slave_idx]
        self.get_slave(slave_idx)
        try:
            objects = self.get_slave(slave_idx).od
        except Exception:
            logger.debug("Failed to read CoE object dictionary from slave %s", slave_idx, exc_info=True)
            return None
        formatted_objects = {obj.index: CoeObject.from_pysoem(obj) for obj in objects}
        self.coe_cache[slave_idx] = formatted_objects
        return formatted_objects

    def get_coe_object(self, slave_idx: int, coe_idx: int) -> CoeObject | None:
        objects = self.slave_coe_object_dict(slave_idx)
        if objects is None:
            return None
        return objects.get(coe_idx)

    def get_coe_entry(self, slave_idx: int, coe_idx: int, subindex: int) -> CoEEntry | None:
        obj = self.get_coe_object(slave_idx, coe_idx)
        if obj is None:
            return None
        for entry in obj.entries:
            if entry.subindex == subindex:
                return entry
        return None

    def read_coe(self, slave_idx: int, coe_idx: int, subindex: int = 0) -> CoeTransfer:
        slave = self.get_slave(slave_idx)
        try:
            raw = slave.sdo_read(coe_idx, subindex)
        except Exception as exc:
            return CoeTransfer(coe_idx, subindex, error=format_coe_exc(exc))
        if raw is None:
            return CoeTransfer(coe_idx, subindex, error=f"Failed to read CoE 0x{coe_idx:04x}:{subindex}")
        return CoeTransfer(coe_idx, subindex, raw=bytes(raw))

    def write_coe(self, slave_idx: int, coe_idx: int, subindex: int, value: bytes | bytearray) -> CoeTransfer:
        slave = self.get_slave(slave_idx)
        try:
            slave.sdo_write(coe_idx, subindex, bytes(value))
        except Exception as exc:
            return CoeTransfer(coe_idx, subindex, error=format_coe_exc(exc))
        return CoeTransfer(coe_idx, subindex, raw=bytes(value))

    def apply_coe_writes(self, slave_idx: int, writes: Sequence[CoeTransfer]) -> None:
        for w in writes:
            if w.raw is None:
                raise ValueError(f"CoE write 0x{w.index:04x}:{w.subindex} has no raw payload")
            result = self.write_coe(slave_idx, w.index, w.subindex, w.raw)
            if result.error is not None:
                raise RuntimeError(
                    f"CoE write slave {slave_idx} 0x{w.index:04x}:0x{w.subindex:02x} "
                    f"payload={format_coe_payload(w.raw)} failed: {result.error}"
                )

    def parse_coe_read(self, slave_idx: int, coe_transfer: CoeTransfer) -> tuple[CoEEntry, Any]:
        if coe_transfer.error is not None or coe_transfer.raw is None:
            raise RuntimeError(coe_transfer.error or "empty CoE read")
        entry = self.get_coe_entry(slave_idx, coe_transfer.index, coe_transfer.subindex)
        if entry is None:
            raise RuntimeError(
                f"CoE entry not found for slave {slave_idx}, "
                f"index 0x{coe_transfer.index:04x}, subindex {coe_transfer.subindex}"
            )
        return entry, entry.unpack(coe_transfer.raw)

    def encode_coe_write(self, slave_idx: int, index: int, subindex: int, value: Any) -> tuple[CoEEntry, bytes]:
        entry = self.get_coe_entry(slave_idx, index, subindex)
        if entry is None:
            raise RuntimeError(
                f"CoE entry not found for slave {slave_idx}, index 0x{index:04x}, subindex {subindex}"
            )
        if not entry.is_valid:
            raise RuntimeError(f"Cannot pack value for {entry.name}: unsupported type {entry.data_type.name}")
        return entry, entry.pack(value)

    def slave_coe_reset_to_default(self, slave_idx: int) -> None:
        self.write_coe(slave_idx,EC_SLAVE_RESET_TO_DEFAULT_INDEX, EC_SLAVE_RESET_TO_DEFAULT_SUB, EC_SLAVE_RESET_TO_DEFAULT_VALUE)

    def read_slave_netid(self, slave_idx: int) -> bytes:
        transfer = self.read_coe(slave_idx, COE_SLAVE_NETID_INDEX, COE_SLAVE_NETID_SUB)
        if transfer.error is not None or transfer.raw is None:
            raise RuntimeError(
                f"Failed to read CoE 0x{COE_SLAVE_NETID_INDEX:04x}:{COE_SLAVE_NETID_SUB}: {transfer.error}"
            )
        return transfer.raw
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                
    def aoe_assign(self, slave_idx: int, slave_netid: bytes) -> None:
        if len(slave_netid) != 6:
            raise ValueError("slave_netid must be 6 bytes")
        self._aoe_slave_netids[slave_idx] = slave_netid

    def aoe_init(self, slave_idx: int) -> bytes:
        """Assign slave AMS netid; call from PRE-OP (e.g. preop_hook), not during PDO exchange."""
        slave_netid = self.read_slave_netid(slave_idx)
        self.aoe_assign(slave_idx, slave_netid)
        return slave_netid

    def _ensure_mailbox_aoe_state(self) -> None:
        """AoE read/write needs SAFE-OP or OP; EL6224 fails in PRE-OP (runtime-tested)."""
        self._require_initialized()
        state = self.master.state
        if state in (pysoem.SAFEOP_STATE, pysoem.OP_STATE):
            return
        if state == pysoem.PREOP_STATE:
            self.to_safeop()
            return
        raise RuntimeError(
            f"AoE transfer requires SAFE-OP or OP, bus is {self.state_to_str(state)}"
        )

    def _aoe_route(self, slave_idx: int, target_port: int) -> tuple[bytes, bytes, int, int]:
        if slave_idx not in self._aoe_slave_netids:
            raise RuntimeError(f"Slave {slave_idx}: call aoe_init(slave_idx) first")
        slave_netid = self._aoe_slave_netids[slave_idx]
        return self.master_netid, slave_netid, self.get_slave(slave_idx).configadr, target_port

    def _aoe_transfer(
        self,
        slave_idx: int,
        index_group: int,
        index_offset: int,
        payload: bytes | int,
        *,
        read: bool,
        target_port: int,
        timeout_us: int,
    ) -> bytes | None:
        self._ensure_mailbox_aoe_state()
        slave = self.get_slave(slave_idx)
        m_net, t_net, s_port, t_port = self._aoe_route(slave_idx, target_port)
        try:
            if read:
                return slave.ads_read(
                    t_net, t_port, index_group, index_offset, payload,
                    source_netid=m_net, source_port=s_port, timeout=timeout_us,
                )
            slave.ads_write(
                t_net, t_port, index_group, index_offset, payload,
                source_netid=m_net, source_port=s_port, timeout=timeout_us,
            )
            return None
        except pysoem.AoeError as exc:
            raise pysoem.AoeError(
                exc.slave_pos, exc.ams_error_code, exc.index_group, exc.index_offset,
                parse_aoe_error(exc.ams_error_code),
            ) from exc
        except pysoem.PacketError as exc:
            n = payload if read else len(payload)  # type: ignore[arg-type]
            raise RuntimeError(
                f"AoE {'read' if read else 'write'}: {parse_packet_error(exc.error_code)} "
                f"(ig=0x{index_group:x} off=0x{index_offset:x}, {n} B)"
            ) from exc

    def aoe_read(
        self, slave_idx: int, index_group: int, index_offset: int, size: int, target_port: int, *,
        timeout_us: int | None = None,
    ) -> bytes:
        t = self.aoe_timeout_us if timeout_us is None else timeout_us
        return self._aoe_transfer(
            slave_idx, index_group, index_offset, size, read=True, target_port=target_port, timeout_us=t,
        )  # type: ignore[return-value]

    def aoe_write(
        self, slave_idx: int, index_group: int, index_offset: int, data: bytes, target_port: int, *,
        timeout_us: int | None = None,
    ) -> None:
        t = self.aoe_timeout_us if timeout_us is None else timeout_us
        self._aoe_transfer(
            slave_idx, index_group, index_offset, data, read=False, target_port=target_port, timeout_us=t,
        )

    def aoe_read_coe(
        self, slave_idx: int, coe_index: int, subindex: int, size: int, target_port: int, *,
        timeout_us: int | None = None,
    ) -> bytes:
        return self.aoe_read(
            slave_idx, INDEX_GROUP_COE, coe_index_offset(coe_index, subindex), size, target_port,
            timeout_us=timeout_us,
        )

    def aoe_write_coe(
        self, slave_idx: int, coe_index: int, subindex: int, data: bytes, target_port: int, *,
        timeout_us: int | None = None,
    ) -> None:
        self.aoe_write(
            slave_idx, INDEX_GROUP_COE, coe_index_offset(coe_index, subindex), data, target_port,
            timeout_us=timeout_us,
        )

    def cycle(self) -> None:
        self._require_initialized()
        self.master.send_processdata()
        self.master.receive_processdata()
    
           
    def pdoin(self,slave_idx:int) -> bytes:
        raw=self.get_slave(slave_idx).input
        if len(raw)==0 or raw is None:
            raise RuntimeError(f"Failed to read input from slave {slave_idx}")
        else:
            return raw

    def pdoout(self,slave_idx:int) -> bytes|None:
        s=self.get_slave(slave_idx)
        return s.output if len(s.output) > 0 else None

    def pdoout_set(self, slave_idx: int, value: bytes) -> None:
        s=self.get_slave(slave_idx)
        s.output = value

    def close(self) -> None:
        try:
            self.master.close()
        except Exception:
            pass
        self.initialized = False
        self._aoe_slave_netids.clear()
        self.coe_cache.clear()

    def _on_enter_preop(self) -> None:
        """UML entry action: invalidate master PDO bookkeeping after downshift from SafeOP/Op."""
        logger.debug("PreOP entry: invalidate PDO IO map")
        # pysoem has no native unmap; config_map on PreOP exit rebuilds from scratch.

    def _on_exit_preop(self) -> None:
        """UML exit action: map PDOs while slaves are still in PreOP (ETG PS transition)."""
        logger.debug("PreOP exit: config_map")
        self.master.config_map()

    def to_preop(self, func: Callable[[], Any] | None = None) -> bool:
        self._require_initialized()
        self.master.read_state()
        prev = self.master.state
        if prev < pysoem.INIT_STATE:
            raise RuntimeError(
                f"Cannot transition to PRE-OP from {self.state_to_str(prev)}"
            )
        if prev == pysoem.PREOP_STATE:
            if func is not None:
                func()
            return False
        from_above = prev > pysoem.PREOP_STATE
        self._set_bus_state(pysoem.PREOP_STATE)
        if from_above:
            self._on_enter_preop()
        if func is not None:
            func()
        return True

    def to_safeop(self) -> bool:
        self._require_initialized()
        self.master.read_state()
        state = self.master.state
        if state in (pysoem.SAFEOP_STATE, pysoem.OP_STATE):
            return False
        if state != pysoem.PREOP_STATE:
            raise RuntimeError(
                f"Cannot transition to SAFE-OP from {self.state_to_str(state)}"
            )
        self._on_exit_preop()
        return self._set_bus_state(pysoem.SAFEOP_STATE)

    def to_init(self) -> bool:
        self._require_initialized()
        return self._set_bus_state(pysoem.INIT_STATE)

    def to_op(self) -> bool:
        self._require_initialized()
        self.master.read_state()
        state = self.master.state
        if state == pysoem.OP_STATE:
            return False
        if state != pysoem.SAFEOP_STATE:
            raise RuntimeError(
                f"Cannot transition to OP from {self.state_to_str(state)}"
            )
        self.cycle()
        return self._set_bus_state(pysoem.OP_STATE)

    def set_bus_state(self, target_state: int, timeout_us: int = 100000) -> bool:
        """Pure AL transition (no PreOP entry/exit actions). Prefer to_* methods."""
        self._require_initialized()
        return self._set_bus_state(target_state, timeout_us=timeout_us)

    def _set_bus_state(self, target_state: int, timeout_us: int = 100000) -> bool:
        self.master.read_state()
        if self.master.state == target_state:
            return False
        self.master.state = target_state
        self.master.write_state()
        self.master.read_state()
        reached = self.master.state_check(target_state, timeout_us)
        if reached != target_state:
            raise RuntimeError(
                f"Failed state transition target={self.state_to_str(target_state)} "
                f"reached={self.state_to_str(reached)}"
            )
        return True
    
    @staticmethod
    def state_to_str(state: int) -> str:
        states = []
        if state & pysoem.INIT_STATE:
            states.append("INIT")
        if state & pysoem.PREOP_STATE:
            states.append("PRE-OP")
        if state & pysoem.SAFEOP_STATE:
            states.append("SAFE-OP")
        if state & pysoem.OP_STATE:
            states.append("OP")
        return "|".join(states) if states else f"UNKNOWN({state})"

