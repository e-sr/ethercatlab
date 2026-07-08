"""Base class for configurable Beckhoff EL terminals."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .master import CoeTransfer
from .pdo import PdoMapping, RxPdoAssignment, TxPdoAssignment

if TYPE_CHECKING:
    from .master import Master


class BeckhoffDevice:
    def __init__(self, bus: Master, slave_idx: int) -> None:
        self._bus = bus
        self.slave_idx = slave_idx
        self._tx_assignment: TxPdoAssignment | None = None
        self._rx_assignment: RxPdoAssignment | None = None

    def coe_setup_writes(self) -> Sequence[CoeTransfer]:
        return ()

    def build_tx_assignment(self) -> TxPdoAssignment | None:
        return None

    def build_rx_assignment(self) -> RxPdoAssignment | None:
        return None

    def refresh_pdo_assignments(self) -> None:
        self._tx_assignment = self.build_tx_assignment()
        self._rx_assignment = self.build_rx_assignment()

    def tx_pdo_assignment(self) -> TxPdoAssignment | None:
        return self._tx_assignment

    def rx_pdo_assignment(self) -> RxPdoAssignment | None:
        return self._rx_assignment

    def decode_tx_pdo_named(self, raw: bytes) -> dict[str, dict[str, Any]]:
        if self._tx_assignment is None:
            raise RuntimeError("no tx PDO assignment configured")
        return self._tx_assignment.decode_named(raw)

    def decode_tx_pdo(self, raw: bytes) -> tuple[Any, ...] | None:
        if self._tx_assignment is None:
            raise RuntimeError("no tx PDO assignment configured")
        return self._tx_assignment.decode(raw)

    def expected_tx_pdo_byte_len(self) -> int:
        if self._tx_assignment is None:
            return 0
        return self._tx_assignment.byte_len()

    def preop_hook(self) -> None:
        pass

    def apply_preop_config(self) -> None:
        writes = list(self.coe_setup_writes())
        for assign in (self._tx_assignment, self._rx_assignment):
            if assign is not None:
                writes.extend(assign.to_coe_writes())
        if writes:
            self._bus.apply_coe_writes(self.slave_idx, writes)

    def configure_preop(self) -> None:
        self._bus.to_preop(self.preop_hook)
        self.apply_preop_config()


def inspect_pdo_mapping(master: Master, slave_idx: int, coe_index: int) -> PdoMapping:
    count_raw = master.read_coe(slave_idx, coe_index, 0).raw
    if count_raw is None:
        raise ValueError("Count is None")
    count = count_raw[0]
    coe_reads = [master.read_coe(slave_idx, coe_index, i + 1) for i in range(count)]
    return PdoMapping.from_coe_reads(coe_reads)
