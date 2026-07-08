from __future__ import annotations

from typing import Any

from .isdu import IsduPort, SensorIsduProfile, apply_isdu_writes, assert_product_matches, read_identity
from .pd_layout import PdWireLayout
from .schema import SensorDescriptor, PdSpec


class DeviceBase:
    """Wire-level PD parse/pack; ISDU setup via ``apply_isdu`` (SAFE-OP / OP)."""

    def __init__(self, descriptor: SensorDescriptor) -> None:
        self.descriptor = descriptor
        self.isdu_profile: SensorIsduProfile | None = None
        pd: PdSpec = descriptor.pd
        if pd.input is not None:
            self._pd_in_layout = PdWireLayout(fields=pd.input.fields, sio=False)
        else:
            self._pd_in_layout = None
        if pd.output is not None:
            self._pd_out_layout = PdWireLayout(fields=pd.output.fields, sio=False)
        else:
            self._pd_out_layout = None

    def isdu_writes(self) -> dict[str, Any]:
        """Register values to push before reading profile. Empty = read-only."""
        return {}

    def load_isdu_profile(
        self, port: IsduPort, *, vendor: str, product: str,
    ) -> SensorIsduProfile:
        raise NotImplementedError(f"{type(self).__name__} has no ISDU profile loader")

    def sync_from_profile(self, profile: SensorIsduProfile) -> None:
        """Apply profile fields to runtime scaling used by ``sample()``."""

    def apply_isdu(self, port: IsduPort) -> SensorIsduProfile:
        """Write optional setup, validate identity, read profile, sync runtime."""
        apply_isdu_writes(port, self.descriptor, self.isdu_writes())
        vendor, product = read_identity(port, self.descriptor)
        assert_product_matches(self.descriptor, product)
        profile = self.load_isdu_profile(port, vendor=vendor, product=product)
        self.sync_from_profile(profile)
        self.isdu_profile = profile
        return profile

    def configure_from_isdu(self, port: IsduPort) -> SensorIsduProfile:
        return self.apply_isdu(port)

    @property
    def pd_in_layout(self) -> PdWireLayout | None:
        return self._pd_in_layout

    @property
    def pd_out_layout(self) -> PdWireLayout | None:
        return self._pd_out_layout

    def _decode_pd(self, raw: bytes) -> list[Any]:
        return self._pd_in_layout.decode(raw)

    def _decode_pd_named(self, raw: bytes) -> dict[str, Any]:
        return self._pd_in_layout.decode_named(raw)

    def _encode_pd(self, values: list[Any]) -> bytes:
        return self.pd_out_layout.encode(values)
