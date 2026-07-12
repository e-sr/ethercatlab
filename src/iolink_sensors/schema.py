from __future__ import annotations

from enum import IntEnum
from typing import Any

import bitstruct
from pydantic import BaseModel, ConfigDict, Field

from .types import FieldDef, RegisterAccess


class RegisterSpec(BaseModel):
    index: int
    subindex: int = 0
    access: RegisterAccess = "r"
    format: str
    fields: list[FieldDef] = Field(default_factory=list)


class PdFrameFieldSpec(BaseModel):
    typeprefix: str
    length: int
    name: str

    @property
    def typestr(self) -> str:
        return self.typeprefix + str(self.length)


class PdFrameSpec(BaseModel):
    fields: list[PdFrameFieldSpec] = Field(default_factory=list)

class PdSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    frame_type: str | None = None
    input: PdFrameSpec | None = Field(default=None, alias="in")
    output: PdFrameSpec | None = Field(default=None, alias="out")


class SensorDescriptor(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    meta: dict[str, Any] = Field(default_factory=dict)
    pd: PdSpec
    registers: dict[str, RegisterSpec]
    system_commands: dict[str, int] = Field(default_factory=dict)
    register_enums: dict[str, type[IntEnum]] = Field(default_factory=dict)
