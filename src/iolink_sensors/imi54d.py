from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iolink_sensors.isdu import IsduPort
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase

# IODD Observe menus: PD raw * gradient → physical unit.
# Raw counts are 0.01 bar; kPa/psi/inHg are converted from that base.
_UNIT_GAIN: dict[int, float] = {
    0: 0.01,      # bar
    1: 1.0,       # kPa
    2: 0.14504,   # psi
    3: 0.2953,    # inHg
}


@dataclass(frozen=True, slots=True)
class Imi54dIsduSetup:
    unit: int | None = None


@dataclass(frozen=True)
class Imi54dSample:
    value: float
    unit: str
    out1: bool
    out2: bool


class Imi54dDevice(DeviceBase):
    DESCRIPTOR = load_descriptor("imi54d")

    def __init__(self, *, setup: Imi54dIsduSetup | None = None) -> None:
        super().__init__(self.DESCRIPTOR)
        self._setup = setup or Imi54dIsduSetup()
        self._gain = _UNIT_GAIN[0]
        self._unit = "bar"

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def unit(self) -> str:
        return self._unit

    def isdu_writes(self) -> dict[str, Any]:
        if self._setup.unit is None:
            return {}
        return {"unit": self._setup.unit}

    def sync_from_isdu(self, port: IsduPort) -> None:
        unit = self.read_reg(port, "unit")
        code = int(unit)
        self._gain = _UNIT_GAIN.get(code, _UNIT_GAIN[0])
        self._unit = unit.label

    def sample(self, process_value: int, out1: bool, out2: bool) -> Imi54dSample:
        return Imi54dSample(
            value=float(process_value) * self._gain,
            unit=self._unit,
            out1=out1,
            out2=out2,
        )

    def parse_sample(self, raw: bytes) -> Imi54dSample:
        return self.sample(**self._decode_pd_named(raw))
