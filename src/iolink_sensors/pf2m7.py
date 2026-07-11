from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iolink_sensors.isdu import IsduPort
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase

_DISPLAY_UNIT: dict[int, str] = {
    0: "L/min",
    1: "cfm",
}


@dataclass(frozen=True, slots=True)
class Pf2m7IsduSetup:
    """Optional ISDU writes before sync. ``None`` = leave device unchanged."""
    display_unit: int | None = None


@dataclass(frozen=True)
class Pf2m7Sample:
    value: float
    unit: str
    out1: bool
    out2: bool
    flags: dict[str, Any]


class Pf2m7Device(DeviceBase):
    DESCRIPTOR = load_descriptor("pf2m7")

    def __init__(self, *, setup: Pf2m7IsduSetup | None = None) -> None:
        super().__init__(self.DESCRIPTOR)
        self._setup = setup or Pf2m7IsduSetup()
        self._scaling = 0.006250
        self._offset = 0.0
        self._unit = "L/min"

    @property
    def scaling(self) -> float:
        return self._scaling

    @property
    def unit(self) -> str:
        return self._unit

    def isdu_writes(self) -> dict[str, Any]:
        if self._setup.display_unit is None:
            return {}
        return {"display_unit": self._setup.display_unit}

    def sync_from_isdu(self, port: IsduPort) -> None:
        self._scaling = float(self.read_reg(port, "gradient_a"))
        self._offset = float(self.read_reg(port, "gradient_b"))
        unit_code = int(self.read_reg(port, "display_unit"))
        self._unit = _DISPLAY_UNIT.get(unit_code, f"code:{unit_code}")

    def sample(
        self,
        process_value: int,
        error_diag: bool,
        fixed_output: bool,
        _pad1: bool,
        meas_diag: bool,
        _pad2: bool,
        out2: bool = False,
        out1: bool = False,
    ) -> Pf2m7Sample:
        return Pf2m7Sample(
            value=float(process_value) * self._scaling + self._offset,
            unit=self._unit,
            out1=out1,
            out2=out2,
            flags={
                "error_diag": error_diag,
                "fixed_output": fixed_output,
                "meas_diag": meas_diag,
            },
        )
