import bitstruct

from ethercat_lab.pdo import PdoMapEntry, PdoMapping, RxPdoAssignment, TxPdoAssignment


def test_pdo_mapping_single_entry_writes() -> None:
    entry = PdoMapEntry(index=0x6000, subindex=1, length=16, name="ch1_pd")
    m = PdoMapping(index=0x1A00, entries=[entry])
    writes = m.to_coe_writes()
    assert len(writes) == 3
    assert (writes[0].index, writes[0].subindex, writes[0].raw) == (0x1A00, 0, b"\x00")
    assert writes[1].index == 0x1A00 and writes[1].subindex == 1
    assert writes[1].raw == bitstruct.pack("u16u8u8", 0x6000, 1, 16)[::-1]
    assert (writes[2].index, writes[2].subindex, writes[2].raw) == (0x1A00, 0, b"\x01")


def test_tx_pdo_assignment_writes() -> None:
    items = [
        ("ch1", PdoMapping(index=0x1A00, entries=[PdoMapEntry(0x6000, 1, 16, name="ch1_pd")])),
        ("ch2", PdoMapping(index=0x1A01, entries=[PdoMapEntry(0x6010, 1, 16, name="ch2_pd")])),
    ]
    assign = TxPdoAssignment.from_mappings(items)
    writes = assign.to_coe_writes()
    assign_writes = [w for w in writes if w.index == 0x1C13]
    assert assign_writes[0].raw == b"\x00"
    assert assign_writes[1].raw == (0x1A00).to_bytes(2, "little")
    assert assign_writes[2].raw == (0x1A01).to_bytes(2, "little")
    assert assign_writes[3].raw == b"\x02"


def test_rx_pdo_assignment_index() -> None:
    assign = RxPdoAssignment.from_mappings([
        ("out1", PdoMapping(index=0x1600, entries=[PdoMapEntry(0x7000, 1, 1, name="out1")])),
    ])
    assert assign.assign_coe_index == 0x1C12
    assert assign.to_coe_writes()[-1].raw == b"\x01"


def test_tx_pdo_assignment_skips_non_writable_map_coe_writes() -> None:
    items = [
        ("fixed", PdoMapping(index=0x1A80, entries=[PdoMapEntry(0xF100, 1, 8, "u", name="s")], writable=False)),
        ("dyn", PdoMapping(index=0x1A00, entries=[PdoMapEntry(0x6000, 1, 16, name="pd")], writable=True)),
    ]
    assign = TxPdoAssignment.from_mappings(items)
    map_writes = [w for w in assign.to_coe_writes() if w.index in (0x1A80, 0x1A00)]
    assert all(w.index == 0x1A00 for w in map_writes)


def test_tx_pdo_assignment_decode_named() -> None:
    items = [
        ("ch1", PdoMapping(index=0x1A01, entries=[PdoMapEntry(0x6000, 0x11, 16, "s", name="value_i16")])),
    ]
    assign = TxPdoAssignment.from_mappings(items)
    raw = bitstruct.pack("s16", 0x1234)[::-1]
    assert assign.decode_named(raw)["ch1"]["value_i16"] == 0x1234
