import bitstruct
from enum import Enum, IntEnum, IntFlag


class CoEDataType(Enum):
    """Mappa tipi CANopen/CoE → bitstruct: tipo, lunghezza fissa (bit), byte order LE."""

    # code, bitstruct_type, bit_length (None = dall'OD), little_endian
    UNUSED = (0x0000, "", None, False)
    BOOLEAN = (0x0001, "b", 1, False)
    INTEGER8 = (0x0002, "s", 8, True)
    INTEGER16 = (0x0003, "s", 16, True)
    INTEGER32 = (0x0004, "s", 32, True)
    UNSIGNED8 = (0x0005, "u", 8, True)
    UNSIGNED16 = (0x0006, "u", 16, True)
    UNSIGNED32 = (0x0007, "u", 32, True)
    REAL32 = (0x0008, "f", 32, True)
    VISIBLE_STRING = (0x0009, "t", None, False)
    OCTET_STRING = (0x000A, "r", None, False)
    UNICODE_STRING = (0x000B, "r", None, False)
    TIME_OF_DAY = (0x000C, "u", 48, True)
    TIME_DIFFERENCE = (0x000D, "u", 48, True)
    DOMAIN = (0x000F, "r", None, False)
    INTEGER24 = (0x0010, "s", 24, True)
    REAL64 = (0x0011, "f", 64, True)
    INTEGER40 = (0x0012, "s", 40, True)
    INTEGER48 = (0x0013, "s", 48, True)
    INTEGER56 = (0x0014, "s", 56, True)
    INTEGER64 = (0x0015, "s", 64, True)
    UNSIGNED24 = (0x0016, "u", 24, True)
    UNSIGNED40 = (0x0018, "u", 40, True)
    UNSIGNED48 = (0x0019, "u", 48, True)
    UNSIGNED56 = (0x001A, "u", 56, True)
    UNSIGNED64 = (0x001B, "u", 64, True)
    BYTE = (0x001E, "u", 8, True)
    WORD = (0x001F, "u", 16, True)
    DWORD = (0x0020, "u", 32, True)
    BITARR8 = (0x002D, "r", None, False)
    BITARR16 = (0x002E, "r", None, False)
    BITARR32 = (0x002F, "r", None, False)
    BIT1 = (0x0030, "u", 1, False)
    BIT2 = (0x0031, "u", 2, False)
    BIT3 = (0x0032, "u", 3, False)
    BIT4 = (0x0033, "u", 4, False)
    BIT5 = (0x0034, "u", 5, False)
    BIT6 = (0x0035, "u", 6, False)
    BIT7 = (0x0036, "u", 7, False)
    BIT8 = (0x0037, "u", 8, False)
    ARRAY_OF_INT = (0x0260, "r", None, False)
    ARRAY_OF_SINT = (0x0261, "r", None, False)
    ARRAY_OF_DINT = (0x0262, "r", None, False)
    ARRAY_OF_UDINT = (0x0263, "r", None, False)

    def __init__(
        self,
        code: int,
        bitstruct_type: str,
        bit_length: int | None,
        little_endian: bool,
    ):
        self.code = code
        self.bitstruct_type = bitstruct_type
        self.bit_length = bit_length
        self.little_endian = little_endian

    def bitstruct_format(self, od_bit_length: int) -> str:
        """Formato bitstruct completo, es. ``u16<`` (suffisso ``<`` = byte order LE)."""
        if not self.bitstruct_type:
            return ""
        bits = self.bit_length if self.bit_length is not None else od_bit_length
        fmt = f"{self.bitstruct_type}{bits}"
        if self.little_endian:
            fmt += "<"
        return fmt

    @classmethod
    def from_code(cls, code: int) -> "CoEDataType":
        for item in cls:
            if item.code == code:
                return item
        # Tipi compositi/vendor-specific (es. 0x0800): decode come blob raw
        return cls.DOMAIN


class ObjectCode(IntEnum):
    VAR = 0x07
    ARRAY = 0x08
    RECORD = 0x09
    DEFTYPE = 0x03
    DEFSTRUCT = 0x04


class ObjAccess(IntFlag):
    Rpre = 0x01
    Rsafe = 0x02
    Rop = 0x04
    Wpre = 0x08
    Wsafe = 0x10
    Wop = 0x20


def _decode_name(raw_name) -> str:
    if isinstance(raw_name, bytes):
        return raw_name.decode("utf-8", errors="replace")
    return str(raw_name)


def format_coe_value(entry: "CoEEntry", value) -> str:
    """Human-readable CoE value for REPL tables."""
    if isinstance(value, int) and entry.data_type == CoEDataType.DOMAIN:
        nbytes = entry.expected_raw_len
        if nbytes == 2:
            return f"0x{value:04x}"
        if nbytes == 4:
            return f"0x{value:08x}"
    return str(value)


def get_entry_subindex(entry, fallback: int) -> int:
    """Use the real subindex from pysoem entry when available."""
    return getattr(entry, "subindex", fallback)


def format_coe_value(entry: "CoEEntry", value) -> str:
    """Human-readable CoE value for REPL tables."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if entry.data_type == CoEDataType.DOMAIN and isinstance(value, int):
        nbytes = entry.expected_raw_len
        if nbytes <= 4:
            return f"0x{value:0{nbytes * 2}x}"
    if isinstance(value, bytes):
        return value.hex(" ")
    return str(value)

class CoEEntry:
    """
    Livello 1: Gestisce la singola CdefCoeObjectEntry.
    Genera la stringa di formato atomica e pulisce il nome del campo.
    """
    def __init__(
        self,
        subindex: int,
        bit_length: int,
        data_type: CoEDataType,
        access: ObjAccess,
        name: str,
    ):
        self.subindex = subindex
        self.bit_length = bit_length
        self.data_type = data_type
        self.access = access
        self.name = name
        self.is_valid = (
            self.data_type != CoEDataType.UNUSED
            and self.bit_length > 0
            and (self.data_type.bitstruct_type != 'f' or self.bit_length in (32, 64))
            and (self.data_type.bitstruct_type not in ('t', 'r') or self.bit_length % 8 == 0)
        )
        self.bitstruct_format = self._bitstruct_format()
        self._compiled = (
            bitstruct.compile(self.bitstruct_format)
            if self.is_valid and self.data_type != CoEDataType.DOMAIN
            else None
        )


    def _bitstruct_format(self) -> str:
        """Genera la stringa di formato per questa entry basata sul tipo CoE e la lunghezza in bit."""
        if self.is_valid:
            return self.data_type.bitstruct_format(self.bit_length)
        return ""

    @property
    def expected_raw_len(self) -> int:
        # CiA 301: BOOLEAN SDO payload is always one byte (0x00 / 0x01).
        if self.data_type == CoEDataType.BOOLEAN:
            return 1
        return (self.bit_length + 7) // 8

    def pack(self, value):
        """Esegue il packing del valore usando bitstruct basato sul formato generato."""
        if not self.is_valid:
            raise ValueError(f"Cannot pack value for invalid entry {self.name} (index {self.subindex})")
        if self.data_type == CoEDataType.BOOLEAN:
            return b"\x01" if value else b"\x00"
        if self.data_type.bitstruct_type == "r":
            return self._pack_raw(value)
        if self.data_type.bitstruct_type == "t":
            if isinstance(value, int):
                raise TypeError(
                    f"Cannot pack int for VISIBLE_STRING entry {self.name}; use a string or --encoded"
                )
            raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            nbytes = self.expected_raw_len
            if len(raw) > nbytes:
                raise ValueError(f"string payload is {len(raw)} B, expected {nbytes} B")
            return raw.ljust(nbytes, b"\x00")
        return self._compiled.pack(value)

    def _pack_raw(self, value) -> bytes:
        nbytes = self.expected_raw_len
        if isinstance(value, int):
            return value.to_bytes(nbytes, "little", signed=value < 0)
        if isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
            if len(raw) != nbytes:
                raise ValueError(f"payload is {len(raw)} B, expected {nbytes} B")
            return raw
        if isinstance(value, str):
            text = value.strip().lower().replace(" ", "")
            if text.startswith("0x"):
                text = text[2:]
            if not text or not all(c in "0123456789abcdef" for c in text):
                raise TypeError(
                    f"cannot pack string {value!r} as raw CoE data; use int, bytes, or hex"
                )
            if len(text) % 2:
                text = "0" + text
            raw = bytes.fromhex(text)
            if len(raw) != nbytes:
                raise ValueError(f"hex payload is {len(raw)} B, expected {nbytes} B")
            return raw
        raise TypeError(f"cannot pack {type(value).__name__} as raw CoE data")

    def _unpack_domain_scalar(self, raw_bytes: bytes):
        nbytes = self.expected_raw_len
        if len(raw_bytes) < nbytes:
            raise ValueError(
                f"DOMAIN payload for {self.name} is {len(raw_bytes)} B, expected {nbytes} B"
            )
        chunk = bytes(raw_bytes[:nbytes])
        if nbytes == 1:
            return chunk[0]
        if nbytes == 2:
            return int.from_bytes(chunk, "little", signed=False)
        if nbytes == 4:
            return int.from_bytes(chunk, "little", signed=True)
        return chunk

    def unpack(self, raw_bytes):
        """Esegue l'unpacking del flusso di byte usando bitstruct basato sul formato generato."""
        if not self.is_valid:
            raise ValueError(f"Cannot unpack value for invalid entry {self.name} (index {self.subindex})")
        if self.data_type == CoEDataType.BOOLEAN:
            if not raw_bytes:
                raise ValueError(f"empty BOOLEAN payload for {self.name}")
            return raw_bytes[0] != 0
        if self.data_type == CoEDataType.DOMAIN:
            return self._unpack_domain_scalar(raw_bytes)
        if self.data_type.bitstruct_type == "r":
            return bytes(raw_bytes[: self.expected_raw_len])
        return self._compiled.unpack(raw_bytes)[0]

    def __repr__(self):
        if self.is_valid:
            return f"(subindex={self.subindex}, name='{self.name}', dtype={self.data_type.name}, format={self.bitstruct_format}, access={self.access.name})"
        else:
            return f"(subindex={self.subindex}, name='{self.name}', dtype={self.data_type.name}, bitlen={self.bit_length}, unsupported)"

    @classmethod
    def from_pysoem(cls, entry, fallback_subindex: int = 0):
        """Factory method per creare un CoEEntry direttamente da una entry di pysoem."""
        subindex = get_entry_subindex(entry, fallback=fallback_subindex)
        data_type = CoEDataType.from_code(entry.data_type)
        access = ObjAccess(entry.obj_access)
        return cls(subindex, entry.bit_length, data_type, access, _decode_name(entry.name))

    

class CoeObject:
    """
    Livello 2: Gestisce l'intero CdefCoeObject.
    Concatena i formati dei CoEEntry e compila il motore bitstruct.
    """
    def __init__(self, index: int, name: str, object_code: ObjectCode, entries: list[CoEEntry]):
        self.index = index
        self.name = name
        self.object_code = object_code
        self.entries = entries
        self.has_subindex = self.object_code in {ObjectCode.ARRAY, ObjectCode.RECORD} or len(self.entries) > 1
        self.subindexset = {e.subindex: e.name for e in self.entries}

    @classmethod
    def from_pysoem(cls, coe_object):
        object_code = ObjectCode(getattr(coe_object, "object_code"))
        if len(coe_object.entries) == 0:
            fake_entry = type(
                "FakeEntry",
                (object,),
                {
                    "subindex": 0,
                    "bit_length": coe_object.bit_length,
                    "data_type": coe_object.data_type,
                    "obj_access": coe_object.obj_access,
                    "name": coe_object.name,
                },
            )()
            entries = [
                CoEEntry.from_pysoem(fake_entry, fallback_subindex=0)
            ]
        else:
            entries = [
                CoEEntry.from_pysoem(e, fallback_subindex=i)
                for i, e in enumerate(coe_object.entries)
            ]

        return cls(
            index=coe_object.index,
            name=_decode_name(coe_object.name),
            object_code=object_code,
            entries=entries,
        )

    def __repr__(self):
        return (
            f"Object {hex(self.index)} [{self.object_code.name}, has_subindex={self.has_subindex}]: {self.name}\t\n"
            f" with entries: \n\t{'\n\t'.join(str(e) for e in self.entries if e.is_valid)}"
        )


