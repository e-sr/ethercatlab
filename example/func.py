"""Banco prova — esempio REPL (`eci --macros func.py --merge-macros-ns`).

Terminali: EL1004 in3 (dig.), EL6224 IO-Link, EL2004 out3, EL3072 AI1 ±10V.

    configure_banco()
    read_pdo()
    exchange_pdo(10, 0.1, [True, False] * 5)
"""

from __future__ import annotations

import bitstruct
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generator, Callable

from ethercat_lab import IOLinkIsduChannel
from ethercat_lab.el6224 import IoLinkChannelConfig, EL6224,decode_port_status_byte
from iolink_sensors.models import DeviceBase
from iolink_sensors.pf2m7 import Pf2m7Device, Pf2m7Sample, Pf2m7IsduSetup
from iolink_sensors.psd4 import Psd4Device, Psd4Sample, Psd4IsduSetup
from ethercat_lab.el3072 import EL3072, AnalogInputChannel, InputInterface, PdoMode, UserScaleConfig, LimitConfig, RangeErrorConfig, IIRFilter, LimitTriggerType
from collections.abc import Generator
from ethercat_lab.pdo import PdoMapEntry, PdoMapping

from rich.console import Console
from rich.live import Live
from rich.text import Text
from ethercat_lab.beckhoff_device import inspect_pdo_mapping
if TYPE_CHECKING:
    from ethercat_lab.master import Master

bus: Master  # injected by `eci --macros` before module execution


def read_pdo_mapping(master: Master, slave_idx: int, coe_index: int) -> PdoMapping:
    count_raw = master.read_coe(slave_idx, coe_index, 0).raw
    if count_raw is None:
        raise ValueError("Count is None")
    count = count_raw[0]
    coe_reads = [master.read_coe(slave_idx, coe_index, i + 1) for i in range(count)]
    if any(coe_read.error is not None or coe_read.raw is None for coe_read in coe_reads):
        raise ValueError("Error reading PDO mapping")
    entries = [PdoMapEntry.from_bytes(coe_read.raw) for coe_read in coe_reads]
    return PdoMapping(index=coe_index, entries=entries)

@dataclass(frozen=True, slots=True)
class BancoLayout:
    el1004: int = 2
    el6224: int = 3
    el2004: int = 4
    el3072: int = 5
    psd4_port_1: int = 2
    psd4_port_2: int = 3
    pf2m7_port: int = 1
    pf2m7_flow_range_l: int = 25


@dataclass(frozen=True, slots=True)
class EL2004Sample:
    o1: bool
    o2: bool
    o3: bool
    o4: bool
    _codec= bitstruct.compile('p4b1b1b1b1')

    def pack(self) -> bytes:
        return self._codec.pack(*[bool(v) for v in [self.o1, self.o2, self.o3, self.o4]])

    @classmethod
    def from_bytes(cls,data:bytes) -> EL2004Sample: 
        out1, out2, out3, out4= cls._codec.unpack(data)
        return cls(*[bool(v) for v in [out1, out2, out3, out4]])

    @classmethod
    def from_hex(cls,value:int) -> EL2004Sample:
        return cls(*[bool((value>>i)&0x01) for i in range(4)])
    
    def to_hex(self) -> int:
        return sum([v<<i for i, v in enumerate([self.o1, self.o2, self.o3, self.o4])])

    def to_list(self) -> list[bool]:
        return [self.o1, self.o2, self.o3, self.o4]
    @classmethod
    def from_list(cls,values:list[bool]) -> EL2004Sample:
        return cls(*values)

@dataclass(frozen=True)
class EL1004Sample:
    in1: bool
    in2: bool
    in3: bool
    in4: bool
    _codec= bitstruct.compile('p4b1b1b1b1')

    @classmethod
    def from_bytes(cls,data:bytes) -> EL1004Sample:
        in1, in2, in3, in4= cls._codec.unpack(data)
        return cls(*[bool(v) for v in [in1, in2, in3, in4]])

    def to_list(self) -> list[bool]:
        return [self.in1, self.in2, self.in3, self.in4]

    def to_hex(self) -> int:
        return sum([v<<i for i, v in enumerate([self.in1, self.in2, self.in3, self.in4])])

@dataclass(frozen=True, slots=True)
class EL3072Sample:
    v1: float
    i2: float

@dataclass(slots=True)
class PdoSnapshot:
    el1004: EL1004Sample
    el3072: EL3072Sample
    psd4_1: Psd4Sample
    psd4_2: Psd4Sample
    pf2m7: Pf2m7Sample

class Banco:
    def __init__(self, master: Master, layout: BancoLayout | None = None) -> None:
        self.bus = master
        self.layout = layout or BancoLayout()

        self.io_link = EL6224(master, self.layout.el6224)
        self.ai = EL3072(master, self.layout.el3072)

        self.psd4_1 = Psd4Device(setup=Psd4IsduSetup())
        self.psd4_2 = Psd4Device(setup=Psd4IsduSetup())
        self.pf2m7 = Pf2m7Device(setup=Pf2m7IsduSetup())

        self.io_link.set_channel(
            IoLinkChannelConfig(port=self.layout.psd4_port_1, pd_in=self.psd4_1.pd_in_layout),
        )
        self.io_link.set_channel(
            IoLinkChannelConfig(port=self.layout.psd4_port_2, pd_in=self.psd4_2.pd_in_layout),
        )
        self.io_link.set_channel(
            IoLinkChannelConfig(port=self.layout.pf2m7_port, pd_in=self.pf2m7.pd_in_layout),
        )
        # I- CH2 4-20mA
        self.ai.set_channel(AnalogInputChannel(
            port=1,
            input_interface=InputInterface.I_4_20MA,
            user_scale= UserScaleConfig.physical(gain=1000.0, offset=-4.0),
            limits=LimitConfig(limit1=4.0, limit2=8.0),
            range_error=RangeErrorConfig(low=1.0, high=5.0),
            iir_filter=IIRFilter.IIR21Hz,
            pdo_mode=PdoMode.COMPACT_REAL32,
            cycle_counters=True
        ))
        # V+ CH1 potenziometro Voltaggio
        self.ai.set_channel(AnalogInputChannel(
            port=2,
            input_interface=InputInterface.V_0_10,
            user_scale=UserScaleConfig.physical(gain=2.0, offset=0.0),
            limits=LimitConfig(limit1=2.0, limit2=4.0),
            range_error=RangeErrorConfig(low=2.0, high=17.0),
            iir_filter=IIRFilter.IIR21Hz,
            pdo_mode=PdoMode.DEFAULT_REAL32,
        ))

        self.do = self.bus.get_slave(self.layout.el2004)
        self.do_max_watchdog_timeout = self.do.get_max_watchdog_time()
        self.di = self.bus.get_slave(self.layout.el1004)

    def configure_preop(self) -> None:
        """Un solo PRE-OP: AoE EL6224, poi recipe CoE/PDO di tutti i terminali."""
        self.io_link.configure_preop(aoe_init=True)
        self.ai.configure_preop()

    def read_inputs(self) -> PdoSnapshot:
        el6224_raw = self.bus.pdoin(self.layout.el6224)
        el3072_raw = self.bus.pdoin(self.layout.el3072)
        el1004_raw = self.bus.pdoin(self.layout.el1004)
        ai_named = self.ai.decode_tx_pdo_named(el3072_raw)
        iolink_ports = self.io_link.decode_tx_pdo_named(el6224_raw)
        
        return PdoSnapshot(
            el1004=EL1004Sample.from_bytes(el1004_raw),
            el3072=EL3072Sample(
                v1=float(ai_named["ch2_DEFAULT_REAL32"]["value_f32"]),
                i2=float(ai_named["ch1_COMPACT_REAL32"]["value_f32"]),
            ),
            pf2m7=self.pf2m7.sample(**iolink_ports["ch1_iolink_pd"]),
            psd4_1=self.psd4_1.sample(**iolink_ports["ch2_iolink_pd"]),
            psd4_2=self.psd4_2.sample(**iolink_ports["ch3_iolink_pd"]),
        )

    def read_pdo_safeop(self, *,repeats: int = 1, sample_period: float = 0.0) -> PdoSnapshot:
        self.bus.to_safeop()
        for i in range(repeats):
            self.bus.cycle()
            if sample_period and i + 1 < repeats:
                time.sleep(sample_period)
        return self.read_inputs()

    def set_ao_watchdog_timeout(self, timeout: int) -> None:
        if timeout > self.do_max_watchdog_timeout:
            raise ValueError(f"Timeout {timeout} is greater than the maximum watchdog timeout {self.do_max_watchdog_timeout}")
        self.do.set_watchdog('processdata',timeout)

    def write_do(self,dosample: EL2004Sample) -> EL2004Sample:
        current = EL2004Sample.from_bytes(self.do.output)
        dosample_next = EL2004Sample.from_hex(current.to_hex() | dosample.to_hex())
        self.do.output = dosample_next.pack()
        return dosample_next

    def exchange_pdo_op(
        self,
        sample_period: float,
        repeat: int | None = None,
        dosample: EL2004Sample = EL2004Sample.from_hex(0x00),
    ) -> Generator[PdoSnapshot, EL2004Sample, int]:
        
        self.set_ao_watchdog_timeout(int(sample_period * 1500))
        self.read_pdo_safeop()
        self.bus.to_op()
        
        i = 0 if repeat is None else repeat
        next_cycle = time.perf_counter()
        
        while True:
            i = i - 1
            
            # 1. Scambio dati hardware
            self.write_do(dosample)
            self.bus.cycle()
            snapshot = self.read_inputs()
            
            if i == 0:
                break
                
            # 2. Calcolo preciso del tempo rimanente
            next_cycle += sample_period
            sleep_time = next_cycle - time.perf_counter()
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_cycle = time.perf_counter()  # Sfasamento: resetta il target al tempo corrente
                
            # 3. Rilascia lo snapshot SOLO DOPO aver atteso il tempo corretto
            dosample = yield snapshot

        return -i if i < 0 else i



    def read_isdu(self, port: IOLinkIsduChannel, sensor: DeviceBase, name: str) -> bytes:
        reg = sensor.descriptor.registers[name]
        size = bitstruct.calcsize(reg.format) // 8
        return port.read_isdu(reg.index, reg.subindex, size=size)


_console = Console(
    color_system="truecolor", 
    force_terminal=True,
    highlight=False
)

def _bool_indicators(values: Sequence[bool | None], *, on: str, off: str) -> Text:
    t = Text()
    for value in values:
        if value is None:
            t.append("·", style="dim")
        elif value:
            t.append("●", style=on)
        else:
            t.append("○", style=off)
    return t


def format_pdo_line(snapshot: PdoSnapshot, do: EL2004Sample) -> Text:
    di = snapshot.el1004
    #psd4 = snapshot.psd4
    pf2m7_sample = snapshot.pf2m7
    ai_sample = snapshot.el3072
    line = Text()
    line.append("TX ", style="bold magenta")
    line.append_text(_bool_indicators(do.to_list(), on="bold green", off="dim"))
    line.append("  RX ", style="bold cyan")
    line.append("DI ", style="cyan")
    line.append_text(_bool_indicators([di.in1, di.in2, di.in3, di.in4], on="bold yellow", off="dim"))
    line.append(f"  AI {ai_sample.v1:+.3f}, overrang", style="blue")
    line.append(f" {ai_sample.i2:+.3f}", style="blue")
    line.append(f"  PF2M7 {pf2m7_sample.value:6.3f} {pf2m7_sample.unit}", style="bright_blue")
    return line

def basic_iolinksensors_pdo_line(snapshot: PdoSnapshot, do: EL2004Sample) -> Text:
    psd4_1_sample = snapshot.psd4_1
    psd4_2_sample = snapshot.psd4_2
    pf2m7_sample = snapshot.pf2m7
    line = Text()
    line.append(f"  PSD4_1 {psd4_1_sample.value:6.3f} {psd4_1_sample.unit}", style="bright_blue")
    line.append(f"  PSD4_2 {psd4_2_sample.value:6.3f} {psd4_2_sample.unit}", style="bright_blue")
    line.append(f"  PF2M7 {pf2m7_sample.value:6.3f} {pf2m7_sample.unit}", style="bright_blue")
    return line

def blink_and_print(banco: Banco, 
sample_period: float,
_line_formatter: Callable[[PdoSnapshot, EL2004Sample], Text], 
_timing: bool = False) -> None:
    gen = banco.exchange_pdo_op(sample_period)

    doON = EL2004Sample.from_hex(0x0F)
    doOFF = EL2004Sample.from_hex(0x00)

    gen.send(None)  # Primi passaggi interni di setup
    current_out = doON

    n = 0
    mean = 0.0
    M2 = 0.0
    min_val = float('inf')
    max_val = float('-inf')

    last_time = time.perf_counter()
    refresh_hz = max(4, min(20, int(1 / sample_period)))

    try:
        with Live(
            Text("Avvio scambio PDO…", style="dim"),
            console=_console,
            refresh_per_second=refresh_hz,
            transient=False,
        ) as live:
            while True:
                try:
                    snapshot = gen.send(current_out)
                except StopIteration:
                    break

                current_time = time.perf_counter()
                dt = (current_time - last_time) * 1000  # Tempo in ms
                last_time = current_time

                if n == 0:
                    current_out = doOFF if current_out == doON else doON
                    n += 1
                    continue

                n += 1
                if dt < min_val:
                    min_val = dt
                if dt > max_val:
                    max_val = dt

                delta = dt - mean
                mean += delta / (n - 1)
                M2 += delta * (dt - mean)

                if n % 4 == 0:
                    std_dev = math.sqrt(M2 / (n - 1)) if n > 2 else 0.0
                    stats_str = (
                        f"| Live Stats (ms) -> Avg: {mean:.2f} | StdDev: {std_dev:.2f} "
                        f"| Min: {min_val:.2f} | Max: {max_val:.2f}"
                    )
                    line = _line_formatter(snapshot, current_out)
                    if _timing:
                        line.append(f" {stats_str}", style="dim")
                    live.update(line)

                current_out = doOFF if current_out == doON else doON

    except KeyboardInterrupt:
        _console.print("[yellow]Test terminato.[/yellow]")

banco = Banco(bus)
el6224 = banco.io_link
banco.configure_preop()