import struct

import bitstruct
import pytest

from ethercat_lab.aoe import (
    DEFAULT_MASTER_NETID, parse_aoe_error, parse_packet_error, coe_index_offset,
    COE_SLAVE_NETID_INDEX, COE_SLAVE_NETID_SUB,
)
from ethercat_lab.master import format_coe_exc
from ethercat_lab.el1xxx import EL1xx4
from ethercat_lab.el2xxx import EL2xx4
from iolink_sensors.pd_layout import PdWireLayout
from ethercat_lab.el6224 import (
    IoLinkChannelConfig,
    decode_pd_settings_byte,
    encode_pd_settings_byte,
)
from ethercat_lab.el3072 import (
    AnalogInputChannel,
    InputInterface,
    PdoMode,
    UserScaleConfig,
    LimitConfig,
    RangeErrorConfig,
    IIRFilter,
    LimitTriggerType,
    decode_limit_trigger,
)


def test_parse_aoe_iolink_isdu_error() -> None:
    msg = parse_aoe_error(0x80192B00)
    assert "0x8019" in msg
    assert "invalid parameter set" in msg


def test_parse_packet_timeout() -> None:
    assert "timeout" in parse_packet_error(4)


def test_format_coe_sdo_error() -> None:
    import pysoem

    exc = pysoem.SdoError(2, 0xF920, 1, 0x06020000, "Object does not exist in the object dictionary")
    msg = format_coe_exc(exc)
    assert "0x06020000" in msg
    assert "Object does not exist" in msg
    assert "0xf920:1" in msg.lower()


def test_write_coe_treats_pysoem_none_as_success() -> None:
    """pysoem.sdo_write returns None on success, not True."""
    from ethercat_lab.master import Master

    class _Slave:
        def sdo_write(self, index, subindex, data):
            return None

    bus = Master.__new__(Master)
    bus.initialized = True
    bus.master = type("_M", (), {"slaves": [_Slave()]})()
    bus._check_slave_index = lambda idx: None  # type: ignore[method-assign]

    result = bus.write_coe(1, 0x8000, 40, b"\x03\x00")
    assert result.error is None
    assert result.raw == b"\x03\x00"


def test_coe_index_offset() -> None:
    assert coe_index_offset(0x1018, 1) == 0x10180001


def test_iolink_index_offset() -> None:
    from ethercat_lab.aoe import iolink_index_offset
    assert iolink_index_offset(0x0018, 0) == 0x00180000


def test_coe_slave_netid_index() -> None:
    assert COE_SLAVE_NETID_INDEX == 0xF920
    assert COE_SLAVE_NETID_SUB == 1


def test_default_master_netid() -> None:
    assert len(DEFAULT_MASTER_NETID) == 6


def test_el6224_pd_settings_byte() -> None:
    assert encode_pd_settings_byte(bit_len=PdWireLayout.from_bitstruct("s14b1b1", sio=True).bit_len, sio=True) == 0x50
    layout = PdWireLayout.from_bitstruct("s16b1b1p5b1p6b1b1", sio=False)
    assert encode_pd_settings_byte(bit_len=layout.bit_len, sio=layout.sio) == 0x83
    in4 = PdWireLayout.from_frame_type("4.0", direction="in", sio=False)
    assert encode_pd_settings_byte(bit_len=in4.bit_len, sio=in4.sio) == 0x83
    out0 = PdWireLayout.from_frame_type("4.0", direction="out")
    assert encode_pd_settings_byte(bit_len=out0.bit_len, sio=out0.sio) == 0
    in2 = PdWireLayout.from_frame_type("2.2", direction="in", sio=True)
    assert encode_pd_settings_byte(bit_len=in2.bit_len, sio=in2.sio) == 0x50
    assert encode_pd_settings_byte(bit_len=16, sio=True) == 0x50
    assert encode_pd_settings_byte(bit_len=PdWireLayout.from_bytes(4).bit_len, sio=False) == 0x83
    assert encode_pd_settings_byte(bit_len=0, sio=False) == 0
    for layout in (
        PdWireLayout.from_bitstruct("s14b1b1", sio=True),
        PdWireLayout.from_bytes(4, sio=False),
        PdWireLayout(16, sio=True),
    ):
        code = encode_pd_settings_byte(bit_len=layout.bit_len, sio=layout.sio)
        bit_len, sio = decode_pd_settings_byte(code)
        assert bit_len == layout.bit_len
        assert sio == layout.sio


def test_el6224_channel_addresses() -> None:
    ch1 = IoLinkChannelConfig(
        1,
        pd_in=PdWireLayout.from_bitstruct("s14b1b1", sio=True),
    )
    ch2 = IoLinkChannelConfig(
        2,
        pd_in=PdWireLayout.from_bitstruct("s16b1b1p5b1p6b1b1", sio=False),
    )
    assert ch1.settings_index == 0x8000
    assert ch2.settings_index == 0x8010
    assert ch1.txpdo_index == 0x1A00
    assert ch2.txpdo_index == 0x1A01
    entry1 = ch1.pdo_map_entry()
    assert entry1.index == 0x6000 and entry1.subindex == 1 and entry1.length == 16
    entry2 = ch2.pdo_map_entry()
    assert entry2.index == 0x6010 and entry2.subindex == 1 and entry2.length == 32
    assert encode_pd_settings_byte(bit_len=ch1.pd_in.bit_len, sio=ch1.pd_in.sio) == 0x50
    assert encode_pd_settings_byte(bit_len=ch2.pd_in.bit_len, sio=ch2.pd_in.sio) == 0x83


def test_el6224_pdo_map_entry() -> None:
    ch = IoLinkChannelConfig(3, pd_in=PdWireLayout.from_bitstruct("s14b1b1"))
    entry = ch.pdo_map_entry()
    assert entry.index == 0x6020 and entry.subindex == 1 and entry.length == 16
    assert ch.settings_index == 0x8020
    assert ch.txpdo_index == 0x1A02
    assert ch.inputs_index == 0x6020


def test_el6224_configure_preop_requires_add_channel() -> None:
    import pytest
    from unittest.mock import MagicMock
    from ethercat_lab.el6224 import EL6224

    dev = EL6224(MagicMock(), 1)
    with pytest.raises(ValueError, match="add_channel"):
        dev.configure_preop()


def test_apply_coe_writes_error_includes_slave_and_payload() -> None:
    from ethercat_lab.master import CoeTransfer, Master, format_coe_payload

    assert format_coe_payload(b"\x00\x02") == "00 02"

    class _Slave:
        def sdo_write(self, index, subindex, data):
            raise RuntimeError("SDO abort")

    bus = Master.__new__(Master)
    bus.initialized = True
    bus.master = type("_M", (), {"slaves": [_Slave()]})()
    bus._check_slave_index = lambda idx: None  # type: ignore[method-assign]
    bus.write_coe = lambda idx, i, s, raw: CoeTransfer(  # type: ignore[method-assign]
        i, s, error="SDO abort 0x06090030 (0x800d:1)"
    )

    import pytest
    with pytest.raises(RuntimeError, match=r"slave 5 0x800d:0x11 payload=02 00 failed"):
        bus.apply_coe_writes(5, [CoeTransfer(0x800D, 0x11, raw=b"\x02\x00")])


def test_coe_entry_pack_raw_int() -> None:
    from ethercat_lab.coe import CoEDataType, CoEEntry, ObjAccess, format_coe_value

    entry = CoEEntry(17, 16, CoEDataType.DOMAIN, ObjAccess.Wpre, "Input Interface")
    assert entry.pack(14) == b"\x0e\x00"
    assert entry.pack(-100) == (-100).to_bytes(2, "little", signed=True)
    assert entry.unpack(b"\x00\x13") == 0x1300
    assert format_coe_value(entry, 0x1300) == "0x1300"


def test_coe_entry_boolean_sdo_byte() -> None:
    from ethercat_lab.coe import CoEDataType, CoEEntry, ObjAccess

    entry = CoEEntry(2, 1, CoEDataType.BOOLEAN, ObjAccess.Rop, "Overrange")
    assert entry.unpack(b"\x01") is True
    assert entry.unpack(b"\x00") is False
    assert entry.pack(True) == b"\x01"
    assert entry.pack(False) == b"\x00"


def test_el6224_channel_config_from_bytes() -> None:
    ch = IoLinkChannelConfig.from_bytes(1, pd_in_bytes=2, master_control=3)
    by_sub = {(w.index, w.subindex): w.raw for w in ch.settings_writes()}
    assert by_sub[(0x8000, 0x28)] == b"\x03\x00"
    assert ch.pdo_in_byte_len == 2


def test_el6224_settings_writes_payload_sizes() -> None:
    ch = IoLinkChannelConfig(
        1,
        pd_in=PdWireLayout.from_frame_type("2.0", direction="in"),
        master_control=3,
    )
    by_sub = {(w.index, w.subindex): w.raw for w in ch.settings_writes()}
    assert by_sub[(0x8000, 0x28)] == b"\x03\x00"
    assert by_sub[(0x8000, 0x24)] == b"\x10"
    assert by_sub[(0x8000, 0x25)] == b"\x00"
    assert ch.pdo_in_byte_len == 2


def test_el6224_port_pd_bytes() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el6224 import EL6224

    ch1 = IoLinkChannelConfig(1, pd_in=PdWireLayout.from_bitstruct("s14b1b1", sio=True))
    ch2 = IoLinkChannelConfig(2, pd_in=PdWireLayout.from_frame_type("4.0", direction="in", sio=False))
    raw = b"\xaa\xbb" + b"\x01\x02\x03\x04"
    dev = EL6224(MagicMock(), 3, include_device_state=False)
    dev.add_channel(ch1)
    dev.add_channel(ch2)
    assert dev.port_pd_bytes(1, raw) == b"\xaa\xbb"
    assert dev.port_pd_bytes(2, raw) == b"\x01\x02\x03\x04"


def test_el6224_device_port_pd_bytes() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el6224 import EL6224

    dev = EL6224(MagicMock(), 3, include_device_state=False)
    dev.add_channel(IoLinkChannelConfig(1, pd_in=PdWireLayout.from_bitstruct("s14b1b1", sio=True)))
    dev.add_channel(IoLinkChannelConfig(2, pd_in=PdWireLayout.from_frame_type("4.0", direction="in", sio=False)))
    raw = b"\xaa\xbb" + b"\x01\x02\x03\x04"
    assert dev.port_pd_bytes(1, raw) == b"\xaa\xbb"
    assert dev.port_pd_bytes(2, raw) == b"\x01\x02\x03\x04"


def test_el6224_port_pd_bytes_with_device_state_prefix() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el6224 import EL6224, DEVICE_STATE_BYTES

    dev = EL6224(MagicMock(), 3, include_device_state=True)
    dev.add_channel(IoLinkChannelConfig(1, pd_in=PdWireLayout.from_bytes(2)))
    prefix = b"\x00" * DEVICE_STATE_BYTES
    raw = prefix + b"\xaa\xbb"
    assert dev.port_pd_bytes(1, raw) == b"\xaa\xbb"


def test_decode_port_status_byte() -> None:
    from ethercat_lab.el6224 import (
        PortStatusError,
        PortStatusFlag,
        PortStatusMode,
        decode_port_status_byte,
    )

    errors, mode, flags = decode_port_status_byte(0x13)
    assert errors == PortStatusError.WATCHDOG
    assert mode == PortStatusMode.COMM_OP
    assert flags == PortStatusFlag(0)

    errors, mode, flags = decode_port_status_byte(0x0C)
    assert errors == PortStatusError(0)
    assert mode == PortStatusMode.COMM_COMSTOP
    assert flags == PortStatusFlag.PD_INVALID


def test_iolink_master_state_to_enum() -> None:
    from unittest.mock import MagicMock

    from ethercat_lab.el6224 import (
        EL6224,
        PortStatusError,
        PortStatusMode,
        _port_functional,
    )

    dev = EL6224(MagicMock(), 3, include_device_state=True)
    states = dev.iolink_master_state_to_enum({
        "dev_state_ports": {"state_ch1": 0xA0, "state_ch2": 0x03, "state_ch3": 0x03, "state_ch4": 0x00},
    })
    assert states[1][0] == PortStatusError.NO_DEVICE
    assert states[2] == (PortStatusError(0), PortStatusMode.COMM_OP, states[2][2])
    assert _port_functional(states[2])
    assert not _port_functional(states[1])


def test_el3072_configure_preop_requires_set_channel() -> None:
    import pytest
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    with pytest.raises(ValueError, match="set_channel"):
        dev.configure_preop()


def test_el3072_channel_addresses() -> None:
    ch1 = AnalogInputChannel(port=1)
    ch2 = AnalogInputChannel(port=2)
    assert ch1.advanced_index == 0x800D
    assert ch2.advanced_index == 0x801D
    assert ch1.settings_index == 0x8000
    assert ch2.settings_index == 0x8010


def test_el3072_input_interface_values() -> None:
    assert InputInterface.V_PM10 == 2
    assert InputInterface.I_0_20MA == 18
    assert InputInterface.V_PM10.to_bytes(2, "little") == b"\x02\x00"
    assert InputInterface.I_0_20MA.to_bytes(2, "little") == b"\x12\x00"


def test_el3072_user_scale_real32_only() -> None:
    ch = AnalogInputChannel(
        port=1,
        input_interface=InputInterface.V_PM10,
        user_scale=UserScaleConfig.physical(gain=2.0, offset=0.5),
    )
    by_idx = {(w.index, w.subindex): w.raw for w in ch.settings_writes()}
    assert by_idx[(0x800D, 0x11)] == b"\x02\x00"
    assert by_idx[(0x8000, 0x01)] == b"\x01"
    assert by_idx[(0x800D, 0x1C)] == struct.pack("<f", 0.5)
    assert by_idx[(0x800D, 0x1D)] == struct.pack("<f", 2.0)
    assert (0x8000, 0x11) not in by_idx
    assert (0x8000, 0x12) not in by_idx


def test_el3072_user_scale_disabled_without_config() -> None:
    ch = AnalogInputChannel(port=1, input_interface=InputInterface.V_PM10)
    by_idx = {(w.index, w.subindex): w.raw for w in ch.settings_writes()}
    assert by_idx == {(0x800D, 0x11): b"\x02\x00"}


def test_el3072_limits_filter_range_error_settings() -> None:
    ch = AnalogInputChannel(
        port=1,
        input_interface=InputInterface.I_4_20MA,
        iir_filter=IIRFilter.IIR21Hz,
        limits=LimitConfig(limit1=3.5, limit2=18.0),
        range_error=RangeErrorConfig(low=-1.0, high=99.0),
    )
    by_idx = {(w.index, w.subindex): w.raw for w in ch.settings_writes()}
    assert by_idx[(0x800D, 0x11)] == b"\x13\x00"
    assert by_idx[(0x8000, 0x06)] == b"\x01"
    assert by_idx[(0x8000, 0x15)] == b"\x04\x00"
    assert by_idx[(0x8000, 0x07)] == b"\x01"
    assert by_idx[(0x800D, 0x29)] == struct.pack("<f", 3.5)
    assert by_idx[(0x8000, 0x08)] == b"\x01"
    assert by_idx[(0x800D, 0x2A)] == struct.pack("<f", 18.0)
    assert by_idx[(0x800D, 0x27)] == struct.pack("<f", -1.0)
    assert by_idx[(0x800D, 0x28)] == struct.pack("<f", 99.0)
    ordered = [
        (w.index, w.subindex)
        for w in ch.settings_writes()
        if w.index == 0x800D and w.subindex in (0x27, 0x28, 0x29, 0x2A)
    ]
    assert ordered.index((0x800D, 0x2A)) < ordered.index((0x800D, 0x29))
    assert ordered.index((0x800D, 0x28)) < ordered.index((0x800D, 0x27))


def test_decode_limit_trigger() -> None:
    assert decode_limit_trigger(2) is LimitTriggerType.GREATER_THAN
    assert decode_limit_trigger(99) is LimitTriggerType.NONE


def test_el3072_decode_parse_limit() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.DEFAULT))
    fmt = dev.tx_pdo_assignment().pdoformat_bigendian
    raw = bitstruct.pack(fmt, 0, False, False, False, 0, 2, False, False)[::-1]
    plain = dev.decode_tx_pdo_named(raw)
    assert plain["ch1_DEFAULT"]["limit1"] == 2
    parsed = dev.decode_tx_pdo_named(raw, parse_limit=True)
    assert parsed["ch1_DEFAULT"]["limit1"] is LimitTriggerType.GREATER_THAN


@pytest.mark.skip(reason="el3072 API refactored to decode_pdo_named")
def test_int16_to_engineering_v0_10() -> None:
    assert int16_to_engineering(30518, InputInterface.V_0_10) == pytest.approx(10.0)
    assert int16_to_engineering(26682, InputInterface.V_0_10) == pytest.approx(8.744, rel=1e-3)


@pytest.mark.skip(reason="el3072 API refactored to decode_pdo_named")
def test_el3072_value_from_port_mixed_pdo() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.DEFAULT, input_interface=InputInterface.V_0_10))
    dev.set_channel(AnalogInputChannel(port=2, pdo_mode=PdoMode.DEFAULT_REAL32))
    assert dev.value_from_port(1, {"value_i16": 30518}) == pytest.approx(10.0)
    assert dev.value_from_port(2, {"value_f32": 4.5}) == pytest.approx(4.5)


def test_el3072_pdo_assignments_default() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1))
    assign = dev.tx_pdo_assignment()
    assert assign is not None
    assert assign.pdo_indices() == [0x1A00]


def test_el3072_pdo_assignments_compact() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.COMPACT))
    dev.set_channel(AnalogInputChannel(port=2, pdo_mode=PdoMode.COMPACT))
    assign = dev.tx_pdo_assignment()
    assert assign is not None
    assert assign.pdo_indices() == [0x1A01, 0x1A03]


def test_el3072_pdo_assignments_with_cycle_counters() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.DEFAULT_REAL32, cycle_counters=True))
    dev.set_channel(AnalogInputChannel(port=2, pdo_mode=PdoMode.DEFAULT_REAL32, cycle_counters=True))
    assign = dev.tx_pdo_assignment()
    assert assign is not None
    assert assign.pdo_indices() == [0x1A10, 0x1A12, 0x1A20, 0x1A22]


def test_el3072_decode_named_real32_two_channels() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.DEFAULT_REAL32))
    dev.set_channel(AnalogInputChannel(port=2, pdo_mode=PdoMode.DEFAULT_REAL32))
    fmt = dev.tx_pdo_assignment().pdoformat_bigendian
    raw = bitstruct.pack(fmt, 2.0, *[False] * 8, 1.0, *[False] * 8)[::-1]
    named = dev.decode_pdo_named(raw)
    assert named["ch1_DEFAULT_REAL32"]["value_f32"] == pytest.approx(1.0)
    assert named["ch2_DEFAULT_REAL32"]["value_f32"] == pytest.approx(2.0)


def test_el3072_decode_compact() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.COMPACT))
    raw = bitstruct.pack("s16", 0x1234)[::-1]
    assert dev.decode_pdo_named(raw)["ch1_COMPACT"]["value_i16"] == 0x1234


def test_el3072_decode_standard() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.DEFAULT))
    fmt = dev.tx_pdo_assignment().pdoformat_bigendian
    raw = bitstruct.pack(fmt, 0x1234, *[False] * 8)[::-1]
    assert dev.decode_pdo_named(raw)["ch1_DEFAULT"]["value_i16"] == 0x1234


def test_pdo_byte_lens() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    def byte_len(mode: PdoMode) -> int:
        dev = EL3072(MagicMock(), 1)
        dev.set_channel(AnalogInputChannel(port=1, pdo_mode=mode))
        return dev.expected_pdo_byte_len()

    assert byte_len(PdoMode.DEFAULT) == 4
    assert byte_len(PdoMode.COMPACT) == 2
    assert byte_len(PdoMode.DEFAULT_REAL32) == 6
    assert byte_len(PdoMode.COMPACT_REAL32) == 4


def test_el3072_clear_channel() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=PdoMode.COMPACT))
    dev.clear_channel(1)
    assert dev.channels == []
    assert dev.tx_pdo_assignment() is None


def test_el3072_coe_only_no_pdo() -> None:
    from unittest.mock import MagicMock
    from ethercat_lab.el3072 import EL3072

    dev = EL3072(MagicMock(), 1)
    dev.set_channel(AnalogInputChannel(port=1, pdo_mode=None))
    assert dev.tx_pdo_assignment() is None
    assert dev.coe_setup_writes()
    with pytest.raises(RuntimeError, match="no tx PDO"):
        dev.decode_tx_pdo_named(b"")


@pytest.mark.skip(reason="Master.read_input removed")
def test_read_input_requires_safeop_or_op() -> None:
    import pysoem

    bus = _state_bus(pysoem.PREOP_STATE)
    bus.get_slave = lambda idx: type("_S", (), {"input": b"\x01"})()  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="read_input"):
        bus.read_input(1)


def _state_bus(state: int):
    """Minimal pysoem master mock for state transition tests."""
    from ethercat_lab.master import Master

    class _PysoemMaster:
        def __init__(self, initial: int) -> None:
            self.state = initial
            self.config_map_calls = 0

        def read_state(self) -> int:
            return self.state

        def write_state(self) -> None:
            pass

        def state_check(self, target: int, _timeout: int) -> int:
            self.state = target
            return target

        def config_map(self) -> int:
            self.config_map_calls += 1
            return 16

        def send_processdata(self) -> None:
            pass

        def receive_processdata(self) -> None:
            pass

    bus = Master.__new__(Master)
    bus.initialized = True
    bus.master = _PysoemMaster(state)
    bus.cycle = lambda: None  # type: ignore[method-assign, assignment]
    return bus


def test_to_safeop_calls_config_map_once() -> None:
    import pysoem

    bus = _state_bus(pysoem.PREOP_STATE)
    assert bus.to_safeop() is True
    assert bus.master.config_map_calls == 1
    assert bus.to_safeop() is False
    assert bus.master.config_map_calls == 1


def test_to_safeop_from_op_is_noop() -> None:
    import pysoem

    bus = _state_bus(pysoem.OP_STATE)
    assert bus.to_safeop() is False
    assert bus.master.config_map_calls == 0


def test_to_op_from_preop_raises() -> None:
    import pytest
    import pysoem

    bus = _state_bus(pysoem.PREOP_STATE)
    with pytest.raises(RuntimeError, match="OP"):
        bus.to_op()


def test_to_op_cycles_before_transition() -> None:
    import pysoem

    bus = _state_bus(pysoem.SAFEOP_STATE)
    cycled = False

    def _cycle() -> None:
        nonlocal cycled
        cycled = True

    bus.cycle = _cycle  # type: ignore[method-assign]
    assert bus.to_op() is True
    assert cycled
    assert bus.master.state == pysoem.OP_STATE
    assert bus.to_op() is False


def test_to_preop_entry_from_safeop() -> None:
    import pysoem

    bus = _state_bus(pysoem.SAFEOP_STATE)
    flags: list[str] = []
    bus._on_enter_preop = lambda: flags.append("enter")  # type: ignore[method-assign]
    assert bus.to_preop() is True
    assert flags == ["enter"]
    assert bus.master.state == pysoem.PREOP_STATE


def test_to_preop_already_preop_runs_hook_no_entry() -> None:
    import pysoem

    bus = _state_bus(pysoem.PREOP_STATE)
    flags: list[str] = []
    bus._on_enter_preop = lambda: flags.append("enter")  # type: ignore[method-assign]
    assert bus.to_preop(lambda: flags.append("hook")) is False
    assert flags == ["hook"]


def test_set_bus_state_raises_when_not_reached() -> None:
    import pytest
    import pysoem

    bus = _state_bus(pysoem.PREOP_STATE)

    def _fail_state_check(_target: int, _timeout: int) -> int:
        return pysoem.PREOP_STATE

    bus.master.state_check = _fail_state_check  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="Failed state transition"):
        bus.to_safeop()


def test_el1xx4_channels_follow_pdo_bit_order() -> None:
    for channel in range(4):
        sample = EL1xx4.from_bytes(bytes([1 << channel]))
        assert sample.to_list() == [i == channel for i in range(4)]
        assert sample.to_hex() == 1 << channel


def test_el2xx4_channels_follow_pdo_bit_order() -> None:
    for channel in range(4):
        value = 1 << channel
        sample = EL2xx4.from_hex(value)
        assert sample.to_list() == [i == channel for i in range(4)]
        # Wire nibble is active-low vs logical channels.
        assert sample.pack() == bytes([(~value) & 0x0F])
        assert EL2xx4.from_bytes(bytes([(~value) & 0x0F])) == sample
        assert sample.to_hex() == value
