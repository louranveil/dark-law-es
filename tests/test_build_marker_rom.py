from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_marker_rom as marker  # noqa: E402
import extract_script as ex  # noqa: E402
import glyph_table as gt  # noqa: E402
import script_format as sf  # noqa: E402
from script_builder import PatchError, RomPatcher  # noqa: E402

REAL_ROM = os.environ.get("DARK_LAW_ROM")
ASAR = os.environ.get("ASAR")
TABLE_FILE = REPO / "tbl" / "original.json"
ROM_SIZE = 0x280000  # llega hasta el final del banco $E7 (desplazamiento de fichero 0x27FFFF)


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def make_entry(address: int, runs: list[bytes], skeleton: str, size: int, slots: list[str]) -> ex.Entry:
    return ex.Entry(
        address,
        "messages",
        slots,
        size,
        "ok",
        [],
        skeleton,
        [{"raw": hex_bytes(raw), "jp": "", "es": "", "status": "todo", "max": None} for raw in runs],
    )


def synthetic_rom(entry_bytes: dict[int, bytes], pointers: dict[int, int]) -> bytes:
    """Una ROM de 0x280000 bytes llena de ``FF`` con blobs en direcciones largas y punteros de 16 bits."""
    rom = bytearray([0xFF]) * ROM_SIZE
    for address, data in entry_bytes.items():
        offset = sf.cpu_to_offset(address)
        rom[offset : offset + len(data)] = data
    for address, value in pointers.items():
        offset = sf.cpu_to_offset(address)
        rom[offset : offset + 2] = value.to_bytes(2, "little")
    return bytes(rom)


def text_run(slots: int) -> bytes:
    return bytes(range(1, slots + 1))  # glifos de un byte


class MarkerTextTests(unittest.TestCase):
    def test_candidates_are_even_and_shrink(self):
        candidates = marker.marker_candidates("E2:EE93", 1)
        self.assertEqual(candidates, ["E2EE93.1", "EE93.1", "93.1", "#1"])
        self.assertTrue(all(len(text) % 2 == 0 for text in candidates))

    def test_candidates_are_even_for_any_run_number_and_their_size_is_what_choose_marker_assumes(self):
        for number in (0, 9, 15, 16, 255, 256):
            for text in marker.marker_candidates("E7:4A00", number):
                with self.subTest(number=number, text=text):
                    self.assertEqual(len(text) % 2, 0)
                    self.assertEqual(len(marker.probe.encode_latin(text)), len(text) // 2 * marker.BYTES_PER_PAIR)

    def test_two_digit_run_numbers_keep_every_candidate_readable(self):
        self.assertEqual(marker.marker_candidates("E7:4A00", 16), ["E74A00.10 ", "4A00.10 ", "00.10 ", "10"])

    def test_run_numbers_above_nine_stay_one_character(self):
        self.assertEqual(marker.marker_candidates("E7:4A00", 15)[0], "E74A00.F")

    def test_every_candidate_is_writable_with_the_latin_font(self):
        for text in marker.marker_candidates("EF:C1FB", 12):
            marker.probe.encode_latin(text)

    def test_choose_marker_takes_the_longest_that_fits(self):
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 12), "E2EE93.0")
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 11), "EE93.0")
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 9), "EE93.0")
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 8), "93.0")
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 5), "#0")
        self.assertEqual(marker.choose_marker("E2:EE93", 0, 3), "#0")
        self.assertIsNone(marker.choose_marker("E2:EE93", 0, 2))

    def test_ruler_counts_positions_and_keeps_the_marker(self):
        text = marker.ruler_text("E2EE93.0", 20)
        self.assertEqual(len(text), 20)
        self.assertTrue(text.startswith("E2EE93.0"))
        self.assertEqual(text[8:], "890123456789")

    def test_ruler_rejects_odd_or_short_requests(self):
        with self.assertRaises(PatchError):
            marker.ruler_text("E2EE93.0", 9)
        with self.assertRaises(PatchError):
            marker.ruler_text("E2EE93.0", 6)

    def test_slot_rows_of_the_original_text(self):
        raw = bytes([0x01, 0x02, 0xFD, 0x10, 0xC3, 0xE5, 0x02, 0x03])
        self.assertEqual(marker.run_slot_rows(raw), [3, 3])


class BuildBlobTests(unittest.TestCase):
    def entry(self, runs: list[bytes], skeleton: str) -> dict:
        return make_entry(0xE20100, runs, skeleton, 99, ["E20000#0"]).to_json()

    def test_runs_are_replaced_and_commands_kept(self):
        blob = marker.build_marked_blob(self.entry([text_run(20)], "<C0>{0}<C8 80><FF>"))
        self.assertEqual(blob.data[0], 0xC0)
        self.assertEqual(blob.data[-3:], bytes([0xC8, 0x80, 0xFF]))
        self.assertEqual(blob.data[1:13], marker.probe.encode_latin("E20100.0"))
        self.assertEqual(blob.runs[0].start, 1)
        self.assertEqual(blob.runs[0].length, 12)
        self.assertEqual(blob.runs[0].marker, "E20100.0")

    def test_a_marker_never_exceeds_the_original_run(self):
        for length in range(3, 40):
            blob = marker.build_marked_blob(self.entry([text_run(length)], "<C0>{0}<FF>"))
            self.assertLessEqual(blob.runs[0].length, length)

    def test_a_run_under_three_bytes_is_left_alone(self):
        blob = marker.build_marked_blob(self.entry([text_run(2)], "<C0>{0}<FF>"))
        self.assertIsNone(blob.runs[0].text)
        self.assertEqual(blob.data, bytes([0xC0, 0x01, 0x02, 0xFF]))

    def test_line_breaks_inside_a_run_disappear_with_the_run(self):
        raw = bytes([0x01, 0x02, 0x03, 0xC3, 0x04, 0x05, 0x06])
        blob = marker.build_marked_blob(self.entry([raw], "<C0>{0}<FF>"))
        self.assertNotIn(0xC3, blob.data)
        self.assertEqual(blob.runs[0].original_rows, [3, 3])

    def test_ruler_writes_the_requested_letters(self):
        blob = marker.build_marked_blob(self.entry([text_run(4)], "<C0>{0}<FF>"), 40)
        self.assertEqual(blob.runs[0].length, 60)
        self.assertEqual(len(blob.runs[0].text), 40)
        self.assertTrue(blob.runs[0].ruler)
        self.assertEqual(blob.runs[0].marker, "E20100.0")

    def test_skeleton_check_accepts_the_marker_blob_and_rejects_changed_commands(self):
        original = bytes([0xC0]) + text_run(20) + bytes([0xC8, 0x80, 0xFF])
        marked = marker.build_marked_blob(self.entry([text_run(20)], "<C0>{0}<C8 80><FF>")).data
        marker.check_skeleton_preserved(original, marked, "E2:0100")
        with self.assertRaises(PatchError):
            marker.check_skeleton_preserved(original, marked.replace(bytes([0xC8, 0x80]), bytes([0xC8, 0x81])), "E2:0100")
        with self.assertRaises(PatchError):
            marker.check_skeleton_preserved(original, marked[:-1], "E2:0100")


class PlaceTests(unittest.TestCase):
    def setUp(self):
        self.skeleton = "<C0>{0}<C8 80><FF>"
        self.blob = bytes([0xC0]) + text_run(20) + bytes([0xC8, 0x80, 0xFF])
        self.address = 0xE20100
        self.rom = synthetic_rom({self.address: self.blob}, {0xE20000: 0x0100, 0xE20002: 0x0100})
        self.entry = make_entry(self.address, [text_run(20)], self.skeleton, len(self.blob), ["E20000#0", "E20000#1"])

    def place(self, rom: bytes, entries: list[ex.Entry], rulers: set[str] = frozenset(), letters: int = 80):
        patcher = RomPatcher(rom)
        mapped = marker.place_entries(patcher, entries, set(rulers), letters)
        return patcher, mapped

    def test_in_place_shrinks_the_blob_and_fills_the_rest_with_ff(self):
        patcher, mapped = self.place(self.rom, [self.entry])
        offset = sf.cpu_to_offset(self.address)
        self.assertEqual(len(patcher.data), len(self.rom))
        self.assertEqual(patcher.data[offset + 16 : offset + len(self.blob)], bytes([0xFF]) * (len(self.blob) - 16))
        self.assertFalse(mapped[0]["relocated"])
        self.assertEqual(mapped[0]["address"], "E2:0100")
        self.assertEqual(mapped[0]["size"], 16)
        self.assertEqual(len(patcher.log), 1)
        self.assertEqual(mapped[0]["runs"][0]["start"], "E2:0101")
        self.assertEqual(mapped[0]["runs"][0]["end"], "E2:010D")

    def test_in_place_changes_only_the_blob(self):
        patcher, _ = self.place(self.rom, [self.entry])
        changed = patcher.changed_offsets()
        start = sf.cpu_to_offset(self.address)
        self.assertTrue(changed <= set(range(start, start + len(self.blob))))
        patcher.verify_log_covers_changes()

    def test_ruler_relocates_and_repoints_every_slot(self):
        patcher, mapped = self.place(self.rom, [self.entry], {"E2:0100"}, 80)
        space = marker.VERIFIED_FREE[0xE2][0]
        self.assertTrue(mapped[0]["relocated"])
        self.assertEqual(mapped[0]["address"], marker.format_address(space))
        for slot in (0xE20000, 0xE20002):
            offset = sf.cpu_to_offset(slot)
            self.assertEqual(int.from_bytes(patcher.data[offset : offset + 2], "little"), space & 0xFFFF)
        new = bytes(patcher.data[sf.cpu_to_offset(space) : sf.cpu_to_offset(space) + mapped[0]["size"]])
        self.assertEqual(new[0], 0xC0)
        self.assertEqual(len(new), 1 + 120 + 3)
        # el blob original queda donde estaba, intacto
        self.assertEqual(bytes(patcher.data[sf.cpu_to_offset(self.address) : sf.cpu_to_offset(self.address) + len(self.blob)]), self.blob)

    def test_relocated_blobs_are_allocated_one_after_another(self):
        second = make_entry(0xE20200, [text_run(20)], self.skeleton, len(self.blob), ["E20004#0"])
        rom = synthetic_rom({self.address: self.blob, 0xE20200: self.blob}, {0xE20000: 0x0100, 0xE20002: 0x0100, 0xE20004: 0x0200})
        _, mapped = self.place(rom, [self.entry, second], {"E2:0100", "E2:0200"}, 40)
        self.assertEqual(mapped[1]["address"], marker.format_address(marker.VERIFIED_FREE[0xE2][0] + mapped[0]["size"]))

    def test_overflow_of_the_free_space_fails_naming_the_entry(self):
        with self.assertRaises(PatchError) as raised:
            self.place(self.rom, [self.entry], {"E2:0100"}, 4000)
        self.assertIn("E2:0100", str(raised.exception))

    def test_a_bank_without_verified_free_space_fails_loudly(self):
        blob = self.blob
        rom = synthetic_rom({0xE30100: blob}, {0xE30000: 0x0100})
        entry = make_entry(0xE30100, [text_run(20)], self.skeleton, len(blob), ["E30000#0"])
        with self.assertRaises(PatchError) as raised:
            self.place(rom, [entry], {"E3:0100"})
        self.assertIn("no verified free space", str(raised.exception))

    def test_a_pointer_that_does_not_match_the_extraction_is_refused(self):
        rom = synthetic_rom({self.address: self.blob}, {0xE20000: 0x0100, 0xE20002: 0x0999})
        with self.assertRaises(PatchError):
            self.place(rom, [self.entry], {"E2:0100"})

    def test_free_space_that_is_not_blank_is_refused(self):
        rom = bytearray(self.rom)
        rom[sf.cpu_to_offset(marker.VERIFIED_FREE[0xE2][0]) + 5] = 0x00
        with self.assertRaises(PatchError):
            marker.verified_free_space(bytes(rom))


class OriginalMapTests(unittest.TestCase):
    def test_run_boundaries_frame_the_original_text(self):
        blob = bytes([0xC0]) + text_run(20) + bytes([0xC8, 0x80, 0xC1]) + text_run(7) + bytes([0xC7])
        rom = synthetic_rom({0xE20100: blob}, {0xE20000: 0x0100})
        entry = make_entry(0xE20100, [text_run(20), text_run(7)], "<C0>{0}<C8 80><C1>{1}<C7>", len(blob), ["E20000#0"])
        (mapped,) = marker.original_map([entry])
        self.assertFalse(mapped["relocated"])
        for run, raw in zip(mapped["runs"], (text_run(20), text_run(7))):
            start, end = (sf.cpu_to_offset(marker.parse_entry_id(run[name])) for name in ("start", "end"))
            self.assertEqual(rom[start:end], raw)
            self.assertIsNone(run["marker"])
        self.assertEqual(mapped["runs"][0]["end"], "E2:0115")


class FinalChangesTests(unittest.TestCase):
    def test_changes_in_the_log_and_in_the_asar_regions_pass(self):
        original = bytes(ROM_SIZE)
        final = bytearray(original)
        final[0x100:0x110] = bytes([1] * 16)
        code = marker.asm_regions()[2][0]
        final[code : code + 8] = bytes([2] * 8)
        marker.check_final_changes(original, bytes(final), [(0x100, 0x110)])

    def test_a_stray_change_is_reported_with_its_offset(self):
        original = bytes(ROM_SIZE)
        final = bytearray(original)
        final[0x500] = 1
        with self.assertRaises(PatchError) as raised:
            marker.check_final_changes(original, bytes(final), [(0x100, 0x110)])
        self.assertIn("0x000500", str(raised.exception))

    def test_a_change_just_outside_a_logged_range_is_a_stray(self):
        original = bytes(ROM_SIZE)
        final = bytearray(original)
        final[0x110] = 1
        with self.assertRaises(PatchError):
            marker.check_final_changes(original, bytes(final), [(0x100, 0x110)])


class SelectionTests(unittest.TestCase):
    def test_only_ok_entries_with_text_in_the_chosen_tables(self):
        good = make_entry(0xE20100, [text_run(5)], "<C0>{0}<FF>", 9, ["E2EE73#0"])
        review = make_entry(0xE20200, [text_run(5)], "<C0>{0}<FF>", 9, ["E2EE73#1"])
        review.status = "review"
        empty = make_entry(0xE20300, [], "<FF>", 1, ["E2EE73#2"])
        other = make_entry(0xE20400, [text_run(5)], "<C0>{0}<FF>", 9, ["E7362B#0"])
        outside = make_entry(0xE20500, [text_run(5)], "<C0>{0}<FF>", 9, ["EF0089#0"])
        event = make_entry(0xE20600, [text_run(5)], "<C0>{0}<FF>", 9, ["E2F393#0"])
        event.role = "events"
        entries = [good, review, empty, other, outside, event]
        self.assertEqual(marker.select_entries(entries, marker.SLICE_TABLES), [good, other])
        self.assertEqual(marker.select_entries(entries, None), [good, other, outside])

    def test_roles_choose_events_and_global_scripts(self):
        message = make_entry(0xE20100, [text_run(5)], "<C0>{0}<FF>", 9, ["E2EE73#0"])
        event = make_entry(0xE20600, [text_run(5)], "<C0>{0}<FF>", 9, ["E2F393#0"])
        event.role = "events"
        script = make_entry(0xE20700, [text_run(5)], "<C1>{0}<FF>", 9, ["EFC1FB#0"])
        script.role = "global"
        entries = [message, event, script]
        self.assertEqual(marker.select_entries(entries, None), [message])
        self.assertEqual(marker.select_entries(entries, None, ("events", "global")), [event, script])
        self.assertEqual(marker.select_entries(entries, None, ("messages", "global")), [message, script])

    def test_the_command_line_rejects_an_unknown_role(self):
        with tempfile.TemporaryDirectory() as folder:
            code = marker.main(["--rom", "x.sfc", "--asar", "x", "--table", "x.json", "--out", str(Path(folder) / "m.sfc"), "--roles", "weapons"])
        self.assertEqual(code, 2)


class RepositoryGuardTests(unittest.TestCase):
    def test_paths_inside_the_repository_are_detected(self):
        self.assertTrue(marker.inside_repository(REPO / "text" / "x.sfc"))
        self.assertFalse(marker.inside_repository(Path(tempfile.gettempdir()) / "x.sfc"))


@unittest.skipUnless(REAL_ROM and ASAR, "set DARK_LAW_ROM and ASAR to build the marker ROM from the real ROM")
class RealRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Path(REAL_ROM).read_bytes()
        cls.glyphs = gt.load_table(TABLE_FILE)
        cls.work = tempfile.TemporaryDirectory()
        cls.final, cls.document = marker.build_marker_rom(
            cls.rom, cls.glyphs, marker.probe.project_font_art(), Path(ASAR), Path(cls.work.name) / "marker.sfc",
            ruler_ids=("E2:EEE2",),
        )

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def test_size_is_unchanged_and_the_hook_is_installed(self):
        self.assertEqual(len(self.final), len(self.rom))
        for start, _ in marker.probe.HOOK_RANGES:
            self.assertEqual(self.final[sf.cpu_to_offset(start)], 0x5C)

    def test_every_marked_run_reads_back_as_its_marker(self):
        font = marker.probe.LATIN_CHARS
        checked = 0
        for entry in self.document["entries"]:
            for run in entry["runs"]:
                if run["marker"] is None or run["ruler"]:
                    continue
                start, end = (marker.parse_entry_id(run[name]) for name in ("start", "end"))
                data = self.final[sf.cpu_to_offset(start) : sf.cpu_to_offset(end)]
                text = "".join(font[data[i + 1]] + font[data[i + 2]] for i in range(0, len(data), 3))
                self.assertEqual(text, run["marker"])
                checked += 1
        self.assertGreater(checked, 100)

    def test_the_slice_covers_both_tables_and_relocates_only_the_ruler_entry(self):
        relocated = [entry["id"] for entry in self.document["entries"] if entry["relocated"]]
        self.assertEqual(relocated, ["E2:EEE2"])
        self.assertEqual(self.document["scope"], ["E2EE73", "E7362B"])
        banks = {entry["id"][:2] for entry in self.document["entries"]}
        self.assertEqual(banks, {"E2", "E7"})

    def test_no_run_is_ambiguous_in_the_map(self):
        boundaries = [run[name] for entry in self.document["entries"] for run in entry["runs"] for name in ("start", "end")]
        self.assertEqual(len(boundaries), len(set(boundaries)))


if __name__ == "__main__":
    unittest.main()
