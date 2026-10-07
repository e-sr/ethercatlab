"""Esempio: 4 sensori IO-Link su EL6224.

Hardware (stesso banco di ``func.py``):
  slave 2 = EL6224 — porta 1 PF2M7, porte 2-3 PSD4, porta 4 IMi54D

Workflow
--------
1. **PRE-OP** — ``init_iolink_master()``: recipe CoE porte + ``aoe_init``
2. **SAFE-OP** — ``apply_sensors()``: ISDU write (opz.) → read identità/scaling
3. **OP** — ``read_sensors()``: PDO ciclico

Run REPL::

    pdm run eci enp2s0 --macros example/iolink_three.py --merge-macros-ns

    init_and_check_sensors_via_isdu(iolink)
    bus.to_op()
    read_sensors(bus, iolink)

    # oppure demo completa:
    run_demo(bus, cycles=10, period=1.0)

Run standalone::

    pdm run python example/iolink_three.py enp2s0
    pdm run python example/iolink_three.py enp2s0 -n 20 -p 0.1
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ethercat_lab import Master
from ethercat_lab.el6224 import EL6224, IoLinkPortConfig
from iolink_sensors.imi54d import Imi54dDevice, Imi54dIsduSetup, Imi54dSample
from iolink_sensors.pf2m7 import Pf2m7Device, Pf2m7IsduSetup, Pf2m7Sample
from iolink_sensors.psd4 import Psd4Device, Psd4IsduSetup, Psd4Sample

if TYPE_CHECKING:
    pass

# Injected by ``eci --macros`` before module exec; ``None`` when imported as library/script.
bus: Master | None = None

EL6224_SLAVE = 2
devices: dict[int, Pf2m7Device | Psd4Device | Imi54dDevice] = {
        1: Pf2m7Device(setup=Pf2m7IsduSetup(display_unit=0)),
        2: Psd4Device(setup=Psd4IsduSetup()),
        3: Psd4Device(setup=Psd4IsduSetup()),
        4: Imi54dDevice(setup=Imi54dIsduSetup())
    }

def init_iolink_master(master: Master) -> EL6224:
    iolinkmaster = EL6224(master, EL6224_SLAVE)
    for port,d in devices.items():
        layout = d.pd_in_layout
        if layout is None:
            raise ValueError(f"Port {port}: device has no PD input layout")
        iolinkmaster.set_port(IoLinkPortConfig(port=port, pd_in=layout))
    # configura il master
    iolinkmaster.configure_preop(aoe_init=True)
    return iolinkmaster


def init_and_check_sensors_via_isdu(
    iolinkmaster: EL6224,
) -> None:
    for port,d in devices.items():
        isdu = iolinkmaster.isdu_port(port)
        try:
            vendor, product = d.check_port(isdu)
        except Exception as e:
            print(f"port {port}: {e}")
        else:
            print(f"port {port}: {vendor} / {product}")
            d.apply_isdu(isdu, verify=False)

def read_sensors(
    master: Master,
    iolinkmaster: EL6224,
) -> dict[int, Pf2m7Sample | Psd4Sample | Imi54dSample]:
    """Fase 3: lettura PDO — bus in OP (o SAFE-OP con almeno un ciclo)."""
    master.cycle()
    pd = iolinkmaster.decode_tx_pdo_named(master.pdoin(EL6224_SLAVE))
    sample: dict[int, Pf2m7Sample | Psd4Sample | Imi54dSample] = {}
    for port, d in devices.items():
        field = f"port{port}_iolink_pd"
        sample[port] = d.sample(**pd[field])  # type: ignore[call-arg]
    return sample


def format_sample(sample: dict[int, Pf2m7Sample | Psd4Sample | Imi54dSample]) -> str:
    parts = [f"p{p}={s.value:7.3f} {s.unit}" for p, s in sorted(samples.items())]
    return "  ".join(parts)



