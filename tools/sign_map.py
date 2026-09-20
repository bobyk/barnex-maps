#!/usr/bin/env python3
"""
sign_map.py — sign a charger protocol map for esp32_coordinator
(docs/CHARGER_DISCOVERY_PROMPT.md §4.5 in that repo).

Thin wrapper over the same Monocypher EdDSA (BLAKE2b) helper
esp32_coordinator's own sign.py uses for OTA firmware — this repo vendors
its own copy of monocypher.c/.h + sign_monocypher.c (tools/) so signing a
map needs nothing beyond this checkout; you do NOT need an
esp32_coordinator working copy alongside it.

IMPORTANT: the firmware verifies with Monocypher's crypto_eddsa_check()
(curve25519 + BLAKE2b) — NOT libsodium/PyNaCl Ed25519 (SHA-512). Signing
with PyNaCl produces a signature that always fails on-device even when the
sha256 matches. This script only ever shells out to the vendored C helper,
never touches PyNaCl, so this can't happen by accident here.

The seed (32 bytes, hex-encoded, typically ota_signing_seed.hex) is the
SAME seed esp32_coordinator's OTA signing already uses — the firmware
verifies charger maps against the exact same embedded public key as
firmware images (OTA_PUBLIC_KEY in esp32_coordinator.ino), no separate key
was introduced for maps. Never commit the seed to this or any repo.

Usage:
  cc -O2 -o tools/sign_monocypher tools/sign_monocypher.c tools/monocypher.c
  python3 tools/sign_map.py --seed /path/to/ota_signing_seed.hex \
      chargers/maps/eveus_current.json

  # then hand-edit (or script) the matching chargers/index.json entry's
  # "sig" field with the printed signature_hex — this script does not
  # write to index.json itself, keeping "sign a file" and "publish an
  # index entry" as two separate, individually-reviewable steps.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "tools" / "sign_monocypher"
HELPER_SRC = ROOT / "tools" / "sign_monocypher.c"
MONO_C = ROOT / "tools" / "monocypher.c"


def ensure_helper() -> Path:
    need = (not HELPER.exists()) or (
        HELPER.stat().st_mtime < max(HELPER_SRC.stat().st_mtime, MONO_C.stat().st_mtime)
    )
    if need:
        subprocess.check_call(["cc", "-O2", "-o", str(HELPER), str(HELPER_SRC), str(MONO_C)])
    return HELPER


def run_helper(seed: Path, digest_hex: str) -> dict[str, str]:
    out = subprocess.check_output([str(ensure_helper()), str(seed), digest_hex], text=True)
    fields: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k.strip()] = v.strip()
    for k in ("public_key_hex", "signature_hex", "signature_b64"):
        if k not in fields:
            raise SystemExit(f"sign helper missing {k}")
    return fields


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=Path, default=Path("ota_signing_seed.hex"),
                     help="path to the OTA signing seed (never committed to any repo)")
    ap.add_argument("--print-pub", action="store_true",
                     help="print the Monocypher public key derived from --seed and exit")
    ap.add_argument("map_file", nargs="?", type=Path, help="path to the map JSON to sign")
    args = ap.parse_args()

    if args.print_pub:
        fields = run_helper(args.seed, "00" * 32)
        print(fields["public_key_hex"])
        return

    if not args.map_file:
        ap.error("map_file required (or use --print-pub)")
    if not args.map_file.exists():
        ap.error(f"{args.map_file}: not found")

    data = args.map_file.read_bytes()
    if len(data) == 0 or len(data) > 8192:
        # Same MAX_FILE_BYTES the firmware's ChargerMapValidate enforces —
        # signing a map the firmware would reject for size alone is
        # pointless; fail loudly here instead of producing an unusable sig.
        raise SystemExit(f"{args.map_file}: {len(data)} bytes — out of esp32_coordinator's "
                          f"ChargerMap::MAX_FILE_BYTES bounds (1..8192), refusing to sign")

    digest = hashlib.sha256(data).digest()
    fields = run_helper(args.seed, digest.hex())

    print(f"file:    {args.map_file}")
    print(f"size:    {len(data)}")
    print(f"sha256:  {digest.hex()}")
    print(f"pub:     {fields['public_key_hex']}")
    print(f"sig:     {fields['signature_hex']}")
    print()
    print("chargers/index.json entry fields to set:")
    print(f'  "sha256": "{digest.hex()}",')
    print(f'  "sig": "{fields["signature_hex"]}"')


if __name__ == "__main__":
    main()
