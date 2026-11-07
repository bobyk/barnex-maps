# Inverter register maps

An inverter map tells the [Barnex](https://barnex.io) controller which Modbus
registers hold grid, PV, load and battery readings on a given inverter. One
JSON file per inverter family; adding a brand is a new file, not a firmware
release.

Files live in [`maps/`](../maps) and are listed in [`index.json`](../index.json)
(see [index format](#indexjson)).

## Safety boundary

**An inverter map only reads telemetry.** It cannot change load thresholds,
import limits or breaker protection, and the firmware never sends a Modbus
write (function codes 6 and 16) from a map. Entries marked `"access": "write"`
are parsed and kept so the file round-trips, but never sent to the inverter.
A wrong map can make the controller read garbage, which the
[fail-safe](#fail-safe) catches, but it cannot switch anything on.

That is why inverter maps are not signed and charger maps with commands are
(see [charger-maps.md](charger-maps.md#signing)).

## Example

```json
{
  "brand": "growatt",
  "model": "SPH-6000",
  "protocol_version": "RTU_II",
  "created_at": "2026-08-04T12:00:00Z",
  "transport": { "type": "tcp", "port": 502, "slave_id": 1, "byte_order": "big_endian" },
  "register_map": [
    { "name": "pv_power",    "address": 3007, "function_code": 4, "data_type": "uint32", "scale": 0.1, "unit": "W", "access": "read" },
    { "name": "battery_soc", "address": 3171, "function_code": 4, "data_type": "uint16", "scale": 1,   "unit": "%", "access": "read" }
  ]
}
```

## Top-level fields

| field | required | notes |
|---|---|---|
| `brand` | yes | up to 19 characters, shown in the UI |
| `model` | yes | up to 27 characters |
| `protocol_version` | no | free text, up to 19 characters, e.g. `RTU_II` |
| `created_at` | no | ISO 8601 author timestamp; must parse if present |
| `checksum` | no | content hash, see [Checksum](#checksum) |
| `phases` | no | `1` or `3`. A Deye whose device-type register (holding 0) says three-phase is only polled through a map that declares `"phases": 3`; the firmware ships the two Deye three-phase maps built in and applies them by device type |
| `transport` | yes | see below |
| `register_map` | yes | 1 to 48 entries, at least one readable |

## `transport`

| field | default | notes |
|---|---|---|
| `type` (alias `modbus_type`) | `tcp` | `tcp` or `rtu` |
| `port` (alias `default_port`) | `502` | TCP only, 1–65535. A port the installer saved during discovery wins |
| `slave_id` | `1` | 1–247 |
| `byte_order` | `big_endian` | `big_endian` (ABCD), `little_endian` (DCBA), `big_endian_word_swap` (CDAB), `little_endian_word_swap` (BADC) |
| `baud` | `9600` | RTU only, 1200–921600 |
| `serial_config` | `8N1` | RTU only: `8N1`, `8N2`, `8E1`, `8O1`, `7E1` |
| `merge_gap` | `24` | 0–48. How many unused registers the reader may read to merge two entries into one request. Raise it only for inverters that tolerate reading holes (Deye three-phase maps use 40) |

## `register_map` entries

| field | required | notes |
|---|---|---|
| `name` | yes | unique, up to 39 characters. A [canonical name](#canonical-names) feeds the control logic |
| `address` | yes | 0–65535, **0-based wire address** |
| `function_code` | yes | 3 or 4 for readable entries (6/16 are kept but never sent) |
| `data_type` | yes | `uint16`/`u16`, `int16`/`i16`/`s16`, `uint32`/`u32`, `int32`/`i32`/`s32`, `float`/`float32`/`f32` (IEEE-754, two registers) |
| `scale` | no (1) | non-zero finite multiplier, applied before `scale_register` |
| `unit` | no | `W`/`kW`, `Wh`/`kWh`/`MWh`, `V`/`mV`/`kV`, `A`/`mA`, `Hz`, `%`; converted to the canonical unit |
| `access` | no (`read`) | `read`, `write`, `read_write` |
| `byte_order` | no | per-entry override of the transport default (32-bit types) |
| `slave_id` | no | per-entry override, for several devices on one RS485 bus |
| `min_refresh_s` | no (0) | 0–3600, see [Slow registers](#slow-registers) |
| `bit` | no | 0–15, 16-bit types only, not with `scale_register`. The value becomes that single bit (0/1) |
| `scale_register` | no | address of a SunSpec-style scale factor, see [Dynamic scale factor](#dynamic-scale-factor) |

### Canonical names

Entries with these names drive the controller exactly like its built-in Deye
reader does:

`grid_power` (W, **+import / −export**) · `pv_power` · `pv1_power` ·
`pv2_power` · `load_power` · `battery_power` (W, **+charging / −discharging**) ·
`battery_soc` (%) · `grid_voltage` · `load_voltage` · `grid_frequency` ·
`today_pv_energy` · `total_pv_energy` · `today_import_energy` ·
`today_export_energy` · `total_import_energy` · `total_export_energy` ·
`today_load_energy` · `total_load_energy` · `today_battery_charge_energy` ·
`today_battery_discharge_energy` · `total_battery_charge_energy` ·
`total_battery_discharge_energy` · `grid_relay` (1 = on grid) ·
`grid_fault` (1 = **not** on grid, inverted polarity)

Per phase (3-phase maps; L1 voltage is `grid_voltage`):
`grid_power_l1` · `grid_power_l2` · `grid_power_l3` (W, **+import / −export**) ·
`grid_voltage_l2` · `grid_voltage_l3` (V) ·
`ct_int_current_l1` · `ct_int_current_l2` · `ct_int_current_l3` (internal CT, signed A) ·
`ct_ext_current_l1` · `ct_ext_current_l2` · `ct_ext_current_l3` (external CT, signed A) ·
`inverter_power_l1` · `inverter_power_l2` · `inverter_power_l3` (inverter output, W).
The controller checks which CT set agrees with power/voltage and uses that one
for the phase current; with neither it uses power/voltage alone.

Aliases: `grid_active_power`, `meter_power`, `pv_total_power`, `solar_power`,
`consumption_power`, `soc`, `grid_freq`, `grid_connected`, `grid_failure`.

- `pv_power` is computed from `pv1_power + pv2_power` when only the strings
  are listed.
- If both `grid_relay`/`grid_connected` and `grid_fault` are present, the
  first two win.
- Other names are read and validated but not used yet, so a richer map does
  not break on older firmware.

### Sign convention (mandatory)

`grid_power`: positive = importing, negative = exporting.
`battery_power`: positive = charging, negative = discharging.
If the inverter's register uses the opposite polarity, flip it with a negative
`scale` (e.g. `-1` or `-0.1`). Write the source's original convention in the
index `notes`.

## Slow registers

`min_refresh_s` means "do not re-read this entry until N seconds have passed
since the last good read; keep the last value until then". It is wall-clock
time, not a poll count. Use it for energy counters (`300` is typical) so the
fast power/SOC registers fit into one request every poll. A held value is
never replaced with zero.

## Dynamic scale factor

SunSpec devices (SolarEdge, Fronius "int+SF", SMA SunSpec) store a raw integer
plus a separate int16 scale-factor register: `value = raw × 10^sf`. Point the
value entry at it:

```json
{ "name": "pv_power", "address": 40100, "function_code": 3,
  "data_type": "int16", "scale_register": 40095, "unit": "W", "access": "read" }
```

`value = raw × scale × 10^sf × unit factor`. Several entries may share one
`scale_register`.

The value and its scale factor are always read in the same request, so they
must be within **64 registers** of each other. A map that breaks this is
rejected when loaded (and by `tools/update_index.py`).

### "Not implemented" sentinels

These raw values mean "no data"; the entry keeps its previous value instead
of publishing a fake zero:

| type | sentinel |
|---|---|
| `uint16` | `0xFFFF` |
| `int16` | `0x8000` |
| `uint32` | `0xFFFFFFFF` |
| `int32` | `0x80000000` |
| `float32` | NaN / Inf |
| scale factor | `0x8000` |

## Checksum

Optional. A SHA-256 over the *meaning* of the register table, so
re-indenting or reordering keys does not break it:

```
sha256( "name:address:function_code:data_type:scale;" per entry, in file order,
        + "b<bit>;" right after an entry that has "bit" )
```

`scale` is formatted as `%.6f`; `data_type` uses the canonical spelling
(`uint16`, `int16`, `uint32`, `int32`, `float`). A prefix of 8+ hex characters
is accepted.

```bash
python3 tools/inverter_map_checksum.py maps/your_map.json          # print
python3 tools/inverter_map_checksum.py --write maps/your_map.json  # write into file
```

This is separate from the index `sha256`, which hashes the exact file bytes.

## `index.json`

```json
{
  "schema_version": 1,
  "updated_at": "2026-09-22T13:00:00Z",
  "maps": [
    {
      "vendor": "Deye",
      "file": "maps/deye_hybrid_native_equivalent.json",
      "label": "Deye Hybrid — native-equivalent (matches built-in reader)",
      "status": "verified",
      "source": ["https://github.com/<owner>/<repo>/blob/<commit-sha>/<path>"],
      "models": ["SUN-*K-SG0*LP1"],
      "notes": "caveats, required inverter settings, known gaps",
      "sha256": "<sha256 of the file bytes>"
    }
  ]
}
```

| field | notes |
|---|---|
| `vendor` | matched case-insensitively against the vendor the controller detects over Modbus. Several entries may share a vendor; the installer then picks one |
| `file` | path from the repo root |
| `label` | shown as-is in the picker |
| `status` | `verified` (checked on real hardware) or `unverified` (badged in the UI) |
| `source` | upstream register tables, each **pinned to a commit SHA** |
| `models` | optional list of models the map covers |
| `notes` | optional; keep short, the device downloads the whole index |
| `sha256` | lowercase hex SHA-256 of the file bytes; `tools/update_index.py` fills it in |

Unknown keys are ignored, so new informational fields do not need a firmware
update.

## How the controller uses a map

1. **Auto-fetch.** When an installer saves an inverter with a detected vendor
   and no map is active, the controller downloads `index.json`, matches
   `vendor`, downloads the file, checks it against the index `sha256` and
   applies it. If several maps match, it asks the installer to pick; if none
   match, it offers the whole catalogue.
2. **Manual.** A map can also be uploaded locally from the installer page or
   pushed from the Barnex cloud. Same validation, same error messages.
3. **Validation errors** name the field and the reason, e.g.
   `register_map[3].scale: must be a non-zero finite number`. A rejected map
   never replaces the running one.

### Fail-safe

- The previous map is kept. Five failed polls in a row after a new map
  arrives roll back to it automatically (at most once per boot, and never
  across brands).
- A map restored from flash at boot is never rolled back automatically, so a
  Wi-Fi outage does not change configuration.
- Configuration errors (bad JSON, bad field) and read errors (timeout, CRC,
  Modbus exception) are counted separately: one is a file problem, the other
  is wiring or network.

## Vendor notes

### SunSpec in general

- Look for the `"SunS"` marker (`0x53756e53`) at base **40000**, and also try
  **0** and **50000**.
- Models form a chain: `(model_id, length)` header, data, next header, ending
  with `0xFFFF`. "Model 103" has no fixed address; it depends on what comes
  before it.
- Maps here use **fixed addresses** (no chain walking on the device), so
  state the base address the map assumes in the index `notes`.
- **0- vs 1-based:** SunSpec documents registers 1-based ("40001" is the first
  holding register); `address` here is the 0-based wire address. This
  off-by-one is the most common SunSpec bug.

### SolarEdge

- Inverter telemetry: SunSpec models 101/102/103 (int+SF).
- The meter (model 203) is on its **own unit id** (1, 2 or 3); use
  `slave_id` to target it.
- Battery and detailed meter data are in the proprietary range from
  `0xE100` (57600): plain `float32`, no scale factor. Source those addresses
  from a document that covers them; do not extrapolate.

### Fronius

- The installer chooses "SunSpec Model Type" in the inverter: **int+SF**
  (models 101/103/160/124) or **float** (111/113). A map for one setting
  misreads the other, so ship both variants and name the required setting in
  `notes`.
- The Smart Meter is a separate device, usually **unit id 240**.

### SMA

- Prefer the **native** profile: unit id 3, registers 30xxx, fixed scale,
  `int32`/`uint32`. Its "not available" values match the sentinels above.
- Fall back to SunSpec int+SF (unit id 126) only when the native profile is
  not documented for that model.

## Related

- [Charger maps](charger-maps.md)
- [Contributing](../README.md#contributing)
- Supported hardware: [barnex.io/en/compatibility](https://barnex.io/en/compatibility)
