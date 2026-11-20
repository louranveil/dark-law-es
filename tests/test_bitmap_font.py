from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import bitmap_font as bf  # noqa: E402
import build_latin_probe as probe  # noqa: E402
import convert_font_art as convert  # noqa: E402
import measure_text_width as measure  # noqa: E402

# Un BDF mínimo: "H" de 3x5 con baja línea base 0, "g" con un píxel bajo la base y un espacio.
SAMPLE_BDF = """STARTFONT 2.1
FONT sample
CHARS 3
STARTCHAR H
ENCODING 72
SWIDTH 500 0
DWIDTH 4 0
BBX 3 5 0 0
BITMAP
A0
A0
E0
A0
A0
ENDCHAR
STARTCHAR g
ENCODING 103
DWIDTH 4 0
BBX 2 2 1 -1
BITMAP
C0
C0
ENDCHAR
STARTCHAR space
ENCODING 32
DWIDTH 3 0
BBX 1 1 0 0
BITMAP
00
ENDCHAR
ENDFONT
"""


def block_font(width: int, height: int, chars: str) -> bf.BitmapFont:
    """Una fuente sintética: cada carácter es un bloque macizo de ``width`` x ``height`` apoyado en la línea base."""
    pixels = frozenset((x, y) for x in range(width) for y in range(height))
    glyphs = {ord(char): bf.Glyph(pixels, width + 1) for char in chars}
    return bf.BitmapFont("block", glyphs)


class ReadBdfTests(unittest.TestCase):
    def test_reads_pixels_relative_to_origin_and_baseline(self) -> None:
        font = bf.read_bdf(SAMPLE_BDF)
        h = font.glyph("H")
        self.assertEqual(h.advance, 4)
        self.assertEqual(h.ink_box(), (0, 0, 2, 4))
        self.assertIn((0, 4), h.pixels)  # fila superior "A0" = 1010 0000: columnas 0 y 2
        self.assertIn((2, 4), h.pixels)
        self.assertNotIn((1, 4), h.pixels)
        self.assertIn((1, 2), h.pixels)  # fila central "E0": tres píxeles

    def test_negative_offset_goes_below_the_baseline(self) -> None:
        g = bf.read_bdf(SAMPLE_BDF).glyph("g")
        self.assertEqual(g.ink_box(), (1, -1, 2, 0))

    def test_blank_glyph_has_no_ink(self) -> None:
        space = bf.read_bdf(SAMPLE_BDF).glyph(" ")
        self.assertIsNone(space.ink_box())
        self.assertEqual(space.advance, 3)

    def test_encoding_minus_one_is_skipped(self) -> None:
        text = SAMPLE_BDF.replace("ENCODING 103", "ENCODING -1")
        self.assertIsNone(bf.read_bdf(text).glyph("g"))


class ReadOtherFormatsTests(unittest.TestCase):
    def test_f8_msbit_is_leftmost_and_rows_count_down_from_the_baseline_row(self) -> None:
        data = bytes([0b10000001] + [0] * 15)  # fila 0: columnas 0 y 7
        glyph = bf.read_f8(data * 1, baseline_row=12).glyph("\x00")
        self.assertEqual(glyph.pixels, frozenset({(0, 12), (7, 12)}))
        self.assertEqual(glyph.advance, 8)

    def test_hex_reads_8_wide_glyphs_and_skips_wide_ones(self) -> None:
        text = "0041:" + "80" + "00" * 15 + "\n0042:" + "00" * 32 + "\n"
        font = bf.read_hex(text, baseline_row=12)
        self.assertEqual(font.glyph("A").pixels, frozenset({(0, 12)}))
        self.assertIsNone(font.glyph("B"))

    def test_charwidths_pairs(self) -> None:
        self.assertEqual(bf.read_charwidths("32 3 33 1\n34 3"), {32: 3, 33: 1, 34: 3})


class OutlineTests(unittest.TestCase):
    def test_single_pixel_gets_eight_neighbors(self) -> None:
        ring = bf.outline_of({(0, 0)})
        self.assertEqual(len(ring), 8)
        self.assertNotIn((0, 0), ring)

    def test_four_neighborhood_has_no_corners(self) -> None:
        self.assertEqual(len(bf.outline_of({(0, 0)}, bf.NEIGHBORS_4)), 4)

    def test_ink_is_never_in_the_ring(self) -> None:
        ink = {(0, 0), (1, 0)}
        self.assertFalse(bf.outline_of(ink) & ink)


class LayoutAndFitTests(unittest.TestCase):
    def test_glyph_that_fits_gets_a_complete_outline(self) -> None:
        font = block_font(6, 12, "A")
        report, art = bf.fit_font(font, "A")
        self.assertEqual((report.ink_clipped, report.outline_clipped, report.wide_glyphs), ("", "", ""))
        rows = art["A"]
        self.assertEqual(len(rows), 16)
        self.assertTrue(all(len(row) == 8 for row in rows))
        # el bloque ocupa 6 columnas centradas, con contorno a ambos lados
        inked_columns = {x for row in rows for x, symbol in enumerate(row) if symbol == bf.FILL}
        self.assertEqual(inked_columns, set(range(1, 7)))
        self.assertTrue(all(row[0] in ".#" and row[7] in ".#" for row in rows))
        self.assertIn("#", rows[0] + rows[-1] + "".join(row[0] for row in rows))

    def test_seven_pixel_glyph_loses_outline_but_not_ink(self) -> None:
        report, art = bf.fit_font(block_font(7, 10, "M"), "M")
        self.assertEqual(report.wide_glyphs, "M")
        self.assertEqual(report.ink_clipped, "")
        self.assertEqual(report.outline_clipped, "M")
        self.assertEqual(sum(row.count(bf.FILL) for row in art["M"]), 7 * 10)

    def test_glyph_wider_than_the_cell_loses_ink(self) -> None:
        report, _ = bf.fit_font(block_font(9, 4, "W"), "W")
        self.assertEqual(report.ink_clipped, "W")

    def test_missing_characters_are_reported(self) -> None:
        report, art = bf.fit_font(block_font(4, 4, "A"), "AB")
        self.assertEqual(report.missing, "B")
        self.assertEqual(list(art), ["A"])

    def test_tall_set_drops_the_bottom_outline_of_descenders_only_when_forced(self) -> None:
        # 15 filas de tinta en total no caben con contorno arriba y abajo: algo se recorta, pero ninguna tinta
        accent = bf.Glyph(frozenset({(2, 10), (2, 9)}), 8)
        descender = bf.Glyph(frozenset({(2, -4), (2, -3)}), 8)
        font = bf.BitmapFont("tall", {ord("A"): accent, ord("g"): descender})
        report, _ = bf.fit_font(font, "Ag")
        self.assertEqual(report.ink_height, 15)
        self.assertEqual(report.ink_clipped, "")
        self.assertNotEqual(report.outline_clipped, "")

    def test_shift_is_off_by_default_and_fixes_one_sided_clipping_when_enabled(self) -> None:
        glyphs = {ord("M"): block_font(7, 10, "M").glyph("M"), ord("i"): block_font(6, 10, "i").glyph("i")}
        font = bf.BitmapFont("mix", glyphs)
        plain, _ = bf.fit_font(font, "Mi")
        shifted, _ = bf.fit_font(font, "Mi", allow_shift=True)
        self.assertEqual(plain.shifted_glyphs, "")
        self.assertLessEqual(len(shifted.outline_clipped), len(plain.outline_clipped))


class ArtFormatTests(unittest.TestCase):
    def test_art_round_trips_through_the_probe_parser_and_packer(self) -> None:
        _, art = bf.fit_font(block_font(5, 8, probe.LATIN_CHARS), probe.LATIN_CHARS)
        text = bf.format_font_art(art, header="synthetic")
        parsed = probe.parse_font_art(text)
        self.assertEqual(parsed, art)
        self.assertEqual(len(probe.font_binary(parsed)), len(probe.LATIN_CHARS) * probe.LETTER_BYTES)

    def test_fill_and_outline_use_the_game_pixel_values(self) -> None:
        self.assertEqual(probe.PIXEL_VALUES[bf.FILL], 1)
        self.assertEqual(probe.PIXEL_VALUES[bf.OUTLINE], 3)
        self.assertEqual(probe.PIXEL_VALUES[bf.BACKGROUND], 0)


class TextWidthTests(unittest.TestCase):
    ADVANCES = {ord("a"): 5, ord("b"): 3, ord(" "): 2, ord("?"): 4}

    def test_width_sums_advances_with_question_mark_fallback(self) -> None:
        self.assertEqual(bf.text_width(self.ADVANCES, "ab a"), 5 + 3 + 2 + 5)
        self.assertEqual(bf.text_width(self.ADVANCES, "z"), 4)

    def test_rows_wrap_at_word_boundaries(self) -> None:
        self.assertEqual(bf.count_rows(self.ADVANCES, "aa aa aa", 14), 1 + 1 + 1)  # 'aa' = 10; con espacio 22 > 14
        self.assertEqual(bf.count_rows(self.ADVANCES, "b b b", 14), 1)  # 3+2+3+2+3 = 13

    def test_empty_text_needs_one_row(self) -> None:
        self.assertEqual(bf.count_rows(self.ADVANCES, "", 14), 1)


class CommandLineTests(unittest.TestCase):
    def test_convert_writes_art_for_a_complete_font(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            bdf = Path(work) / "full.bdf"
            lines = ["STARTFONT 2.1"]
            for char in convert.SPANISH_CHARSET:
                lines += [f"STARTCHAR c{ord(char)}", f"ENCODING {ord(char)}", "DWIDTH 6 0", "BBX 4 6 0 0", "BITMAP"]
                lines += ["F0"] * 6 + ["ENDCHAR"]
            bdf.write_text("\n".join(lines + ["ENDFONT"]), encoding="utf-8")
            out = Path(work) / "art.txt"
            with redirect_stdout(io.StringIO()) as captured:
                code = convert.main(["--format", "bdf", "--font", str(bdf), "--out", str(out), "--report"])
            self.assertEqual(code, 0)
            self.assertIn("missing characters: none", captured.getvalue())
            self.assertEqual(set(probe.parse_font_art(out.read_text(encoding="utf-8"))), set(convert.SPANISH_CHARSET))

    def test_convert_refuses_a_font_that_lacks_spanish_letters(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            bdf = Path(work) / "poor.bdf"
            bdf.write_text(SAMPLE_BDF, encoding="utf-8")
            out = Path(work) / "art.txt"
            self.assertEqual(convert.main(["--format", "bdf", "--font", str(bdf), "--out", str(out)]), 2)
            self.assertFalse(out.exists())

    def test_convert_rejects_a_missing_file(self) -> None:
        self.assertEqual(convert.main(["--format", "bdf", "--font", "nope.bdf", "--out", "x.txt"]), 2)

    def test_measure_reports_fixed_and_bdf_advances(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            sample = Path(work) / "sample.txt"
            sample.write_text("ab ab\nba\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as captured:
                code = measure.main(["--text-file", str(sample), "--fixed", "8", "6"])
            self.assertEqual(code, 0)
            output = captured.getvalue()
            self.assertIn("fixed 8 px", output)
            self.assertIn("8.00 px/letter", output)
            self.assertIn("6.00 px/letter", output)

    def test_measure_rejects_a_missing_text_file(self) -> None:
        self.assertEqual(measure.main(["--text-file", "nope.txt"]), 2)


if __name__ == "__main__":
    unittest.main()
