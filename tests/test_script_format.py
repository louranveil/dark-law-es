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
        parsed = sf.tokenize(bytes([0xE6, 0x01, 0x02, 0xFF]))
        self.assertIn(0xE6, parsed.unresolved)  # leído en el código, no medido
        self.assertNotIn(0xC8, sf.tokenize(bytes([0xC8, 0x01, 0xFF])).unresolved)

    def test_measured_argument_counts_from_the_probe(self):
        expected = {0xC0: 0, 0xC8: 1, 0xD5: 2, 0xDC: 4, 0xDE: 3, 0xEC: 2, 0xED: 0, 0xEE: 2, 0xF2: 5, 0xFE: 1, 0xD7: 1}
        for code, arguments in expected.items():
            self.assertEqual(sf.command_arguments(code)[0], arguments, hex(code))

    def test_arguments_read_from_the_handler_code(self):
        expected = {0xCB: 1, 0xDA: 1, 0xDB: 1, 0xE6: 2, 0xE8: 5, 0xC2: 4, 0xD9: 2, 0xF3: 2}
        for code, arguments in expected.items():
            self.assertEqual(sf.command_arguments(code), (arguments, sf.Evidence.CODE), hex(code))

    def test_an_unknown_command_is_assumed_to_have_no_arguments(self):
        self.assertEqual(sf.command_arguments(0xF7), (0, sf.Evidence.UNKNOWN))


class SelectorCommandTests(unittest.TestCase):
    def test_fe_length_depends_on_the_selector(self):
        for selector, arguments in {0x00: 1, 0x03: 6, 0x05: 7, 0x08: 4, 0x18: 0, 0x29: 2, 0x2E: 6, 0x3F: 6, 0x42: 2, 0x43: 4}.items():
            data = bytes([0xFE, selector] + [0x01] * arguments + [0xFF])
            parsed = sf.tokenize(data)
            self.assertEqual([len(t.raw) for t in parsed.tokens], [2 + arguments, 1], hex(selector))
            self.assertTrue(parsed.complete)

    def test_the_selector_is_part_of_the_command_and_never_text(self):
        # FE 03 lleva seis argumentos: 0A 19 son argumentos, no glifos
        parsed = sf.tokenize(bytes([0xFE, 0x03, 0x0A, 0x19, 0x01, 0x02, 0x03, 0x04, 0xFF]))
        self.assertEqual([t.kind for t in parsed.tokens], ["command", "command"])
        self.assertEqual(parsed.tokens[0].key, 0xFE03)
        self.assertEqual(parsed.tokens[0].code, 0xFE)

    def test_fe_with_a_truncated_selector_is_incomplete(self):
        self.assertFalse(sf.tokenize(bytes([0x0A, 0xFE])).complete)
        self.assertFalse(sf.tokenize(bytes([0xFE, 0x03, 0x01])).complete)

    def test_selectors_outside_the_handler_table_are_unknown_except_f4(self):
        self.assertEqual(sf.command_arguments(0xFE7F), (0, sf.Evidence.UNKNOWN))
        self.assertEqual(sf.command_arguments(0xFEF4), (2, sf.Evidence.MEASURED))
        self.assertIn(0xFE7F, sf.tokenize(bytes([0xFE, 0x7F, 0xFF])).unresolved)

    def test_fe_arguments_resolved_only_from_code_are_reported_as_unmeasured(self):
        self.assertEqual(sf.command_arguments(0xFE40), (8, sf.Evidence.CODE))
        parsed = sf.tokenize(bytes([0xFE, 0x42, 0x01, 0x02, 0xFF]))
        self.assertNotIn(0xFE42, parsed.unresolved)  # medido
        self.assertIn(0xFE39, sf.tokenize(bytes([0xFE, 0x39, 0xFF])).unresolved)  # solo leído en el código

    def test_fe_2d_keeps_the_corpus_length_and_documents_the_conflict(self):
        arguments, evidence = sf.command_arguments(0xFE2D)
        self.assertEqual((arguments, evidence), (6, sf.Evidence.CORPUS))
        self.assertIn("7", sf.FE_SUBCOMMANDS[0x2D].note)

    def test_d7_is_a_selector_command_with_a_handler_table(self):
        self.assertEqual(len(sf.D7_SUBCOMMANDS), 0x9D)
        self.assertEqual(sf.command_arguments(0xD700), (0, sf.Evidence.CODE))
        self.assertEqual(sf.command_arguments(0xD719)[0], 5)
        parsed = sf.tokenize(bytes([0xD7, 0x19, 1, 2, 3, 4, 5, 0xFF]))
        self.assertEqual([len(t.raw) for t in parsed.tokens], [7, 1])
        self.assertEqual(parsed.tokens[0].key, 0xD719)

    def test_d7_selector_without_an_entry_is_unknown(self):
        self.assertEqual(sf.command_arguments(0xD7AA), (0, sf.Evidence.UNKNOWN))

    def test_the_arguments_of_a_selector_command_are_not_text_even_when_they_look_like_terminators(self):
        parsed = sf.tokenize(bytes([0xFE, 0x00, 0xFF, 0xC7]))
        self.assertEqual([len(t.raw) for t in parsed.tokens], [3, 1])


class LeavingCommandTests(unittest.TestCase):
    def test_leaving_commands_close_the_blob_after_their_arguments(self):
        cases = {
            "C2": bytes([0xC2, 1, 2, 3, 4]),
            "E8": bytes([0xE8, 5, 1, 0, 2, 0]),
            "EC": bytes([0xEC, 1, 2]),
            "D9": bytes([0xD9, 1, 2]),
            "F3": bytes([0xF3, 1, 2]),
            "FE 0C": bytes([0xFE, 0x0C, 1, 2, 3]),
            "FE 32": bytes([0xFE, 0x32, 8]),
            "FE 40": bytes([0xFE, 0x40] + [1] * 8),
        }
        for name, data in cases.items():
            parsed = sf.tokenize(data + bytes([0x0A, 0x0B]))
            self.assertTrue(parsed.complete, name)
            self.assertEqual(parsed.length, len(data), name)

    def test_a_non_leaving_selector_does_not_close_the_blob(self):
        self.assertFalse(sf.tokenize(bytes([0xFE, 0x00, 0x01])).complete)

    def test_a_leaving_command_with_cut_arguments_is_incomplete(self):
        self.assertFalse(sf.tokenize(bytes([0xE8, 5, 1])).complete)

    def test_command_info_describes_size_key_and_end(self):
        data = bytes([0xFE, 0x32, 0x08])
        info = sf.command_info(data, 0)
        self.assertEqual((info.size, info.key, info.ends), (3, 0xFE32, True))
        self.assertIs(info.evidence, sf.Evidence.CODE)
        self.assertEqual(sf.command_info(bytes([0xFE]), 0).size, None)
        self.assertFalse(sf.command_info(bytes([0xC8, 1]), 0).ends)


class DeadTailTests(unittest.TestCase):
    def test_up_to_two_redundant_terminators_after_the_end_are_absorbed(self):
        parsed = sf.tokenize(bytes([0xEC, 0x0D, 0x00, 0xFF, 0xFF]))
        self.assertEqual(parsed.length, 3)
        absorbed = sf.absorb_dead_tail(parsed, bytes([0xFF, 0xFF]))
        self.assertEqual(absorbed.length, 5)
        self.assertEqual(sf.absorb_dead_tail(parsed, bytes([0xC7])).length, 4)

    def test_other_bytes_or_longer_tails_are_not_absorbed(self):
        parsed = sf.tokenize(bytes([0xEC, 0x0D, 0x00]))
        for tail in (b"", bytes([0xFF, 0xFF, 0xFF]), bytes([0x0A]), bytes([0xF0])):
            self.assertEqual(sf.absorb_dead_tail(parsed, tail).length, 3, tail)

    def test_an_incomplete_blob_absorbs_nothing(self):
        parsed = sf.tokenize(bytes([0x0A, 0x0B]))
        self.assertEqual(sf.absorb_dead_tail(parsed, bytes([0xFF])).length, 2)

    def test_check_table_accepts_the_dead_tail_as_part_of_the_gap(self):
        rom = bytearray(synthetic_rom())
        offset = sf.cpu_to_offset(0xE20004)
        # blob A: C8 80 C7 al final y un FF sobrante; el blob B queda un byte más allá
        blob_a = bytes([0xC0, 0x00, 0x0A, 0xFD, 0x04, 0xC3, 0x19, 0xC8, 0x80, 0xC7, 0xFF])
        blob_b = bytes([0xC1, 0x05, 0xC2, 0x0A, 0x00, 0x60, 0x00])
        rom[offset : offset + len(blob_a) + len(blob_b)] = blob_a + blob_b
        rom[sf.cpu_to_offset(0xE20000) : sf.cpu_to_offset(0xE20000) + 4] = struct.pack("<2H", 0x0004, 0x0004 + len(blob_a))
        reports = sf.check_table(bytes(rom), sf.read_table(bytes(rom), 0xE20000))
        self.assertEqual([p for p in reports[0].problems if "unmeasured" not in p], [])
        self.assertEqual(reports[0].parsed.length, len(blob_a))


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
