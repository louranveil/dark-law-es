#!/usr/bin/env python3
"""Convierte una fuente de mapa de bits en el arte de letras que lee build_latin_probe.py.

Lee un BDF, un ``.f8`` de Sweet16 o una TTF de píxeles (esta con Pillow), coloca cada
carácter del español en una celda de 8x16 con relleno de valor 1 y contorno de valor 3
(el esquema del juego, ver docs/re/font.md) y escribe el arte en texto. Con --report
imprime también cuánto de la fuente cabe en la celda.

Códigos de salida: 0 arte escrito, 2 uso o datos incorrectos (por ejemplo, faltan caracteres).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bitmap_font import BitmapFont, FitReport, fit_font, format_font_art, read_bdf, read_f8, read_hex, read_ttf

# Letras que necesita el texto en español: ASCII imprimible y los signos propios (igual que LATIN_CHARS de build_latin_probe).
SPANISH_CHARSET = "".join(chr(code) for code in range(0x20, 0x7F)) + "ñÑ¿¡áéíóúüÁÉÍÓÚÜ"


def load_font(kind: str, path: Path, name: str, baseline_row: int, pixel_size: int, encoding: str) -> BitmapFont:
    if kind == "bdf":
        return read_bdf(path.read_text(encoding=encoding), name)
    if kind == "f8":
        return read_f8(path.read_bytes(), baseline_row, name)
    if kind == "hex":
        return read_hex(path.read_text(encoding=encoding), baseline_row, name)
    return read_ttf(path, pixel_size, name)


def describe(report: FitReport) -> str:
    lines = [
        f"font: {report.name}",
        f"cell: {report.cell[0]}x{report.cell[1]}, pen origin column {report.layout.origin_column}, baseline row {report.layout.baseline_row}",
        f"missing characters: {report.missing!r}" if report.missing else "missing characters: none",
        f"widest ink: {report.ink_width_max} px (a full outline needs {report.cell[0] - 2} or fewer)",
        f"ink height over the set: {report.ink_height} rows (a full outline needs {report.cell[1] - 2} or fewer)",
        f"too wide for a full outline: {report.wide_glyphs!r}",
        f"shifted one column: {report.shifted_glyphs!r}",
        f"ink lost: {report.ink_clipped!r}",
        f"outline clipped: {report.outline_clipped!r}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--format", choices=["bdf", "f8", "hex", "ttf"], required=True, help="formato de la fuente")
    parser.add_argument("--font", type=Path, required=True, help="archivo de la fuente")
    parser.add_argument("--name", help="nombre para el informe (por defecto, el del archivo)")
    parser.add_argument("--baseline-row", type=int, default=12, help="f8 y hex: fila de la base de las letras sin descendente (por defecto 12)")
    parser.add_argument("--pixel-size", type=int, default=16, help="ttf: tamaño en píxeles con que se rasteriza (por defecto 16)")
    parser.add_argument("--encoding", default="utf-8", help="bdf: codificación del archivo de texto (por defecto utf-8)")
    parser.add_argument("--allow-shift", action="store_true", help="desplazar una columna los glifos cuyo contorno se recorta")
    parser.add_argument("--out", type=Path, required=True, help="arte de salida")
    parser.add_argument("--report", action="store_true", help="imprimir el informe de encaje")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.font.is_file():
        print(f"error: {args.font} does not exist", file=sys.stderr)
        return 2
    name = args.name or args.font.stem
    font = load_font(args.format, args.font, name, args.baseline_row, args.pixel_size, args.encoding)
    report, art = fit_font(font, SPANISH_CHARSET, allow_shift=args.allow_shift)
    if args.report:
        print(describe(report))
    if report.missing:
        print(f"error: {name} lacks {report.missing!r}", file=sys.stderr)
        return 2
    args.out.write_text(format_font_art(art, header=f"{name}, converted by convert_font_art.py"), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
