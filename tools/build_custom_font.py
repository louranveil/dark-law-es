#!/usr/bin/env python3
"""Construye el arte de la fuente latina propia a partir de su fuente de tinta.

La fuente de tinta (``assets/font/latin-8x16.txt``) solo dibuja el relleno de cada
letra en la celda de 8x16; este script compone los acentos y las vocales
volteadas, genera el contorno del juego (valor 3, los ocho vecinos de la tinta,
recortado por la celda) y escribe el arte que lee ``build_latin_probe.py`` con
``--font-art``: por letra una línea ``U+XXXX`` y 16 filas de 8 símbolos
(``.`` fondo, ``-`` relleno, ``#`` contorno).

Formato de la fuente de tinta (todo lo que sigue a ``#`` al comienzo de una línea es comentario):

* ``glyph <letra|U+XXXX> top=<fila> left=<columna>`` y a continuación las filas del
  dibujo (``X`` tinta, ``.`` vacío) hasta una línea en blanco.
* ``mark <nombre> x,y x,y ...``: píxeles de tinta en coordenadas de la celda.
* ``compose <letra> <base> <marca>``: la base más la marca (no pueden solaparse).
* ``flip <letra> <origen> <primera fila> <última fila>``: el origen volteado en vertical.
* ``rotate <letra> <origen> <primera fila> <última fila> <primera columna> <última columna>``: el origen
  girado 180 grados dentro de esa caja (la ``¿`` es la ``?`` girada).

Códigos de salida: 0 arte escrito, 1 faltan letras del juego (con ``--allow-missing`` se escribe igual),
2 fuente de tinta o uso incorrectos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CELL_WIDTH, CELL_HEIGHT = 8, 16
# Las 111 letras con las que se probó el gancho (ASCII imprimible y los signos del español) y las marcas tipográficas
# que se añaden detrás para que los índices de las primeras no cambien: raya, puntos suspensivos y comillas angulares.
CORE_CHARS = "".join(chr(code) for code in range(0x20, 0x7F)) + "ñÑ¿¡áéíóúüÁÉÍÓÚÜ"
EXTRA_CHARS = "—…«»"
LATIN_CHARS = CORE_CHARS + EXTRA_CHARS
NEIGHBORS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]

Pixels = frozenset[tuple[int, int]]


class SourceError(ValueError):
    """La fuente de tinta no cumple el formato."""


def parse_char(token: str) -> str:
    """Una letra literal o ``U+XXXX``."""
    if token.startswith("U+") and len(token) > 2:
        return chr(int(token[2:], 16))
    if len(token) != 1:
        raise SourceError(f"not a single character: {token!r}")
    return token


def _check_in_cell(char: str, pixels: set[tuple[int, int]]) -> None:
    for x, y in pixels:
        if not (0 <= x < CELL_WIDTH and 0 <= y < CELL_HEIGHT):
            raise SourceError(f"glyph {char!r} has ink outside the cell at ({x}, {y})")


def parse_source(text: str) -> dict[str, Pixels]:
    """Tinta de cada letra de la fuente, como píxeles ``(columna, fila)`` de la celda."""
    glyphs: dict[str, set[tuple[int, int]]] = {}
    marks: dict[str, set[tuple[int, int]]] = {}
    pending: list[tuple[str, list[str]]] = []  # compose / flip, resueltos al final
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        keyword = fields[0]
        if keyword == "glyph":
            char = parse_char(fields[1])
            options = dict(field.split("=", 1) for field in fields[2:])
            top, left = int(options["top"]), int(options["left"])
            pixels: set[tuple[int, int]] = set()
            row = top
            while index < len(lines) and lines[index].strip():
                art = lines[index].strip()
                index += 1
                if set(art) - set("X."):
                    raise SourceError(f"glyph {char!r}: bad row {art!r}")
                pixels |= {(left + column, row) for column, symbol in enumerate(art) if symbol == "X"}
                row += 1
            if char in glyphs:
                raise SourceError(f"glyph {char!r} is defined twice")
            _check_in_cell(char, pixels)
            glyphs[char] = pixels
        elif keyword == "mark":
            marks[fields[1]] = {tuple(int(value) for value in pair.split(",")) for pair in fields[2:]}
        elif keyword in ("compose", "flip", "rotate"):
            pending.append((keyword, fields[1:]))
        else:
            raise SourceError(f"unknown line: {line!r}")

    for keyword, args in pending:
        char = parse_char(args[0])
        if char in glyphs:
            raise SourceError(f"glyph {char!r} is defined twice")
        base = glyphs.get(parse_char(args[1]))
        if base is None:
            raise SourceError(f"{keyword} {char!r}: unknown base {args[1]!r}")
        if keyword == "compose":
            mark = marks.get(args[2])
            if mark is None:
                raise SourceError(f"compose {char!r}: unknown mark {args[2]!r}")
            if base & mark:
                raise SourceError(f"compose {char!r}: the mark overlaps the base glyph")
            result = base | mark
        elif keyword == "flip":
            first, last = int(args[2]), int(args[3])
            result = {(x, first + last - y) for x, y in base}
        else:
            first, last, left, right = (int(value) for value in args[2:6])
            result = {(left + right - x, first + last - y) for x, y in base}
        _check_in_cell(char, result)
        glyphs[char] = result
    return {char: frozenset(pixels) for char, pixels in glyphs.items()}


def outline_of(ink: Pixels) -> set[tuple[int, int]]:
    """Contorno del juego: los vecinos de la tinta que no son tinta y caben en la celda."""
    ring = {(x + dx, y + dy) for x, y in ink for dx, dy in NEIGHBORS} - ink
    return {(x, y) for x, y in ring if 0 <= x < CELL_WIDTH and 0 <= y < CELL_HEIGHT}


def render_cell(ink: Pixels, with_outline: bool) -> list[str]:
    ring = outline_of(ink) if with_outline else set()
    return [
        "".join("-" if (x, y) in ink else "#" if (x, y) in ring else "." for x in range(CELL_WIDTH))
        for y in range(CELL_HEIGHT)
    ]


def build_art(glyphs: dict[str, Pixels], with_outline: bool) -> dict[str, list[str]]:
    return {char: render_cell(ink, with_outline) for char, ink in glyphs.items()}


def missing_chars(glyphs: dict[str, Pixels], charset: str = LATIN_CHARS) -> str:
    return "".join(char for char in charset if char not in glyphs)


def ink_extent(ink: Pixels) -> tuple[int, int, int, int] | None:
    """(columna mínima, fila mínima, columna máxima, fila máxima) de la tinta, o None si no hay."""
    if not ink:
        return None
    columns = [x for x, _ in ink]
    rows = [y for _, y in ink]
    return min(columns), min(rows), max(columns), max(rows)


def clipped_outline_count(ink: Pixels) -> int:
    """Píxeles de contorno que no caben en la celda (la tinta pegada a un borde)."""
    ring = {(x + dx, y + dy) for x, y in ink for dx, dy in NEIGHBORS} - ink
    return len(ring) - len(outline_of(ink))


def format_art(art: dict[str, list[str]], header: str) -> str:
    parts = [f"#! {header}"]
    for char, rows in sorted(art.items(), key=lambda item: ord(item[0])):
        parts.append(f"U+{ord(char):04X}")
        parts.extend(rows)
    return "\n".join(parts) + "\n"


def report(glyphs: dict[str, Pixels], charset: str = LATIN_CHARS) -> str:
    drawn = [char for char in charset if char in glyphs]
    extents = {char: ink_extent(glyphs[char]) for char in drawn if glyphs[char]}
    clipped = sorted(char for char in drawn if clipped_outline_count(glyphs[char]))
    widest = max((box[2] - box[0] + 1 for box in extents.values()), default=0)
    top = min((box[1] for box in extents.values()), default=0)
    bottom = max((box[3] for box in extents.values()), default=0)
    lines = [
        f"covered {len(drawn)} of {len(charset)} characters; missing: {missing_chars(glyphs, charset)!r}",
        f"ink columns up to {widest}; rows {top}-{bottom}",
        f"outline clipped by the cell in {len(clipped)} glyphs: {''.join(clipped)!r}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construye el arte de la fuente latina propia.")
    parser.add_argument("--source", required=True, help="fuente de tinta (assets/font/latin-8x16.txt)")
    parser.add_argument("--out", required=True, help="arte de salida para build_latin_probe.py --font-art")
    parser.add_argument("--outline", choices=("full", "none"), default="full", help="contorno de valor 3 (por defecto full)")
    parser.add_argument("--allow-missing", action="store_true", help="escribir el arte aunque falten letras del juego")
    arguments = parser.parse_args(argv)

    try:
        glyphs = parse_source(Path(arguments.source).read_text(encoding="utf-8"))
    except (SourceError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(report(glyphs))
    missing = missing_chars(glyphs)
    if missing and not arguments.allow_missing:
        print(f"error: the font lacks {missing!r}", file=sys.stderr)
        return 1
    art = build_art(glyphs, arguments.outline == "full")
    header = f"dark-law-latin-8x16 outline={arguments.outline}"
    Path(arguments.out).write_text(format_art(art, header), encoding="utf-8")
    print(f"wrote {len(art)} glyphs to {arguments.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
