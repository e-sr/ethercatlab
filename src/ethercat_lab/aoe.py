"""AoE helpers (ETG.1020)."""

from __future__ import annotations

INDEX_GROUP_COE = 0xF302
AOE_TIMEOUT_US = 5_000_000

# Local EtherCAT master AMS Net ID (no ADS routing). Only needs to stay consistent
# between aoe_init and subsequent AoE transfers on this bus.
DEFAULT_MASTER_NETID = bytes([1, 1, 5, 0, 0, 1])

# Beckhoff: AMS Net ID dello slave in OD (6 byte), non 0xF820 ADS Server Settings.
COE_SLAVE_NETID_INDEX = 0xf920
COE_SLAVE_NETID_SUB = 1

_AOE_RESULT = {
    0x00: "error class < device error >", 0x01: "service not supported",
    0x02: "invalid indexGroup", 0x03: "invalid indexOffset",
    0x04: "reading/writing not permitted", 0x05: "parameter size not correct",
    0x06: "invalid parameter value(s)", 0x07: "device is not in a ready state",
    0x08: "device is busy", 0x0A: "out of memory", 0x0B: "invalid parameter value(s)",
    0x0C: "not found", 0x0D: "syntax error in command or file",
    0x0E: "objects do not match", 0x0F: "object already exists",
    0x19: "device has a timeout", 0x23: "access denied",
}
_ADS_ERR = {
    0x700: "error class", 0x701: "internal error", 0x702: "invalid index group",
    0x703: "invalid index offset", 0x704: "read/write not permitted",
    0x705: "parameter size not correct", 0x706: "invalid parameter value",
    0x707: "device not ready", 0x708: "device busy", 0x710: "symbol not found",
    0x712: "device/server in invalid state", 0x714: "invalid notification handle",
    0x71E: "request pending",
}
_PACKET_ERR = {1: "unexpected frame", 2: "AoE fragment", 3: "buffer too small", 4: "no mailbox response (timeout)"}
_IOLINK_ISDU = {
    0x8011: "index not available", 0x8012: "subindex not available",
    0x8013: "service not available", 0x8014: "service temporarily not available",
    0x8015: "access denied", 0x8016: "parameter value out of range",
    0x8017: "above limit", 0x8018: "below limit",
    0x8019: "invalid parameter set / wrong data format", 0x801A: "invalid parameter set (alt)",
    0x8020: "parameter set deactivated", 0x8021: "index not readable",
    0x8022: "index not writable", 0x8023: "service not available in present state",
}
_IOLINK_ACCESS = {2: "w", 12: "rw", 16: "r", 17: "r", 18: "r", 19: "r", 20: "r",
                  21: "r", 22: "r", 23: "r", 24: "rw", 36: "r", 37: "r"}


def coe_index_offset(coe_index: int, subindex: int = 0, *, complete_access: int = 0) -> int:
    return (coe_index << 16) | (complete_access << 8) | subindex


def iolink_index_offset(isdu_index: int, subindex: int = 0) -> int:
    return (isdu_index << 16) | (subindex & 0xFF)


def iolink_ams_port(port: int) -> int:
    if not 1 <= port <= 4:
        raise ValueError(f"IO-Link port must be 1..4, got {port}")
    return 0x1000 + port - 1


def parse_packet_error(code: int) -> str:
    return _PACKET_ERR.get(code, f"packet error {code}")


def parse_aoe_error(code: int) -> str:
    u, low, high = code & 0xFFFFFFFF, code & 0xFFFF, (code >> 16) & 0xFFFF
    aoe_byte = (code >> 8) & 0xFF
    if aoe_byte in _AOE_RESULT:
        return f"AoE 0x{u:08x}: {_AOE_RESULT[aoe_byte]}"
    if high in _IOLINK_ISDU:
        return f"IO-Link ISDU 0x{high:04x}: {_IOLINK_ISDU[high]} (result 0x{u:08x})"
    if u in _ADS_ERR:
        return f"ADS 0x{u:03x}: {_ADS_ERR[u]}"
    if low in _AOE_RESULT:
        return f"AoE 0x{u:08x}: {_AOE_RESULT[low]}"
    if 0x700 <= u <= 0x7FF:
        return f"ADS device error 0x{u:03x}"
    return f"unknown AoE/ADS error 0x{u:08x}"


def isdu_access_hint(isdu_index: int, *, writing: bool) -> str:
    acc = _IOLINK_ACCESS.get(isdu_index)
    if not acc or (writing and "w" in acc) or (not writing and "r" in acc):
        return ""
    mode = "read only" if "w" not in acc else "write only"
    return f" (index 0x{isdu_index:04x} is {acc!r} — {mode})"
