#!/usr/bin/env python3
"""Tests for the Tuya device profile validator and index checks.

    python3 -m unittest discover -s tools/tests -v
"""
from __future__ import annotations

import argparse
import contextlib
import io
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "tools"))

import update_index as ui  # noqa: E402

FIX = HERE / "fixtures" / "tuya"
GOOD = ["ok_readonly.json", "ok_cmd.json", "ok_relay.json"]
BAD = sorted(p.name for p in FIX.glob("bad_*.json"))


def load(name: str):
    raw = (FIX / name).read_bytes()
    doc, err = ui.parse_tuya_profile(raw)
    return doc, err, len(raw)


class ValidatorTests(unittest.TestCase):
    def test_good_fixtures_have_no_errors(self):
        for name in GOOD:
            with self.subTest(name):
                doc, err, n = load(name)
                self.assertIsNone(err)
                self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def test_every_bad_fixture_is_rejected(self):
        self.assertGreaterEqual(len(BAD), 26)
        for name in BAD:
            with self.subTest(name):
                doc, err, n = load(name)
                errors = [err] if err else ui.validate_tuya_profile(doc, n)
                self.assertTrue(errors, f"{name} was accepted")

    def test_oversized_is_rejected_only_for_size(self):
        doc, err, n = load("bad_oversized.json")
        self.assertEqual(n, 4097)
        self.assertIsNone(err)
        errors = ui.validate_tuya_profile(doc, n)
        self.assertEqual(len(errors), 1)
        self.assertIn("4096", errors[0])
        self.assertEqual(ui.validate_tuya_profile(doc, 4096), [])

    def test_published_profile_is_byte_identical_to_fixture(self):
        self.assertEqual((REPO / "tuya" / "profiles" / "feyree_evse.json").read_bytes(),
                         (FIX / "ok_readonly.json").read_bytes())
        self.assertTrue((FIX / "ok_readonly.json").read_bytes().endswith(b"}\n"))

    def test_relay_does_not_need_state_or_limits(self):
        doc, _, n = load("ok_relay.json")
        self.assertNotIn("state", doc["read"])
        self.assertNotIn("limits", doc)
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def test_relay_with_bad_limits_still_rejected(self):
        doc, _, n = load("ok_relay.json")
        doc["limits"] = {"min_a": 5, "max_a": 10, "phases": 1}
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_boundaries(self):
        doc, _, n = load("ok_readonly.json")
        doc["limits"] = {"min_a": 32, "max_a": 80, "phases": 3}
        doc["rev"] = 65535
        doc["id"] = "a" * 32
        doc["label"] = "x" * 64
        doc["read"]["set_a"]["dp"] = 255
        doc["read"]["state"]["map"] = {("k" * 23 if i == 0 else "k%d" % i): "A" for i in range(12)}
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        doc["rev"] = 65536
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_scale_range(self):
        doc, _, n = load("ok_readonly.json")
        for ok in (1e-3, 0.1, 1, 100, 1e3):
            with self.subTest(ok=ok):
                doc["read"]["power_w"]["scale"] = ok
                self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        for bad in (0, 0.0, -0.0, -1, -100, 0.000999, 1000.001, 1e39):
            with self.subTest(bad=bad):
                doc["read"]["power_w"]["scale"] = bad
                self.assertTrue(ui.validate_tuya_profile(doc, n), f"scale {bad} was accepted")
        for name in ("bad_scale_zero.json", "bad_scale_negative.json", "bad_scale_huge.json"):
            with self.subTest(name):
                d, err, m = load(name)
                self.assertIsNone(err)
                errors = ui.validate_tuya_profile(d, m)
                self.assertEqual(len(errors), 1)
                self.assertIn("scale", errors[0])

    def test_label_65_chars_rejected(self):
        doc, _, n = load("ok_readonly.json")
        doc["label"] = "x" * 65
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_label_is_counted_in_utf8_bytes(self):
        doc, _, n = load("ok_readonly.json")
        doc["label"] = "\u00e9" * 32  # 32 code points, exactly 64 bytes
        self.assertEqual(len(doc["label"].encode("utf-8")), 64)
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        doc["label"] = "\u00e9" * 32 + "a"  # 65 bytes
        self.assertTrue(ui.validate_tuya_profile(doc, n))
        doc["label"] = "a\x7fb"
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_surrogates(self):
        doc, err = ui.parse_tuya_profile(b'{"label": "ok \\ud83d\\ude00"}')
        self.assertIsNone(err)
        self.assertEqual(doc["label"], "ok \U0001F600")
        good, _, n = load("ok_readonly.json")
        good["label"] = "ok \U0001F600"  # paired surrogates decode to one code point
        self.assertEqual(ui.validate_tuya_profile(good, n), [])
        for lone in ("\ud800", "\udfff"):
            with self.subTest(lone):
                d1 = json.loads(json.dumps(good))
                d1["label"] = "a" + lone
                self.assertTrue(any("surrogate" in e for e in ui.validate_tuya_profile(d1, n)))
                d2 = json.loads(json.dumps(good))
                d2["limits"] = {"min_a": 6, "max_a": 32, "phases": 1, "x" + lone: 1}
                self.assertTrue(any("surrogate" in e for e in ui.validate_tuya_profile(d2, n)))

    def test_enum_words_are_printable_ascii(self):
        doc, _, n = load("ok_cmd.json")
        doc["read"]["state"]["map"] = {"a b~": "A", "x" * 23: "B"}
        doc["cmd"]["enable"].update(on="x" * 23, off="~ ")
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        for bad in ("\x7f", "\x1f", "\u00e9", ""):
            with self.subTest(repr(bad)):
                d2 = json.loads(json.dumps(doc))
                d2["cmd"]["enable"]["off"] = "a" + bad
                self.assertTrue(ui.validate_tuya_profile(d2, n) or bad == "")
        d3 = json.loads(json.dumps(doc))
        d3["cmd"]["enable"]["off"] = ""
        self.assertTrue(ui.validate_tuya_profile(d3, n))

    def test_bool_is_not_an_int(self):
        doc, _, n = load("ok_readonly.json")
        doc["rev"] = True
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_nan_and_duplicate_keys_fail_to_parse(self):
        _, err = ui.parse_tuya_profile(b'{"schema": NaN}')
        self.assertTrue(err)
        _, err = ui.parse_tuya_profile(b'{"schema": 1, "schema": 1}')
        self.assertTrue(err)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "tuya" / "profiles").mkdir(parents=True)
        self._root, self._idx = ui.ROOT, ui.TUYA_INDEX_PATH
        ui.ROOT, ui.TUYA_INDEX_PATH = self.tmp, self.tmp / "tuya" / "index.json"
        self.addCleanup(self._restore)

    def _restore(self):
        ui.ROOT, ui.TUYA_INDEX_PATH = self._root, self._idx

    def add(self, fixture, fname, **over):
        raw = (FIX / fixture).read_bytes()
        (self.tmp / "tuya" / "profiles" / fname).write_bytes(raw)
        d = json.loads(raw)
        e = {"id": d["id"], "rev": d["rev"], "kind": d["kind"], "schema": d["schema"],
             "file": f"tuya/profiles/{fname}", "sha256": hashlib.sha256(raw).hexdigest(),
             "sig": "", "verified": d["verified"], "product_ids": d["match"]["product_ids"],
             "label": d["label"]}
        e.update(over)
        return e

    def write_index(self, entries):
        ui.TUYA_INDEX_PATH.write_text(json.dumps(
            {"schema_version": 1, "updated_at": "2026-01-01T00:00:00Z", "profiles": entries}))

    def run_index(self, check):
        problems: list[str] = []
        with contextlib.redirect_stdout(io.StringIO()):
            changed, count = ui.process_tuya_index(argparse.Namespace(check=check), problems)
        return changed, count, problems

    def test_clean_index_passes_check(self):
        self.write_index([self.add("ok_readonly.json", "a.json")])
        self.assertEqual(self.run_index(True), (False, 1, []))

    def test_fill_sha256_when_not_check(self):
        self.write_index([self.add("ok_readonly.json", "a.json", sha256="")])
        changed, _, problems = self.run_index(False)
        self.assertTrue(changed)
        self.assertEqual(problems, [])
        entry = json.loads(ui.TUYA_INDEX_PATH.read_text())["profiles"][0]
        self.assertEqual(entry["sha256"], hashlib.sha256(
            (FIX / "ok_readonly.json").read_bytes()).hexdigest())
        self.assertEqual(self.run_index(True)[2], [])

    def test_check_fails_on_stale_sha(self):
        self.write_index([self.add("ok_readonly.json", "a.json", sha256="0" * 64)])
        problems = self.run_index(True)[2]
        self.assertTrue(any("sha256" in p for p in problems))
        self.assertEqual(json.loads(ui.TUYA_INDEX_PATH.read_text())["profiles"][0]["sha256"], "0" * 64)

    def test_check_fails_on_index_file_mismatch(self):
        for key, val in [("id", "other-1"), ("rev", 2), ("kind", "relay"), ("schema", 2),
                         ("product_ids", ["zzz"])]:
            with self.subTest(key):
                self.write_index([self.add("ok_readonly.json", "a.json", **{key: val})])
                self.assertTrue(self.run_index(True)[2])

    def test_index_comparison_is_type_exact(self):
        for key, val in [("rev", True), ("rev", 1.0), ("schema", True), ("schema", 1.0)]:
            with self.subTest(f"{key}={val!r}"):
                self.write_index([self.add("ok_readonly.json", "a.json", **{key: val})])
                self.assertTrue(self.run_index(True)[2])

    def test_cmd_without_sig_fails(self):
        self.write_index([self.add("ok_cmd.json", "c.json", sig="")])
        problems = self.run_index(True)[2]
        self.assertTrue(any("sig" in p for p in problems))

    def test_cmd_with_sig_and_readonly_without_sig_pass(self):
        self.write_index([self.add("ok_cmd.json", "c.json", sig="ab" * 64)])
        self.assertEqual(self.run_index(True)[2], [])
        self.write_index([self.add("ok_relay.json", "r.json", sig="ab" * 64)])
        self.assertEqual(self.run_index(True)[2], [])
        self.write_index([self.add("ok_readonly.json", "a.json")])
        self.assertEqual(self.run_index(True)[2], [])

    def test_sig_must_be_128_hex_when_present(self):
        for bad in ("ab" * 63, "ab" * 65, "zz" * 64, "ab" * 63 + "a ", " " + "a" * 127):
            with self.subTest(bad=bad):
                self.write_index([self.add("ok_cmd.json", "c.json", sig=bad)])
                problems = self.run_index(True)[2]
                self.assertTrue(any("128 hex" in p for p in problems), problems)
        self.write_index([self.add("ok_readonly.json", "a.json", sig="AB" * 64)])
        self.assertEqual(self.run_index(True)[2], [])

    def run_raw_index(self, text):
        ui.TUYA_INDEX_PATH.write_text(text)
        return self.run_index(True)

    def test_malformed_index_is_a_clean_error(self):
        cases = {
            "not json": "{not json",
            "array": "[]",
            "profiles not a list": '{"profiles": {"a": 1}}',
            "entry not an object": '{"profiles": ["x", 3, null]}',
            "file not a string": '{"profiles": [{"file": 7}]}',
        }
        for name, text in cases.items():
            with self.subTest(name):
                changed, _, problems = self.run_raw_index(text)
                self.assertFalse(changed)
                self.assertTrue(problems, f"{name}: no problem reported")
        _, count, problems = self.run_raw_index('{"profiles": ["x", 3]}')
        self.assertEqual(count, 2)
        self.assertEqual(len(problems), 2)

    def test_duplicate_product_id_same_rev_fails(self):
        a = self.add("ok_readonly.json", "a.json")
        c = self.add("ok_cmd.json", "c.json", sig="ab" * 64,
                     product_ids=["hytatexziwaifxj1"])
        # keep the file's own product_ids in sync so only the duplicate rule fires
        raw = json.loads((self.tmp / "tuya/profiles/c.json").read_text())
        raw["match"]["product_ids"] = ["hytatexziwaifxj1"]
        data = (json.dumps(raw, indent=2) + "\n").encode()
        (self.tmp / "tuya/profiles/c.json").write_bytes(data)
        c["sha256"] = hashlib.sha256(data).hexdigest()
        self.write_index([a, c])
        problems = self.run_index(True)[2]
        self.assertTrue(any("hytatexziwaifxj1" in p for p in problems), problems)

    def test_missing_file_and_invalid_profile_reported(self):
        self.write_index([self.add("ok_readonly.json", "a.json", file="tuya/profiles/nope.json")])
        self.assertTrue(self.run_index(True)[2])
        self.write_index([self.add("bad_schema2.json", "b.json")])
        self.assertTrue(self.run_index(True)[2])

    def test_real_index_is_current(self):
        ui.ROOT, ui.TUYA_INDEX_PATH = self._root, self._idx
        changed, count, problems = self.run_index(True)
        self.assertEqual(problems, [])
        self.assertFalse(changed)
        self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
