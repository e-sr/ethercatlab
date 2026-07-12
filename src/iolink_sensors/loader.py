from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from iolink_sensors.models import SensorDescriptor
from iolink_sensors.register_enum import build_value_enum, extract_enum_map


DESCRIPTORS_DIR = Path(__file__).parent / "descriptors"
_STANDARD_FILE = DESCRIPTORS_DIR / "iolink_standard.yaml"


def _load_raw(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(base: dict, overlay: dict) -> dict:
    """Merge *overlay* onto *base*.

    ``registers`` and ``system_commands`` are dict-merged (overlay wins on
    key conflict). All other top-level keys are replaced by the overlay value.
    """
    result = dict(base)
    for key, val in overlay.items():
        if key in ("registers", "system_commands") and key in result:
            result[key] = {**result[key], **val}
        else:
            result[key] = val
    return result


def _attach_register_enums(desc: SensorDescriptor) -> SensorDescriptor:
    sensor_id = desc.meta.get("id", "sensor")
    enums = {}
    for reg_name, reg in desc.registers.items():
        mapping = extract_enum_map(reg)
        if mapping:
            enums[reg_name] = build_value_enum(f"{sensor_id}_{reg_name}", mapping)
    desc.register_enums = enums
    return desc


@lru_cache(maxsize=32)
def load_descriptor(name: str) -> SensorDescriptor:
    base = _load_raw(_STANDARD_FILE)
    sensor = _load_raw(DESCRIPTORS_DIR / f"{name}.yaml")
    data = _merge(base, sensor)
    return _attach_register_enums(SensorDescriptor.model_validate(data))
