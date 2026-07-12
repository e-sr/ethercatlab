from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from IPython.core.magic import Magics, magics_class, line_magic
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from rich.console import Console
from rich.table import Table
from IPython.display import display

from .master import CoeTransfer, Master, State
from .coe import CoEEntry, CoeObject, format_coe_value

_console = Console(color_system="truecolor", force_terminal=True)


def _int(value: str) -> int:
    return int(value, 0)


def _coe_value(value: str):
    v = value.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    try:
        return int(value, 0)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _hex_bytes(value: str) -> bytes:
    text = value.strip().lower().replace(" ", "")
    if text.startswith("0x"):
        text = text[2:]
    if len(text) % 2:
        raise ValueError("hex payload must have even length")
    return bytes.fromhex(text)


def _netid(text: str) -> bytes:
    parts = [int(p, 16) for p in text.split(":")]
    if len(parts) != 6:
        raise ValueError("AMS netid: 6 colon-separated hex bytes")
    return bytes(parts)


def _render(table: Table) -> str:
    with _console.capture() as cap:
        _console.print(table)
    return cap.get()


def _coe_table(obj: CoeObject) -> str:
    t = Table(title=f"0x{obj.index:x} [{obj.object_code.name}] {obj.name}", header_style="bold")
    for col in ("Sub", "Name", "Type", "Fmt", "Acc"):
        t.add_column(col)
    for e in obj.entries:
        if e.is_valid:
            t.add_row(str(e.subindex), e.name, e.data_type.name, str(e.bitstruct_format), e.access.name)
    return _render(t)


class CoeObjectList:
    def __init__(self, objects: dict[int, CoeObject]):
        self.objects = objects

    def __str__(self) -> str:
        t = Table(title="CoE objects", header_style="bold")
        for col in ("Index", "Name", "Code", "Entries"):
            t.add_column(col)
        for idx, obj in self.objects.items():
            n = sum(1 for e in obj.entries if e.is_valid)
            t.add_row(hex(idx), obj.name, obj.object_code.name, f"{n}/{len(obj.entries)}")
        return _render(t)


@dataclass(slots=True)
class CoeParsed:
    transfer: CoeTransfer
    entry: CoEEntry | None = None
    value: Any = None


def read_coe_parsed(bus: Master, slave_idx: int, coe_idx: int, subindex: int = 0) -> CoeParsed:
    entry = bus.get_coe_entry(slave_idx, coe_idx, subindex)
    if entry is None:
        return CoeParsed(
            CoeTransfer(coe_idx, subindex, error=f"CoE entry not found: 0x{coe_idx:04x}:{subindex}"),
        )
    transfer = bus.read_coe(slave_idx, coe_idx, subindex)
    if transfer.error is not None:
        return CoeParsed(transfer, entry=entry)
    try:
        _, value = bus.parse_coe_read(slave_idx, transfer)
    except Exception as exc:
        return CoeParsed(
            CoeTransfer(coe_idx, subindex, raw=transfer.raw, error=str(exc)),
            entry=entry,
        )
    return CoeParsed(transfer, entry=entry, value=value)


def write_coe_value(
    bus: Master, slave_idx: int, coe_idx: int, subindex: int, value: Any,
) -> CoeParsed:
    try:
        entry, payload = bus.encode_coe_write(slave_idx, coe_idx, subindex, value)
        print(f"Encoded CoE write: {entry.name} {subindex} = {value}")
    except Exception as exc:
        return CoeParsed(CoeTransfer(coe_idx, subindex, error=str(exc)))
    result = bus.write_coe(slave_idx, coe_idx, subindex, payload)
    if result.error is not None:
        return CoeParsed(result, entry=entry)
    return CoeParsed(result, entry=entry, value=value)


def read_coe_object(bus: Master, slave_idx: int, coe_idx: int) -> tuple[CoeObject, list[CoeParsed]]:
    obj = bus.get_coe_object(slave_idx, coe_idx)
    if obj is None:
        raise RuntimeError(f"CoE object not found for slave {slave_idx}, index 0x{coe_idx:04x}")
    reads: list[CoeParsed] = []
    for entry in obj.entries:
        if not entry.is_valid:
            continue
        reads.append(read_coe_parsed(bus, slave_idx, coe_idx, entry.subindex))
    return obj, reads


class CoeParsedList:
    def __init__(self, parsed: list[CoeParsed]):
        self.parsed = parsed

    def __str__(self) -> str:
        t = Table(header_style="bold")
        for col in ("Sub", "Name", "Type", "Raw", "Value", "Acc"):
            t.add_column(col)
        for item in self.parsed:
            tr = item.transfer
            if tr.error:
                name = item.entry.name if item.entry else "?"
                acc = item.entry.access.name if item.entry else ""
                sub = str(item.entry.subindex) if item.entry else str(tr.subindex)
                t.add_row(sub, name, "ERR", tr.error, "", acc)
            elif item.entry is not None:
                t.add_row(
                    str(item.entry.subindex), item.entry.name, item.entry.data_type.name,
                    tr.raw_str, format_coe_value(item.entry, item.value), item.entry.access.name,
                )
            else:
                t.add_row(str(tr.subindex), "?", "?", tr.raw_str, "", "")
        return _render(t)


@magics_class
class EtherMagics(Magics):
    def __init__(self, shell, bus: Master):
        super().__init__(shell)
        self.bus = bus
        self.bus.open(manual_state_change=True)
        print(f"bus on {self.bus.ifname}: {len(self.bus.master.slaves)} slave(s)")

    @magic_arguments()
    @argument("slaveindex", type=int, nargs="?")
    @line_magic
    def ec_slaves(self, line):
        args = parse_argstring(self.ec_slaves, line)
        if args.slaveindex is None:
            for pos, s in enumerate(self.bus.master.slaves, start=1):
                print(f"Slave {pos}: {s.name}  adr=0x{s.configadr:x}  {State(s.state)!s}")
        else:
            s = self.bus.get_slave(args.slaveindex)
            print(f"Slave {args.slaveindex}: {s.name}  adr=0x{s.configadr:x}  {State(s.state)!s}")

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("coeindex", type=_int, nargs="?")
    @line_magic
    def ec_coe(self, line):
        args = parse_argstring(self.ec_coe, line)
        od = self.bus.slave_coe_object_dict(args.slaveindex)
        if not od:
            print(f"No CoE OD on slave {args.slaveindex}")
            return
        if args.coeindex is not None:
            obj = self.bus.get_coe_object(args.slaveindex, args.coeindex)
            display(obj) if obj else print("object not found")
            return
        display(CoeObjectList(od))

    @line_magic
    def ec_reinit(self, line):
        self.bus.close()
        self.bus.open(manual_state_change=True)

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("coeindex", type=_int)
    @argument("subindex", type=_int, nargs="?", default=0)
    @argument("--all", action="store_true")
    @argument("--parsed", action="store_true", help="decode via OD (default)")
    @argument("--encoded", action="store_true", help="raw bus bytes as hex")
    @line_magic
    def ec_coe_read(self, line):
        args = parse_argstring(self.ec_coe_read, line)
        encoded = args.encoded
        if args.all and encoded:
            print("read failed: --all requires --parsed")
            return
        try:
            if args.all:
                obj, reads = read_coe_object(self.bus, args.slaveindex, args.coeindex)
                print(f"0x{args.coeindex:x} {obj.name}")
                display(CoeParsedList(reads))
            elif encoded:
                transfer = self.bus.read_coe(args.slaveindex, args.coeindex, args.subindex)
                if transfer.error is not None or transfer.raw is None:
                    print(f"read failed: {transfer.error or 'empty response'}")
                else:
                    print(transfer.raw.hex())
            else:
                parsed = read_coe_parsed(self.bus, args.slaveindex, args.coeindex, args.subindex)
                display(CoeParsedList([parsed]))
        except Exception as exc:
            print(f"read failed: {exc}")

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("coeindex", type=_int)
    @argument("subindex", type=_int)
    @argument("value", type=str)
    @argument("--parsed", action="store_true", help="encode value via OD (default)")
    @argument("--encoded", action="store_true", help="write raw hex bytes")
    @line_magic
    def ec_coe_write(self, line):
        args = parse_argstring(self.ec_coe_write, line)
        try:
            if args.encoded:
                result = self.bus.write_coe(
                    args.slaveindex, args.coeindex, args.subindex, _hex_bytes(args.value),
                )
                if result.error is not None:
                    print(f"write failed: {result.error}")
            else:
                parsed = write_coe_value(
                    self.bus, args.slaveindex, args.coeindex, args.subindex, _coe_value(args.value),
                )
                if parsed.transfer.error is not None:
                    print(f"write failed: {parsed.transfer.error}")
        except Exception as exc:
            print(f"write failed: {exc}")

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("snet", type=str, nargs="?")
    @line_magic
    def ec_aoe_init(self, line):
        """%ec_aoe_init S [SNET] — senza SNET legge slave netid da CoE 0x0920."""
        args = parse_argstring(self.ec_aoe_init, line)
        try:
            if args.snet:
                self.bus.aoe_assign(args.slaveindex, _netid(args.snet))
            else:
                self.bus.aoe_init(args.slaveindex)
        except Exception as exc:
            print(f"aoe_init failed: {exc}")

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("ig", type=_int)
    @argument("off", type=_int)
    @argument("size", type=_int)
    @argument("port", type=_int)
    @line_magic
    def ec_aoe_read(self, line):
        args = parse_argstring(self.ec_aoe_read, line)
        try:
            print(self.bus.aoe_read(args.slaveindex, args.ig, args.off, args.size, args.port).hex())
        except Exception as exc:
            print(f"aoe read failed: {exc}")

    @magic_arguments()
    @argument("slaveindex", type=_int)
    @argument("ig", type=_int)
    @argument("off", type=_int)
    @argument("port", type=_int)
    @argument("hexdata", type=str)
    @line_magic
    def ec_aoe_write(self, line):
        args = parse_argstring(self.ec_aoe_write, line)
        try:
            self.bus.aoe_write(args.slaveindex, args.ig, args.off, _hex_bytes(args.hexdata), args.port)
        except Exception as exc:
            print(f"aoe write failed: {exc}")


def register_custom_formatters(shell):
    fmt = shell.display_formatter.formatters["text/plain"]
    fmt.for_type(CoeParsedList, lambda o, p, c: p.text(str(o)))
    fmt.for_type(CoeObject, lambda o, p, c: p.text(_coe_table(o)))
    fmt.for_type(CoeObjectList, lambda o, p, c: p.text(str(o)))
