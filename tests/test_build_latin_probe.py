from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_latin_probe as probe  # noqa: E402
import script_format as sf  # noqa: E402

REAL_ROM = os.environ.get("DARK_LAW_ROM")
ASAR = os.environ.get("ASAR")
BLANK = ["." * 8] * 16


def solid_art() -> dict[str, list[str]]:
    """Una fuente sintética: cada letra tiene su índice marcado en la primera fila (para distinguirlas)."""
    art = {}
    for index, char in enumerate(probe.LATIN_CHARS):
        rows = list(BLANK)
        rows[0] = "".join("#" if (index >> bit) & 1 else "." for bit in range(8))
        art[char] = rows
    return art


class PackLetterTests(unittest.TestCase):
    def test_pixel_values_go_to_the_right_planes(self):
        rows = ["#-+.....", *["." * 8] * 15]
        packed = probe.pack_letter(rows)
        self.assertEqual(len(packed), 32)
        # columna 0 = 3 (ambos planos), 1 = 1 (plano 0), 2 = 2 (plano 1)
        self.assertEqual(packed[0], 0b11000000)
        self.assertEqual(packed[1], 0b10100000)

    def test_bottom_rows_land_in_the_second_tile(self):
        rows = [*["." * 8] * 8, "#" * 8, *["." * 8] * 7]
        packed = probe.pack_letter(rows)
        self.assertEqual(packed[16:18], b"\xff\xff")
        self.assertEqual(packed[:16], bytes(16))


class ParseArtTests(unittest.TestCase):
    def test_round_trip(self):
        text = "U+0041\n" + "\n".join(["#......."] + ["." * 8] * 15) + "\n"
        art = probe.parse_font_art(text)
        self.assertEqual(art["A"][0], "#.......")

    def test_bad_row_width_is_rejected(self):
        with self.assertRaises(ValueError):
            probe.parse_font_art("U+0041\n" + "\n".join(["#"] + ["." * 8] * 15))

    def test_missing_letters_are_reported(self):
        with self.assertRaises(ValueError):
            probe.font_binary({"A": list(BLANK)})

    def test_font_binary_size(self):
        self.assertEqual(len(probe.font_binary(solid_art())), len(probe.LATIN_CHARS) * probe.LETTER_BYTES)


class EncodeTests(unittest.TestCase):
    def test_ascii_index_is_code_minus_0x20(self):
        self.assertEqual(probe.letter_index("A"), 0x41 - 0x20)
        self.assertEqual(probe.letter_index(" "), 0)

    def test_pairs_and_padding(self):
        data = probe.encode_latin("Hola!")
        self.assertEqual(data, bytes([0xF9, probe.letter_index("H"), probe.letter_index("o"),
                                       0xF9, probe.letter_index("l"), probe.letter_index("a"),
                                       0xF9, probe.letter_index("!"), probe.letter_index(" ")]))

    def test_line_break_between_lines_only(self):
        data = probe.encode_latin("ab\ncd")
        self.assertEqual(data.count(probe.LINE_BREAK), 1)
        self.assertEqual(data[3], probe.LINE_BREAK)

    def test_accented_letters_have_glyphs(self):
        for char in "ñÑ¿¡áéíóúüÁÉÍÓÚÜ":
            probe.letter_index(char)

    def test_unknown_character_is_rejected(self):
        with self.assertRaises(ValueError):
            probe.letter_index("日")

    def test_message_blob_parses_to_the_end(self):
        blob = probe.message_blob("Hace trescientos años...\n¿Quién lo recordará hoy?")
        parsed = sf.tokenize(blob)
        self.assertTrue(parsed.complete)
        self.assertEqual(parsed.length, len(blob))


class ChangedRangesTests(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(probe.changed_ranges(b"abcdef", b"aXcdYZ"), [(1, 2), (4, 6)])

    def test_unexpected_change_is_rejected(self):
        with self.assertRaises(probe.PatchError):
            probe.check_changes_are_expected([(0x500, 0x501)], (0x22F8A6, 0x22F8B0))


@unittest.skipUnless(REAL_ROM and ASAR, "set DARK_LAW_ROM and ASAR to assemble the hook against the real ROM")
class AssembleTests(unittest.TestCase):
    def test_hook_assembles_and_only_expected_bytes_change(self):
        rom = Path(REAL_ROM).read_bytes()
        with tempfile.TemporaryDirectory() as work:
            patched = probe.build_probe(rom, solid_art(), "Hola mundo", Path(ASAR), Path(work) / "probe.sfc")
        self.assertEqual(len(patched), len(rom))
        hook = cpu_hook = probe.cpu_to_offset(probe.HOOK_RANGE[0])
        self.assertEqual(patched[hook], 0x5C)  # JML
        self.assertEqual(rom[cpu_hook : cpu_hook + 4].hex(), "c9e5f06b")


if __name__ == "__main__":
    unittest.main()
