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
| [`socket_standard_cmd.json`](socket_standard_cmd.json) | a new generic `relay` profile for standard Tuya sockets: switch (DP 1) with a safety countdown (DP 9), current, power and voltage (DP 18, 19, 20); no energy counter until DP 17 is checked (it is often an increment) | draft, `verified: false`; `match.product_ids` is empty on purpose (no product has been named yet, only drafts may do this); the DPs are the standard socket ones and still have to be tried on a real socket |
| [`evse_qccdz_ebdm_cmd.json`](evse_qccdz_ebdm_cmd.json) | rev 1 of a new `evse-qccdz-ebdm-1` charger profile for product `ebdm8ax35pgodi2s` (category `qccdz`): state DP 3 (enum), on/off DP 18, current limit DP 115 (int amps, 8–32 A, seen moving with the app slider together with DP 125), voltage DP 102 (×0.1) | draft, `verified: false`; read from the cloud DP map and cloud reports only; which of DP 115 / 125 takes a write, and DPs 105–107 while charging, still have to be checked on the LAN |

How a draft becomes a published profile is described in
[`docs/tuya-profiles.md`](../../docs/tuya-profiles.md#from-draft-to-published).
