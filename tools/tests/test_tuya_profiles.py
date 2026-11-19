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
GOOD = ["ok_readonly.json", "ok_cmd.json", "ok_cmd_enum.json", "ok_relay.json"]
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
        doc, _, n = load("ok_cmd_enum.json")
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

    def test_cmd_type_mismatch_fixture_has_one_clear_error(self):
        doc, err, n = load("bad_cmd_type_mismatch.json")
        self.assertIsNone(err)
        errors = ui.validate_tuya_profile(doc, n)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("cmd.enable", errors[0])
        self.assertIn("read.enabled", errors[0])

    def test_cmd_type_compatibility_rule(self):
        doc, _, n = load("ok_cmd.json")
        # enum enable against a read DP declared as str is compatible
        d = json.loads(json.dumps(doc))
        d["read"]["enabled"]["type"] = "str"
        d["cmd"]["enable"] = {"dp": 112, "type": "enum", "on": "start", "off": "stop"}
        self.assertEqual(ui.validate_tuya_profile(d, n), [])
        # ... against enum too
        d["read"]["enabled"]["type"] = "enum"
        self.assertEqual(ui.validate_tuya_profile(d, n), [])
        # bool enable against a read DP declared int is a mismatch
        d = json.loads(json.dumps(doc))
        d["read"]["enabled"]["type"] = "int"
        self.assertTrue(any("cmd.enable" in e for e in ui.validate_tuya_profile(d, n)))
        # set_a int against a read DP declared bool / enum / str is a mismatch
        for other in ("bool", "enum", "str"):
            d = json.loads(json.dumps(doc))
            d["read"]["set_a"]["type"] = other
            errors = ui.validate_tuya_profile(d, n)
            self.assertTrue(any("cmd.set_a" in e for e in errors), (other, errors))
        # a cmd DP that read does not declare is not compared
        d = json.loads(json.dumps(doc))
        d["cmd"]["set_a"]["dp"] = 130
        self.assertEqual(ui.validate_tuya_profile(d, n), [])

    def test_charger_cmd_needs_both_commands(self):
        for name, missing in (("bad_cmd_only_set_a.json", "cmd.enable"),
                              ("bad_cmd_only_enable.json", "cmd.set_a")):
            with self.subTest(name):
                doc, err, n = load(name)
                self.assertIsNone(err)
                errors = ui.validate_tuya_profile(doc, n)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(missing, errors[0])

    def test_relay_cmd_may_have_enable_only(self):
        doc, _, n = load("ok_relay.json")
        self.assertEqual(list(doc["cmd"]), ["enable"])
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def relay(self, **cmd_extra):
        doc, _, n = load("ok_relay.json")
        doc["cmd"].update(cmd_extra)
        return doc, n

    def test_relay_with_countdown_passes(self):
        doc, n = self.relay(countdown={"dp": 9, "type": "int"})
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def test_relay_countdown_must_be_int_with_a_valid_dp(self):
        for spec in ({"dp": 9, "type": "bool"}, {"dp": 9, "type": "enum"},
                     {"dp": 0, "type": "int"}, {"dp": 256, "type": "int"},
                     {"dp": 9, "type": "int", "scale": 2}, {"type": "int"}):
            with self.subTest(spec):
                doc, n = self.relay(countdown=spec)
                self.assertTrue(any("cmd.countdown" in e
                                    for e in ui.validate_tuya_profile(doc, n)))

    def test_charger_countdown_is_rejected(self):
        doc, _, n = load("ok_cmd.json")
        doc["cmd"]["countdown"] = {"dp": 9, "type": "int"}
        errors = ui.validate_tuya_profile(doc, n)
        self.assertTrue(any("cmd.countdown" in e for e in errors), errors)

    def test_relay_cmd_needs_enable_and_read_enabled(self):
        doc, _, n = load("ok_relay.json")
        del doc["cmd"]["enable"]
        doc["cmd"]["countdown"] = {"dp": 9, "type": "int"}
        self.assertTrue(any("cmd.enable" in e for e in ui.validate_tuya_profile(doc, n)))
        doc, _, n = load("ok_relay.json")
        del doc["read"]["enabled"]
        self.assertTrue(any("read.enabled" in e for e in ui.validate_tuya_profile(doc, n)))
        # a read-only relay (no cmd) needs no read.enabled
        del doc["cmd"]
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def test_countdown_type_must_match_read_of_same_dp(self):
        doc, n = self.relay(countdown={"dp": 9, "type": "int"})
        doc["read"]["power_w"] = {"dp": 9, "type": "bool"}
        errors = ui.validate_tuya_profile(doc, n)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("cmd.countdown: dp 9 has type 'int'", errors[0])
        self.assertIn("read.power_w", errors[0])

    def test_read_enabled_type_must_fit_cmd_enable_even_on_other_dp(self):
        doc, _, n = load("ok_relay.json")
        doc["read"]["enabled"] = {"dp": 2, "type": "int"}
        errors = ui.validate_tuya_profile(doc, n)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("cmd.enable", errors[0])
        self.assertIn("read.enabled", errors[0])
        doc["read"]["enabled"] = {"dp": 2, "type": "bool"}
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        doc["cmd"]["enable"] = {"dp": 1, "type": "enum", "on": "on", "off": "off"}
        self.assertTrue(ui.validate_tuya_profile(doc, n))
        doc["read"]["enabled"] = {"dp": 2, "type": "str"}
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])

    def test_countdown_dp_must_differ_from_enable_dp(self):
        doc, n = self.relay(countdown={"dp": 1, "type": "int"})
        errors = ui.validate_tuya_profile(doc, n)
        self.assertTrue(any("cmd.countdown" in e and "cmd.enable" in e for e in errors), errors)

    def test_energy_kwh_is_a_relay_read_role(self):
        doc, _, n = load("ok_relay.json")
        doc["read"]["energy_kwh"] = {"dp": 17, "type": "int", "scale": 0.001}
        self.assertEqual(ui.validate_tuya_profile(doc, n), [])
        doc["read"]["energy_kwh"] = {"dp": 17, "type": "int", "scale": 0}
        self.assertTrue(ui.validate_tuya_profile(doc, n))
        doc, _, n = load("ok_cmd.json")
        doc["read"]["energy_kwh"] = {"dp": 17, "type": "int", "scale": 0.001}
        self.assertTrue(any("energy_kwh" in e for e in ui.validate_tuya_profile(doc, n)))

    def test_empty_product_ids_only_for_drafts(self):
        doc, _, n = load("ok_relay.json")
        doc["match"]["product_ids"] = []
        self.assertTrue(ui.validate_tuya_profile(doc, n))
        self.assertEqual(ui.validate_tuya_profile(doc, n, draft=True), [])
        doc["match"]["product_ids"] = ["bad id"]
        self.assertTrue(ui.validate_tuya_profile(doc, n, draft=True))

    def test_standard_socket_draft(self):
        path = REPO / "tuya" / "drafts" / "socket_standard_cmd.json"
        errors, _ = ui.check_tuya_draft(path)
        self.assertEqual(errors, [])
        doc = json.loads(path.read_text())
        self.assertEqual(doc["kind"], "relay")
        self.assertIs(doc["verified"], False)
        self.assertEqual(doc["match"]["product_ids"], [])
        self.assertEqual(doc["cmd"], {"enable": {"dp": 1, "type": "bool"},
                                      "countdown": {"dp": 9, "type": "int"}})
        self.assertEqual(doc["read"]["enabled"], {"dp": 1, "type": "bool"})
        self.assertEqual(doc["read"]["current_a"], {"dp": 18, "type": "int", "scale": 0.001})
        self.assertEqual(doc["read"]["power_w"], {"dp": 19, "type": "int", "scale": 0.1})
        self.assertEqual(doc["read"]["voltage_v"], {"dp": 20, "type": "int", "scale": 0.1})
        self.assertEqual(doc["read"]["energy_kwh"], {"dp": 17, "type": "int", "scale": 0.001})
        index = json.loads((REPO / "tuya" / "index.json").read_text())
        self.assertFalse(any("socket_standard" in e["file"] for e in index["profiles"]))

    def test_bool_is_not_an_int(self):
        doc, _, n = load("ok_readonly.json")
        doc["rev"] = True
        self.assertTrue(ui.validate_tuya_profile(doc, n))

    def test_nan_and_duplicate_keys_fail_to_parse(self):
        _, err = ui.parse_tuya_profile(b'{"schema": NaN}')
        self.assertTrue(err)
        _, err = ui.parse_tuya_profile(b'{"schema": 1, "schema": 1}')
        self.assertTrue(err)


class DraftTests(unittest.TestCase):
    """`--draft FILE` and the tuya/drafts/ directory."""

    def draft(self, path):
        return ui.check_tuya_draft(Path(path))

    def test_good_fixtures_pass_as_drafts(self):
        for name in GOOD:
            with self.subTest(name):
                errors, entry = self.draft(FIX / name)
                self.assertEqual(errors, [])
                self.assertEqual(entry["sig"], "")
                self.assertEqual(entry["sha256"], hashlib.sha256((FIX / name).read_bytes()).hexdigest())

    def test_draft_allows_cmd_without_signature(self):
        errors, entry = self.draft(FIX / "ok_cmd.json")
        self.assertEqual(errors, [])
        self.assertEqual(entry["file"], "tuya/profiles/ok_cmd.json")
        self.assertEqual(entry["id"], "feyree-evse-cmd-1")
        self.assertEqual(entry["product_ids"], ["hytatexziwaifxj1", "emvuyyax4lekiooj"])

    def test_draft_rejects_every_bad_fixture_with_the_index_messages(self):
        for name in BAD:
            with self.subTest(name):
                doc, err, n = load(name)
                expected = [err] if err else ui.validate_tuya_profile(doc, n)
                errors, entry = self.draft(FIX / name)
                self.assertEqual(errors, expected)
                self.assertIsNone(entry)

    def test_draft_marked_verified_is_rejected(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        doc = json.loads((FIX / "ok_cmd.json").read_text(encoding="utf-8"))
        doc["verified"] = True
        path = tmp / "v.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        errors, entry = self.draft(path)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("never verified", errors[0])
        self.assertIsNone(entry)
        # the published-profile rules still accept verified: true
        self.assertEqual(ui.validate_tuya_profile(doc, path.stat().st_size), [])

    def test_draft_with_non_object_top_level_gives_errors_not_an_exception(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for text in ("[]", '"x"', "3"):
            with self.subTest(text):
                path = tmp / "n.json"
                path.write_text(text, encoding="utf-8")
                errors, entry = self.draft(path)
                self.assertTrue(errors)
                self.assertIsNone(entry)

    def test_draft_missing_file_is_an_error(self):
        errors, entry = self.draft(FIX / "nope.json")
        self.assertTrue(errors)
        self.assertIsNone(entry)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["update_index.py", *argv]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ui.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_cli_draft_accepts_and_prints_the_index_entry(self):
        code, out, _ = self.run_cli("--draft", str(FIX / "ok_cmd.json"))
        self.assertEqual(code, 0)
        self.assertIn('"sha256"', out)
        self.assertIn("tuya/profiles/ok_cmd.json", out)
        self.assertIn("signature", out.lower())

    def test_cli_draft_rejects_with_the_same_message_as_the_index_path(self):
        code, _, err = self.run_cli("--draft", str(FIX / "bad_cmd_type_mismatch.json"))
        self.assertEqual(code, 1)
        self.assertIn("FAILED Tuya profile validation", err)
        self.assertIn("cmd.enable", err)

    def test_cli_draft_does_not_touch_the_index(self):
        before = ui.TUYA_INDEX_PATH.read_bytes()
        self.run_cli("--draft", str(FIX / "ok_cmd.json"))
        self.assertEqual(ui.TUYA_INDEX_PATH.read_bytes(), before)

    def test_published_draft_file_is_valid_and_unlisted(self):
        path = REPO / "tuya" / "drafts" / "feyree_evse_cmd.json"
        errors, _ = self.draft(path)
        self.assertEqual(errors, [])
        doc = json.loads(path.read_text())
        self.assertEqual(doc["id"], "feyree-evse-1")
        self.assertEqual(doc["rev"], 2)
        self.assertIs(doc["verified"], False)
        self.assertEqual(doc["cmd"], {"set_a": {"dp": 102, "type": "int"},
                                      "enable": {"dp": 112, "type": "bool"}})
        self.assertEqual(doc["quirks"], {"reassert_set_a_on_plug": True})
        published = json.loads((REPO / "tuya" / "profiles" / "feyree_evse.json").read_text())
        for key in ("read", "match", "limits", "kind", "schema"):
            self.assertEqual(doc[key], published[key], key)
        index = json.loads((REPO / "tuya" / "index.json").read_text())
        self.assertFalse(any("drafts" in e["file"] for e in index["profiles"]))


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

    def test_check_fails_if_index_references_a_draft(self):
        (self.tmp / "tuya" / "drafts").mkdir()
        raw = (FIX / "ok_readonly.json").read_bytes()
        (self.tmp / "tuya" / "drafts" / "d.json").write_bytes(raw)
        entry = self.add("ok_readonly.json", "a.json", file="tuya/drafts/d.json")
        self.write_index([entry])
        problems = self.run_index(True)[2]
        self.assertTrue(any("draft" in p for p in problems), problems)
        self.assertTrue(any("draft" in p for p in self.run_index(False)[2]))

    def test_draft_path_is_normalised_before_the_guard(self):
        (self.tmp / "tuya" / "drafts").mkdir()
        (self.tmp / "tuya" / "drafts" / "d.json").write_bytes((FIX / "ok_readonly.json").read_bytes())
        for rel in ("tuya/profiles/../drafts/d.json", "tuya/./drafts/d.json",
                    "tuya\\drafts\\d.json", "tuya/profiles/../drafts/../drafts/d.json"):
            with self.subTest(rel):
                self.write_index([self.add("ok_readonly.json", "a.json", file=rel)])
                problems = self.run_index(True)[2]
                self.assertTrue(any("draft" in p for p in problems), problems)

    def test_check_validates_drafts_with_the_draft_rules(self):
        self.write_index([])
        (self.tmp / "tuya" / "drafts").mkdir()
        (self.tmp / "tuya" / "drafts" / "ok.json").write_bytes((FIX / "ok_cmd.json").read_bytes())
        problems: list[str] = []
        self.assertEqual(ui.process_tuya_drafts(problems), 1)
        self.assertEqual(problems, [])  # cmd without a signature is fine in a draft
        (self.tmp / "tuya" / "drafts" / "bad.json").write_bytes(
            (FIX / "bad_cmd_type_mismatch.json").read_bytes())
        problems = []
        self.assertEqual(ui.process_tuya_drafts(problems), 2)
        self.assertTrue(any("bad.json" in p for p in problems), problems)
        self.assertTrue(any("cmd.enable" in p for p in problems), problems)
        self.assertFalse(any("ok.json" in p for p in problems), problems)

    def test_real_index_is_current(self):
        ui.ROOT, ui.TUYA_INDEX_PATH = self._root, self._idx
        changed, count, problems = self.run_index(True)
        self.assertEqual(problems, [])
        self.assertFalse(changed)
        self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
