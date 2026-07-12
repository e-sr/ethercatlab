"""Build runtime value enums from YAML register ``fields`` maps."""

from __future__ import annotations

import re
from enum import IntEnum
from typing import Any

from .schema import RegisterSpec


def extract_enum_map(reg: RegisterSpec) -> dict[int, str] | None:
    """Return ``{code: label}`` for scalar registers with one enum field map."""
    if not reg.fields:
        return None
    for field in reg.fields:
        if not isinstance(field, dict):
            continue
        for mapping in field.values():
            if isinstance(mapping, dict) and mapping and all(isinstance(k, int) for k in mapping):
                return {int(k): str(v) for k, v in mapping.items()}
    return None


def sanitize_member_name(label: str, code: int) -> str:
    """Turn an IODD label into a valid unique Python identifier."""
    name = re.sub(r"[^\w]+", "_", label.strip())
    name = name.strip("_") or f"code_{code}"
    if name[0].isdigit():
        name = f"_{name}"
    return name


def _enum_label(self: IntEnum) -> str:
    labels: dict[int, str] = self.__class__._labels  # type: ignore[attr-defined]
    return labels.get(int(self.value), f"code:{int(self.value)}")


def _enum_from_code(cls: type[IntEnum], code: int) -> IntEnum:
    try:
        return cls(code)
    except ValueError:
        return cls._missing_(code)  # type: ignore[arg-type, return-value]


def _enum_from_label(cls: type[IntEnum], text: str) -> IntEnum:
    labels: dict[int, str] = cls._labels  # type: ignore[attr-defined]
    for code, label in labels.items():
        if label == text:
            return cls.from_code(code)  # type: ignore[attr-defined]
    raise ValueError(f"Unknown label {text!r} for {cls.__name__}")


def _enum_missing(cls: type[IntEnum], value: object) -> IntEnum:
    if not isinstance(value, int):
        raise ValueError(f"{value!r} is not a valid {cls.__name__}")
    obj = int.__new__(cls, value)
    obj._value_ = value
    return obj


def build_value_enum(class_name: str, mapping: dict[int, str]) -> type[IntEnum]:
    """Build an ``IntEnum`` subclass with ``.label`` and lookup helpers."""
    labels = dict(mapping)
    used: set[str] = set()
    members: dict[str, int] = {}
    for code, label in sorted(mapping.items()):
        base = sanitize_member_name(label, code)
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        members[name] = code

    enum_cls = IntEnum(class_name, members)  # type: ignore[call-overload]
    enum_cls._labels = labels  # type: ignore[attr-defined]
    enum_cls.label = property(_enum_label)  # type: ignore[attr-defined]
    enum_cls.from_code = classmethod(_enum_from_code)  # type: ignore[attr-defined]
    enum_cls.from_label = classmethod(_enum_from_label)  # type: ignore[attr-defined]
    enum_cls._missing_ = classmethod(_enum_missing)  # type: ignore[attr-defined]
    return enum_cls


def coerce_enum_value(enum_cls: type[IntEnum], value: Any) -> int:
    """Accept enum member, valid int code, or IODD label string."""
    labels: dict[int, str] = enum_cls._labels  # type: ignore[attr-defined]
    if isinstance(value, enum_cls):
        return int(value.value)
    if isinstance(value, int):
        if value in labels:
            return value
        raise ValueError(f"Invalid code {value} for {enum_cls.__name__}")
    if isinstance(value, str):
        return int(enum_cls.from_label(value).value)  # type: ignore[attr-defined]
    raise TypeError(f"Expected {enum_cls.__name__}, int, or str, got {type(value).__name__}")
