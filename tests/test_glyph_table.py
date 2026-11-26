from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import glyph_table as gt  # noqa: E402
import script_format as sf  # noqa: E402

TABLE_FILE = REPO / "tbl" / "original.json"


def entry(char, kind="text", confidence="seen", **extra):
    return {"char": char, "kind": kind, "confidence": confidence, **extra}


def sample_document():
    return {
        "format": 1,
        "glyphs": {
            "0A": entry("こ"),
            "FD 3F": entry("魔"),
            "40": entry(None, "placeholder", "unknown"),
            "FB 4C": entry("災", confidence="uncertain"),
        },
    }


class ValidateTest(unittest.TestCase):
    def test_a_good_document_has_no_problems(self):
        self.assertEqual(gt.validate(sample_document()), [])

    def test_wrong_format_or_missing_glyphs(self):
        self.assertTrue(gt.validate({"format": 2, "glyphs": {}}))
        self.assertTrue(gt.validate({"format": 1}))
        self.assertTrue(gt.validate([]))

    def test_keys_must_be_canonical_glyph_keys(self):
        for key in ("0a", "FD3F", "C0 01", "FD 3F 00", "100"):
            document = {"format": 1, "glyphs": {key: entry("あ")}}
            self.assertTrue(gt.validate(document), key)

    def test_entry_fields_are_checked(self):
        cases = [
            entry("あ", kind="nonsense"),
            entry("あ", confidence="maybe"),
            entry("ああ"),
            entry(None, "text"),
            entry("あ", "placeholder", "unknown"),
        ]
        for case in cases:
            self.assertTrue(gt.validate({"format": 1, "glyphs": {"0A": case}}), case)

    def test_an_icon_may_or_may_not_carry_a_character(self):
        document = {"format": 1, "glyphs": {"B8": entry("◀", "icon"), "B9": entry(None, "icon")}}
        self.assertEqual(gt.validate(document), [])


class TableTest(unittest.TestCase):
    def test_lookup_and_review_list(self):
        table = gt.GlyphTable(sample_document()["glyphs"])
        self.assertEqual(table.char("0A"), "こ")
        self.assertIsNone(table.char("40"))
        self.assertIsNone(table.char("FF"))
        self.assertEqual(table.needs_review(), ["40", "FB 4C"])

    def test_format_round_trips_and_keeps_one_entry_per_line(self):
        table = gt.GlyphTable(sample_document()["glyphs"])
        text = gt.format_table(table, "test")
        data = json.loads(text)
        self.assertEqual(data["glyphs"], table.entries)
        self.assertEqual(data["description"], "test")
        self.assertEqual(text.count("\n"), 4 + len(table.entries) + 2 + 0)
        self.assertLess(text.index('"0A"'), text.index('"40"'))
        self.assertLess(text.index('"40"'), text.index('"FD 3F"'))

    def test_load_reports_bad_json_and_bad_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "t.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(gt.TableError):
                gt.load_table(path)
            path.write_text(json.dumps({"format": 1, "glyphs": {"xx": entry("あ")}}), encoding="utf-8")
            with self.assertRaises(gt.TableError):
                gt.load_table(path)


class DecodeTest(unittest.TestCase):
    def test_text_commands_and_missing_glyphs(self):
        table = gt.GlyphTable(sample_document()["glyphs"])
        blob = bytes([0xC0, 0x0A, 0xFD, 0x3F, 0x40, 0x05, 0xC8, 0x80, 0xFF])
        text = gt.decode_tokens(sf.tokenize(blob).tokens, table)
        self.assertEqual(text, "<C0>こ魔[40][05]<C8 80><FF>")

    def test_uncovered_and_without_char(self):
        table = gt.GlyphTable(sample_document()["glyphs"])
        usage = Counter({"0A": 5, "40": 3, "99": 2, "FD 01": 1})
        self.assertEqual(gt.uncovered(usage, table), Counter({"99": 2, "FD 01": 1}))
        self.assertEqual(gt.without_char(usage, table), Counter({"40": 3}))

    def test_blob_argument(self):
        self.assertEqual(gt.read_blob_arg("E2EE73/5"), (0xE2EE73, 5))
        self.assertEqual(gt.read_blob_arg("E2EE73"), (0xE2EE73, 0))


class RealTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = gt.load_table(TABLE_FILE)

    def test_the_project_table_is_valid_and_complete(self):
        self.assertEqual(len(self.table.entries), 920)

    def test_kana_blocks_follow_the_gojuon_order(self):
        self.assertEqual(self.table.char("01"), "あ")
        self.assertEqual(self.table.char("2E"), "ん")
        self.assertEqual(self.table.char("41"), "ア")
        self.assertEqual(self.table.char("6E"), "ン")
        self.assertEqual(self.table.char("9E"), "・")
        self.assertEqual(self.table.char("A8"), "０")

    def test_each_character_belongs_to_one_glyph(self):
        counts = Counter(entry["char"] for entry in self.table.entries.values() if entry["char"] and entry["kind"] != "blank")
        self.assertEqual([char for char, count in counts.items() if count > 1], [])

    def test_the_open_readings_are_the_ones_listed_in_the_docs(self):
        self.assertEqual(self.table.needs_review(), ["40", "B2", "BD", "FB 4C"])

    def test_the_file_is_in_canonical_format(self):
        data = json.loads(TABLE_FILE.read_text(encoding="utf-8"))
        self.assertEqual(TABLE_FILE.read_text(encoding="utf-8"), gt.format_table(gt.GlyphTable(data["glyphs"]), data["description"]))


class MainTest(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gt.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_check_without_rom_validates_the_table(self):
        code, out, _ = self.run_main("check", "--table", str(TABLE_FILE))
        self.assertEqual(code, 0)
        self.assertIn("920 glyphs", out)

    def test_bad_table_and_missing_rom_are_usage_errors(self):
        code, _, err = self.run_main("check", "--table", "none.json")
        self.assertEqual(code, 2)
        self.assertIn("error", err)
        code, _, err = self.run_main("check", "--table", str(TABLE_FILE), "--rom", "none.sfc")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
