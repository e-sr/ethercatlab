from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from iolink_sensors.isdu import IsduPort, SensorIsduProfile, read_decoded_register
from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase


@dataclass(frozen=True, slots=True)
class Psd4IsduSetup:
    unit_process_data: int | None = None


@dataclass(frozen=True)
class Psd4Sample:
    value: float
    unit: str
    ou1: bool
    ou2: bool


class Psd4Device(DeviceBase):
    DESCRIPTOR = load_descriptor("psd4")

    def __init__(self, *, setup: Psd4IsduSetup | None = None) -> None:
        super().__init__(self.DESCRIPTOR)
        self._setup = setup or Psd4IsduSetup()
        self._gain = 1.0
        self._unit = "?"

    @property
    def gain(self) -> float:
        return self._gain

    def isdu_writes(self) -> dict[str, Any]:
        if self._setup.unit_process_data is None:
            return {}
        return {"unit_process_data": self._setup.unit_process_data}

    def load_isdu_profile(
        self, port: IsduPort, *, vendor: str, product: str,
    ) -> SensorIsduProfile:
        gain = float(read_decoded_register(port, self.descriptor, "gradient"))
        unit_code = int(read_decoded_register(port, self.descriptor, "unit_process_data"))
        status = int(read_decoded_register(port, self.descriptor, "sensor_status"))
        return SensorIsduProfile(
            product_name=product,
            vendor_name=vendor,
            scaling=gain,
            unit=f"unit:{unit_code}",
            device_status=status,
            extra={"unit_process_data": unit_code},
        )

    def sync_from_profile(self, profile: SensorIsduProfile) -> None:
        self._gain = float(profile.scaling or self._gain)
        self._unit = profile.unit or self._unit

    def sample(self, process_value_raw14: int, ou1: bool, ou2: bool) -> Psd4Sample:
        return Psd4Sample(
            value=float(process_value_raw14) * self._gain,
            unit=self._unit,
            ou1=ou1,
            ou2=ou2,
        )

    def parse_sample(self, raw: bytes) -> Psd4Sample:
        return self.sample(**self._decode_pd_named(raw))
