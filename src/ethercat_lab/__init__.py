"""EtherCAT lab REPL."""

from pysoem import State

from .master import Master, CoeTransfer
from .pdo import PdoMapping, PdoAssignment, TxPdoAssignment, RxPdoAssignment
from .beckhoff_device import BeckhoffDevice
from .el6224 import (
    EL6224,
    IoLinkChannelConfig as EL6224ChannelConfig,
    IOLinkIsduChannel,
    PdWireLayout,
    all_channel_coe_writes,
    encode_pd_settings_byte,
    decode_pd_settings_byte,
    PortStatusError,
    PortStatusFlag,
    PortStatusMode,
    decode_port_status_byte,
)
from .el3072 import (
    EL3072,
    AnalogInputChannel,
    InputInterface,
    PdoMode,
    UserScaleConfig,
    LimitConfig,
    RangeErrorConfig,
    IIRFilter,
    LimitTriggerType,
    decode_limit_trigger,
    INPUT_10V,
    INPUT_20MA,
)
from .aoe import (
    DEFAULT_MASTER_NETID, INDEX_GROUP_COE, COE_SLAVE_NETID_INDEX, COE_SLAVE_NETID_SUB,
    coe_index_offset, parse_aoe_error,
)

__all__ = [
    "Master", "CoeTransfer", "State", "PdoMapping", "PdoAssignment", "TxPdoAssignment", "RxPdoAssignment",
    "BeckhoffDevice",
    "EL6224", "EL6224ChannelConfig", "IOLinkIsduChannel", "PdWireLayout",
    "encode_pd_settings_byte", "decode_pd_settings_byte",
    "all_channel_coe_writes",
    "PortStatusError", "PortStatusFlag", "PortStatusMode",
    "decode_port_status_byte",
    "EL3072", "AnalogInputChannel", "UserScaleConfig", "LimitConfig", "RangeErrorConfig",
    "IIRFilter", "LimitTriggerType", "decode_limit_trigger",
    "InputInterface", "PdoMode",
    "INPUT_10V", "INPUT_20MA",
    "DEFAULT_MASTER_NETID", "INDEX_GROUP_COE", "COE_SLAVE_NETID_INDEX", "COE_SLAVE_NETID_SUB",
    "coe_index_offset", "parse_aoe_error",
]
