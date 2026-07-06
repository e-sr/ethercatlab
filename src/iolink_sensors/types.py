from __future__ import annotations

from typing import Literal

RegisterAccess = Literal["r", "w", "rw"]

# str — raw field name; dict — {name: {int: label}} for enum-mapped fields
FieldDef = str | dict[str, dict[int, str]]
