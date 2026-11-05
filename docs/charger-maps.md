# EV charger protocol maps

A charger map describes how the [Barnex](https://barnex.io) controller finds
an EV charger on the local network, reads its state over HTTP+JSON and, when
allowed, sets the charging current or pauses charging. A new charger
generation or brand becomes a new map file, not a firmware update.

Files live in [`chargers/maps/`](../chargers/maps) and are listed in
[`chargers/index.json`](../chargers/index.json).

## Safety rules

A charger map can switch a contactor and change a car's charging current, so
the rules are stricter than for [inverter maps](inverter-maps.md):

- **Two commands only:** `set_current` and `set_enabled`. Nothing else is
  ever sent.
- **The firmware limits the value.** The current sent is always inside the
  overlap of the map's `range`, the installer's min/max for that charger and
  the hardware limit. A map cannot send a number outside that overlap.
- **Requests go only to the paired charger's IP.** `path` must start with
  `/`, must not contain a scheme, host or CR/LF; the body is at most 128
  bytes and has exactly one `{v}` placeholder.
- **Service parameters are blocked.** Any mention of calibration, relay type,
  ground control, factory reset, time settings or config pages (`kC*`, `kV*`,
  `kCl`, `evseType`, `typeRelay`, `groundCtrl`, `curDesign`, `minCurrent`,
  `Cmax`, `suspendErrors`, `factoryReset`, `systemTime`, `timeZone`,
  `/config*`, `/init`, `/ocppEvent`) rejects the whole map.
- **No scripts or expressions.** Only the declarative rules below.
- **Signature.** A map with a `cmd` section must be signed (see
  [Signing](#signing)). A read-only map needs no signature.
- **`"verified": false` means observe only.** The controller reads the
  charger but never sends commands, and the UI says control is off until the
  protocol is checked on a real charger.
- **Size:** at most 8 KiB per file, at most 32 read fields.

## Example

[`chargers/maps/eveus_current.json`](../chargers/maps/eveus_current.json),
shortened:

```json
{
  "schema": 1,
  "kind": "charger",
  "vendor": "eveus",
  "variant": "current",
  "rev": 2,
  "model_hint": "Eveus Pro / Energy Star, current API",
  "verified": true,
  "transport": { "type": "http", "port": 80, "auth": "basic" },
  "detect": {
    "probe": { "method": "GET", "path": "/main" },
    "all":  [ { "json": "verFWWifi", "exists": true }, { "json": "currentSet", "exists": true } ],
    "none": []
  },
  "auth_check": { "method": "GET", "path": "/", "ok": [200], "bad": [401] },
  "ident": { "serial": ["serialNum", "stationId"], "fw": ["verFWMain", "verFWWifi"], "model": ["model"] },
  "poll": { "method": "GET", "path": "/main", "min_interval_ms": 1000 },
  "read": {
    "state": "state",
    "set_a": "currentSet",
    "meas_a": "curMeas1",
    "enabled": { "key": "evseEnabled", "invert": true }
  },
  "states": { "2": "A", "3": "B", "4": "C", "7": "E" },
  "cmd": {
    "set_current": { "method": "POST", "path": "/pageEvent",
                     "body": "pageevent=currentSet&currentSet={v}", "range": [7, 32], "ok_body": "OK" },
    "set_enabled": { "method": "POST", "path": "/pageEvent",
                     "body": "pageevent=evseEnabled&evseEnabled={v}", "on": 0, "off": 1, "ok_body": "OK" }
  },
  "quirks": { "skip_polls_after_write": 2, "single_connection": true }
}
```

## Fields

### Header

| field | required | notes |
|---|---|---|
| `schema` | yes | `1` |
| `kind` | yes | `"charger"` |
| `vendor` | yes | lowercase vendor id, e.g. `eveus` |
| `variant` | yes | protocol generation, e.g. `current`, `legacy` |
| `rev` | yes | integer; bump it on every change. A higher `rev` for the applied variant replaces it |
| `model_hint` | no | text shown to the installer |
| `verified` | no (`false`) | `true` only after testing on a real charger |

### `transport`

| field | notes |
|---|---|
| `type` | `"http"` (the only transport today) |
| `port` | TCP port, usually 80 |
| `auth` | `"basic"` (HTTP Basic, credentials entered by the installer) or `"none"` |

### `detect`

How the controller recognises the charger during a LAN scan. It sends
`probe` (`method`, `path`) and checks the response:

- `all`: every rule must match.
- `none`: no rule may match.

Rules:

| rule | matches when |
|---|---|
| `{"json": "key", "exists": true}` | the JSON body has `key` |
| `{"json": "key", "exists": false}` | the JSON body has no `key` |
| `{"json": "key", "equals": "v"}` | `key` equals the string or number `v` |
| `{"status": 200}` | HTTP status code |
| `{"body_contains": "text"}` | body contains `text` (case-insensitive) |
| `{"header_contains": "text"}` | response headers contain `text` (case-insensitive) |

Different firmware generations of one vendor are **separate variant files**
told apart by `detect` (see how `eveus_legacy` uses `none` on `verFWWifi`),
not one file with branches.

### `auth_check`

A request that tells "password needed or wrong" from "OK": `method`, `path`,
`ok` (status codes meaning authorised, up to 4) and `bad` (codes meaning the
credentials are wrong, up to 4).

### `ident`

Where to find `serial`, `fw` and `model` in the poll response. Each is a list
of key aliases; the first one present wins.

### `poll`

`method`, `path` and `min_interval_ms` (default 1000). The response must be a
JSON object.

### `read`

Maps the controller's slots to JSON keys in the poll response:

| slot | meaning |
|---|---|
| `state` | vendor state code, translated through `states` |
| `set_a` | current setpoint, A |
| `meas_a` | measured current, A |
| `volt` | voltage, V |
| `power_w` | power, W |
| `session_kwh` | energy this session, kWh |
| `enabled` | charging allowed (0/1) |
| `temp_c` | charger temperature, °C |

A slot value is either a key (`"currentSet"`), a list of aliases
(`["evseType", "typeEvse"]`) or an object
`{"key": ..., "scale": 0.1, "invert": true}`. `scale` multiplies any numeric
slot and must not be 0; `invert` applies only to `enabled`.

### `states`

Vendor state code → IEC 61851 / J1772 pilot state: `A` (no car), `B` (car connected, not
charging), `C` (charging), `D`, `E`, `F` (error). Unknown codes are treated as
unknown, never guessed.

### `cmd`

Optional. Only `set_current` and `set_enabled`:

| field | notes |
|---|---|
| `method`, `path` | the request; `path` passes the rules above |
| `body` | form body with exactly one `{v}` |
| `ok_body` | optional text the response must contain to count as success |
| `range` | `set_current` only, required: `[min, max]` amps, within 1–100 |
| `on`, `off` | `set_enabled` only: values for `{v}` (default 1 and 0) |

### `quirks`

| field | notes |
|---|---|
| `skip_polls_after_write` | polls to skip after a command, for chargers that answer stale data right after a write |
| `single_connection` | the charger handles one HTTP connection at a time |

## `chargers/index.json`

```json
{
  "schema_version": 1,
  "updated_at": "2026-09-22T00:00:00Z",
  "chargers": [
    {
      "id": "eveus-current-1",
      "vendor": "eveus",
      "variant": "current",
      "rev": 2,
      "file": "chargers/maps/eveus_current.json",
      "sha256": "<sha256 of the file bytes>",
      "sig": "<128 hex chars, or \"\" for a read-only map>",
      "verified": true,
      "label": "Eveus Pro / Energy Star — current API",
      "detect_summary": { "probe": { "method": "GET", "path": "/main" }, "all": [ ... ], "none": [ ... ] }
    }
  ]
}
```

`detect_summary` repeats the map's `detect` so the controller can match
devices without downloading every map. Keep it identical to the map.

## How the controller uses a map

1. A LAN scan finds candidates; each is matched against `detect_summary`.
2. Only the matching map is downloaded. Its bytes must match the index
   `sha256`; a map with `cmd` must also carry a valid `sig`.
3. The map is validated against the rules above and applied. The previous
   map is kept; five failed polls in a row after a new map roll back to it
   (once per boot). A map restored from flash at boot is never rolled back
   automatically.
4. The firmware also carries a built-in Eveus map, so a known charger works
   without internet.

## Signing

Signature scheme: **Monocypher EdDSA (curve25519 + BLAKE2b)** over the
32-byte SHA-256 of the map file. The public key is the one already built into
the Barnex firmware for firmware updates; there is no separate key for maps.

> Standard Ed25519 libraries (libsodium, PyNaCl, OpenSSL) use SHA-512 and
> produce signatures the device will **always reject**, even with the right
> seed. Use only the helper in this repo.

Only the maintainer holds the seed. Contributors open a PR with a
**read-only** map, or with `cmd` and `"sig": ""`; the maintainer signs before
merge:

```bash
python3 tools/sign_map.py --seed /path/to/signing_seed.hex chargers/maps/your_map.json
```

The script builds `tools/sign_monocypher` from the vendored sources on first
run, refuses files over 8 KiB, and prints the `sha256` and `sig` to put into
`chargers/index.json`. It never edits the index itself. Never commit the seed
anywhere.

Any change to a signed map file, even whitespace, changes its SHA-256 and
needs a new signature.

## Related

- [Inverter maps](inverter-maps.md)
- [Contributing](../README.md#contributing)
- Guide (Ukrainian): [EVEUS and Electros from solar](https://barnex.io/blog/eveus-electros-vid-sontsia-nalashtuvannia)
