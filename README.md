# barnex-inverter-maps

Public register-map index for [esp32_coordinator](https://bitbucket.org/bobyk/esp32_coordinator)'s
auto-fetch feature. When the coordinator identifies an inverter on the Modbus
network with high confidence, it fetches a matching register map from this
repository over HTTPS and applies it automatically — no manual JSON upload
needed for supported vendors.

## `index.json`

Root-level index the device fetches first:

```json
{
  "schema_version": 1,
  "updated_at": "<ISO-8601>",
  "maps": [
    {
      "vendor": "Deye",
      "file": "maps/deye_hybrid_native_equivalent.json",
      "label": "Deye Hybrid — native-equivalent (matches built-in reader)",
      "status": "verified",
      "source": ["<upstream URL pinned to a commit SHA>", "..."],
      "models": ["<model names this map applies to>"],
      "notes": "<caveats, required device settings, known gaps>",
      "sha256": "<sha256 of the raw file bytes at that path>"
    }
  ]
}
```

- `vendor` — matched case-insensitively against the vendor string the
  coordinator's Modbus identification produces (e.g. `Deye`, `Growatt`,
  `Victron`). Multiple entries may share the same `vendor` — the device
  presents a picker to the installer when more than one map matches.
- `file` — path to the map JSON, relative to the repo root.
- `label` — shown verbatim in the coordinator's picker UI.
- `status` — `verified` (confirmed against real hardware) or `unverified`
  (sourced from a community register table but not independently confirmed
  on this specific device). The coordinator's picker UI badges `unverified`
  maps. **Only one map in this repo is `verified`** —
  `maps/deye_hybrid_native_equivalent.json`, which matches the coordinator's
  own built-in native Deye reader byte-for-byte.
- `source` — list of upstream file URLs, each pinned to the exact commit SHA
  it was read at, that every register address/scale/byte_order in the map
  traces back to. Empty only for pre-existing maps whose original provenance
  predates this field.
- `models` (optional) — the specific inverter models/series this map applies to.
- `notes` (optional) — caveats: required installer settings (e.g. Fronius's
  "SunSpec Model Type"), known gaps (missing canonical fields, unverified
  base addresses), or sign-convention subtleties.
- `sha256` — lowercase hex SHA-256 of the exact committed bytes of `file`.
  Recompute via `tools/update_index.py` whenever a map file changes, even for
  whitespace-only edits — this is an integrity check independent of the
  map's own internal `checksum` field (which only hashes semantic register
  content).

`schema_version` stays at `1` — the coordinator's JSON parser ignores unknown
keys, so `status`/`source`/`models`/`notes` are additive and don't require a
firmware update to be present in the index.

## `maps/`

Register maps themselves, in the format documented by
[`docs/INVERTER_MAP.md`](https://bitbucket.org/bobyk/esp32_coordinator/src/main/docs/INVERTER_MAP.md)
in the coordinator's own repo — including the `scale_register` field for
SunSpec-style dynamic scale factors (SolarEdge, Fronius int+SF, SMA SunSpec
fallback).

## Vendor coverage

| Vendor | Auto-detectable by the coordinator? | Maps |
|---|---|---|
| Deye | Yes (`InverterVendors.cpp`) | native-equivalent (**verified**), SG04LP3, SG01HP3/SG04HP3, microinverter |
| Growatt | Only at heuristic confidence (never auto-fetched) | SPH-6000 (legacy, unverified), GEN4, GEN3 hybrid — telemetry-only, see notes |
| Victron | Yes | Cerbo/Venus GX |
| SRNE | No detection signature | HF2430U60-100 |
| Solis | No detection signature | Hybrid RHI/RAI |
| Sofar | No detection signature | G3 Hybrid |
| Huawei | No detection signature | SUN2000 |
| Sungrow | No detection signature | SH-series |
| Fronius | No detection signature | Symo/Primo (int+SF and float variants) |
| SMA | No detection signature | native profile, SunSpec fallback |
| SolarEdge | No detection signature | SunSpec + proprietary battery/meter range |

"No detection signature" means the coordinator's `identifyInverter()` cannot
currently produce that vendor string on its own — these maps are reachable
via manual upload / MQTT push today, not the GitHub auto-fetch path, until
detection logic is added on the firmware side (tracked separately; adding
detection signatures is out of scope for this repo).

## Contributing a map

1. Add your map JSON under `maps/`, sourced from a citable upstream register
   table — **never invent or guess a register address**. Every field should
   trace to a specific line in a specific file at a specific commit.
2. Add an entry to `index.json` with `vendor`, `file`, `label`, `status`
   (start at `unverified` unless you've confirmed it on real hardware),
   `source` (the URLs you cited, pinned to commit SHA), and any `models`/
   `notes` worth recording (required device settings, sign-convention
   caveats, known gaps).
3. Run `tools/update_index.py` to validate your map against the schema and
   fill in `sha256`/`updated_at` automatically.
4. Open a PR. CI (`.github/workflows/validate.yml`) runs
   `tools/update_index.py --check` and fails on any schema violation or
   stale hash.

Only entries whose `vendor` string matches what the coordinator's Modbus
identification can actually produce will ever be auto-fetched — check
`src/ModbusScan/InverterVendors.cpp` in the coordinator repo for the current
list before assuming a new vendor string will be reachable automatically.

### Sign convention (mandatory)

Every map must normalize to: **`grid_power`: positive = importing from the
grid, negative = exporting. `battery_power`: positive = charging, negative =
discharging.** If your source's native register uses the opposite polarity,
flip it with `"scale": -1` (or fold the sign into whatever scale you're
already applying) — do not ship a map with the wrong sign. State your
source's original convention in the map's `notes` or the PR description.
