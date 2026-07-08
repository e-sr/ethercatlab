from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iolink_sensors.isdu import (
    IsduPort,
    SensorIsduProfile,
    read_decoded_register,
)
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase

_FLOW_SCALING_TABLE: dict[int, float] = {
    1: 0.000250, 2: 0.000500, 5: 0.001250, 10: 0.002500,
    25: 0.006250, 50: 0.012500, 100: 0.025000,
}

_DISPLAY_UNIT: dict[int, str] = {
    0: "L/min",
    1: "cfm",
}


@dataclass(frozen=True, slots=True)
class Pf2m7IsduSetup:
    """Optional ISDU writes before profile read. ``None`` = leave device unchanged."""

    display_unit: int | None = None


@dataclass(frozen=True)
class Pf2m7Sample:
    value: float
    unit: str
    flags: dict[str, Any]


class Pf2m7Device(DeviceBase):
    DESCRIPTOR = load_descriptor("pf2m7")

    def __init__(
        self,
        *,
        setup: Pf2m7IsduSetup | None = None,
        flow_range_l: int | None = 25,
    ) -> None:
        super().__init__(self.DESCRIPTOR)
        self._setup = setup or Pf2m7IsduSetup()
        self._flow_range_l = flow_range_l
        self._scaling = _FLOW_SCALING_TABLE.get(flow_range_l, 0.006250) if flow_range_l else 0.006250
        self._offset = 0.0
        self._unit = "L/min"
        if self.pd_in_layout is None:
            raise ValueError("pd_in_layout is None")

    def isdu_writes(self) -> dict[str, Any]:
        if self._setup.display_unit is None:
            return {}
        return {"display_unit": self._setup.display_unit}

    def load_isdu_profile(
        self, port: IsduPort, *, vendor: str, product: str,
    ) -> SensorIsduProfile:
        scaling = float(read_decoded_register(port, self.descriptor, "gradient_a"))
        offset = float(read_decoded_register(port, self.descriptor, "gradient_b"))
        unit_code = int(read_decoded_register(port, self.descriptor, "display_unit"))
        return SensorIsduProfile(
            product_name=product,
            vendor_name=vendor,
            scaling=scaling,
            offset=offset,
            unit=_DISPLAY_UNIT.get(unit_code, f"code:{unit_code}"),
            extra={"display_unit_code": unit_code},
        )

    def sync_from_profile(self, profile: SensorIsduProfile) -> None:
        self._scaling = float(profile.scaling or self._scaling)
        self._offset = float(profile.offset or 0.0)
        self._unit = profile.unit or self._unit

    def sample(
        self,
        pd_raw_s16: int,
        error_diag: bool,
        fixed_output: bool,
        _pad1: bool,
        meas_diag: bool,
        _pad2: bool,
        out2: bool = False,
        out1: bool = False,
    ) -> Pf2m7Sample:
        return Pf2m7Sample(
            value=float(pd_raw_s16) * self._scaling + self._offset,
            unit=self._unit,
            flags={
                "error_diag": error_diag,
                "fixed_output": fixed_output,
                "meas_diag": meas_diag,
                "out1": out1,
                "out2": out2,
            },
        )
