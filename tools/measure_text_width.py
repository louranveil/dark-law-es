#!/usr/bin/env python3
"""Mide cuánto ocupa un texto con distintas fuentes y espaciados (rejilla fija o proporcional).

Sirve para estimar la capacidad de una ventana: el ancho de fila del relato del intro es de
12 celdas de 16 píxeles (192 px). Compara un avance fijo (cada letra, 8 px en el motor actual)
con avances proporcionales: el de un BDF más un espaciado extra, o el de ``Sweet16_charwidths.txt``
más un espaciado.

Códigos de salida: 0 informe impreso, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bitmap_font import count_rows, read_bdf, read_charwidths, text_width


def paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def summarize(label: str, advances: dict[int, int], text: str, row_width: int) -> str:
    lines = paragraphs(text)
    letters = sum(len(line) for line in lines)
    pixels = sum(text_width(advances, line) for line in lines)
    rows = sum(count_rows(advances, line, row_width) for line in lines)
    return (
        f"{label:<34} {pixels / letters:5.2f} px/letter  {row_width / (pixels / letters):5.1f} letters/row  "
        f"{rows:3d} rows for {letters} letters"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--text-file", type=Path, required=True, help="texto de muestra (un párrafo por línea)")
    parser.add_argument("--row-width", type=int, default=192, help="ancho de la fila en píxeles (por defecto 192)")
    parser.add_argument("--fixed", type=int, nargs="*", default=[8], help="avances fijos a comparar (por defecto 8)")
    parser.add_argument("--bdf", type=Path, nargs="*", default=[], help="BDF cuyos avances se usan tal cual")
    parser.add_argument("--charwidths", type=Path, help="Sweet16_charwidths.txt")
    parser.add_argument("--spacing", type=int, nargs="*", default=[1, 2], help="espaciado extra para los anchos de --charwidths")
    parser.add_argument("--encoding", default="utf-8", help="codificación de los BDF (por defecto utf-8)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.text_file.is_file():
        print(f"error: {args.text_file} does not exist", file=sys.stderr)
        return 2
    text = args.text_file.read_text(encoding="utf-8")
    codes = {ord(char) for char in text}
    for advance in args.fixed:
        print(summarize(f"fixed {advance} px", {code: advance for code in codes}, text, args.row_width))
    for path in args.bdf:
        font = read_bdf(path.read_text(encoding=args.encoding), path.stem)
        print(summarize(f"{path.stem} advances", {code: glyph.advance for code, glyph in font.glyphs.items()}, text, args.row_width))
    if args.charwidths:
        widths = read_charwidths(args.charwidths.read_text(encoding="utf-8"))
        for spacing in args.spacing:
            print(summarize(f"Sweet16 widths + {spacing} px", {code: width + spacing for code, width in widths.items()}, text, args.row_width))
    return 0


if __name__ == "__main__":
    sys.exit(main())
