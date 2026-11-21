from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_custom_font as font  # noqa: E402
import build_latin_probe as probe  # noqa: E402

ASSET = REPO / "assets" / "font" / "latin-8x16.txt"

SAMPLE = """# comentario
glyph T top=3 left=1
XXX
.X.
.X.

glyph U+0131 top=5 left=2
X

mark acute 4,1 3,2
compose Ť T acute
flip ⊥ T 3 5
rotate L U+0131 5 5 2 4
"""


class ParseSourceTest(unittest.TestCase):
    def test_glyph_rows_are_placed_by_top_and_left(self):
        glyphs = font.parse_source(SAMPLE)
        self.assertEqual(glyphs["T"], frozenset({(1, 3), (2, 3), (3, 3), (2, 4), (2, 5)}))

    def test_compose_adds_the_mark(self):
        glyphs = font.parse_source(SAMPLE)
        self.assertEqual(glyphs["Ť"], glyphs["T"] | {(4, 1), (3, 2)})

    def test_flip_is_vertical_within_the_rows(self):
        glyphs = font.parse_source(SAMPLE)
        self.assertEqual(glyphs["⊥"], frozenset({(1, 5), (2, 5), (3, 5), (2, 4), (2, 3)}))

    def test_rotate_turns_the_glyph_half_a_turn_in_the_box(self):
        glyphs = font.parse_source(SAMPLE)
        self.assertEqual(glyphs["L"], frozenset({(4, 5)}))  # (2, 5) en la caja columnas 2-4, fila 5

    def test_mark_overlapping_the_base_is_an_error(self):
        text = "glyph T top=3 left=1\nXXX\n\nmark bad 2,3\ncompose Ť T bad\n"
        with self.assertRaises(font.SourceError):
            font.parse_source(text)

    def test_ink_outside_the_cell_is_an_error(self):
        with self.assertRaises(font.SourceError):
            font.parse_source("glyph T top=15 left=7\nXX\nXX\n")

    def test_duplicate_glyph_is_an_error(self):
        with self.assertRaises(font.SourceError):
            font.parse_source("glyph T top=3 left=1\nX\n\nglyph T top=3 left=1\nX\n")

    def test_unknown_line_is_an_error(self):
        with self.assertRaises(font.SourceError):
            font.parse_source("nonsense here\n")


class OutlineTest(unittest.TestCase):
    def test_outline_surrounds_the_ink_with_eight_neighbours(self):
        ring = font.outline_of(frozenset({(3, 3)}))
        self.assertEqual(len(ring), 8)
        self.assertNotIn((3, 3), ring)

    def test_outline_is_clipped_by_the_cell(self):
        ink = frozenset({(0, 0)})
        self.assertEqual(font.outline_of(ink), {(1, 0), (0, 1), (1, 1)})
        self.assertEqual(font.clipped_outline_count(ink), 5)

    def test_render_cell_symbols(self):
        rows = font.render_cell(frozenset({(1, 1)}), True)
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0], "###.....")
        self.assertEqual(rows[1], "#-#.....")
        self.assertEqual(font.render_cell(frozenset({(1, 1)}), False)[0], "." * 8)


class AssetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glyphs = font.parse_source(ASSET.read_text(encoding="utf-8"))

    def test_covers_every_character_of_the_game_set(self):
        self.assertEqual(font.missing_chars(self.glyphs), "")

    def test_every_drawn_glyph_has_ink_except_the_space(self):
        blank = [char for char, ink in self.glyphs.items() if not ink]
        self.assertEqual(blank, [" "])

    def test_accented_letters_keep_the_base_letter(self):
        for accented, base in zip("áéóúüñÁÉÓÚÜÑ", "aeouunAEOUUN"):
            self.assertTrue(self.glyphs[base] <= self.glyphs[accented], accented)

    def test_spanish_marks_do_not_touch_the_letter(self):
        for char in "áéíóúüñÁÉÍÓÚÜÑ":
            rows = sorted({y for _, y in self.glyphs[char]})
            gap = [row for row in range(rows[0], rows[-1]) if row not in rows]
            self.assertTrue(gap, f"{char} has no empty row between the mark and the letter")

    def test_art_is_accepted_by_the_probe_builder(self):
        art_text = font.format_art(font.build_art(self.glyphs, True), "test")
        art = probe.parse_font_art(art_text)
        self.assertEqual(len(probe.font_binary(art)), 32 * len(probe.LATIN_CHARS))

    def test_outline_never_overwrites_the_ink(self):
        for char, rows in font.build_art(self.glyphs, True).items():
            ink = {(x, y) for y, row in enumerate(rows) for x, symbol in enumerate(row) if symbol == "-"}
            self.assertEqual(ink, set(self.glyphs[char]), char)


class MainTest(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = font.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_writes_the_art_for_the_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "art.txt"
            code, out, _ = self.run_main("--source", str(ASSET), "--out", str(target))
            self.assertEqual(code, 0)
            self.assertIn("covered 111 of 111", out)
            self.assertTrue(target.read_text(encoding="utf-8").startswith("#! dark-law-latin-8x16 outline=full"))

    def test_missing_characters_fail_unless_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "small.txt"
            source.write_text("glyph T top=3 left=1\nXXX\n", encoding="utf-8")
            target = Path(folder) / "art.txt"
            code, _, err = self.run_main("--source", str(source), "--out", str(target))
            self.assertEqual(code, 1)
            self.assertIn("lacks", err)
            self.assertFalse(target.exists())
            code, _, _ = self.run_main("--source", str(source), "--out", str(target), "--allow-missing")
            self.assertEqual(code, 0)
            self.assertTrue(target.exists())

    def test_bad_source_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.txt"
            source.write_text("nonsense\n", encoding="utf-8")
            code, _, err = self.run_main("--source", str(source), "--out", str(Path(folder) / "art.txt"))
            self.assertEqual(code, 2)
            self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
