from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_custom_font as custom  # noqa: E402
import export_font as export  # noqa: E402

ASSET = REPO / "assets" / "font" / "latin-8x16.txt"

try:
    import fontTools  # noqa: F401

    HAS_FONTTOOLS = True
except ImportError:
    HAS_FONTTOOLS = False

try:
    import PIL  # noqa: F401

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

PIXEL = export.UNITS_PER_PIXEL


def signed_area(loop):
    """Área con signo (fórmula del topógrafo): negativa en sentido horario con el eje Y hacia arriba."""
    total = 0
    for index, (x0, y0) in enumerate(loop):
        x1, y1 = loop[(index + 1) % len(loop)]
        total += x0 * y1 - x1 * y0
    return total / 2


class ContoursTest(unittest.TestCase):
    def test_one_pixel_is_one_clockwise_square_on_the_baseline(self):
        loops = export.contours(frozenset({(0, 12)}))  # fila 12: justo sobre la línea base
        self.assertEqual(loops, [[(0, 0), (0, PIXEL), (PIXEL, PIXEL), (PIXEL, 0)]])
        self.assertLess(signed_area(loops[0]), 0)

    def test_a_row_of_pixels_is_one_rectangle_without_collinear_points(self):
        loops = export.contours(frozenset({(1, 12), (2, 12), (3, 12)}))
        self.assertEqual(len(loops), 1)
        self.assertEqual(len(loops[0]), 4)
        self.assertEqual(abs(signed_area(loops[0])), 3 * PIXEL * PIXEL)

    def test_a_hole_runs_the_other_way(self):
        ring = frozenset((x, y) for x in range(3) for y in range(3)) - {(1, 1)}
        loops = export.contours(ring)
        self.assertEqual(len(loops), 2)
        areas = sorted(signed_area(loop) for loop in loops)
        self.assertEqual(areas, [-9 * PIXEL * PIXEL, PIXEL * PIXEL])

    def test_diagonal_pixels_keep_their_total_area(self):
        loops = export.contours(frozenset({(0, 12), (1, 11)}))
        self.assertEqual(sum(signed_area(loop) for loop in loops), -2 * PIXEL * PIXEL)

    def test_total_area_of_every_glyph_matches_its_ink(self):
        glyphs = custom.parse_source(ASSET.read_text(encoding="utf-8"))
        for char, ink in glyphs.items():
            if not ink:
                continue
            area = -sum(signed_area(loop) for loop in export.contours(ink))
            self.assertEqual(area, len(ink) * PIXEL * PIXEL, char)

    def test_metrics_are_the_game_cell(self):
        self.assertEqual(export.UNITS_PER_EM, 16 * PIXEL)
        self.assertEqual(export.ADVANCE, 8 * PIXEL)
        self.assertEqual(export.ASCENT + export.DESCENT, export.UNITS_PER_EM)


@unittest.skipUnless(HAS_FONTTOOLS, "needs fontTools")
class BuildFontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.glyphs = custom.parse_source(ASSET.read_text(encoding="utf-8"))
        cls.font = export.build_font(cls.glyphs)

    def test_cmap_covers_the_whole_source(self):
        cmap = self.font.getBestCmap()
        for char in self.glyphs:
            self.assertIn(ord(char), cmap, char)

    def test_every_advance_is_eight_pixels(self):
        metrics = self.font["hmtx"].metrics
        self.assertEqual({advance for advance, _ in metrics.values()}, {export.ADVANCE})

    def test_vertical_metrics_and_names(self):
        self.assertEqual(self.font["hhea"].ascent, export.ASCENT)
        self.assertEqual(self.font["hhea"].descent, -export.DESCENT)
        self.assertEqual(self.font["head"].unitsPerEm, export.UNITS_PER_EM)
        self.assertEqual(self.font["name"].getDebugName(1), export.FAMILY)

    def test_has_the_no_op_programs_that_keep_freetype_from_autohinting(self):
        self.assertIn("fpgm", self.font)
        self.assertIn("prep", self.font)
        self.assertGreater(self.font["maxp"].maxSizeOfInstructions, 0)


@unittest.skipUnless(HAS_FONTTOOLS and HAS_PILLOW, "needs fontTools and Pillow")
class RasterTest(unittest.TestCase):
    def test_every_glyph_renders_pixel_exact_at_whole_multiples_of_16(self):
        from PIL import Image, ImageDraw, ImageFont

        glyphs = custom.parse_source(ASSET.read_text(encoding="utf-8"))
        buffer = io.BytesIO()
        export.build_font(glyphs).save(buffer)
        for scale in (1, 2, 3):
            buffer.seek(0)
            font = ImageFont.truetype(buffer, 16 * scale, layout_engine=ImageFont.Layout.BASIC)
            for char, ink in glyphs.items():
                image = Image.new("L", (8 * scale, 16 * scale), 0)
                draw = ImageDraw.Draw(image)
                draw.fontmode = "1"
                draw.text((0, 13 * scale), char, font=font, fill=255, anchor="ls")
                pixels = {
                    (x // scale, y // scale)
                    for y in range(16 * scale)
                    for x in range(8 * scale)
                    if image.getpixel((x, y)) > 127
                }
                self.assertEqual(pixels, set(ink), f"{char!r} at {16 * scale} px")


@unittest.skipUnless(HAS_FONTTOOLS, "needs fontTools")
class MainTest(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = export.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_writes_a_loadable_ttf(self):
        from fontTools.ttLib import TTFont

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "font.ttf"
            code, out, _ = self.run_main("--source", str(ASSET), "--out", str(target))
            self.assertEqual(code, 0)
            self.assertIn("wrote 116 glyphs", out)
            self.assertEqual(TTFont(str(target))["head"].unitsPerEm, export.UNITS_PER_EM)

    def test_bad_source_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "bad.txt"
            source.write_text("nonsense\n", encoding="utf-8")
            code, _, err = self.run_main("--source", str(source), "--out", str(Path(folder) / "font.ttf"))
            self.assertEqual(code, 2)
            self.assertIn("error", err)


if __name__ == "__main__":
    unittest.main()
