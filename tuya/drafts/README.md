# Tuya profile drafts

Files here are **drafts**: proposed profiles that are

- **unverified**: nobody has confirmed the values on a real device,
- **unsigned**: no signature exists for them,
- **not listed** in [`tuya/index.json`](../index.json), and
- **not published**: nothing in this folder is published, only files listed
  in `tuya/index.json` are.

CI validates every file here with the draft rules
(`python3 tools/update_index.py --check`) and fails if the index ever points
into this folder.

| Draft | Proposes | Status |
|---|---|---|
| [`feyree_evse_cmd.json`](feyree_evse_cmd.json) | rev 2 of `feyree-evse-1`: the published read section plus `cmd.set_a` (DP 102, int), `cmd.enable` (DP 112, bool) and the `reassert_set_a_on_plug` quirk | draft, `verified: false`; the command DPs are taken from the read section and still have to be tried on the bench |
| [`evse_qccdz_ebdm.json`](evse_qccdz_ebdm.json) | rev 4 of `evse-qccdz-ebdm-1`, **read-only**: state on DP 101 (`no_connet`, `connect`, `wait_rfid`, `wait_charing`, `finish`, `charing`, `error`), set current DP 115, voltage DP 102 (x0.1 V), power DP 109 (x100 W), temperature DP 110 (x0.1 °C). Rev 1 to 3 read DP 3 and DP 18, which this product does not report over the local network, so no reading ever matched. Commands are withdrawn until start/stop (DP 124 `OpenCharging`/`CloseCharging`) is tried on a real charge | draft, `verified: false`; DPs from a local DP dump of two units (plugged and free) and the public Feyree DP lists; must be signed (rev 3 is signed and outranks an unsigned rev) |
| [`socket_standard_cmd.json`](socket_standard_cmd.json) | a new generic `relay` profile for standard Tuya sockets: switch (DP 1) with a safety countdown (DP 9), current, power and voltage (DP 18, 19, 20); no energy counter until DP 17 is checked (it is often an increment) | draft, `verified: false`; `match.product_ids` is empty on purpose (no product has been named yet, only drafts may do this); the DPs are the standard socket ones and still have to be tried on a real socket |

How a draft becomes a published profile is described in
[`docs/tuya-profiles.md`](../../docs/tuya-profiles.md#from-draft-to-published).
