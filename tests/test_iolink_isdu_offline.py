"""Offline tests for IO-Link ISDU decode helpers."""

from __future__ import annotations

import struct

import pytest

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

    def read_isdu(self, index: int, subindex: int = 0, *, size: int | None = None) -> bytes:
        key = (index, subindex)
        if key not in self._data:
            raise KeyError(f"no fake ISDU data for {key}")
        raw = self._data[key]
        if size is not None and len(raw) != size:
            raise ValueError(f"expected {size} bytes, got {len(raw)}")
        return raw

    def write_isdu(self, index: int, data: bytes, subindex: int = 0) -> None:
        self.writes.append((index, subindex, bytes(data)))
        self._data[(index, subindex)] = bytes(data)


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


def test_pf2m7_apply_isdu_read_only() -> None:
    port = _FakeIsduPort({
        (16, 0): b"SMC" + b"\x00" * 61,
        (18, 0): b"PF2M771" + b"\x00" * 57,
        (1000, 0): b"\x00",
        (8000, 0): struct.pack("<f", 0.00625),
        (8010, 0): struct.pack("<f", 0.0),
    })
    dev = Pf2m7Device(flow_range_l=None)
    profile = dev.apply_isdu(port)
    assert profile.scaling == pytest.approx(0.00625)
    assert profile.unit == "L/min"
    assert port.writes == []
    assert dev.sample(
        pd_raw_s16=1000,
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
    dev = Pf2m7Device(setup=Pf2m7IsduSetup(display_unit=0), flow_range_l=None)
    profile = dev.apply_isdu(port)
    assert port.writes == [(1000, 0, b"\x00")]
    assert profile.unit == "L/min"


def test_psd4_apply_isdu_with_write() -> None:
    port = _FakeIsduPort({
        (16, 0): b"WIKA" + b"\x00" * 60,
        (18, 0): b"PSD4" + b"\x00" * 60,
        (66, 0): b"\x03",
        (67, 0): struct.pack("<f", 0.1),
        (123, 0): b"\x00",
    })
    dev = Psd4Device(setup=Psd4IsduSetup(unit_process_data=3))
    profile = dev.apply_isdu(port)
    assert port.writes == [(66, 0, b"\x03")]
    assert profile.extra["unit_process_data"] == 3
    assert dev.sample(process_value_raw14=100, ou1=True, ou2=False).value == pytest.approx(10.0)


def test_write_rejects_readonly_register() -> None:
    desc = load_descriptor("pf2m7")
    port = _FakeIsduPort({})
    with pytest.raises(ValueError, match="cannot write"):
        write_decoded_register(port, desc, "gradient_a", 1.0)
