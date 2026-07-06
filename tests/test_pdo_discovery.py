"""Tests for pdo_discovery.discover_slave using a mock adapter."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from beckhoff_devices import DeviceIdentifier, devices_from_esi
from banco_prova.adapters.pdo_discovery import discover_slave
from banco_prova.adapters.ethercat_adapter import SlaveInfo

ROOT = Path(__file__).resolve().parents[1]
EL6224_XML = ROOT / "data" / "beckhoff" / "xmls" / "Beckhoff EL6xxx.xml"


def _load_el6224():
    devices = devices_from_esi([EL6224_XML], DeviceIdentifier(type_name="EL6224", revision_no=0x00150000))
    assert len(devices) == 1
    return devices[0]


def _make_info(slave_idx: int = 0) -> SlaveInfo:
    return SlaveInfo(index=slave_idx, name="EL6224", rev=0x00150000, id_hex="0x18503052")


def _make_adapter(rx_pdo_indices: list[int], tx_pdo_indices: list[int]) -> MagicMock:
    """Build a mock adapter that returns the given PDO index lists from 0x1C12/0x1C13."""
    sm_tables = {
        0x1C12: rx_pdo_indices,
        0x1C13: tx_pdo_indices,
    }

    def read_u32(slave_idx, index, subindex):
        table = sm_tables[index]
        if subindex == 0x00:
            return len(table)
        return table[subindex - 1]

    adapter = MagicMock()
    adapter.read_u32.side_effect = read_u32
    return adapter


# ---------------------------------------------------------------------------
# Basic happy-path tests
# ---------------------------------------------------------------------------

def test_tx_pdo_state_inputs():
    """0x1A04 (DeviceState Inputs, 4 × u8) should produce u8u8u8u8 format."""
    device = _load_el6224()
    adapter = _make_adapter(rx_pdo_indices=[], tx_pdo_indices=[0x1A04])

    slave = discover_slave(adapter, _make_info(0), device)
    image = slave.process_image

    assert len(image.tx_pdos) == 1
    assert int(image.tx_pdos[0].index) == 0x1A04
    assert image.tx_offsets[0] == 0
    assert image.tx_format == "u8u8u8u8"


def test_tx_pdo_two_assigned():
    """Two TxPDOs assigned: byte offsets should be sequential."""
    device = _load_el6224()
    # 0x1A04 = 4 bytes (u8*4), 0x1A05 = 2 bytes (p8p4u1p2u1 = 16 bits)
    adapter = _make_adapter(rx_pdo_indices=[], tx_pdo_indices=[0x1A04, 0x1A05])

    slave = discover_slave(adapter, _make_info(0), device)
    image = slave.process_image

    assert len(image.tx_pdos) == 2
    assert image.tx_offsets[0] == 0
    assert image.tx_offsets[1] == 4     # 0x1A04 = 4 bytes
    assert image.tx_format == "u8u8u8u8" + "p8p4u1p2u1"


def test_rx_pdo_empty_format_skips_offset():
    """An empty-format PDO contributes 0 bytes — offset stays at 0."""
    device = _load_el6224()
    adapter = _make_adapter(rx_pdo_indices=[0x1600, 0x1601], tx_pdo_indices=[])

    slave = discover_slave(adapter, _make_info(0), device)
    image = slave.process_image

    assert len(image.rx_pdos) == 2
    # Both have empty compact_format → bit_size 0 each
    assert all(off == 0 for off in image.rx_offsets)
    assert image.rx_format == ""


def test_unknown_pdo_index_is_warned_and_skipped(caplog):
    """A PDO index not in the descriptor must produce a warning and be skipped."""
    import logging
    device = _load_el6224()
    adapter = _make_adapter(rx_pdo_indices=[], tx_pdo_indices=[0xDEAD])

    with caplog.at_level(logging.WARNING, logger="beckhoff_devices.models"):
        slave = discover_slave(adapter, _make_info(0), device)

    image = slave.process_image
    assert len(image.tx_pdos) == 0
    assert any("0xDEAD" in rec.message or "DEAD" in rec.message for rec in caplog.records)


def test_no_pdos_assigned():
    """Empty assignment → empty image, empty formats."""
    device = _load_el6224()
    adapter = _make_adapter(rx_pdo_indices=[], tx_pdo_indices=[])

    slave = discover_slave(adapter, _make_info(3), device)
    image = slave.process_image

    assert image.slave_idx == 3
    assert image.rx_format == ""
    assert image.tx_format == ""
    assert image.rx_pdos == []
    assert image.tx_pdos == []


def test_discover_slave_returns_ethercat_slave():
    """discover_slave must return an EthercatSlave with matching info and device."""
    from banco_prova.adapters.slave import EthercatSlave
    device = _load_el6224()
    adapter = _make_adapter(rx_pdo_indices=[], tx_pdo_indices=[0x1A04])
    info = _make_info(2)

    slave = discover_slave(adapter, info, device)

    assert isinstance(slave, EthercatSlave)
    assert slave.info is info
    assert slave.device is device
    assert slave.process_image.slave_idx == 2


def test_fixed_pdo_device_uses_all_descriptor_pdos():
    """When 0x1C12/0x1C13 raise (fixed-PDO device), all descriptor PDOs are used."""
    device = _load_el6224()
    adapter = MagicMock()
    adapter.read_u32.side_effect = Exception("SDO not supported")

    slave = discover_slave(adapter, _make_info(0), device)
    image = slave.process_image

    # None indices → from_assignment uses all device.rx_pdos / device.tx_pdos
    assert image.rx_pdos == list(device.rx_pdos)
    assert image.tx_pdos == list(device.tx_pdos)

