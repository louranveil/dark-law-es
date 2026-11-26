#!/usr/bin/env python3
"""Lee los glifos de 16x16 de la fuente de diálogo y los dibuja en hojas numeradas.

La fuente está sin comprimir en los bancos ``$D2`` y ``$D3`` (ver ``docs/re/font.md``): una página de
códigos de un byte (``00``-``BF``) y cuatro páginas de kanji (prefijos ``FD FC FB FA``). Cada glifo son
cuatro tiles de 2 bpp (16 bytes por tile): la mitad superior ocupa 32 bytes seguidos y la inferior los
32 siguientes a ``+0x100``.

Las hojas sirven para asignar un carácter a cada glifo (tabla de glifos, ``tbl/original.json``): cada
celda lleva su clave (``0A`` para un byte, ``FD 3A`` para un kanji) y cuántas veces aparece en el texto.

Uso::

    python tools/glyph_font.py --rom <original.sfc> --out <carpeta> [--per-sheet 60] [--scale 4]

Requiere Pillow solo para dibujar (importación tardía). Códigos de salida: 0 hojas escritas,
1 falta Pillow, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import script_format as sf

GLYPH_SIZE = 16
PAGE_BASES = {  # prefijo -> dirección larga de la página
    None: 0xD20129,
    0xFD: 0xD23B78,
    0xFC: 0xD27B78,
    0xFB: 0xD30000,
    0xFA: 0xD34000,
}
PAGE_SIZE = 256


def glyph_address(prefix: int | None, index: int) -> int:
    """Dirección larga del glifo ``index`` de la página de ``prefix`` (``None`` = códigos de un byte)."""
    if prefix not in PAGE_BASES:
        raise ValueError(f"unknown page prefix: {prefix!r}")
    if not 0 <= index < PAGE_SIZE:
        raise ValueError(f"glyph index out of range: {index!r}")
    base = PAGE_BASES[prefix]
    return base + (index >> 4) * 0x400 + ((index >> 3) & 1) * 0x200 + (index & 7) * 0x20


def decode_tile(data: bytes) -> list[list[int]]:
    """Un tile de 2 bpp (16 bytes) como 8 filas de 8 valores: plano 0 en el bit bajo y plano 1 en el alto."""
    if len(data) != 16:
        raise ValueError("a 2 bpp tile has 16 bytes")
    return [
        [((data[row * 2] >> (7 - column)) & 1) | (((data[row * 2 + 1] >> (7 - column)) & 1) << 1) for column in range(8)]
        for row in range(8)
    ]


def read_glyph(rom: bytes, prefix: int | None, index: int) -> list[list[int]]:
    """El glifo como 16 filas de 16 valores (0 fondo, 1 relleno, 3 contorno, 2 no usado por el juego)."""
    address = glyph_address(prefix, index)
    rows: list[list[int]] = [[] for _ in range(GLYPH_SIZE)]
    for half in range(2):
        left = decode_tile(sf.read_bytes(rom, address + half * 0x100, 16))
        right = decode_tile(sf.read_bytes(rom, address + half * 0x100 + 16, 16))
        for row in range(8):
            rows[half * 8 + row] = left[row] + right[row]
    return rows


def glyph_key(prefix: int | None, index: int) -> str:
    return f"{index:02X}" if prefix is None else f"{prefix:02X} {index:02X}"


def parse_key(key: str) -> tuple[int | None, int]:
    parts = key.split()
    if len(parts) == 1:
        return None, int(parts[0], 16)
    if len(parts) == 2:
        return int(parts[0], 16), int(parts[1], 16)
    raise ValueError(f"bad glyph key: {key!r}")


def glyph_usage(rom: bytes) -> Counter[str]:
    """Cuántas veces aparece cada glifo en todos los bloques de diálogo de las tablas (cada bloque una vez)."""
    usage: Counter[str] = Counter()
    seen: set[int] = set()
    for table in sf.read_all_tables(rom).values():
        for index in range(len(table.entries)):
            address = table.blob_address(index)
            if address in seen:
                continue
            seen.add(address)
            for token in sf.tokenize(sf.read_bytes(rom, address, 512)).tokens:
                if token.kind == "glyph":
                    usage[glyph_key(None, token.code)] += 1
                elif token.kind == "wide":
                    usage[glyph_key(token.raw[0], token.raw[1])] += 1
    return usage


def ordered_keys(usage: Counter[str]) -> list[str]:
    """Primero los códigos de un byte y después los kanji, cada grupo de más a menos frecuente."""
    def sort_key(key: str) -> tuple[int, int, str]:
        return (0 if " " not in key else 1, -usage[key], key)

    return sorted(usage, key=sort_key)


def render_sheets(rom: bytes, keys: list[str], usage: Counter[str], per_sheet: int, scale: int) -> list:
    """Hojas de Pillow con ``per_sheet`` glifos cada una, ampliados ``scale`` veces y con su clave y su cuenta."""
    from PIL import Image, ImageDraw, ImageFont

    columns = 10
    label_height = 28
    pad = 6
    cell_w = GLYPH_SIZE * scale + pad * 2
    cell_h = GLYPH_SIZE * scale + label_height + pad
    colors = {0: (20, 20, 28), 1: (245, 245, 245), 2: (230, 60, 60), 3: (110, 110, 130)}
    font = ImageFont.load_default(size=13)
    sheets = []
    for start in range(0, len(keys), per_sheet):
        chunk = keys[start : start + per_sheet]
        rows = (len(chunk) + columns - 1) // columns
        image = Image.new("RGB", (columns * cell_w, rows * cell_h), (40, 40, 48))
        draw = ImageDraw.Draw(image)
        for position, key in enumerate(chunk):
            x0 = (position % columns) * cell_w + pad
            y0 = (position // columns) * cell_h
            draw.text((x0, y0 + 2), f"{key}", fill=(255, 220, 120), font=font)
            draw.text((x0, y0 + 14), f"x{usage.get(key, 0)}", fill=(150, 200, 255), font=font)
            prefix, index = parse_key(key)
            for row, values in enumerate(read_glyph(rom, prefix, index)):
                for column, value in enumerate(values):
                    left = x0 + column * scale
                    top = y0 + label_height + row * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=colors[value])
        sheets.append(image)
    return sheets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dibuja hojas numeradas con los glifos del juego.")
    parser.add_argument("--rom", required=True, help="ROM original (solo lectura)")
    parser.add_argument("--out", required=True, help="carpeta de salida (se crea)")
    parser.add_argument("--per-sheet", type=int, default=60, help="glifos por hoja (por defecto 60)")
    parser.add_argument("--scale", type=int, default=4, help="ampliación de cada píxel (por defecto 4)")
    arguments = parser.parse_args(argv)
    if arguments.per_sheet < 1 or arguments.scale < 1:
        print("error: --per-sheet and --scale must be positive", file=sys.stderr)
        return 2
    try:
        rom = Path(arguments.rom).read_bytes()
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    usage = glyph_usage(rom)
    keys = ordered_keys(usage)
    try:
        sheets = render_sheets(rom, keys, usage, arguments.per_sheet, arguments.scale)
    except ImportError:
        print("error: drawing the sheets needs Pillow (pip install pillow)", file=sys.stderr)
        return 1
    folder = Path(arguments.out)
    folder.mkdir(parents=True, exist_ok=True)
    for number, sheet in enumerate(sheets, 1):
        sheet.save(folder / f"sheet-{number:02d}.png")
    singles = sum(1 for key in keys if " " not in key)
    print(f"{len(keys)} glyphs in use ({singles} single-byte, {len(keys) - singles} kanji) in {len(sheets)} sheets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
