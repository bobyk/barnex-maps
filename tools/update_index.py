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
CHARGERS_INDEX_PATH = ROOT / "chargers" / "index.json"

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


# ---------------------------------------------------------------------------
# Charger protocol maps (chargers/index.json, chargers/maps/*.json) —
# docs/CHARGER_DISCOVERY_PROMPT.md §4 in esp32_coordinator. Mirrors
# src/ChargerMap/ChargerMapValidate.cpp + ChargerMapParser.cpp closely
# enough to catch hand-authoring mistakes before CI does — NOT a substitute
# for the firmware's own validator, which is the actual security boundary
# (this script has no signature-checking capability at all; see
# tools/sign_map.py for that half).
# ---------------------------------------------------------------------------

# Same list as ChargerMapValidate.cpp's kBlockedSubstrings — keep in sync by
# hand; a mismatch here only means CI catches a bad map later than it could,
# never that the firmware would accept something this script rejects (the
# firmware's own C++ validator is authoritative and re-checks everything
# this script does, independently, at apply time).
CHARGER_BLOCKED_SUBSTRINGS = [
    "kc", "kv", "kcl",
    "evsetype", "typerelay", "groundctrl", "curdesign", "mincurrent", "cmax",
    "suspenderrors", "factoryreset", "systemtime", "timezone",
    "/config", "/configap", "/confighttp", "/init", "/ocppevent",
]


def charger_path_allowed(path) -> str | None:
    """Returns an error string, or None if `path` passes every check
    ChargerMapValidate::isPathAllowed() applies."""
    if not isinstance(path, str) or not path.startswith("/"):
        return f"path must start with '/': {path!r}"
    if "://" in path:
        return f"path must not contain a scheme/host: {path!r}"
    if "\r" in path or "\n" in path:
        return "path must not contain CR/LF"
    low = path.lower()
    for term in CHARGER_BLOCKED_SUBSTRINGS:
        if term in low:
            return f"path contains blocklisted term {term!r}: {path!r}"
    return None


def charger_body_template_ok(body) -> str | None:
    """Mirrors ChargerMapValidate::isValidBodyTemplate()."""
    if not isinstance(body, str) or not body:
        return "body template missing/empty"
    if len(body) > 128:
        return "body template over 128 bytes"
    if "\r" in body or "\n" in body:
        return "body template must not contain CR/LF"
    low = body.lower()
    for term in CHARGER_BLOCKED_SUBSTRINGS:
        if term in low:
            return f"body template contains blocklisted term {term!r}"
    count = body.count("{v}")
    if count != 1:
        return f"body template must contain exactly one '{{v}}' (found {count})"
    # No other "{...}" placeholder besides the one {v}.
    rest = body.replace("{v}", "", 1)
    if "{" in rest:
        return "body template must not contain any placeholder other than {v}"
    return None


CHARGER_READ_SLOTS = {"state", "set_a", "meas_a", "volt", "power_w", "session_kwh", "enabled"}
MAX_CHARGER_READ_FIELDS = 32  # ChargerMap::MAX_READ_FIELDS
MAX_CHARGER_FILE_BYTES = 8192  # ChargerMap::MAX_FILE_BYTES


def validate_charger_map(path: Path) -> list[str]:
    """Returns a list of error strings; empty means the map is structurally
    sound per this script's (necessarily partial) mirror of the firmware's
    real C++ validator."""
    errors: list[str] = []
    raw = path.read_bytes()
    if len(raw) == 0 or len(raw) > MAX_CHARGER_FILE_BYTES:
        return [f"file size {len(raw)} bytes out of bounds (1..{MAX_CHARGER_FILE_BYTES})"]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"cannot parse JSON: {e}"]

    if doc.get("kind") != "charger":
        errors.append(f"'kind' must be \"charger\", got {doc.get('kind')!r}")
    if doc.get("schema") != 1:
        errors.append(f"unsupported 'schema' {doc.get('schema')!r} (only 1 is known)")
    for key in ("vendor", "variant"):
        if not doc.get(key):
            errors.append(f"missing/empty top-level '{key}'")

    transport = doc.get("transport") or {}
    if transport.get("type") != "http":
        errors.append(f"transport.type must be \"http\" in v1, got {transport.get('type')!r}")

    poll = doc.get("poll") or {}
    if not poll.get("path"):
        errors.append("poll.path is required")
    else:
        err = charger_path_allowed(poll["path"])
        if err:
            errors.append(f"poll.path: {err}")

    read = doc.get("read") or {}
    if not read:
        errors.append("'read' must have at least one field")
    field_count = 0
    for slot_name, value in read.items():
        if slot_name not in CHARGER_READ_SLOTS:
            errors.append(f"read.{slot_name}: unknown slot name (expected one of {sorted(CHARGER_READ_SLOTS)})")
            continue
        field_count += 1
        if isinstance(value, dict):
            if not value.get("key"):
                errors.append(f"read.{slot_name}: object form missing 'key'")
            scale = value.get("scale", 1.0)
            if scale == 0:
                errors.append(f"read.{slot_name}: scale must not be zero")
        elif not isinstance(value, (str, list)) or not value:
            errors.append(f"read.{slot_name}: must be a string, non-empty array, or object")
    if field_count > MAX_CHARGER_READ_FIELDS:
        errors.append(f"too many read fields ({field_count} > {MAX_CHARGER_READ_FIELDS})")

    cmd = doc.get("cmd") or {}
    for cmd_name in ("set_current", "set_enabled"):
        spec = cmd.get(cmd_name)
        if not spec:
            continue
        if not spec.get("path"):
            errors.append(f"cmd.{cmd_name}.path is required")
        else:
            err = charger_path_allowed(spec["path"])
            if err:
                errors.append(f"cmd.{cmd_name}.path: {err}")
        err = charger_body_template_ok(spec.get("body"))
        if err:
            errors.append(f"cmd.{cmd_name}.body: {err}")
        if cmd_name == "set_current":
            rng = spec.get("range")
            if not (isinstance(rng, list) and len(rng) == 2):
                errors.append("cmd.set_current.range must be [min, max]")
            else:
                lo, hi = rng
                if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))
                        and lo > 0 and hi > 0 and lo <= hi and hi <= 100):
                    errors.append(f"cmd.set_current.range {rng} out of sane bounds (1..100A, min<=max)")
    # Only set_current/set_enabled are ever consumed by the firmware
    # (ChargerMap::Config has exactly these two CmdSpec fields) — a stray
    # third key under `cmd` is harmless (never parsed, never acted on) but
    # almost certainly a typo worth flagging here.
    for extra in set(cmd.keys()) - {"set_current", "set_enabled"}:
        errors.append(f"cmd.{extra}: not a recognised action (only set_current/set_enabled exist) — "
                        f"typo? this key will be silently ignored by the firmware")

    return errors


def process_chargers_index(args, problems: list[str]) -> tuple[bool, int]:
    """Same shape as the inverter-maps loop in main() below, kept separate
    because the two index files have different schemas (`maps` vs
    `chargers`, `status` vs `verified`+`sig`) — see chargers/index.json's
    entry shape (id/vendor/variant/rev/file/sha256/sig/verified/label/
    detect_summary). Returns (changed, entry_count)."""
    if not CHARGERS_INDEX_PATH.exists():
        return False, 0
    index = json.loads(CHARGERS_INDEX_PATH.read_text())
    changed = False

    for entry in index.get("chargers", []):
        rel_path = entry.get("file")
        if not rel_path:
            problems.append(f"chargers/index.json entry missing 'file': {entry}")
            continue
        map_path = ROOT / rel_path
        if not map_path.exists():
            problems.append(f"{rel_path}: referenced in chargers/index.json but does not exist")
            continue

        errors = validate_charger_map(map_path)
        if errors:
            problems.append(f"{rel_path}: FAILED charger-map schema validation:")
            problems.extend(f"    - {e}" for e in errors)
            continue

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

        # sig is NOT recomputed/validated here — this script has no private
        # key and no Monocypher verify capability; an empty 'sig' is valid
        # (an unsigned, necessarily read-only map — the firmware's own
        # ChargerMapStore::validate() refuses to apply a `cmd`-bearing map
        # without one, independent of anything this script checks). Use
        # tools/sign_map.py to actually sign a map before publishing one
        # with `cmd` entries.
        doc = json.loads(map_path.read_text())
        has_cmd = bool((doc.get("cmd") or {}).get("set_current") or (doc.get("cmd") or {}).get("set_enabled"))
        if has_cmd and not entry.get("sig"):
            problems.append(
                f"{rel_path}: has cmd entries but index 'sig' is empty — the firmware will refuse "
                f"to apply this map at all (CHG_MAP_REQUIRE_SIG=1 default); run tools/sign_map.py "
                f"before publishing, or ship it read-only (drop 'cmd') until it's ready to sign")

    if not args.check and changed:
        index["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        CHARGERS_INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")
        print(f"wrote {CHARGERS_INDEX_PATH} (updated_at bumped)")

    return changed, len(index.get("chargers", []))


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

    chargers_changed, chargers_count = process_chargers_index(args, problems)

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\n{len(problems)} problem(s) found.", file=sys.stderr)
        return 1

    if args.check:
        print(f"OK — {len(index.get('maps', []))} inverter maps + {chargers_count} charger maps "
              f"validated, all hashes current.")
        return 0

    if changed:
        index["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n")
        print(f"wrote {INDEX_PATH} (updated_at bumped)")
    if not changed and not chargers_changed:
        print(f"OK — {len(index.get('maps', []))} inverter maps + {chargers_count} charger maps "
              f"validated, all hashes already current.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
