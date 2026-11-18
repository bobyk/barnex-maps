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

How a draft becomes a published profile is described in
[`docs/tuya-profiles.md`](../../docs/tuya-profiles.md#from-draft-to-published).
