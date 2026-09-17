# barnex-inverter-maps

Public register-map index for [esp32_coordinator](https://github.com/bobyk/esp32_coordinator)'s
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
      "file": "maps/deye_hybrid_full.json",
      "label": "Deye Hybrid — full (power + energy counters)",
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
- `sha256` — lowercase hex SHA-256 of the exact committed bytes of `file`.
  Recompute and update this whenever a map file changes, even for
  whitespace-only edits — this is an integrity check independent of the
  map's own internal `checksum` field (which only hashes semantic register
  content).

## `maps/`

Register maps themselves, in the format documented by
[`docs/INVERTER_MAP.md`](https://github.com/bobyk/esp32_coordinator/blob/main/docs/INVERTER_MAP.md)
in the coordinator's own repo.

## Contributing a map

1. Add your map JSON under `maps/`.
2. Add an entry to `index.json` with its `vendor`, `file`, a short `label`,
   and its `sha256` (`shasum -a 256 maps/your_map.json`).
3. Bump `updated_at`.
4. Open a PR.

Only entries whose `vendor` string matches what the coordinator's Modbus
identification can actually produce will ever be auto-fetched — check
`src/ModbusScan/InverterVendors.cpp` in the coordinator repo for the current
list before assuming a new vendor string will be reachable automatically.
