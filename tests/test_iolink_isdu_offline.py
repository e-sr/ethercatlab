"""Offline tests for IO-Link ISDU decode helpers."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from ethercat_lab.aoe import parse_aoe_error
from iolink_sensors.isdu import (
    assert_product_matches,
    decode_register_value,
    encode_register_value,
    register_byte_size,
    write_decoded_register,
)
from iolink_sensors.loader import load_descriptor
from iolink_sensors.pf2m7 import Pf2m7Device, Pf2m7IsduSetup
from iolink_sensors.psd4 import Psd4Device, Psd4IsduSetup
from iolink_sensors.schema import RegisterSpec


class _FakeIsduPort:
    def __init__(self, data: dict[tuple[int, int], bytes]) -> None:
        self._data = dict(data)
        self.writes: list[tuple[int, int, bytes]] = []

    def read_isdu(self, index: int, subindex: int = 0, *, size: int | None = None, **_: Any) -> bytes:
        key = (index, subindex)
        if key not in self._data:
            raise KeyError(f"no fake ISDU data for {key}")
        raw = self._data[key]
        if size is not None:
            if len(raw) < size:
                raise ValueError(f"expected at least {size} bytes, got {len(raw)}")
            return raw[:size]
        return raw

    def write_isdu(self, index: int, data: bytes, subindex: int = 0) -> None:
        self.writes.append((index, subindex, bytes(data)))
        self._data[(index, subindex)] = bytes(data)


def test_parse_aoe_error_11000700() -> None:
    msg = parse_aoe_error(0x11000700)
    assert "not in a ready state" in msg


def test_register_byte_size_f32() -> None:
    reg = RegisterSpec(index=67, format="<f32")
    assert register_byte_size(reg) == 4


def test_decode_text_register() -> None:
    reg = RegisterSpec(index=18, format="t512")
    raw = b"PF2M771-01\x00" + b"\x00" * 53
    assert decode_register_value(reg, raw) == "PF2M771-01"


def test_encode_u8() -> None:
    reg = RegisterSpec(index=1000, format="u8", access="rw")
    assert encode_register_value(reg, 1) == b"\x01"


def test_assert_product_matches() -> None:
    desc = load_descriptor("pf2m7")
    assert_product_matches(desc, "SMC PF2M771")
    with pytest.raises(ValueError, match="Unexpected product"):
        assert_product_matches(desc, "TotallyOther")


def test_assert_product_matches_psd4() -> None:
    from iolink_sensors.isdu import assert_product_matches
    from iolink_sensors.loader import load_descriptor

    desc = load_descriptor("psd4")
    assert_product_matches(desc, "PSD-4")
    with pytest.raises(ValueError, match="Unexpected product"):
        assert_product_matches(desc, "TotallyOther")


def test_device_check_port() -> None:
    from iolink_sensors.pf2m7 import Pf2m7Device
    from iolink_sensors.psd4 import Psd4Device

    pf2_port = _FakeIsduPort({
        (16, 0): b"SMC" + b"\x00" * 61,
        (18, 0): b"PF2M771" + b"\x00" * 57,
    })
    vendor, product = Pf2m7Device().check_port(pf2_port)
    assert vendor == "SMC"
    assert product == "PF2M771"

    psd_port = _FakeIsduPort({
        (16, 0): b"WIKA" + b"\x00" * 60,
        (18, 0): b"PSD-4" + b"\x00" * 60,
    })
    vendor, product = Psd4Device().check_port(psd_port)
    assert vendor == "WIKA"
    assert product == "PSD-4"

    with pytest.raises(ValueError, match="Unexpected product"):
        Psd4Device().check_port(pf2_port)


def test_pf2m7_apply_isdu_read_only() -> None:
    port = _FakeIsduPort({
        (16, 0): b"SMC" + b"\x00" * 61,
        (18, 0): b"PF2M771" + b"\x00" * 57,
        (1000, 0): b"\x00",
        (8000, 0): struct.pack("<f", 0.00625),
        (8010, 0): struct.pack("<f", 0.0),
    })
    dev = Pf2m7Device()
    dev.apply_isdu(port)
    assert dev.scaling == pytest.approx(0.00625)
    assert dev.unit == "L/min"
    assert port.writes == []
    assert dev.sample(
        process_value=1000,
        error_diag=False,
        fixed_output=False,
        _pad1=False,
        meas_diag=False,
        _pad2=False,
    ).value == pytest.approx(6.25)


def test_pf2m7_apply_isdu_with_write() -> None:
    port = _FakeIsduPort({
        (16, 0): b"SMC" + b"\x00" * 61,
        (18, 0): b"PF2M771" + b"\x00" * 57,
        (1000, 0): b"\x01",
        (8000, 0): struct.pack("<f", 0.00625),
        (8010, 0): struct.pack("<f", 0.0),
    })
    dev = Pf2m7Device(setup=Pf2m7IsduSetup(display_unit=0))
    dev.apply_isdu(port)
    assert port.writes == [(1000, 0, b"\x00")]
    assert dev.unit == "L/min"


def test_psd4_apply_isdu_with_write() -> None:
    port = _FakeIsduPort({
        (16, 0): b"WIKA" + b"\x00" * 60,
        (18, 0): b"PSD4" + b"\x00" * 60,
        (66, 0): b"\x03",
        (67, 0): struct.pack("<f", 0.1),
        (68, 0): b"\x00\x00",
        (69, 0): b"\xe8\x03",
        (123, 0): b"\x00",
    })
    dev = Psd4Device(setup=Psd4IsduSetup(unit_process_data=3))
    dev.apply_isdu(port)
    assert port.writes == [(66, 0, b"\x03")]
    assert dev.unit == "kPa"
    assert dev.sample(process_value=100, ou1=True, ou2=False).value == pytest.approx(10.0)


def test_write_rejects_readonly_register() -> None:
    desc = load_descriptor("pf2m7")
    port = _FakeIsduPort({})
    with pytest.raises(ValueError, match="cannot write"):
        write_decoded_register(port, desc.registers["gradient_a"], "gradient_a", 1.0)


def test_decode_register_enum() -> None:
    desc = load_descriptor("psd4")
    reg = desc.registers["unit_process_data"]
    enum_cls = desc.register_enums["unit_process_data"]
    member = decode_register_value(reg, b"\x03", enum_cls=enum_cls)
    assert member.value == 3
    assert member.label == "kPa"


def test_encode_register_enum() -> None:
    desc = load_descriptor("psd4")
    reg = desc.registers["unit_process_data"]
    enum_cls = desc.register_enums["unit_process_data"]
    member = enum_cls.from_code(3)
    assert encode_register_value(reg, member, enum_cls=enum_cls) == b"\x03"
    assert encode_register_value(reg, "kPa", enum_cls=enum_cls) == b"\x03"
    assert encode_register_value(reg, 3, enum_cls=enum_cls) == b"\x03"
    with pytest.raises(ValueError, match="Invalid code"):
        encode_register_value(reg, 99, enum_cls=enum_cls)


def test_device_register_and_command_enums() -> None:
    from iolink_sensors.device import register_address, split_register_address

    dev = Psd4Device()
    assert dev.Registers.gradient.value == register_address(0x43)
    assert split_register_address(dev.Registers.gradient.value) == (0x43, 0)
    assert dev.Commands.reset_high_pressure.value == 160
    assert dev.read_reg(
        _FakeIsduPort({(0x43, 0): struct.pack("<f", 0.1)}),
        dev.Registers.gradient,
    ) == pytest.approx(0.1)
