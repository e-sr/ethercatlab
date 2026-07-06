from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from iolink_sensors.models import SensorDescriptor


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


@lru_cache(maxsize=32)
def load_descriptor(name: str) -> SensorDescriptor:
    base = _load_raw(_STANDARD_FILE)
    sensor = _load_raw(DESCRIPTORS_DIR / f"{name}.yaml")
    data = _merge(base, sensor)
    return SensorDescriptor.model_validate(data)
