# Tuya device profiles

Many EV chargers and smart relays are Tuya devices. On the local network they
speak the Tuya protocol, and every value is a numbered **data point** (DP):
DP 101 might be the charging state, DP 102 the current limit. The numbers
differ per product, so a controller needs a table that says which DP means
what. A **profile** is that table, one JSON file per product family. A new
device becomes a new profile, not a software update.

Files live in [`tuya/profiles/`](../tuya/profiles) and are listed in
[`tuya/index.json`](../tuya/index.json). A profile is matched to a device by
its Tuya **product id** (`match.product_ids`).

A profile only describes. It does not carry keys, addresses or credentials.

## Format (schema 1)

```json
{
  "schema": 1, "id": "feyree-evse-1", "rev": 1, "kind": "charger", "verified": false,
  "label": "Feyree EV charger (read-only, unverified)",
  "match": {"product_ids": ["hytatexziwaifxj1", "emvuyyax4lekiooj"]},
  "limits": {"min_a": 6, "max_a": 32, "phases": 1},
  "read": {
    "state": {"dp": 101, "type": "enum", "map": {"no_connect": "A", "charing": "C", "error": "E"}},
    "set_a": {"dp": 102, "type": "int"},
    "power_w": {"dp": 109, "type": "int", "scale": 100}
  }
}
```

See [`feyree_evse.json`](../tuya/profiles/feyree_evse.json) for a complete one.

| field | rule |
|---|---|
| file size | at most 4096 bytes |
| `schema` | `1` |
| `id` | `[a-z0-9-]`, 1 to 32 chars |
| `rev` | integer 1 to 65535; raise it on every change |
| `kind` | `charger` or `relay` |
| `verified` | optional boolean, default `false` |
| `label` | string, 1 to 64 chars |
| `match.product_ids` | 1 to 8 items, each `[0-9A-Za-z]`, 1 to 16 chars |
| `limits.min_a` | integer 6 to 32 |
| `limits.max_a` | integer `min_a` to 80 |
| `limits.phases` | `1` or `3` |
| data point `dp` | integer 1 to 255 |
| data point `type` | `bool`, `int`, `enum` or `str` |
| data point `scale` | finite number, default `1`; the raw value is multiplied by it |
| `state.map` | 1 to 12 entries, keys 1 to 23 chars |

`limits` is required for `charger` and optional for `relay` (if present it is
checked the same way). Unknown top-level keys, unknown roles and unknown keys
inside a role are rejected. Duplicate JSON keys and `NaN`/`Infinity` are
rejected too, so every reader sees the same file.

### `read` roles

All optional, except `state` for `kind: charger`.

| role | meaning |
|---|---|
| `state` | `type: "enum"` plus `map` from the device's own strings to `A`, `B`, `C` or `E` (IEC 61851 style: A no vehicle, B vehicle connected, C charging, E error) |
| `set_a` | current limit the device reports, amps |
| `enabled` | charging or output on/off |
| `power_w`, `current_a`, `voltage_v` | live measurements (use `scale` for units) |
| `session_kwh` | energy of the current session |
| `temp_c` | device temperature |

### `cmd` (optional)

Commands make a profile able to change the device, so they are limited to two:

- `set_a`: `{"dp": N, "type": "int"}`
- `enable`: `{"dp": N, "type": "bool"}` or `{"dp": N, "type": "enum", "on": "<str>", "off": "<str>"}` (`on`/`off` 1 to 23 chars)

### `quirks` (optional)

`reassert_set_a_on_plug` (boolean): the device forgets its current limit when
a vehicle connects, so the client should send it again.

## Signing

A profile **with `cmd` must have a non-empty `sig`** in its index entry. A
profile without `cmd` needs no signature (`"sig": ""`). `update_index.py`
fails if a `cmd` profile is unsigned. Signing is done by a maintainer with
[`tools/sign_map.py`](../tools/sign_map.py), the same tool and key as for
[charger maps](charger-maps.md#signing); it accepts profile files (4096 byte
limit) and prints the `sha256` and `sig` to put in the index entry.

## Index entry

```json
{"id": "feyree-evse-1", "rev": 1, "kind": "charger", "schema": 1,
 "file": "tuya/profiles/feyree_evse.json", "sha256": "...", "sig": "",
 "verified": false, "product_ids": ["hytatexziwaifxj1"], "label": "..."}
```

`id`, `rev`, `kind`, `schema` and `product_ids` must equal the file's. Two
entries may not claim the same product id with the same `rev`.

## Adding a profile

1. Write the file in `tuya/profiles/`. Every DP number must come from a
   source you can cite (the device's Tuya product schema or a DP dump from the
   device itself); put it in the PR description. Do not guess.
2. Start read-only (no `cmd`) and `"verified": false`.
3. Add an index entry and run:

   ```bash
   python3 tools/update_index.py          # fills sha256
   python3 tools/update_index.py --check  # what CI runs
   python3 -m unittest discover -s tools/tests -v
   ```

4. Open a PR. Adding `cmd` later is a new `rev` and needs a maintainer
   signature.

## Verification status

`verified: false` means nobody has confirmed the DP numbers on a real device
of that product. Clients should show such a profile as unverified and keep it
read-only. A maintainer sets `verified: true` (and raises `rev`) only after
the readings were checked against the device, and for a `cmd` profile after
commands were tried on the bench.
