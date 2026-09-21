# barnex-maps

Public protocol-map index for [esp32_coordinator](https://bitbucket.org/bobyk/esp32_coordinator)'s
auto-fetch features — two independent branches sharing one repo and one
signing key:

- **Inverters** (`index.json` + `maps/`, the original content — renamed
  from `barnex-inverter-maps`, do not create a repo under the old name,
  see "Repo rename" below). When the coordinator identifies an inverter on
  the Modbus network with high confidence, it fetches a matching register
  map from here over HTTPS and applies it automatically.
- **Chargers** (`chargers/index.json` + `chargers/maps/`, new) — declarative
  HTTP+JSON protocol maps for EV chargers (docs/CHARGER_DISCOVERY_PROMPT.md
  §4 in esp32_coordinator). A charger map may additionally carry two signed
  *write* commands (`set_current`, `set_enabled`) — inverter maps never do
  (read-only, unsigned); see "Charger maps" below for why chargers need a
  signature and inverters don't.

Both are auto-fetched the same way: the coordinator identifies a device
(Modbus vendor string for inverters, HTTP detect rules for chargers),
downloads the matching map over HTTPS, and applies it — no manual JSON
upload needed for supported vendors.

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
| Luxpower | No detection signature | LXP/SNA hybrid (EG4 and other rebrands) — RTU only, see notes |
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

## Repo rename

This repo was renamed from `barnex-inverter-maps` to `barnex-maps` when
charger-map support was added — it now covers two device families, not just
inverters. GitHub redirects the old name automatically; existing
`raw.githubusercontent.com/.../barnex-inverter-maps/...` URLs baked into
already-deployed firmware keep working. Don't create a separate
`barnex-inverter-maps` repo for new inverter work — this one repo is the
single source for both.

## Charger maps

`chargers/index.json` + `chargers/maps/` hold declarative HTTP+JSON protocol
maps for EV chargers, format documented in
[`docs/CHARGER_DISCOVERY_PROMPT.md`](https://bitbucket.org/bobyk/esp32_coordinator/src/main/docs/CHARGER_DISCOVERY_PROMPT.md)
§4.3 in the coordinator's own repo. The coordinator fetches
`chargers/index.json`, matches a discovered device against each entry's
`detect` rules, downloads the matching map, and applies it.

### Why charger maps carry a signature and inverter maps don't

A charger map's `cmd` section can drive two *write* actions —
`set_current`, `set_enabled` — actuating real hardware (an EVSE contactor,
a car's charge rate). An inverter map is read-only telemetry: worst case a
bad map misreads a value. A bad or malicious charger map, unsigned, could
be fetched from a compromised or spoofed host and used to open/close a
contactor or set current to an unsafe value. So the firmware requires every
charger map with a non-empty `cmd` section to carry a valid Ed25519
signature (Monocypher: curve25519 + BLAKE2b, **not** libsodium/PyNaCl
SHA-512 Ed25519) from the same embedded key already used for OTA firmware
updates (`OTA_PUBLIC_KEY` in `esp32_coordinator.ino`). A **read-only** map
(no `cmd` section) needs no signature — `sig` may be `""` — since it can
only misreport, never actuate.

### Contributing a charger map

1. Add your map JSON under `chargers/maps/`, following §4.3's schema
   (`detect`/`auth_check`, `ident`, `poll`, `read`, `states`, and — only if
   the vendor's API is documented well enough to actuate safely — `cmd`).
   Prefer starting **read-only** (no `cmd`): it needs no signature and is
   far lower risk to merge and to run on someone else's hardware.
2. Add an entry to `chargers/index.json`: `vendor_id`, `file`, `label`,
   `verified` (only set `true` if you've confirmed it against real
   hardware — say so in the PR), `sha256`, and `sig` (`""` for a read-only
   map).
3. Run `tools/update_index.py` to validate the map against the §4.6 rules
   (allowed `cmd` actions, blocklisted params/paths, field bounds) and
   refresh `sha256`/`updated_at`.
4. If your map includes `cmd`, it must be signed before merge — see
   `tools/sign_map.py`. **Never commit the OTA signing seed to this or any
   repo**; only the repo maintainer (holder of the seed) can produce a
   valid signature, so a PR adding `cmd` support should expect a
   maintainer round-trip to attach `sig` before merge. PRs adding
   read-only maps don't need this step.
5. Open a PR against `chargers-v1` or `main` per the maintainer's current
   branching instructions at the time. CI (`.github/workflows/validate.yml`)
   runs `tools/update_index.py --check`, which validates both the inverter
   and charger indices, and compiles the vendored signing helper as a
   build-health check.

The repo root's `index.json` and `maps/` (inverters) and the `chargers/`
subtree are independent — a PR should touch only the branch it's adding to,
not both, unless it's a shared-tooling change (e.g. `update_index.py`).
