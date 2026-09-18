#!/usr/bin/env python3
"""Validates every map in index.json against esp32_coordinator's register-map
schema, recomputes each entry's sha256, and bumps updated_at.

    tools/update_index.py            # rewrite index.json in place
    tools/update_index.py --check    # CI mode: fail (exit 1) on any mismatch,
                                      # don't write anything

The schema check mirrors InverterMapStore::validate() in esp32_coordinator
(src/InverterMap/InverterMapStore.cpp) closely enough to catch the mistakes
that actually happen when hand-assembling a map from research notes: bad
data_type/byte_order/access strings, duplicate or missing names, addresses
out of range, and — the one specific to this schema's SunSpec support —
a scale_register too far from its value register to ever share one 64-register
Modbus request (see docs/INVERTER_MAP.md in esp32_coordinator for why that's
a hard rejection, not a warning). It is NOT a substitute for the firmware's
own validator; a map passing this script should still be smoke-tested against
a real or bench inverter before being trusted in production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "index.json"

VALID_DATA_TYPES = {
    "uint16", "u16", "int16", "i16", "s16",
    "uint32", "u32", "int32", "i32", "s32",
    "float", "float32", "f32",
}
VALID_BYTE_ORDERS = {
    "big_endian", "little_endian", "big_endian_word_swap", "little_endian_word_swap",
    "big", "little", "abcd", "dcba", "cdab", "badc", "word_swap", "byte_swap",
}
VALID_ACCESS = {"read", "write", "read_write", "r", "w", "rw", "readwrite"}
VALID_STATUS = {"verified", "unverified"}
MAX_BLOCK_REGS = 64  # must match InverterMap::MAX_BLOCK_REGS in esp32_coordinator


def words_for(data_type: str) -> int:
    return 1 if data_type in ("uint16", "u16", "int16", "i16", "s16") else 2


def validate_map(path: Path) -> list[str]:
    """Returns a list of error strings; empty means the map is structurally sound."""
    errors: list[str] = []
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"cannot read/parse: {e}"]

    for key in ("brand", "model", "transport", "register_map"):
        if key not in doc:
            errors.append(f"missing top-level '{key}'")
    if errors:
        return errors  # nothing else is safe to check without these

    transport = doc["transport"]
    if transport.get("type") not in ("tcp", "rtu"):
        errors.append(f"transport.type invalid: {transport.get('type')!r}")
    slave_id = transport.get("slave_id", 1)
    if not (1 <= slave_id <= 247):
        errors.append(f"transport.slave_id out of range: {slave_id}")
    byte_order = transport.get("byte_order", "big_endian")
    if byte_order not in VALID_BYTE_ORDERS:
        errors.append(f"transport.byte_order invalid: {byte_order!r}")

    names: set[str] = set()
    readable = 0
    for i, entry in enumerate(doc.get("register_map", [])):
        name = entry.get("name")
        if not name:
            errors.append(f"[{i}] missing name")
        elif name in names:
            errors.append(f"[{i}] duplicate name {name!r}")
        elif len(name) > 39:
            errors.append(f"[{i}] name too long (>39 chars): {name!r}")
        names.add(name)

        address = entry.get("address")
        if address is None or not (0 <= address <= 65535):
            errors.append(f"[{i}] {name}: bad address {address!r}")

        fc = entry.get("function_code")
        if fc not in (3, 4, 6, 16):
            errors.append(f"[{i}] {name}: bad function_code {fc!r}")

        data_type = entry.get("data_type")
        if data_type not in VALID_DATA_TYPES:
            errors.append(f"[{i}] {name}: bad data_type {data_type!r}")

        access = entry.get("access", "read")
        if access not in VALID_ACCESS:
            errors.append(f"[{i}] {name}: bad access {access!r}")
        is_readable = access in ("read", "read_write", "r", "rw", "readwrite")
        if is_readable:
            readable += 1
            if fc not in (3, 4):
                errors.append(f"[{i}] {name}: readable entry needs function_code 3/4, got {fc!r}")

        entry_bo = entry.get("byte_order")
        if entry_bo is not None and entry_bo not in VALID_BYTE_ORDERS:
            errors.append(f"[{i}] {name}: bad byte_order override {entry_bo!r}")

        scale = entry.get("scale", 1.0)
        if scale == 0:
            errors.append(f"[{i}] {name}: scale is zero")

        min_refresh_s = entry.get("min_refresh_s", 0)
        if not (0 <= min_refresh_s <= 3600):
            errors.append(f"[{i}] {name}: min_refresh_s out of range: {min_refresh_s}")

        sf_addr = entry.get("scale_register")
        if sf_addr is not None and address is not None and data_type in VALID_DATA_TYPES:
            words = words_for(data_type)
            if address <= sf_addr <= address + words - 1:
                errors.append(f"[{i}] {name}: scale_register {sf_addr} overlaps its own address range")
            lo = min(address, sf_addr)
            hi = max(address + words - 1, sf_addr)
            span = hi - lo + 1
            if span > MAX_BLOCK_REGS:
                errors.append(
                    f"[{i}] {name}: scale_register {sf_addr} is {span} registers from address "
                    f"{address} — cannot share one {MAX_BLOCK_REGS}-register Modbus request "
                    f"(esp32_coordinator's Store::validate() would reject this map at load time)"
                )

    if readable == 0:
        errors.append("no readable entries (every entry is access=\"write\")")

    return errors


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="CI mode: fail on any validation/hash mismatch, write nothing")
    args = ap.parse_args()

    index = json.loads(INDEX_PATH.read_text())
    problems: list[str] = []
    changed = False

    for entry in index.get("maps", []):
        rel_path = entry.get("file")
        if not rel_path:
            problems.append(f"index entry missing 'file': {entry}")
            continue
        map_path = ROOT / rel_path
        if not map_path.exists():
            problems.append(f"{rel_path}: referenced in index.json but does not exist")
            continue

        errors = validate_map(map_path)
        if errors:
            problems.append(f"{rel_path}: FAILED schema validation:")
            problems.extend(f"    - {e}" for e in errors)
            continue

        status = entry.get("status")
        if status not in VALID_STATUS:
            problems.append(f"{rel_path}: invalid or missing 'status' ({status!r}), "
                            f"must be one of {sorted(VALID_STATUS)}")

        computed = sha256_of(map_path)
        declared = entry.get("sha256")
        if computed != declared:
            if args.check:
                problems.append(f"{rel_path}: sha256 mismatch — index says {declared}, "
                                f"actual file is {computed} (run without --check to fix)")
            else:
                entry["sha256"] = computed
                changed = True
                print(f"updated sha256 for {rel_path}")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\n{len(problems)} problem(s) found.", file=sys.stderr)
        return 1

    if args.check:
        print(f"OK — {len(index.get('maps', []))} maps validated, all hashes current.")
        return 0

    if changed:
        index["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")
        print(f"wrote {INDEX_PATH} (updated_at bumped)")
    else:
        print(f"OK — {len(index.get('maps', []))} maps validated, all hashes already current.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
