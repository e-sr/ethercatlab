"""Backward-compatible re-exports. Prefer direct imports from submodules."""

from .device import DeviceBase
from .pd_layout import PdWireLayout
from .schema import PdFrameFieldSpec, PdFrameSpec, PdSpec, RegisterSpec, SensorDescriptor
from .types import FieldDef, RegisterAccess

__all__ = [
    "DeviceBase",
    "FieldDef",
    "PdFrameFieldSpec",
    "PdFrameSpec",
    "PdWireLayout",
    "PdSpec",
    "RegisterAccess",
    "RegisterSpec",
    "SensorDescriptor",
]
