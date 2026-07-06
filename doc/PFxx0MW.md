# IO-Link Interface Spec (AI-ready)

Source manual: `PFxx-OMW0007-E` (SMC Digital Flow Switch, Integrated display type)

Target device family: `PF2M7xx` (Digital Flow Switch)

This document converts the IO-Link sections of the manual into an implementation-ready reference for:
- Process Data parsing (cyclic input)
- PD (process data) <-> flow conversion
- ISDU/service access (direct parameters and parameter download via IO-Link)
- Diagnostic / event code mapping

---

## 1) IO-Link communication basics

### 1.1 Supported IO-Link features
- Cyclic data communication (process data)
- On-request data communication: available
- Data storage function: available (backup/restore at the master)
- Event function: available

### 1.2 Communication settings (as stated in the manual)
- IO-Link version: `V1.1`
- Communication speed: `COM2` (`38.4 kbps`)
- Minimum cycle time: `3.4 ms`

### 1.3 Process data length (important discrepancy)
The manual states two different values in different sections:
- In `IO-Link Specifications` (process data section): **Input Data = 6 byte**, Output Data = 0 byte
- In `Communication (During IO-Link mode)` (later specifications section): **Input Data = 4 byte**, Output Data = 0 byte

Given the explicit bit mapping in the process data table uses bits **0..31** (i.e., exactly **32 bits**), the effective process data word is consistent with **4 bytes**.

Implementation recommendation:
- Treat the cyclic input process data as a **32-bit word** (`pd32`) and parse bits as specified below.
- When configuring your IO-Link master, prefer **Input Data length = 4 bytes** unless your specific master requires 6 bytes exactly.

---

## 2) Cyclic Process Data (PD) - Input Data (32-bit word)

### 2.1 Endianness
- The manual states: **process data is Big-Endian type**
- If your upper communication uses **Little-Endian**, the **byte order will be changed**.

Implementation recommendation:
- Receive the 4 bytes from the master.
- Convert them into a `uint32` in the **manual-defined bit numbering** order, respecting Big-Endian as required by your stack/master.

### 2.2 Bit mapping (bits 0..31)
The process data contains switch output status, diagnostic flags, and flow measurement value.

Let `pd32` be the 32-bit process data container, where bit offsets correspond to the manual table.

Bits:
- `bit 0`: `OUT1 output` (`0=OFF`, `1=ON`)
- `bit 1`: `OUT2 output` (`0=OFF`, `1=ON`)
- `bit 8`: `Measurement diagnostics` (`0=Within range`, `1=Out of range (HHH/LLL)`)
- `bit 14`: `Fixed output` (`0=Normal output`, `1=Fixed output`)
- `bit 15`: `Error Diagnosis` (`0=Error not generated`, `1=Error generated`)
- `bits 16..31`: `Flow measurement value (PD)` (`16-bit signed`)

### 2.3 Reference extraction pseudocode
```text
out1 = (pd32 >> 0) & 0x1
out2 = (pd32 >> 1) & 0x1
meas_diag = (pd32 >> 8) & 0x1
fixed_output = (pd32 >> 14) & 0x1
error_diag = (pd32 >> 15) & 0x1

pd_raw_u16 = (pd32 >> 16) & 0xFFFF
pd_raw_s16 = sign_extend_16_to_int(pd_raw_u16)   // interpret bits 16..31 as signed 16-bit
flow = a * pd_raw_s16 + b
```

---

## 3) PD <-> Flow conversion (Pr = a * PD + b)

The manual provides conversion equations:
- From process data to flow measurement value:
  - `Pr = a * (PD) + b`
- From flow measurement value to process data:
  - `(PD) = (Pr - b) / a`

Where:
- `Pr` = flow measurement value (and pressure set value)
- `PD` = flow measurement value (process data, signed 16-bit)
- `a` = inclination
- `b` = intercept

### 3.1 a/b values from the unit/range table (PF2M7 series)
For `L/min`:
- 1 L range:   `a = 0.00025`,  `b = 0`
- 2 L range:   `a = 0.0005`,   `b = 0`
- 5 L range:   `a = 0.00125`,  `b = 0`
- 10 L range:  `a = 0.0025`,   `b = 0`
- 25 L range:  `a = 0.00625`,  `b = 0`
- 50 L range:  `a = 0.0125`,   `b = 0`
- 100 L range: `a = 0.025`,     `b = 0`

For `Cfm x 10^-3` (as stated):
- 1 L:   `a = 0.0088275`,  `b = 0`
- 2 L:   `a = 0.0176575`,  `b = 0`
- 5 L:   `a = 0.00004415`, `b = 0`
- 10 L:  `a = 0.000088275`,`b = 0`
- 25 L:  `a = 0.000220725`,`b = 0`
- 50 L:  `a = 0.0004415`, `b = 0`
- 100 L: `a = 0.00088275`, `b = 0`

### 3.2 Example (from manual)
- PF2M7 series, `L/min`, flow range 25 L, `PD = 3000`:
  - `Pr = 0.00625 * 3000 + 0 = 18.75 L/min`
- PF2M7 series, `L/min`, flow range 100 L, `Pr = 50`:
  - `PD = (50 - 0) / 0.025 = 2000`

### 3.3 Recommended runtime source for a and b (read via IO-Link parameters)
The manual also exposes the conversion equation as readable parameters:
- `8000 (0x1F40)` : `PD conversion equation :: a` (F32)
- `8010 (0x1F4A)` : `PD conversion equation :: b` (F32)

Recommendation:
- Prefer reading `a` and `b` from the device (via parameter download / ISDU / master parameter access) rather than hard-coding the table.

---

## 4) IO-Link Device Description (IODD) naming

The manual states that the IODD can be downloaded from SMC.

IODD file naming pattern (placeholders kept as in manual):
- `SMC-PF2M7<S> - <...> - L<...> - <yyyymmdd> - IODD1.1`

Meaning of placeholders:
- `S` includes parts of product number (device-specific encoding)
- `yyyymmdd` = file preparation date

---

## 5) ISDU / Service data (indices and commands)

### 5.1 System command (ISDU index `0x0002`)
Writable system commands (8-bit UInteger):
- `128`: `Device Reset` (restarts the device)
- `129`: `Application Reset`
  - reset peak/bottom values
  - reset accumulated flow value
- `130`: `Restore Factory Reset` (initialize set values to default)
- `160`: `Zero clear` (conduct a zero-clear function)
- `170`: `Flow peak/bottom Reset` (reset peak/bottom value)
- `190`: `Integrated flow Reset` (reset accumulated flow value)

### 5.2 Device access lock parameter (ISDU index `0x000C`)
16-bit Record:
- `0`: Key lock release, DS unlock (initial value)
- `2`: Key lock release, DS lock
- `8`: Key lock, DS unlock
- `10`: Key lock, DS lock

Description:
- Key-lock prevents physical changes via buttons (button operations not accepted)
- Even with key-lock active, settings can be changed via IO-Link communication
- DS lock invalidates data storage function (backup/restore denied)

### 5.3 Device status parameters (ISDU index `0x0024`)
8-bit UInteger:
- `0`: Normal operation
- `1`: Maintenance inspection required (Not available)
- `2`: Outside specification range (outside flow measurement range; below range)
- `3`: Function check (Not available)
- `4`: Failure (internal failure of digital flow switch)

### 5.4 Device detailed state / event codes (ISDU index `0x0025` and/or `0x0027` section shows as `index 37`)
The manual table for “Device detail status parameters” lists readable event contents using an array.

Readable device status events are shown in section `Device detail status parameters (index 37)`.

Each array entry includes:
- Event content
- Event classification
- Event code

Event mapping (as extracted):
- Internal failure of digital flow switch (Error classification `0xF4`)
  - Event code `0x8D03`
  - Event code `0x8D04`
  - Event code `0x8D05`
  - Event code `0x8D01`
  - Event code `0x8D06`
  - Event code `0x8D08`
- OUT2 over current error (Error `0xF4`): `0x8CC0`
- Outside accumulated flow measurement warning (Warning `0xE4`): `0x8D80`
- Outside instantaneous flow measurement warning (Warning `0xE4`):
  - `0x8C10`
  - `0x8C30`
- Test event A warning (Warning `0xE4`): `0x8CA0`
- Test event B warning (Warning `0xE4`): `0x8CA1`
- Data storage upload request notification (classification `0x54`): `0xFF91`

Note:
- The manual explicitly labels the table as `index 37`, but it is located in the IO-Link ISDU parameter section where `index 37` corresponds to “Device detailed state parameter”.
- The exact ISDU index number for “Device detailed state” is shown as `0x0025` in the ISDU list, and the device detailed status table is labelled as `index 37`. When implementing, validate the master access path against your IO-Link stack / IODD.

### 5.5 Process data input via ISDU (ISDU index `0x0028`)
- `0x0028`: `Process data input` (read latest value of process data)

---

## 6) Direct parameters page (DPP1) - Vendor ID and Device ID

The manual lists “Direct parameters page 1”.

DPP1 (as extracted):
- DPP1 address `0x07`: Vendor ID
  - Initial value: `0x0083` (131)
  - Text: “SMC Corporation”
- DPP1 address `0x08` and `0x09`: Device ID
  - Initial values shown as multiple IDs depending on product No.
  - Device ID values present in manual extraction:
    - `0x00016D (365)` through `0x000188 (392)`
    - `0x00023B (571)` through `0x00023E (574)`

Implementation note:
- Your master may already expose Vendor ID and Device ID directly; the key part is to avoid assuming a single Device ID across all PF2M7 variants.

---

## 7) Product individual parameters (index/sub-index mapping)

These parameters are used to configure the device behavior (OUT1/OUT2, units, filters, IO-Link mode screen, analogue output settings, and to read back conversion parameters).

Symbols:
- `R/W`: read/write
- `Y` in “Data storage”: setting is saved to master (backup/restore behavior)
- `N`: not saved

### 7.1 General / display / unit selection
Index `1000 (0x03E8)`:
- Sub 0: `Display unit` (U8, R/W, saved Y)
  - `0`: `L/min (L)`
  - `1`: `cfm (ft3)`

Index `1010 (0x03F2)`:
- Sub 0: `Display colour` (U8, R/W, saved Y)
  - `0`: rEd (Constantly red)
  - `1`: Grn (Constantly green)
  - `2`: 1SoG (OUT1 turns green at ON)
  - `3`: 1Sor (OUT1 turns red at ON)
  - `4`: 2SoG (OUT2 turns green at ON)
  - `5`: 2Sor (OUT2 turns red at ON)

Index `1020 (0x03FC)`:
- Sub 0: `NPN/PNP switching` (U8, R/W, saved Y)
  - `0`: nPn
  - `1`: PnP

Index `1030 (0x0406)`:
- Sub 0: `Selection of external input` (U8, R/W, saved Y)
  - `0`: oUt (Switch output)
  - `1`: in (Exterior input)
  - Output type constraint: “L2 only”

Index `1060 (0x0424)`:
- Sub 0: `Fluid` (U8, R/W, saved Y)
  - `0`: Air
  - `1`: Ar
  - `2`: Co2

Index `1070 (0x042E)`:
- Sub 0: `Normal condition` (U8, R/W, saved Y)
  - `0`: std
  - `1`: nor

### 7.2 OUT1 configuration
Index `1210 (0x04BA)`:
- Sub 1: `OUT1 setting - Output operation mode` (U8, R/W, saved Y)
  - `0`: HYS (Hysteresis)
  - `1`: Wind (Window comparator)
  - `2`: AC (Accumulated output)
  - `3`: PLS (Accumulated pulse output)
  - `4`: Err (Error output)
  - `5`: oFF (Output OFF)
- Sub 2: `Output type` (U8, R/W, saved Y)
  - `0`: 1_P (Normal output)
  - `1`: 1_n (Reverse output)

Index `1220 (0x04C4)`:
- Sub 1: `Hysteresis setting value` (S16, R/W, saved Y)
  - range: `-200 .. 4200` (Hysteresis mode)
- Sub 2: `Hysteresis` (S16, R/W, saved Y)
  - range: `0 .. 4400`
- Sub 3: `Lower limit of window comparator` (S16, R/W, saved Y)
  - range: `-200 .. 4200`
- Sub 4: `Upper limit of window comparator` (S16, R/W, saved Y)
  - range: `-200 .. 4200`
- Sub 5: `Window comparator hysteresis` (S16, R/W, saved Y)
  - range: `0 .. 2200`
- Sub 6: `Delay time` (S16, R/W, saved Y)
  - range: `0 .. 6000`

Index `1300 (0x0514)` (Accumulated output, unit L):
- Sub 1: `Accumulated output set value L` (S16, R/W, saved Y)
  - range: `0 .. 9999`
- Sub 2: `Accumulated output index L` (S16, R/W, saved Y)
  - depends on the configured flow range:
    - ranges `1, 2`: `-2 .. 3`
    - ranges `5, 10`: `-1 .. 4`
    - ranges `25, 50, 100, 200`: `0 .. 5`

Index `1310 (0x051E)` (Accumulated output, unit ft3):
- Sub 1: `Accumulated output set value ft3` (S16, R/W, saved Y)
  - range: `0 .. 9999`
- Sub 2: `Accumulated output index ft3` (S16, R/W, saved Y)
  - ranges `1, 2, 5, 10, 25, 50`: `-2 .. 3`
  - ranges `100, 200`: `-1 .. 4`

### 7.3 OUT2 configuration
Index `1410 (0x0582)`:
- Sub 1: `OUT2 setting - Output operation mode` (U8, R/W, saved Y)
  - `0`: HYS
  - `1`: Wind
  - `2`: AC
  - `3`: PLS
  - `4`: Err
  - `5`: oFF
- Sub 2: `Output type` (U8, R/W, saved Y)
  - `0`: 2_P (Normal output)
  - `1`: 2_n (Reverse output)

Index `1420 (0x058C)`:
- Sub 1: `Hysteresis set value` (S16, R/W, saved Y)
  - range: `-200 .. 4200`
- Sub 2: `Hysteresis` (S16, R/W, saved Y)
  - range: `0 .. 4400`
- Sub 3: `Lower limit of window comparator` (S16, R/W, saved Y)
  - range: `-200 .. 4200`
- Sub 4: `Upper limit of window comparator` (S16, R/W, saved Y)
  - range: `-200 .. 4200`
- Sub 5: `Window comparator hysteresis` (S16, R/W, saved Y)
  - range: `0 .. 2200`
- Sub 6: `Delay time` (S16, R/W, saved Y)
  - range: `0 .. 6000`

Index `1500 (0x05DC)` (Accumulated output, unit L):
- Sub 1: `Accumulated output set value L` (S16, R/W, saved Y)
  - range: `0 .. 9999`
- Sub 2: `Accumulated output index L` (S16, R/W, saved Y)
  - depends on configured flow range (same structure as OUT1 L index).

Index `1510 (0x05E6)` (Accumulated output, unit ft3):
- Sub 1: `Accumulated output set value ft3` (S16, R/W, saved Y)
  - range: `0 .. 9999`
- Sub 2: `Accumulated output index ft3` (S16, R/W, saved Y)
  - depends on configured flow range (same structure as OUT1 ft3 index).

### 7.4 Accumulated flow logic / filtering / display / IO mode
Index `1600 (0x0640)`:
- Sub 0: `Accumulated flow output direction` (U8, R/W, saved Y)
  - `0`: Add (Addition)
  - `1`: dEC1 (Subtraction OUT1)
  - `2`: dEC2 (Subtraction OUT2)

Index `1800 (0x0708)`:
- Sub 0: `Digital filter` (U8, R/W, saved Y)
  - `0`: 0.05 sec
  - `1`: 0.1 sec
  - `2`: 0.5 sec
  - `3`: 1.0 sec
  - `4`: 2.0 sec
  - `5`: 5.0 sec

Index `2000 (0x07D0)`:
- Sub 0: `Display mode` (U8, R/W, saved Y)
  - `0`: inS (Instantaneous flow)
  - `1`: AC (Accumulated flow)
  - `2`: ioL (IO-Link mode)

Index `2010 (0x07DA)`:
- Sub 0: `Display resolution` (U8, R/W, saved Y)
  - `0`: 1000 resolution
  - `1`: 100 resolution
  - only available for certain models/ranges (manual note: for 1 L, 10 L and 100 L)

Index `2020 (0x07E4)`:
- Sub 0: `Reversed Display` (U8, R/W, saved Y)
  - `0`: oFF (not reversed)
  - `1`: on (reversed)

Index `2030 (0x07EE)`:
- Sub 0: `Zero cut-off range setting` (S8, R/W, saved Y)
  - range: `0 .. 10 [%]`
  - note: “Zero cut-off” expressed in percent of F.S.

### 7.5 External input behavior
Index `2040 (0x07F8)`:
- Sub 0: `Exterior input` (U8, R/W, saved Y)
  - `0`: oFF
  - `1`: rAC (Reset accumulation)
  - `2`: rPb (Reset peak/bottom value)
  - output type constraint: “L2 only”

### 7.6 Analogue output configuration (when device supports it)
Index `2100 (0x0834)` (Analogue voltage output):
- Sub 0: `Analogue voltage output` (U8, R/W, saved Y)
  - `0`: 1 to 5 V
  - `1`: 0 to 10 V (only when power supply supports 24 VDC)
  - output type constraint: “L2 only”

Index `2110 (0x083E)` (Analogue free span function):
- Sub 1: `Analogue free span ON/OFF` (U8, R/W, saved Y)
  - `0`: oFF
  - `1`: on
- Sub 2: `Analogue free span set value` (S16, R/W, saved Y)
  - range: `400 .. 4200`

Index `2200 (0x0898)`:
- Sub 0: `Accumulated-value holding function` (U8, R/W, saved Y)
  - `0`: oFF
  - `1`: 2.0 min
  - `2`: 5.0 min

Index `2400 (0x0960)`:
- Sub 0: `Display OFF mode` (U8, R/W, saved Y)
  - `0`: on
  - `1`: oFF

Index `2410 (0x0960)` (Security code):
- Sub 1: `Security code Used/Not used` (U8, R/W, saved Y)
  - `0`: invalid
  - `1`: valid
- Sub 2: `Security code` (S16, R/W, saved Y)
  - range: `0 .. 999`

### 7.7 Communication test / diagnostics parameters
Index `7000 (0x1B58)`:
- Sub 0: `Communication OUT output test` (U8, WO, not stored Y)
  - `0`: Normal output
  - `1`: Fixed (Fixed output)

Index `7010 (0x1B62)`:
- Sub 0: `Toggle output` (U8, WO, not stored Y)
  - `0`: Flow rate
  - `16`: OUT1
  - `17`: OUT2
  - `80`: Analogue output
  - `224`: Diagnostic bit
  - `255`: Error bit
  - manual note: effective only when OUT output test is set to “fixed”

Index `7100 (0x1BBC)`:
- Sub 0: `Analogue output check` (F32, read-only, not stored Y)
  - Voltage output: unit `0.1 V`
  - Current output: unit `1 mA`
  - current analogue output value is returned

### 7.8 PD conversion equation and measurement snapshots (read-only)
Index `8000 (0x1F40)`:
- Sub 0: `PD conversion equation :: a` (F32, read-only)

Index `8010 (0x1F4A)`:
- Sub 0: `PD conversion equation :: b` (F32, read-only)

Index `8020 (0x1F54)`:
- Sub 1: `Instantaneous flow peak value` (S16, read-only, range `-200 .. 4000`)
  - conversion method equals process data conversion

Index `8030 (0x1F5E)`:
- Sub 1: `Instantaneous flow bottom value` (S16, read-only, range `-200 .. 4000`)

Index `8040 (0x1F68)`:
- Sub 1: `Accumulated flow value measured value (temporary)` (S16, read-only, range `0 .. 9999`)
- Sub 2: `Accumulated measured value (index)` (S16, read-only, range `-2 .. 5`)
  - reply corresponds to product range and unit selection

---

## 8) Device display error indications (context for diagnostics)

The manual also lists display errors (not IO-Link events directly). Useful for validating behavior.

Errors:
- Instantaneous flow error:
  - flow exceeding upper limit of set flow range
  - or flow below the lower limit
- OUT1 over current error:
  - load current exceeded maximum value (OUT1)
- OUT2 over current error:
  - load current exceeded maximum value (OUT2)
- Zero clear error:
  - during zero-clear operation, pressure greater than `±5% F.S.` applied
- System error:
  - internal data error
- Accumulated flow error:
  - accumulated flow exceeded accumulated flow range (flashing)
  - or accumulated flow reached set accumulated flow
- Version does not match:
  - master and device IO-Link version mismatch (notably: master version is 1.0)

---

## 9) Implementation checklist (quick)

1. Parse 4-byte (32-bit) cyclic input `pd32`:
   - out1/out2 flags
   - measurement diagnostics + fixed output + error diagnosis
   - signed 16-bit flow PD at bits 16..31
2. Convert signed flow PD to engineering units:
   - `flow = a*PD + b`
   - prefer reading `a`/`b` from indices `8000` and `8010`
3. Configure outputs via parameter indices:
   - OUT1: `1210` + `1220` or `1300/1310` depending on mode and unit
   - OUT2: `1410` + `1420` or `1500/1510`
4. Read diagnostics/events via “Device detailed status” event code table:
   - ISDU index `37` table entries include event codes such as `0x8D03`, `0x8CC0`, warnings `0x8D80`, etc.
5. Implement system commands (ISDU index `0x0002`):
   - reset flows/peak-bottom and factory reset
   - zero clear

---

## 10) Open items / assumptions

- The manual indicates conflicting process data length (6 bytes vs 4 bytes). This document assumes 4 bytes because bit mapping uses bits 0..31.
- The manual lists “Device detailed state parameter” and separately labels the events table as “index 37”. When implementing, confirm the actual ISDU index mapping through the IODD (or your master’s parameter list).

