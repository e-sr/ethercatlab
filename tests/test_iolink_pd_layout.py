import bitstruct

from iolink_sensors.loader import load_descriptor
from iolink_sensors.models import DeviceBase, PdWireLayout
from iolink_sensors.psd4 import Psd4Device


def test_unpack_pack_psd4() -> None:
    dev = Psd4Device()
    layout = dev.pd_in_layout
    raw = bitstruct.pack("s14b1b1", 100, False, True)  # ou2, ou1
    parsed = layout.unpack(raw)
    assert parsed["process_value_raw14"] == 100
    assert parsed["ou2"] is False
    assert parsed["ou1"] is True
    assert dev.parse_pd(raw) == parsed


def test_device_base_delegates_to_layout() -> None:
    class _Dev(DeviceBase):
        pass

    desc = load_descriptor("pf2m7")
    dev = _Dev(desc)
    assert dev.pd_in_bytes == dev.pd_in_layout.byte_len
    assert dev.pd_in_layout.format == desc.pd.input.format  # type: ignore[union-attr]
    assert len(desc.pd.input.fields) == 8  # type: ignore[union-attr]


def test_pd_frame_spec_format_helpers() -> None:
    desc = load_descriptor("pf2m7")
    frame = desc.pd.input  # type: ignore[union-attr]
    assert frame.format == "s16b1b1p5b1p6b1b1"
    assert frame.format_reversed() == "b1b1p6b1p5b1b1s16"
    assert frame.format_bigendian() == ">b1b1p6b1p5b1b1s16"
    assert frame.with_reversed_fields().format == frame.format_reversed()


def test_codec_shared_by_format() -> None:
    a = PdWireLayout.from_bitstruct("s14b1b1")
    b = PdWireLayout.from_bitstruct("s14b1b1")
    assert a._codec_for("s14b1b1") is b._codec_for("s14b1b1")
