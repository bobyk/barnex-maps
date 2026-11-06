# barnex-maps

Register and protocol maps for **[Barnex](https://barnex.io)**, a home
solar-surplus controller. Barnex keeps solar energy at home by steering water
heaters and EV charging, and keeps the main breaker from tripping.

These maps are how Barnex learns to talk to your inverter and EV charger
without a firmware update: when it recognises a device, it downloads the
matching map from this repo over HTTPS, checks its hash (and, for chargers
with commands, its signature) and applies it.

- Product site: **[barnex.io](https://barnex.io)**
- Supported hardware: [barnex.io/en/compatibility](https://barnex.io/en/compatibility) ([UA](https://barnex.io/compatibility))

## What's inside

| path | what |
|---|---|
| [`index.json`](index.json), [`maps/`](maps) | inverter register maps (Modbus TCP/RTU, read-only) |
| [`chargers/index.json`](chargers/index.json), [`chargers/maps/`](chargers/maps) | EV charger protocol maps (HTTP+JSON) |
| [`docs/inverter-maps.md`](docs/inverter-maps.md) | inverter map format, index fields, SunSpec notes |
| [`docs/charger-maps.md`](docs/charger-maps.md) | charger map format, safety rules, signing |
| [`tools/`](tools) | validator, checksum and signing helpers |

Inverter and charger maps are independent: a PR should touch one of them,
not both, unless it changes shared tooling.

## Inverters

| Vendor | Detected automatically | Maps |
|---|---|---|
| Deye | yes | native-equivalent (**verified**), SG04LP3, SG01HP3/SG04HP3, microinverter |
| Growatt | yes (low confidence) | SPH-6000 (legacy), GEN4, GEN3 hybrid (telemetry only, see notes) |
| Victron | yes | Cerbo/Venus GX |
| Luxpower | no | LXP/SNA hybrid (EG4 and other rebrands), RTU only |
| SRNE | no | HF2430U60-100 |
| Solis | no | Hybrid RHI/RAI |
| Sofar | no | G3 Hybrid |
| Huawei | no | SUN2000 |
| Sungrow | no | SH series |
| Fronius | no | Symo/Primo (int+SF and float variants) |
| SMA | no | native profile, SunSpec fallback |
| SolarEdge | no | SunSpec + proprietary battery/meter range |

"No" means Barnex cannot yet tell that vendor apart over Modbus on its own.
The installer can still pick the map from the full catalogue in the setup
UI.

Only `maps/deye_hybrid_native_equivalent.json` is `verified` on real
hardware. The rest are built from public register tables (each `source` is
pinned to a commit) and marked `unverified` in the UI until someone confirms
them on a real inverter.

## EV chargers

| Vendor | Map | Control |
|---|---|---|
| Eveus Pro, firmware R3.01.8 to R3.05.x (reports `verFWWifi`) | `eveus_current.json` | read + set current / pause, **signed**, verified |
| Eveus / EnergyStar, old firmware EnergyStar V5.x | `eveus_legacy.json` | read-only (this firmware has no stop command) |

## Contributing

1. **Never guess a register address or API field.** Every value must trace to
   a specific line of a public source, pinned to a commit SHA. Put those URLs
   in the index `source` field (inverters) or the PR description (chargers).
2. Add the map file and an index entry. Start inverter maps at
   `"status": "unverified"` and charger maps at `"verified": false`, unless
   you tested on real hardware (say so in the PR).
3. Follow the sign convention: `grid_power` positive = import,
   `battery_power` positive = charging. Flip with a negative `scale` if the
   source uses the opposite polarity.
4. Run the validator. It checks every map against the schema and the
   firmware's limits, and fills in `sha256` and `updated_at`:

   ```bash
   python3 tools/update_index.py          # update the indexes
   python3 tools/update_index.py --check  # what CI runs
   ```

5. Open a PR. CI runs the same check.

Charger maps with a `cmd` section need a maintainer signature before merge;
see [Signing](docs/charger-maps.md#signing). Read-only charger maps do not.
Prefer starting read-only.

## Guides on barnex.io

Inverters (Ukrainian unless noted):
- [Wiring options for inverter, boiler and EV charger](https://barnex.io/blog/yak-pidkliuchyty-barnex-skhema-dlia-invertora-boilera-zariadky)
- [Connecting Barnex to a Deye Wi-Fi logger](https://barnex.io/blog/pidkliuchennia-barnex-do-deye-wifi-lohera-maister)
- [Restoring local Modbus TCP access to Deye](https://barnex.io/blog/deye-modbus-tcp-lokalno-home-assistant)
- [Changing Deye settings over Modbus from a PC](https://barnex.io/blog/deye-modbus-keruvannia-nalashtuvannia-lokalno)
- [Deye logger port 8899 closed? Local Modbus TCP moved to port 502 (English)](https://barnex.io/en/blog/deye-logger-port-8899-closed-modbus-tcp-502)

EV chargers:
- [EV charging from solar: EVEUS, Electros and OCPP chargers](https://barnex.io/blog/zariadka-elektromobilia-vid-sontsia)
- [EVEUS and Electros: connecting and setting the current](https://barnex.io/blog/eveus-electros-vid-sontsia-nalashtuvannia)
- [Charger before or after the inverter, Electros and OCPP 1.6J](https://barnex.io/blog/pidkliuchennia-zariadky-avto-do-barnex-skhemy-ocpp-electros)

## Repo name

This repo was called `barnex-inverter-maps` before charger maps were added.
GitHub redirects the old name, and devices that still use the old URL keep
working. **Do not create a new repo under the old name**: it would break
those devices.

## License

[MIT](LICENSE). Vendored Monocypher keeps its own BSD-2-Clause / CC0 license.
