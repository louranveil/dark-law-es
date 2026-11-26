from __future__ import annotations

import io
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import glyph_font as gf  # noqa: E402

try:
    import PIL  # noqa: F401

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


def synthetic_rom() -> bytearray:
    return bytearray(b"\x00" * 0x140000)  # cubre $D2 y $D3 (HiROM: banco $D2 = desplazamiento 0x120000)


class AddressTest(unittest.TestCase):
    def test_single_byte_page_layout(self):
        self.assertEqual(gf.glyph_address(None, 0), 0xD20129)
        self.assertEqual(gf.glyph_address(None, 1), 0xD20129 + 0x20)
        self.assertEqual(gf.glyph_address(None, 8), 0xD20129 + 0x200)
        self.assertEqual(gf.glyph_address(None, 16), 0xD20129 + 0x400)

    def test_kanji_pages_have_their_own_base(self):
        self.assertEqual(gf.glyph_address(0xFD, 0), 0xD23B78)
        self.assertEqual(gf.glyph_address(0xFC, 0), 0xD27B78)
        self.assertEqual(gf.glyph_address(0xFB, 0), 0xD30000)
        self.assertEqual(gf.glyph_address(0xFA, 0), 0xD34000)

    def test_last_glyph_of_a_page_ends_inside_the_page(self):
        end = gf.glyph_address(0xFD, 255) + 0x100 + 0x20
        self.assertEqual(end, 0xD23B78 + 0x4000)

    def test_bad_arguments_are_errors(self):
        with self.assertRaises(ValueError):
            gf.glyph_address(0xE0, 0)
        with self.assertRaises(ValueError):
            gf.glyph_address(None, 256)


class DecodeTest(unittest.TestCase):
    def test_tile_planes_combine_into_two_bit_values(self):
        data = bytes([0b10000000, 0b10000000, 0b01000000, 0b00000000, 0b00100000, 0b11111111] + [0] * 10)
        tile = gf.decode_tile(data)
        self.assertEqual(tile[0][:3], [3, 0, 0])
        self.assertEqual(tile[1][:3], [0, 1, 0])
        self.assertEqual(tile[2][:3], [2, 2, 3])

    def test_tile_needs_sixteen_bytes(self):
        with self.assertRaises(ValueError):
            gf.decode_tile(b"\x00" * 15)

    def test_glyph_halves_and_tiles_are_placed(self):
        rom = synthetic_rom()
        address = gf.glyph_address(None, 0) - 0xD20000 + 0x120000
        rom[address] = 0x80  # tile superior izquierdo, fila 0, columna 0
        rom[address + 16] = 0x01  # tile superior derecho, fila 0, columna 7 -> x = 15
        rom[address + 0x100 + 1] = 0x80  # mitad inferior, fila 8, plano 1, columna 0 -> valor 2
        glyph = gf.read_glyph(bytes(rom), None, 0)
        self.assertEqual((len(glyph), len(glyph[0])), (16, 16))
        self.assertEqual(glyph[0][0], 1)
        self.assertEqual(glyph[0][15], 1)
        self.assertEqual(glyph[8][0], 2)
        self.assertEqual(sum(1 for row in glyph for value in row if value), 3)


class KeyTest(unittest.TestCase):
    def test_keys_round_trip(self):
        self.assertEqual(gf.glyph_key(None, 0x0A), "0A")
        self.assertEqual(gf.glyph_key(0xFD, 0x3A), "FD 3A")
        self.assertEqual(gf.parse_key("0A"), (None, 0x0A))
        self.assertEqual(gf.parse_key("FD 3A"), (0xFD, 0x3A))
        with self.assertRaises(ValueError):
            gf.parse_key("FD 3A 00")

    def test_order_puts_single_bytes_first_then_by_frequency(self):
        usage = Counter({"FD 01": 9, "0B": 1, "0A": 5, "FC 02": 20})
        self.assertEqual(gf.ordered_keys(usage), ["0A", "0B", "FC 02", "FD 01"])


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class SheetTest(unittest.TestCase):
    def test_sheets_are_split_and_sized(self):
        rom = bytes(synthetic_rom())
        keys = [gf.glyph_key(None, index) for index in range(25)]
        sheets = gf.render_sheets(rom, keys, Counter(), per_sheet=12, scale=2)
        self.assertEqual(len(sheets), 3)
        self.assertEqual(sheets[0].size[0], 10 * (16 * 2 + 12))

    def test_ink_is_drawn_at_the_scale(self):
        rom = synthetic_rom()
        address = gf.glyph_address(None, 0) - 0xD20000 + 0x120000
        rom[address] = 0x80
        sheet = gf.render_sheets(bytes(rom), ["00"], Counter(), per_sheet=1, scale=3)[0]
        self.assertEqual(sheet.getpixel((6 + 1, 28 + 1)), (245, 245, 245))


class MainTest(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gf.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_missing_rom_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as folder:
            code, _, err = self.run_main("--rom", str(Path(folder) / "none.sfc"), "--out", folder)
            self.assertEqual(code, 2)
            self.assertIn("error", err)

    def test_bad_sheet_size_is_a_usage_error(self):
        code, _, err = self.run_main("--rom", "x", "--out", "y", "--per-sheet", "0")
        self.assertEqual(code, 2)
        self.assertIn("positive", err)


if __name__ == "__main__":
    unittest.main()
