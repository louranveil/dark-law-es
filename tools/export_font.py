#!/usr/bin/env python3
"""Exporta la fuente latina propia como TrueType (.ttf) instalable.

Lee la fuente de tinta (``assets/font/latin-8x16.txt``, ver ``build_custom_font.py``)
y escribe una TTF de píxeles: cada píxel de tinta es un cuadrado del contorno vectorial,
así que la fuente se ve exacta con un cuerpo de 16 px (o múltiplos enteros, sin suavizado)
y borrosa con cualquier otro tamaño. Es la fuente sin el contorno del juego: el contorno
de valor 3 lo pone ``build_custom_font.py`` al generar el arte para la ROM.

Métricas: 1600 unidades por em (100 por píxel), avance 800 (8 px), ascenso 1300 (13 px, la
línea base queda bajo la fila 12) y descenso 300 (3 px), es decir, la celda de 8x16 del juego.

Requiere ``fontTools`` (dependencia opcional, importación tardía): ``pip install fonttools``.

Códigos de salida: 0 fuente escrita, 1 falta fontTools, 2 fuente de tinta o uso incorrectos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import build_custom_font as custom

UNITS_PER_PIXEL = 100
UNITS_PER_EM = 16 * UNITS_PER_PIXEL
ADVANCE = custom.CELL_WIDTH * UNITS_PER_PIXEL
BASELINE_ROW = 13  # la línea base queda en el borde superior de la fila 13: sobre ella caen las filas 0-12
ASCENT = BASELINE_ROW * UNITS_PER_PIXEL
DESCENT = (custom.CELL_HEIGHT - BASELINE_ROW) * UNITS_PER_PIXEL

FAMILY = "Dark Law Latin"
STYLE = "Regular"
COPYRIGHT = "Copyright (c) 2026 louranveil. Original work of the Dark Law Spanish translation project."
LICENSE = "MIT License, as the rest of the dark-law-es repository."


def notdef_pixels() -> frozenset[tuple[int, int]]:
    """El glifo de las letras que faltan: un marco hueco con la caja de las mayúsculas."""
    box = {(x, y) for x in range(1, 7) for y in range(3, 13)}
    inside = {(x, y) for x in range(2, 6) for y in range(4, 12)}
    return frozenset(box - inside)


def contours(ink: frozenset[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Contornos de la tinta en unidades de fuente: los exteriores en sentido horario y los huecos al revés.

    Se recorren los bordes de cada píxel (con el relleno a la derecha), se anulan los compartidos y se
    encadena lo que queda; dos píxeles que solo se tocan en una esquina quedan en un mismo contorno
    (no como dos cuadrados sueltos que se rozan, que algunos rasterizadores dibujan mal). Los puntos
    en línea recta se eliminan.
    """
    edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for column, row in ink:
        left, bottom = column, BASELINE_ROW - row - 1
        square = [(left, bottom), (left, bottom + 1), (left + 1, bottom + 1), (left + 1, bottom)]
        for index in range(4):
            start, finish = square[index], square[(index + 1) % 4]
            if (finish, start) in edges:
                edges.remove((finish, start))
            else:
                edges.add((start, finish))
    outgoing: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for start, finish in edges:
        outgoing.setdefault(start, []).append(finish)

    def turn_rank(previous: tuple[int, int], here: tuple[int, int], candidate: tuple[int, int]) -> int:
        """Menor es más a la derecha: con el relleno a la derecha eso mantiene unidos los píxeles en diagonal."""
        direction = (here[0] - previous[0], here[1] - previous[1])
        step = (candidate[0] - here[0], candidate[1] - here[1])
        cross = direction[0] * step[1] - direction[1] * step[0]
        return cross  # negativo = giro a la derecha

    loops = []
    while outgoing:
        start = min(outgoing)
        loop = [start]
        here = outgoing[start].pop()
        if not outgoing[start]:
            del outgoing[start]
        previous = start
        while here != start:
            loop.append(here)
            options = outgoing[here]
            options.sort(key=lambda candidate: turn_rank(previous, here, candidate))
            following = options.pop(0)
            if not options:
                del outgoing[here]
            previous, here = here, following
        loops.append(loop)

    result = []
    for loop in loops:
        count = len(loop)
        corners = []
        for index, point in enumerate(loop):
            before, after = loop[index - 1], loop[(index + 1) % count]
            if (point[0] - before[0], point[1] - before[1]) != (after[0] - point[0], after[1] - point[1]):
                corners.append(point)
        result.append([(x * UNITS_PER_PIXEL, y * UNITS_PER_PIXEL) for x, y in corners])
    return result


def glyph_name(char: str) -> str:
    return f"uni{ord(char):04X}"


def build_font(glyphs: dict[str, frozenset[tuple[int, int]]], version: str = "0.2"):
    """``fontTools.ttLib.TTFont`` con los glifos de la fuente de tinta (importa fontTools aquí)."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    chars = sorted(glyphs, key=ord)
    names = [glyph_name(char) for char in chars]
    pens = {}
    metrics = {}

    def draw(name: str, ink: frozenset[tuple[int, int]]) -> None:
        pen = TTGlyphPen(None)
        loops = contours(ink) if ink else []
        for loop in loops:
            pen.moveTo(loop[0])
            for point in loop[1:]:
                pen.lineTo(point)
            pen.closePath()
        pens[name] = pen.glyph()
        metrics[name] = (ADVANCE, min((x for loop in loops for x, _ in loop), default=0))

    draw(".notdef", notdef_pixels())
    for char, name in zip(chars, names):
        draw(name, glyphs[char])

    builder = FontBuilder(UNITS_PER_EM, isTTF=True)
    builder.setupGlyphOrder([".notdef"] + names)
    builder.setupCharacterMap({ord(char): name for char, name in zip(chars, names)})
    builder.setupGlyf(pens)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ASCENT, descent=-DESCENT)
    builder.setupNameTable(
        {
            "familyName": FAMILY,
            "styleName": STYLE,
            "uniqueFontIdentifier": f"{FAMILY} {version}",
            "fullName": f"{FAMILY} {STYLE}",
            "psName": FAMILY.replace(" ", "") + "-" + STYLE,
            "version": f"Version {version}",
            "copyright": COPYRIGHT,
            "licenseDescription": LICENSE,
        }
    )
    builder.setupOS2(
        sTypoAscender=ASCENT,
        sTypoDescender=-DESCENT,
        sTypoLineGap=0,
        usWinAscent=ASCENT,
        usWinDescent=DESCENT,
        sxHeight=7 * UNITS_PER_PIXEL,
        sCapHeight=10 * UNITS_PER_PIXEL,
        achVendID="DLES",
    )
    builder.setupPost(keepGlyphNames=False, isFixedPitch=1)
    builder.font["head"].fontRevision = float(version)
    add_pixel_hinting(builder.font)
    return builder.font


def add_pixel_hinting(font) -> None:
    """Evita que FreeType aplique su auto-hinter, que mueve píxeles sueltos como los de las marcas.

    FreeType auto-ajusta las TrueType sin instrucciones (comprobado con Pillow: el píxel superior del
    acento agudo subía una fila). Con programas ``fpgm`` y ``prep`` que no hacen nada usa el intérprete
    TrueType, que no cambia nada y respeta las coordenadas. ``gasp`` pide el dibujo sin suavizado (solo
    ajuste a la rejilla), el que corresponde a una fuente de píxeles.
    """
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables import ttProgram

    for tag in ("fpgm", "prep"):
        program = ttProgram.Program()
        program.fromAssembly(["PUSHB[ ]", "0", "POP[ ]"])
        table = newTable(tag)
        table.program = program
        font[tag] = table
    font["maxp"].maxSizeOfInstructions = 8
    gasp = newTable("gasp")
    gasp.version = 1
    gasp.gaspRange = {0xFFFF: 0x0001}
    font["gasp"] = gasp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta la fuente latina propia como TrueType.")
    parser.add_argument("--source", required=True, help="fuente de tinta (assets/font/latin-8x16.txt)")
    parser.add_argument("--out", required=True, help="archivo .ttf de salida")
    parser.add_argument("--version", default="0.2", help="versión de la fuente (por defecto 0.2)")
    arguments = parser.parse_args(argv)

    try:
        glyphs = custom.parse_source(Path(arguments.source).read_text(encoding="utf-8"))
    except (custom.SourceError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        font = build_font(glyphs, arguments.version)
    except ImportError:
        print("error: exporting a TTF needs fontTools (pip install fonttools)", file=sys.stderr)
        return 1
    font.save(arguments.out)
    print(f"wrote {len(glyphs)} glyphs to {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
