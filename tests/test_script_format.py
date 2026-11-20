from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import script_format as sf  # noqa: E402

ROM_SIZE = 0x300000  # cubre hasta el banco $EF con el mapeo HiROM


def synthetic_rom() -> bytearray:
    """ROM mínima con un directorio de 32 áreas, un registro y tres tablas, cada una con dos blobs."""
    rom = bytearray(b"\xff" * ROM_SIZE)

    def put(address: int, data: bytes) -> None:
        offset = sf.cpu_to_offset(address)
        rom[offset : offset + len(data)] = data

    record = 0xEF0100
    for index in range(32):
        put(sf.DIRECTORY_ADDRESS + 3 * index, bytes([record & 0xFF, record >> 8 & 0xFF, record >> 16]))
    tables = (0xE20000, 0xE20100, 0xE20200)
    put(record, b"".join(bytes([t & 0xFF, t >> 8 & 0xFF, t >> 16]) for t in tables))
    # tabla 0: dos mensajes; el blob A termina en C7, el B en C2 con 4 argumentos
    blob_a = bytes([0xC0, 0x00, 0x0A, 0xFD, 0x04, 0xC3, 0x19, 0xC8, 0x80, 0xC7])
    blob_b = bytes([0xC1, 0x05, 0xC2, 0x0A, 0x00, 0x60, 0x00])
    put(tables[0], struct.pack("<2H", 0x0004, 0x0004 + len(blob_a)))
    put(0xE20004, blob_a + blob_b)
    # tabla 1: dos guiones que terminan en FF
    script_a = bytes([0xEE, 0x01, 0x00, 0xFF])
    script_b = bytes([0xC8, 0x40, 0xFF])
    put(tables[1], struct.pack("<2H", 0x0104, 0x0104 + len(script_a)))
    put(0xE20104, script_a + script_b)
    # tabla 2: un guion de un solo byte repetido
    put(tables[2], struct.pack("<2H", 0x0204, 0x0204))
    put(0xE20204, bytes([0xFF]))
    return rom


class TokenizeTests(unittest.TestCase):
    def test_kinds_and_roundtrip(self):
        data = bytes([0xC0, 0x00, 0x0A, 0xFD, 0x04, 0xC3, 0xC8, 0x80, 0xC7])
        parsed = sf.tokenize(data)
        self.assertTrue(parsed.complete)
        self.assertEqual([t.kind for t in parsed.tokens], ["command", "glyph", "glyph", "wide", "command", "command", "command"])
        self.assertEqual(sf.encode(parsed.tokens), data)
        self.assertEqual(parsed.length, len(data))

    def test_stops_after_the_first_terminator(self):
        parsed = sf.tokenize(bytes([0x0A, 0xFF, 0x0B, 0x0C]))
        self.assertTrue(parsed.complete)
        self.assertEqual(parsed.length, 2)

    def test_c2_takes_four_arguments_and_terminates(self):
        parsed = sf.tokenize(bytes([0xC2, 0x0A, 0x00, 0x60, 0x00, 0x99]))
        self.assertTrue(parsed.complete)
        self.assertEqual(parsed.length, 5)

    def test_argument_bytes_are_not_taken_for_commands(self):
        # C8 80: el 0x80 es el argumento aunque pareciera un glifo; C8 FF: el 0xFF es un argumento, no un terminador
        parsed = sf.tokenize(bytes([0xC8, 0xFF, 0xC7]))
        self.assertEqual([len(t.raw) for t in parsed.tokens], [2, 1])

    def test_second_byte_of_a_wide_glyph_may_be_a_command_code(self):
        parsed = sf.tokenize(bytes([0xFD, 0xC7, 0xFF]))
        self.assertEqual([t.kind for t in parsed.tokens], ["wide", "command"])
        self.assertEqual(parsed.length, 3)

    def test_truncated_blob_is_incomplete(self):
        self.assertFalse(sf.tokenize(bytes([0x0A, 0xFD])).complete)
        self.assertFalse(sf.tokenize(bytes([0xC8])).complete)
        self.assertFalse(sf.tokenize(bytes([0x0A, 0x0B])).complete)

    def test_unmeasured_commands_are_reported(self):
        parsed = sf.tokenize(bytes([0xE6, 0xFF]))
        self.assertIn(0xE6, parsed.unresolved)
        self.assertNotIn(0xC8, sf.tokenize(bytes([0xC8, 0x01, 0xFF])).unresolved)

    def test_measured_argument_counts_from_the_probe(self):
        expected = {0xC0: 0, 0xC8: 1, 0xD5: 2, 0xDC: 4, 0xDE: 3, 0xEE: 2, 0xF2: 5, 0xFE: 2}
        for code, arguments in expected.items():
            self.assertEqual(sf.command_arguments(code)[0], arguments, hex(code))


class AddressTests(unittest.TestCase):
    def test_hirom_conversion(self):
        self.assertEqual(sf.cpu_to_offset(0xC00012), 0x000012)
        self.assertEqual(sf.cpu_to_offset(0xD14571), 0x114571)
        self.assertEqual(sf.cpu_to_offset(0xE2EE93), 0x22EE93)
        self.assertEqual(sf.cpu_to_offset(0xFFFFC0), 0x3FFFC0)

    def test_read_past_the_end_fails(self):
        with self.assertRaises(ValueError):
            sf.read_bytes(bytes(16), 0xC00008, 16)


class TableTests(unittest.TestCase):
    def setUp(self):
        self.rom = bytes(synthetic_rom())

    def test_areas_and_tables(self):
        areas = sf.read_areas(self.rom)
        self.assertEqual(len(areas), sf.USED_AREA_COUNT)
        self.assertEqual(areas[0].table_addresses, (0xE20000, 0xE20100, 0xE20200))

    def test_table_length_ends_at_the_first_blob(self):
        table = sf.read_table(self.rom, 0xE20000)
        self.assertEqual(table.entries, (0x0004, 0x000E))
        self.assertEqual(table.blob_address(1), 0xE2000E)

    def test_distinct_tables_only_once(self):
        self.assertEqual(sorted(sf.read_all_tables(self.rom)), [0xE20000, 0xE20100, 0xE20200, sf.CALLED_SCRIPTS_TABLE])

    def test_blobs_close_exactly(self):
        reports = sf.check_table(self.rom, sf.read_table(self.rom, 0xE20000))
        self.assertEqual([r.parsed.length for r in reports], [10, 7])
        self.assertEqual([p for p in reports[0].problems if "unmeasured" not in p], [])

    def test_a_gap_is_reported(self):
        rom = bytearray(self.rom)
        rom[sf.cpu_to_offset(0xE20004) + 5] = 0xFF  # el blob A acaba antes de lo que dice la tabla
        reports = sf.check_table(bytes(rom), sf.read_table(bytes(rom), 0xE20000))
        self.assertTrue(any("ends" in p for p in reports[0].problems))

    def test_duplicate_entries_are_one_blob(self):
        table = sf.read_table(self.rom, 0xE20200)
        self.assertEqual(len(sf.check_table(self.rom, table)), 1)


if __name__ == "__main__":
    unittest.main()
