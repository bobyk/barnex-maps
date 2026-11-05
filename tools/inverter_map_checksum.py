#!/usr/bin/env python3
"""Compute the optional `checksum` field for an inverter register map.

The device validates `checksum` against the *semantic content* of the map, not
its bytes, so an author can reformat, re-indent or reorder keys without
invalidating it:

    sha256( "name:address:function_code:data_type:scale;" for each entry,
             in file order, + "b<bit>;" right after an entry that has "bit" )

`scale` is formatted with %.6f, and `data_type` uses the canonical spelling the
firmware stores (uint16 / int16 / uint32 / int32 / float).

The field is optional: omit it and the map is accepted on JSON validity alone.
Include it and a corrupted or hand-edited register table is rejected before it
ever reaches the inverter.

Usage:
    tools/inverter_map_checksum.py maps/growatt_sph6000.json
    tools/inverter_map_checksum.py --write maps/growatt_sph6000.json
"""

import argparse
import hashlib
import json
import sys

CANONICAL_TYPES = {
    "uint16": "uint16", "u16": "uint16",
    "int16": "int16", "i16": "int16", "s16": "int16",
    "uint32": "uint32", "u32": "uint32",
    "int32": "int32", "i32": "int32", "s32": "int32",
    "float": "float", "float32": "float", "f32": "float",
}


def content_checksum(doc: dict) -> str:
    h = hashlib.sha256()
    for i, entry in enumerate(doc.get("register_map", [])):
        try:
            dtype = CANONICAL_TYPES[str(entry["data_type"]).lower()]
        except KeyError:
            sys.exit(f"entry {i}: unknown data_type {entry.get('data_type')!r}")
        line = "%s:%d:%d:%s:%.6f;" % (
            entry["name"],
            int(entry["address"]),
            int(entry["function_code"]),
            dtype,
            float(entry.get("scale", 1)),
        )
        h.update(line.encode("utf-8"))
        if entry.get("bit") is not None:   # only when used: existing checksums stay valid
            h.update(("b%d;" % int(entry["bit"])).encode("utf-8"))
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="register map JSON")
    ap.add_argument("--write", action="store_true",
                    help="write the checksum back into the file")
    args = ap.parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    digest = content_checksum(doc)
    if not args.write:
        print(digest)
        return 0

    doc["checksum"] = digest
    with open(args.path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"{args.path}: checksum = {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
