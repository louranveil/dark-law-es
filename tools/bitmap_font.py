"""Lectura de fuentes de mapa de bits y su adaptación a una celda con contorno.

Módulo sin dependencias del juego (solo biblioteca estándar; Pillow solo si se
leen TTF): convierte una fuente bitmap en glifos de una celda fija con relleno
de valor 1 y contorno de valor 3, el esquema de la fuente original de Dark Law
(ver docs/re/font.md), y mide cuánto de la fuente cabe en la celda.

Convenciones: un glifo es un conjunto de píxeles ``(x, y)`` con ``x`` creciendo
a la derecha desde el origen de la pluma e ``y`` creciendo hacia arriba desde la
línea base (la fila inferior de una ``H`` tiene ``y = 0``). Una celda es una
lista de filas de texto con los símbolos ``.`` (0, fondo), ``-`` (1, relleno) y
``#`` (3, contorno).

Es candidato a extraerse a un repositorio genérico (nada aquí es de Dark Law);
mientras tanto vive junto a las herramientas del juego.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FILL = "-"
OUTLINE = "#"
BACKGROUND = "."
NEIGHBORS_8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
NEIGHBORS_4 = [(0, 1), (0, -1), (1, 0), (-1, 0)]
# Un píxel de relleno perdido pesa mucho más que uno de contorno: se prefiere recortar el contorno.
INK_LOSS_WEIGHT = 1000


@dataclass(frozen=True)
class Glyph:
    pixels: frozenset[tuple[int, int]]
    advance: int

    def ink_box(self) -> tuple[int, int, int, int] | None:
        """(x mínimo, y mínimo, x máximo, y máximo) de la tinta, o None si el glifo está en blanco."""
        if not self.pixels:
            return None
        xs = [x for x, _ in self.pixels]
        ys = [y for _, y in self.pixels]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass
class BitmapFont:
    name: str
    glyphs: dict[int, Glyph] = field(default_factory=dict)

    def glyph(self, char: str) -> Glyph | None:
        return self.glyphs.get(ord(char))


def read_bdf(text: str, name: str = "") -> BitmapFont:
    """Lee un BDF (Glyph Bitmap Distribution Format): codificación Unicode, ``BBX`` y ``BITMAP`` hexadecimal."""
    font = BitmapFont(name=name)
    encoding = advance = None
    bbox = None
    rows: list[int] | None = None
    row_bits = 0
    for line in text.splitlines():
        if line.startswith("STARTCHAR"):
            encoding = advance = bbox = rows = None
        elif line.startswith("ENCODING"):
            encoding = int(line.split()[1])
        elif line.startswith("DWIDTH"):
            advance = int(line.split()[1])
        elif line.startswith("BBX"):
            bbox = tuple(int(value) for value in line.split()[1:5])
        elif line == "BITMAP":
            rows = []
        elif line == "ENDCHAR":
            if encoding is not None and encoding >= 0 and bbox is not None and rows is not None:
                width, height, x_offset, y_offset = bbox
                pixels = set()
                for index, value in enumerate(rows[:height]):
                    for column in range(width):
                        if value >> (row_bits - 1 - column) & 1:
                            pixels.add((x_offset + column, y_offset + height - 1 - index))
                font.glyphs[encoding] = Glyph(frozenset(pixels), advance if advance is not None else width)
            rows = None
        elif rows is not None and re.fullmatch(r"[0-9A-Fa-f]+", line):
            row_bits = len(line) * 4
            rows.append(int(line, 16))
    return font


def read_f8(data: bytes, baseline_row: int, name: str = "", cell_width: int = 8, cell_height: int = 16) -> BitmapFont:
    """Lee un ``.f8`` de Sweet16: ``cell_height`` bytes por carácter, el bit más alto es la columna izquierda.

    El archivo no dice dónde está la línea base; ``baseline_row`` es la fila (contando desde arriba) de la
    fila inferior de las letras sin descendente.
    """
    font = BitmapFont(name=name)
    for code in range(len(data) // cell_height):
        pixels = set()
        for row in range(cell_height):
            value = data[code * cell_height + row]
            for column in range(cell_width):
                if value >> (cell_width - 1 - column) & 1:
                    pixels.add((column, baseline_row - row))
        font.glyphs[code] = Glyph(frozenset(pixels), cell_width)
    return font


def read_hex(text: str, baseline_row: int, name: str = "") -> BitmapFont:
    """Lee el formato ``.hex`` de Unifont y Unscii: ``CODIGO:`` y 32 dígitos (16 filas de 8 píxeles); se omiten los anchos."""
    font = BitmapFont(name=name)
    for line in text.splitlines():
        code, _, digits = line.strip().partition(":")
        if len(digits) != 32:
            continue
        glyph = read_f8(bytes.fromhex(digits), baseline_row, name).glyphs[0]
        font.glyphs[int(code, 16)] = glyph
    return font


def read_ttf(path: Path, pixel_size: int, name: str = "") -> BitmapFont:
    """Rasteriza una TTF de mapa de bits sin suavizado con Pillow (importación tardía: dependencia opcional)."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    font_file = ImageFont.truetype(str(path), pixel_size)
    font = BitmapFont(name=name)
    margin, baseline = 8, pixel_size * 2
    for code in list(range(0x20, 0x7F)) + list(range(0xA0, 0x180)):
        canvas = Image.new("1", (pixel_size * 3, pixel_size * 3), 0)
        drawer = ImageDraw.Draw(canvas)
        drawer.fontmode = "1"
        drawer.text((margin, baseline), chr(code), font=font_file, fill=1, anchor="ls")
        pixels = {
            (x - margin, baseline - y)
            for y in range(canvas.height)
            for x in range(canvas.width)
            if canvas.getpixel((x, y))
        }
        font.glyphs[code] = Glyph(frozenset(pixels), round(font_file.getlength(chr(code))))
    return font


def outline_of(pixels: set[tuple[int, int]], neighbors: list[tuple[int, int]] = NEIGHBORS_8) -> set[tuple[int, int]]:
    """Píxeles de contorno: vecinos de la tinta que no son tinta."""
    ring = {(x + dx, y + dy) for x, y in pixels for dx, dy in neighbors}
    return ring - pixels


@dataclass(frozen=True)
class Layout:
    """Dónde cae el origen de la pluma en la celda: ``origin_column`` y ``baseline_row`` (fila de ``y = 0``)."""

    origin_column: int
    baseline_row: int


def _cell_pixels(glyph: Glyph, layout: Layout, column_shift: int = 0):
    ink = {(layout.origin_column + column_shift + x, layout.baseline_row - y) for x, y in glyph.pixels}
    return ink, outline_of(ink)


def _clipping_cost(glyph: Glyph, layout: Layout, width: int, height: int, column_shift: int = 0) -> int:
    ink, ring = _cell_pixels(glyph, layout, column_shift)

    def outside(pixel: tuple[int, int]) -> bool:
        return not (0 <= pixel[0] < width and 0 <= pixel[1] < height)

    return INK_LOSS_WEIGHT * sum(outside(pixel) for pixel in ink) + sum(outside(pixel) for pixel in ring)


def choose_layout(glyphs: list[Glyph], width: int = 8, height: int = 16) -> Layout:
    """Elige origen y línea base comunes que minimizan la tinta y el contorno recortados; a igualdad, centrados."""
    inked = [glyph for glyph in glyphs if glyph.pixels]
    best: tuple[int, int, Layout] | None = None
    for baseline_row in range(0, height + 8):
        for origin_column in range(-width, 2 * width):
            layout = Layout(origin_column, baseline_row)
            cost = sum(_clipping_cost(glyph, layout, width, height) for glyph in inked)
            off_center = abs(2 * origin_column - width) + abs(2 * baseline_row - height)
            candidate = (cost, off_center, layout)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    assert best is not None
    return best[2]


def render_cell(
    glyph: Glyph, layout: Layout, width: int = 8, height: int = 16, column_shift: int = 0
) -> list[str]:
    """Celda de ``height`` filas de ``width`` símbolos: relleno ``-``, contorno ``#``, fondo ``.``; lo que cae fuera se recorta."""
    ink, ring = _cell_pixels(glyph, layout, column_shift)
    rows = []
    for row in range(height):
        line = ""
        for column in range(width):
            pixel = (column, row)
            line += FILL if pixel in ink else OUTLINE if pixel in ring else BACKGROUND
        rows.append(line)
    return rows


@dataclass
class FitReport:
    name: str
    cell: tuple[int, int]
    layout: Layout
    missing: str
    ink_width_max: int
    ink_height: int  # filas entre el píxel más alto y el más bajo del conjunto, ambos incluidos
    wide_glyphs: str  # caracteres cuya tinta no deja hueco horizontal para el contorno
    shifted_glyphs: str  # caracteres desplazados una columna para que quepa su contorno
    ink_clipped: str  # caracteres que pierden tinta
    outline_clipped: str  # caracteres cuyo contorno queda recortado tras ajustar
    advance_widths: dict[int, int]


def fit_font(
    font: BitmapFont, charset: str, width: int = 8, height: int = 16, allow_shift: bool = False
) -> tuple[FitReport, dict[str, list[str]]]:
    """Coloca cada carácter de ``charset`` en la celda y mide el encaje. Devuelve el informe y el arte por carácter."""
    present = {char: font.glyph(char) for char in charset if font.glyph(char) is not None}
    missing = "".join(char for char in charset if char not in present)
    inked = {char: glyph for char, glyph in present.items() if glyph.pixels}
    layout = choose_layout(list(present.values()), width, height)

    shifts: dict[str, int] = {}
    for char, glyph in present.items():
        base = _clipping_cost(glyph, layout, width, height)
        if base and allow_shift:
            options = [(_clipping_cost(glyph, layout, width, height, shift), abs(shift), shift) for shift in (-1, 1)]
            cost, _, shift = min(options)
            if cost < base:
                shifts[char] = shift

    art: dict[str, list[str]] = {}
    ink_lost, outline_lost = [], []
    for char, glyph in present.items():
        shift = shifts.get(char, 0)
        art[char] = render_cell(glyph, layout, width, height, shift)
        cost = _clipping_cost(glyph, layout, width, height, shift)
        if cost >= INK_LOSS_WEIGHT:
            ink_lost.append(char)
        elif cost:
            outline_lost.append(char)

    boxes = [glyph.ink_box() for glyph in inked.values()]
    ink_width_max = max((box[2] - box[0] + 1 for box in boxes), default=0)
    y_min = min((box[1] for box in boxes), default=0)
    y_max = max((box[3] for box in boxes), default=0)
    wide = "".join(char for char, glyph in inked.items() if _ink_width(glyph) > width - 2)
    report = FitReport(
        name=font.name,
        cell=(width, height),
        layout=layout,
        missing=missing,
        ink_width_max=ink_width_max,
        ink_height=y_max - y_min + 1 if boxes else 0,
        wide_glyphs=wide,
        shifted_glyphs="".join(shifts),
        ink_clipped="".join(ink_lost),
        outline_clipped="".join(outline_lost),
        advance_widths={ord(char): glyph.advance for char, glyph in present.items()},
    )
    return report, art


def _ink_width(glyph: Glyph) -> int:
    box = glyph.ink_box()
    return box[2] - box[0] + 1 if box else 0


def format_font_art(art: dict[str, list[str]], header: str = "") -> str:
    """Texto que lee ``build_latin_probe.parse_font_art``: una línea ``U+XXXX`` y 16 filas por letra."""
    parts = [f"#! {header}"] if header else []
    for char, rows in art.items():
        parts.append(f"U+{ord(char):04X}")
        parts.extend(rows)
    return "\n".join(parts) + "\n"


def read_charwidths(text: str) -> dict[int, int]:
    """Lee ``Sweet16_charwidths.txt``: pares ``código ancho`` separados por espacios; el ancho no incluye el espaciado."""
    numbers = [int(token) for token in text.split()]
    return dict(zip(numbers[::2], numbers[1::2]))


def text_width(advances: dict[int, int], text: str) -> int:
    """Ancho en píxeles de una línea con el avance de cada carácter; los que no tienen avance cuentan como ``?``."""
    fallback = advances.get(ord("?"), 0)
    return sum(advances.get(ord(char), fallback) for char in text)


def count_rows(advances: dict[int, int], text: str, row_width: int) -> int:
    """Filas necesarias para ``text`` con ajuste de línea por palabras en filas de ``row_width`` píxeles."""
    rows, used = 1, 0
    space = advances.get(ord(" "), 0)
    for word in text.split():
        width = text_width(advances, word)
        if used and used + space + width > row_width:
            rows, used = rows + 1, width
        else:
            used += (space if used else 0) + width
    return rows
