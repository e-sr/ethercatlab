"""Hardware-in-the-loop tests for EtherCAT bus discovery and PDO reading.

These tests require real hardware. Run with:

    ETHERCAT_IFACE=enp49s0 pytest tests/test_hw_ethercat.py -v

The bus goes through the full PRE-OP → OP lifecycle in session scope, so all
tests in this file share the same adapter and bus state.
"""
from __future__ import annotations

import pytest

from banco_prova.adapters.slave import EthercatSlave
from bitstruct import unpack
import logging 
pytestmark = pytest.mark.hw


# ---------------------------------------------------------------------------
# PRE-OP: discovery
# ---------------------------------------------------------------------------

def test_bus_has_slaves(hw_adapter: EthercatMasterAdapter) -> None:
    """At least one slave must be visible on the bus."""
    slaves = hw_adapter.slaveinfo()
    print(f"Found {len(slaves)} slaves on the bus:")
    for s in slaves:
        print(f"  Slave {s.index}: {s.name} (rev 0x{s.rev:08X}, id {s.id_hex})")
    assert slaves, "No EtherCAT slaves found — check cable and interface"


def test_all_slaves_have_descriptors(hw_discovered: list[EthercatSlave]) -> None:
    """Every slave on the bus must have a matching YAML descriptor."""
    assert hw_discovered, "No slaves with descriptors found"


def test_discovered_process_images(hw_discovered: list[EthercatSlave]) -> None:
    """Each discovered slave must have a coherent process image."""
    for slave in hw_discovered:
        img = slave.process_image
        assert img.slave_idx == slave.info.index
        # rx/tx format must be valid bitstruct (compile would have raised in __post_init__)
        # Check that offsets list length matches PDO count
        assert len(img.rx_offsets) == len(img.rx_pdos)
        assert len(img.tx_offsets) == len(img.tx_pdos)

def test_discovered_slaves_have_accessible_obj(hw_adapter:EthercatMasterAdapter,hw_discovered: list[EthercatSlave]) -> None:
    """Each discovered slave with obj list should have the list accessible."""
    registri_falliti = []
    registri_testati = []
    for slave in hw_discovered:
        for obj in slave.device.objects:
            rawval=[]
            for field in obj.fields:
                try:
                    rawval.append(hw_adapter.coe_read(slave.info.index,obj.index , field.subindex))
                except Exception as e:
                    registri_falliti.append(f"Slave ({slave.info.name}): SDO {obj.index:#06x} sub {field.subindex:#04x} read failed with error: {e}")
                    break
            #unpacking del valore letto per verificare che sia coerente con il formato atteso
            if rawval and obj.bitstruct_format:
                try:
                    unpacked = unpack(obj.bitstruct_format, b"".join(rawval))
                    registri_testati.append(f"Slave ({slave.info.name}): SDO {obj.index:#06x} unpacked successfully with values: {unpacked}")
                except Exception as e:
                    registri_falliti.append(f"Slave ({slave.info.name}): SDO {obj.index:#06x} unpack failed with error: {e}")           
    # 3. Validazione finale dopo aver girato tutti i registri
    if registri_falliti:
        # Logghiamo l'errore per i file di log
        logging.error("Unpack falliti per i seguenti registri:\n%s", "\n".join(registri_falliti))   
        
        # Il test fallisce qui, mostrando la lista completa a schermo
        report_errori = "\n".join(registri_falliti)
        assert False, f"L'unpack è andato in crash sui seguenti registri:\n{report_errori}"

def test_assignment_writes_well_formed(hw_discovered: list[EthercatSlave]) -> None:
    """assignment_writes() must produce a write-0 / entries / write-count sequence."""
    for slave in hw_discovered:
        ops = slave.process_image.assignment_writes()
        # 4 ops minimum: clear+set for 0x1C12, clear+set for 0x1C13 (even if no PDOs)
        assert len(ops) >= 4
        sm_indices = {op.index for op in ops}
        assert 0x1C12 in sm_indices
        assert 0x1C13 in sm_indices


# ---------------------------------------------------------------------------
# PRE-OP → OP transition
# ---------------------------------------------------------------------------

def test_bus_reaches_op(hw_operational: list[EthercatSlave]) -> None:
    """Bus must transition to OP state without errors (fixture raises on failure)."""
    assert hw_operational  # fixture reaching here means transition succeeded


# ---------------------------------------------------------------------------
# OP: PDO reads
# ---------------------------------------------------------------------------

PDO_READ_CYCLES = 20


def test_read_pdo_cycles(hw_adapter: EthercatMasterAdapter, hw_operational: list[EthercatSlave]) -> None:
    """Bus must sustain PDO read cycles in OP state."""
    for cycle in range(PDO_READ_CYCLES):
        wkc = hw_adapter.read_process_data_once()
        assert wkc >= 0, f"Negative working counter on cycle {cycle}: {wkc}"

#skip
@pytest.mark.skip(reason="Requires manual verification of unpacked values")
def test_unpack_tx_process_data(hw_adapter: EthercatMasterAdapter, hw_operational: list[EthercatSlave]) -> None:
    """TxPDO data must be unpackable using the compiled bitstruct format."""
    import pysoem

    hw_adapter.read_process_data_once()
    slaves_raw = hw_adapter._require_slaves()

    for slave in hw_operational:
        img = slave.process_image
        if img.tx_compiled is None:
            continue  # no TxPDOs — skip

        raw = slaves_raw[slave.info.index].input
        if not raw:
            continue

        expected_bytes = img.tx_compiled.calcsize() // 8
        assert len(raw) >= expected_bytes, (
            f"Slave {slave.info.index} ({slave.info.name}): "
            f"input buffer {len(raw)} bytes < expected {expected_bytes}"
        )
        values = img.tx_compiled.unpack(raw[:expected_bytes])
        assert values is not None
