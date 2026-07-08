"""Esempio minimale: 3 sensori IO-Link su EL6224.

Hardware (stesso banco di ``func.py``):
  slave 3 = EL6224 — porta 1 PF2M7, porte 2-3 PSD4

Workflow
--------
1. **PRE-OP** — ``init_stack()``: recipe CoE canali + ``aoe_init``
2. **SAFE-OP** — ``apply_sensors()``: ISDU write (opz.) → read identità/scaling
3. **OP** — ``read_sensors()``: PDO ciclico

Run REPL::

    pdm run eci enp2s0 --macros example/iolink_three.py --merge-macros-ns

    apply_sensors(bus, iolink, channels)
    bus.to_op()
    read_sensors(bus, iolink, channels)

    # oppure demo completa:
    run_demo(bus, cycles=10, period=0.1)

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

from ethercat_lab import IOLinkIsduChannel, Master
from ethercat_lab.el6224 import EL6224, IoLinkChannelConfig
from iolink_sensors.isdu import SensorIsduProfile
from iolink_sensors.pf2m7 import Pf2m7Device, Pf2m7IsduSetup, Pf2m7Sample
from iolink_sensors.psd4 import Psd4Device, Psd4IsduSetup, Psd4Sample

if TYPE_CHECKING:
    pass

# Injected by ``eci --macros`` before module exec; ``None`` when imported as library/script.
bus: Master | None = None

EL6224_SLAVE = 3


@dataclass(slots=True)
class SensorChannel:
    port: int
    device: Pf2m7Device | Psd4Device


@dataclass(slots=True)
class SensorSnapshot:
    pf2m7: Pf2m7Sample
    psd4_p2: Psd4Sample
    psd4_p3: Psd4Sample


def make_channels(ports: tuple[int, ...] = (1, 2, 3)) -> list[SensorChannel]:
    factory: dict[int, Pf2m7Device | Psd4Device] = {
        1: Pf2m7Device(setup=Pf2m7IsduSetup(display_unit=0)),
        2: Psd4Device(),
        3: Psd4Device(),
    }
    return [SensorChannel(port, factory[port]) for port in ports]


def register_channels(iolink: EL6224, channels: list[SensorChannel]) -> None:
    for ch in channels:
        layout = ch.device.pd_in_layout
        if layout is None:
            raise ValueError(f"Port {ch.port}: device has no PD input layout")
        iolink.set_channel(IoLinkChannelConfig(port=ch.port, pd_in=layout))


def setup_preop(iolink: EL6224) -> None:
    """Fase 1: CoE/AoE — eseguita in PRE-OP da ``configure_preop``."""
    iolink.configure_preop(aoe_init=True)


def init_stack(master: Master, ports: tuple[int, ...] = (1, 2, 3)) -> tuple[EL6224, list[SensorChannel]]:
    iolink = EL6224(master, EL6224_SLAVE)
    channels = make_channels(ports)
    register_channels(iolink, channels)
    setup_preop(iolink)
    return iolink, channels


def apply_sensors(
    master: Master,
    iolink: EL6224,
    channels: list[SensorChannel],
    *,
    enter_safeop: bool = True,
    settle_s: float = 5.0,
) -> dict[int, SensorIsduProfile]:
    """Fase 2: ISDU — scrive setup (se definito), valida, legge profile."""
    if enter_safeop:
        master.to_safeop()
    ports = [ch.port for ch in channels]
    iolink.wait_ports_ready(master, ports, timeout_s=settle_s)
    profiles: dict[int, SensorIsduProfile] = {}
    for ch in channels:
        isdu = IOLinkIsduChannel(iolink, ch.port)
        writes = ch.device.isdu_writes()
        profile = ch.device.apply_isdu(isdu)
        profiles[ch.port] = profile
        w = f" writes={writes}" if writes else ""
        print(
            f"port {ch.port}: {profile.vendor_name} / {profile.product_name} "
            f"scale={profile.scaling} unit={profile.unit}{w}"
        )
    return profiles


def read_sensors(
    master: Master,
    iolink: EL6224,
    channels: list[SensorChannel],
) -> dict[int, Pf2m7Sample | Psd4Sample]:
    """Fase 3: lettura PDO — bus in OP (o SAFE-OP con almeno un ciclo)."""
    master.cycle()
    pd = iolink.decode_tx_pdo_named(master.pdoin(EL6224_SLAVE))
    samples: dict[int, Pf2m7Sample | Psd4Sample] = {}
    for ch in channels:
        field = f"ch{ch.port}_iolink_pd"
        samples[ch.port] = ch.device.sample(**pd[field])  # type: ignore[call-arg]
    return samples


def snapshot_from_samples(samples: dict[int, Pf2m7Sample | Psd4Sample]) -> SensorSnapshot:
    return SensorSnapshot(
        pf2m7=samples[1],  # type: ignore[arg-type]
        psd4_p2=samples[2],  # type: ignore[arg-type]
        psd4_p3=samples[3],  # type: ignore[arg-type]
    )


def format_snapshot(snapshot: SensorSnapshot | dict[int, Pf2m7Sample | Psd4Sample]) -> str:
    if isinstance(snapshot, dict):
        parts = [f"p{p}={s.value:7.3f} {s.unit}" for p, s in sorted(snapshot.items())]
        return "  ".join(parts)
    p1, p2, p3 = snapshot.pf2m7, snapshot.psd4_p2, snapshot.psd4_p3
    return (
        f"PF2M7={p1.value:7.3f} {p1.unit}  "
        f"PSD4/2={p2.value:7.3f} {p2.unit}  "
        f"PSD4/3={p3.value:7.3f} {p3.unit}"
    )


def run_demo(
    master: Master,
    *,
    ports: tuple[int, ...] = (1, 2, 3),
    cycles: int = 10,
    period: float = 0.1,
) -> None:
    """Workflow completo: PRE-OP → ISDU (SAFE-OP) → OP → letture PDO."""
    iolink, channels = init_stack(master, ports)
    apply_sensors(master, iolink, channels)
    master.to_op()
    try:
        for i in range(cycles):
            samples = read_sensors(master, iolink, channels)
            print(f"[{i + 1}/{cycles}] {format_snapshot(samples)}")
            if i + 1 < cycles and period > 0:
                time.sleep(period)
    except KeyboardInterrupt:
        print("\nInterrotto.")


def _parse_ports(text: str) -> tuple[int, ...]:
    ports = tuple(int(p.strip()) for p in text.split(",") if p.strip())
    if not ports or any(p not in (1, 2, 3, 4) for p in ports):
        raise argparse.ArgumentTypeError("ports must be comma-separated values in 1..4")
    return ports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="3 sensori IO-Link su EL6224 (PF2M7 + 2× PSD4)")
    parser.add_argument("ifname", help="Interfaccia EtherCAT (es. enp2s0)")
    parser.add_argument(
        "--ports", type=_parse_ports, default=(1, 2, 3),
        help="Porte IO-Link da usare (default: 1,2,3). Es. --ports 1 se solo PF2M7",
    )
    parser.add_argument("-n", "--cycles", type=int, default=10, help="Cicli PDO in OP (default: 10)")
    parser.add_argument("-p", "--period", type=float, default=0.1, help="Periodo tra letture in secondi (default: 0.1)")
    args = parser.parse_args(argv)

    master = Master(args.ifname)
    master.open(manual_state_change=True)
    try:
        run_demo(master, ports=args.ports, cycles=args.cycles, period=args.period)
    finally:
        master.close()
    return 0


# --- bootstrap REPL (``eci --macros`` inietta ``bus`` prima dell'exec) -----

iolink: EL6224 | None = None
channels: list[SensorChannel] | None = None

if bus is not None:
    iolink, channels = init_stack(bus)


if __name__ == "__main__":
    sys.exit(main())
