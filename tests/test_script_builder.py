from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests"))

import build_relocation_probe as probe  # noqa: E402
import check_scripts  # noqa: E402
import script_builder as sb  # noqa: E402
import script_format as sf  # noqa: E402
from test_script_format import synthetic_rom  # noqa: E402

REAL_ROM = os.environ.get("DARK_LAW_ROM")


class RomPatcherTests(unittest.TestCase):
    def setUp(self):
        self.original = bytes(range(256)) * 4
        self.patcher = sb.RomPatcher(self.original)

    def test_write_is_logged_with_the_original_bytes(self):
        self.patcher.write(10, b"\xaa\xbb", reason="test")
        self.assertEqual(self.patcher.log[0].old, self.original[10:12])
        self.assertEqual(bytes(self.patcher.data[10:12]), b"\xaa\xbb")
        self.assertEqual(self.patcher.original, self.original)

    def test_expected_bytes_must_match_the_original_not_the_work_buffer(self):
        self.patcher.write(10, b"\xaa\xbb")
        with self.assertRaises(sb.PatchError):
            self.patcher.write(20, b"\x00", expected=b"\xff")

    def test_overlap_is_rejected(self):
        self.patcher.write(10, b"\xaa\xbb\xcc")
        with self.assertRaises(sb.PatchError):
            self.patcher.write(12, b"\x01\x02")

    def test_adjacent_writes_are_fine(self):
        self.patcher.write(10, b"\xaa\xbb")
        self.patcher.write(12, b"\xcc")

    def test_write_outside_the_rom_is_rejected(self):
        with self.assertRaises(sb.PatchError):
            self.patcher.write(len(self.original) - 1, b"\x00\x00")

    def test_a_change_without_a_logged_write_is_detected(self):
        self.patcher.write(10, b"\xaa")
        self.patcher.verify_log_covers_changes()
        self.patcher.data[500] ^= 0xFF
        with self.assertRaises(sb.PatchError):
            self.patcher.verify_log_covers_changes()


class FreeSpaceTests(unittest.TestCase):
    def test_allocation_and_exhaustion(self):
        space = sb.FreeSpace(0xE20400, 0xE20410)
        self.assertEqual(space.allocate(10), 0xE20400)
        self.assertEqual(space.allocate(6), 0xE2040A)
        with self.assertRaises(sb.PatchError):
            space.allocate(1)


class RelocateBlobTests(unittest.TestCase):
    def setUp(self):
        self.rom = bytes(synthetic_rom())
        self.table = sf.read_table(self.rom, 0xE20000)

    def test_blob_is_moved_and_pointer_updated(self):
        patcher = sb.RomPatcher(self.rom)
        new_blob = bytes([0xC0, 0x01, 0x02, 0x03, 0xC7])
        address = sb.relocate_blob(patcher, self.table, 0, new_blob, sb.FreeSpace(0xE20800, 0xE20900))
        self.assertEqual(address, 0xE20800)
        rebuilt = bytes(patcher.data)
        moved = sf.read_table(rebuilt, 0xE20000)
        self.assertEqual(moved.entries[0], 0x0800)
        self.assertEqual(sf.read_bytes(rebuilt, moved.blob_address(0), len(new_blob)), new_blob)
        self.assertEqual(moved.entries[1], self.table.entries[1])
        patcher.verify_log_covers_changes()

    def test_free_space_in_another_bank_is_rejected(self):
        patcher = sb.RomPatcher(self.rom)
        with self.assertRaises(sb.PatchError):
            sb.relocate_blob(patcher, self.table, 0, b"\xc7", sb.FreeSpace(0xE30000, 0xE30100))

    def test_stale_table_entry_is_rejected(self):
        patcher = sb.RomPatcher(self.rom)
        stale = sf.MessageTable(self.table.address, (0x1234,) + self.table.entries[1:])
        with self.assertRaises(sb.PatchError):
            sb.relocate_blob(patcher, stale, 0, b"\xc7", sb.FreeSpace(0xE20800, 0xE20900))


class IdentityBuildTests(unittest.TestCase):
    def test_synthetic_rom_rebuilds_identically(self):
        rom = bytes(synthetic_rom())
        tables = sf.read_all_tables(rom)
        self.assertEqual(check_scripts.identity_build(rom, tables), rom)

    def test_analysis_counts_blobs(self):
        rom = bytes(synthetic_rom())
        report = check_scripts.analyze(rom)
        self.assertEqual(report.tables, 4)
        self.assertTrue(report.identity_ok)
        self.assertEqual(report.blobs, report.exact + report.needs_review)


@unittest.skipUnless(REAL_ROM, "set DARK_LAW_ROM to run the tests against the real ROM")
class RealRomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Path(REAL_ROM).read_bytes()

    def test_directory_and_tables(self):
        tables = sf.read_all_tables(self.rom)
        self.assertEqual(len(tables), 26)
        self.assertEqual(tables[0xE2EE73].entries[0], 0xEE93)

    def test_identity_build_is_byte_identical(self):
        report = check_scripts.analyze(self.rom)
        self.assertTrue(report.identity_ok)

    def test_most_messages_close_exactly(self):
        report = check_scripts.analyze(self.rom)
        messages = report.by_role["messages"]
        self.assertGreaterEqual(messages["exact"], 1600)

    def test_free_space_candidate_is_filler(self):
        free = self.rom[sf.cpu_to_offset(probe.FREE_START) : sf.cpu_to_offset(probe.FREE_END)]
        self.assertEqual(free.count(0xFF), len(free))

    def test_probe_relocates_only_the_message_and_its_pointer(self):
        patched, patcher = probe.build_probe(self.rom)
        self.assertEqual(len(patched), len(self.rom))
        self.assertEqual(len(patcher.log), 2)
        original = sf.read_table(self.rom, probe.TABLE_ADDRESS)
        # La longitud de la tabla se fija con la ROM original: en la modificada la heurística
        # "acaba donde empieza el primer blob" ya no vale, porque el primer blob se ha movido.
        table = sf.read_table(patched, probe.TABLE_ADDRESS)
        count = len(original.entries)
        self.assertEqual(table.entries[0], probe.FREE_START & 0xFFFF)
        self.assertEqual(table.entries[1:count], original.entries[1:])
        new_blob = sf.read_bytes(patched, table.blob_address(0), 82)
        old_blob = sf.read_bytes(self.rom, original.blob_address(0), 79)
        self.assertEqual(len(new_blob) - len(old_blob), probe.EXTRA_DOTS)
        self.assertTrue(sf.tokenize(new_blob).complete)
        changed = patcher.changed_offsets()
        allowed = {sf.cpu_to_offset(probe.TABLE_ADDRESS) + k for k in range(2)} | set(
            range(sf.cpu_to_offset(probe.FREE_START), sf.cpu_to_offset(probe.FREE_START) + 82)
        )
        self.assertLessEqual(changed, allowed)


if __name__ == "__main__":
    unittest.main()
