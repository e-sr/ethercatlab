from __future__ import annotations

from typing import Any

from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase

import bitstruct
from dataclasses import dataclass

@dataclass(frozen=True)
class Psd4Sample:
    value: float
    ou1: bool
    ou2: bool


class Psd4Device(DeviceBase):
    DESCRIPTOR = load_descriptor("psd4")

    def __init__(self) -> None:
        super().__init__(self.DESCRIPTOR)
        self._gain:float|None=None

    @property
    def gain(self) -> float:
        if self._gain is None:
            return 1.0
        return self._gain

    def read_gain(self) -> float:
        self._gain=2.0
        return self._gain
        
    def parse_sample(self, raw: bytes) -> Psd4Sample:
        """Parse raw PD bytes into pressure value + output flags."""
        parsed = self.parse_pd(raw)
        return Psd4Sample(
            value=float(parsed["process_value_raw14"]) * self.gain,
            ou1=bool(parsed["ou1"]),
            ou2=bool(parsed["ou2"]),
        )
