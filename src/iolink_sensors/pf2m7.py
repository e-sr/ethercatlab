from __future__ import annotations
from typing import Any
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase
from dataclasses import dataclass
_FLOW_SCALING_TABLE: dict[int, float] = {
    1: 0.000250, 2: 0.000500, 5: 0.001250, 10: 0.002500,
    25: 0.006250, 50: 0.012500, 100: 0.025000,
}

@dataclass(frozen=True)
class Pf2m7Sample:
    value: float
    unit: str
    flags: dict[str, Any]
class Pf2m7Device(DeviceBase):
    DESCRIPTOR = load_descriptor("pf2m7")

    def __init__(self, flow_range_l: int = 25) -> None:
        super().__init__(self.DESCRIPTOR)
        if flow_range_l not in _FLOW_SCALING_TABLE:
            raise ValueError(f"Invalid flow_range_l. Valid: {list(_FLOW_SCALING_TABLE)}")
        self._flow_range_l = flow_range_l
        self._scaling = _FLOW_SCALING_TABLE[flow_range_l]
        if self.pd_in_layout is None:
            raise ValueError("pd_in_layout is None")

    def sample(self, pd_raw_s16: int, error_diag: bool, fixed_output: bool, _pad1: bool, meas_diag: bool, _pad2: bool) ->Pf2m7Sample:
        """Parse raw PD bytes into scaled flow value + flags."""
        return Pf2m7Sample(
            value=float(pd_raw_s16) * self._scaling,
            unit="L/min",
            flags={
                "error_diag": error_diag,
                "fixed_output": fixed_output,
                "meas_diag": meas_diag,
            },
        )