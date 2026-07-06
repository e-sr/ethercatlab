from __future__ import annotations

from typing import Any
from collections.abc import Sequence

from .pd_layout import PdWireLayout
from .schema import SensorDescriptor, PdSpec, PdFrameSpec


class DeviceBase:
    """Wire-level PD parse/pack via ``PdWireLayout``.

    Subclasses add physical scaling (gradients, units) often backed by ISDU reads.
    """

    def __init__(self, descriptor: SensorDescriptor) -> None:
        self.descriptor = descriptor
        pd: PdSpec = descriptor.pd
        if pd.input is not None:
            self._pd_in_layout = PdWireLayout(fields=pd.input.fields,sio=False)
        else:
            self._pd_in_layout = None
        if pd.output is not None:
            self._pd_out_layout = PdWireLayout(fields=pd.output.fields,sio=False)
        else:
            self._pd_out_layout = None

    @property
    def pd_in_layout(self) -> PdWireLayout|None:
        return self._pd_in_layout

    @property
    def pd_out_layout(self) -> PdWireLayout|None:
        return self._pd_out_layout

    def _decode_pd(self, raw: bytes) -> list[Any]:
        return self._pd_in_layout.decode(raw)

    def _decode_pd_named(self, raw: bytes) -> dict[str, Any]:
        return self._pd_in_layout.decode_named(raw)

    def _encode_pd(self, values: list[Any]) -> bytes:
        return self.pd_out_layout.encode(values)
