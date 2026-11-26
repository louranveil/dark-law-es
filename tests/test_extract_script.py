from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests"))

import extract_script as ex  # noqa: E402
import glyph_table as gt  # noqa: E402
import script_format as sf  # noqa: E402
from test_script_format import synthetic_rom  # noqa: E402

TABLE_FILE = REPO / "tbl" / "original.json"


def small_table() -> gt.GlyphTable:
    def entry(char, kind="text"):
        return {"char": char, "kind": kind, "confidence": "seen"}

    return gt.GlyphTable(
        {
            "00": entry("　", "blank"),
            "0A": entry("こ"),
            "19": entry("の"),
            "FD 04": entry("世"),
            "FA 2A": entry("　", "blank"),
            "40": {"char": None, "kind": "placeholder", "confidence": "unknown"},
        }
    )


def tokens_of(*data: int):
    return sf.tokenize(bytes(data)).tokens


class RenderTest(unittest.TestCase):
    def test_text_line_breaks_indents_and_missing_glyphs(self):
        text = ex.render_run(tokens_of(0x00, 0x0A, 0xFD, 0x04, 0xC3, 0xE5, 0x02, 0x19, 0x40, 0xFF)[:-1], small_table())
        self.assertEqual(text, "　こ世\n<E5 02>の[40]")

    def test_a_repeated_character_uses_the_key_escape_unless_canonical(self):
        text = ex.render_run(tokens_of(0x00, 0xFA, 0x2A, 0xFF)[:-1], small_table())
        self.assertEqual(text, "　[FA 2A]")

    def test_parse_is_the_inverse_of_render(self):
        table = small_table()
        for data in (bytes([0x00, 0x0A, 0xFD, 0x04, 0xC3, 0xE5, 0x02, 0x19, 0x40]), bytes([0x00, 0xFA, 0x2A, 0x0A])):
            tokens = sf.tokenize(data + b"\xff").tokens[:-1]
            self.assertEqual(ex.parse_run(ex.render_run(tokens, table), table), data)

    def test_parse_rejects_unknown_characters(self):
        with self.assertRaises(ValueError):
            ex.parse_run("A", small_table())


class SplitTest(unittest.TestCase):
    def test_runs_and_skeleton(self):
        skeleton, runs = ex.split_entry(tokens_of(0xC0, 0x0A, 0x19, 0xC3, 0x0A, 0xC8, 0x80, 0xFF), small_table())
        self.assertEqual(skeleton, "<C0>{0}<C8 80><FF>")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["raw"], "0A 19 C3 0A")
        self.assertEqual(runs[0]["jp"], "この\nこ")
        self.assertEqual((runs[0]["es"], runs[0]["status"], runs[0]["max"]), ("", "todo", None))

    def test_two_runs_are_numbered_in_order(self):
        skeleton, runs = ex.split_entry(tokens_of(0x0A, 0xC8, 0x01, 0x19, 0xFF), small_table())
        self.assertEqual(skeleton, "{0}<C8 01>{1}<FF>")
        self.assertEqual([run["raw"] for run in runs], ["0A", "19"])

    def test_blank_or_marker_only_text_stays_in_the_skeleton(self):
        skeleton, runs = ex.split_entry(tokens_of(0xC0, 0x00, 0xC3, 0x00, 0x40, 0xFF), small_table())
        self.assertEqual(runs, [])
        self.assertEqual(skeleton, "<C0><00><C3><00><40><FF>")

    def test_assemble_rebuilds_the_bytes(self):
        data = bytes([0xC0, 0x0A, 0x19, 0xC3, 0x0A, 0xC8, 0x80, 0x00, 0xFD, 0x04, 0xC7])
        skeleton, runs = ex.split_entry(sf.tokenize(data).tokens, small_table())
        self.assertEqual(ex.assemble({"id": "x", "skeleton": skeleton, "runs": runs}), data)

    def test_a_broken_skeleton_is_an_error(self):
        with self.assertRaises(ValueError):
            ex.assemble({"id": "x", "skeleton": "C0", "runs": []})


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.rom = bytes(synthetic_rom())
        self.table = small_table()

    def test_entries_come_from_every_table(self):
        entries, summary = ex.build_entries(self.rom, self.table)
        self.assertEqual(summary["blobs"], 6)  # los cinco de las tablas de área y el de los scripts llamables
        roles = {entry.id: entry.role for entry in entries}
        self.assertEqual(roles["E2:0004"], "messages")
        self.assertEqual(roles["E2:0104"], "events")

    def test_the_message_with_text_is_extracted(self):
        entries, _ = ex.build_entries(self.rom, self.table)
        with_text = [entry for entry in entries if entry.runs]
        self.assertEqual([entry.id for entry in with_text], ["E2:0004"])
        self.assertEqual(with_text[0].runs[0]["raw"], "00 0A FD 04 C3 19")

    def test_round_trip_has_no_failures(self):
        entries, _ = ex.build_entries(self.rom, self.table)
        self.assertEqual(ex.verify_round_trip(self.rom, entries, self.table), [])

    def test_a_run_after_fe_is_flagged_for_review(self):
        rom = bytearray(self.rom)
        offset = sf.cpu_to_offset(0xE20004)
        rom[offset : offset + 6] = bytes([0xFE, 0x03, 0x0A, 0x19, 0xC7, 0xC7])
        entries, _ = ex.build_entries(bytes(rom), self.table)
        entry = next(entry for entry in entries if entry.id == "E2:0004")
        self.assertEqual(entry.status, "review")
        self.assertIn(ex.VARIABLE_COMMAND_PROBLEM, entry.problems)


class DumpTest(unittest.TestCase):
    def setUp(self):
        self.rom = bytes(synthetic_rom())
        self.table = small_table()
        self.entries, _ = ex.build_entries(self.rom, self.table)

    def test_only_entries_with_text_are_written(self):
        with tempfile.TemporaryDirectory() as folder:
            written, refused = ex.dump(self.entries, Path(folder), force=False)
            self.assertEqual(written, ["E2-0000-messages.json"])
            self.assertEqual(refused, [])
            data = json.loads((Path(folder) / written[0]).read_text(encoding="utf-8"))
            self.assertEqual(data["format"], 1)
            self.assertEqual(data["entries"][0]["id"], "E2:0004")

    def test_an_existing_file_is_not_overwritten_without_force(self):
        with tempfile.TemporaryDirectory() as folder:
            ex.dump(self.entries, Path(folder), force=False)
            path = Path(folder) / "E2-0000-messages.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["entries"][0]["runs"][0]["es"] = "traducción"
            path.write_text(json.dumps(data), encoding="utf-8")
            written, refused = ex.dump(self.entries, Path(folder), force=False)
            self.assertEqual((written, refused), ([], ["E2-0000-messages.json"]))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["entries"][0]["runs"][0]["es"], "traducción")

    def test_force_keeps_the_translations_whose_raw_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            ex.dump(self.entries, Path(folder), force=False)
            path = Path(folder) / "E2-0000-messages.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["entries"][0]["runs"][0].update(es="traducción", status="done", max=24, jp="texto viejo")
            path.write_text(json.dumps(data), encoding="utf-8")
            ex.dump(self.entries, Path(folder), force=True)
            merged = json.loads(path.read_text(encoding="utf-8"))["entries"][0]["runs"][0]
            self.assertEqual((merged["es"], merged["status"], merged["max"]), ("traducción", "done", 24))
            self.assertNotEqual(merged["jp"], "texto viejo")  # jp se vuelve a derivar

    def test_force_drops_a_translation_whose_raw_changed(self):
        old = [{"id": "E2:0004", "runs": [{"raw": "AA", "es": "vieja", "status": "done", "max": 1}]}]
        new = [{"id": "E2:0004", "runs": [{"raw": "BB", "es": "", "status": "todo", "max": None}]}]
        self.assertEqual(ex.merge_translations(new, old)[0]["runs"][0]["es"], "")


class MainTest(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ex.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_rom_is_required(self):
        saved = os.environ.pop("DARK_LAW_ROM", None)
        try:
            code, _, err = self.run_main("check", "--table", str(TABLE_FILE))
        finally:
            if saved is not None:
                os.environ["DARK_LAW_ROM"] = saved
        self.assertEqual(code, 2)
        self.assertIn("--rom", err)

    def test_check_on_a_synthetic_rom(self):
        with tempfile.TemporaryDirectory() as folder:
            rom = Path(folder) / "synthetic.bin"
            rom.write_bytes(bytes(synthetic_rom()))
            code, out, _ = self.run_main("check", "--rom", str(rom), "--table", str(TABLE_FILE))
            self.assertEqual(code, 0)
            self.assertIn("round trip: ok", out)

    def test_dump_refuses_to_overwrite_and_reports_it(self):
        with tempfile.TemporaryDirectory() as folder:
            rom = Path(folder) / "synthetic.bin"
            rom.write_bytes(bytes(synthetic_rom()))
            args = ("dump", "--rom", str(rom), "--table", str(TABLE_FILE), "--out", str(Path(folder) / "text"))
            self.assertEqual(self.run_main(*args)[0], 0)
            code, _, err = self.run_main(*args)
            self.assertEqual(code, 1)
            self.assertIn("refused", err)
            self.assertEqual(self.run_main(*args, "--force")[0], 0)


if __name__ == "__main__":
    unittest.main()
