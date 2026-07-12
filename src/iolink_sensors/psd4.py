from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iolink_sensors.isdu import IsduPort
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase


@dataclass(frozen=True, slots=True)
class Psd4IsduSetup:
    unit_process_data: int | None = None


@dataclass(frozen=True)
class Psd4Sample:
    value: float
    unit: str
    out1: bool
    out2: bool


class Psd4Device(DeviceBase):
    DESCRIPTOR = load_descriptor("psd4")

    def __init__(self, *, setup: Psd4IsduSetup | None = None) -> None:
        super().__init__(self.DESCRIPTOR)
        self._setup = setup or Psd4IsduSetup()
        self._gain = 1.0
        self._unit = "?"
        self._sensor_status = 0

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def sensor_status(self) -> int:
        return self._sensor_status

    def isdu_writes(self) -> dict[str, Any]:
        if self._setup.unit_process_data is None:
            return {}
        return {"unit_process_data": self._setup.unit_process_data}

    def sync_from_isdu(self, port: IsduPort) -> None:
        self._gain = float(self.read_reg(port, "gradient"))
        unit = self.read_reg(port, "unit_process_data")
        self._unit = unit.label
        self._sensor_status = int(self.read_reg(port, "sensor_status"))

    def sample(self, process_value: int, out1: bool, out2: bool) -> Psd4Sample:
        return Psd4Sample(
            value=float(process_value) * self._gain,
            unit=self._unit,
            out1=out1,
            out2=out2,
        )

    def parse_sample(self, raw: bytes) -> Psd4Sample:
        return self.sample(**self._decode_pd_named(raw))
