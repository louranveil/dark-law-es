#!/usr/bin/env python3
"""Tabla de glifos del juego: qué carácter dibuja cada glifo, y utilidades para leer el texto con ella.

La tabla vive en ``tbl/original.json`` (formato 1). Cada glifo tiene una clave (``0A`` para los códigos de
un byte, ``FD 3A`` para un kanji: prefijo de página e índice, ver ``glyph_font.py``) y una entrada::

    {"char": "こ", "kind": "text", "confidence": "seen", "note": "..."}

* ``kind``: ``text`` (kana, kanji, signos), ``latin`` (letras grandes M P K O L), ``icon`` (dibujos),
  ``blank`` (espacio), ``placeholder`` (cuadro de "glifo no definido") o ``unknown``.
* ``confidence``: ``seen`` (leído en la hoja y comprobado con su contexto), ``uncertain`` (la mejor lectura,
  sin cerrar; la revisa una persona) o ``unknown``.
* ``char`` es un solo carácter, o ``null`` si el glifo no es un carácter (marcadores, algunos iconos).

Uso::

    python tools/glyph_table.py check --table tbl/original.json [--rom <original.sfc>]
    python tools/glyph_table.py show --table tbl/original.json --rom <original.sfc> --blob E2EE73/0

``check`` valida la tabla y, con ``--rom``, lista los glifos que usa el texto y la tabla no recoge (error) y los que recoge sin carácter; ``show`` escribe
un mensaje con los comandos como ``<C8 80>`` y los glifos sin carácter como ``[40]``. Códigos de salida: 0 bien,
1 la tabla no cubre el texto, 2 tabla o uso incorrectos.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import glyph_font as gf
import script_format as sf

FORMAT_VERSION = 1
KINDS = frozenset({"text", "latin", "icon", "blank", "placeholder", "unknown"})
CONFIDENCES = frozenset({"seen", "uncertain", "unknown"})
CHAR_KINDS = frozenset({"text", "latin", "blank"})  # los tipos que tienen que traer un carácter


class TableError(ValueError):
    """La tabla de glifos no cumple el formato."""


@dataclass(frozen=True)
class GlyphTable:
    entries: dict[str, dict]

    def char(self, key: str) -> str | None:
        entry = self.entries.get(key)
        return entry["char"] if entry else None

    def needs_review(self) -> list[str]:
        """Las claves cuya lectura no está cerrada, para que las revise una persona."""
        return [key for key, entry in self.entries.items() if entry["confidence"] != "seen"]


def validate(data: object) -> list[str]:
    """Los problemas del documento ya leído (lista vacía si cumple el formato)."""
    if not isinstance(data, dict) or data.get("format") != FORMAT_VERSION:
        return [f"the table must be an object with format {FORMAT_VERSION}"]
    glyphs = data.get("glyphs")
    if not isinstance(glyphs, dict):
        return ["'glyphs' must be an object"]
    problems = []
    for key, entry in glyphs.items():
        try:
            prefix, index = gf.parse_key(key)
            gf.glyph_address(prefix, index)
            if gf.glyph_key(prefix, index) != key:
                raise ValueError("not canonical")
        except ValueError:
            problems.append(f"{key!r}: not a glyph key (upper-case hex, '0A' or 'FD 3A')")
            continue
        if not isinstance(entry, dict):
            problems.append(f"{key}: the entry must be an object")
            continue
        kind, confidence, char = entry.get("kind"), entry.get("confidence"), entry.get("char")
        if kind not in KINDS:
            problems.append(f"{key}: bad kind {kind!r}")
        if confidence not in CONFIDENCES:
            problems.append(f"{key}: bad confidence {confidence!r}")
        if char is not None and (not isinstance(char, str) or len(char) != 1):
            problems.append(f"{key}: char must be one character or null")
        if kind in CHAR_KINDS and char is None:
            problems.append(f"{key}: a {kind} glyph needs a char")
        if kind in ("placeholder", "unknown") and char is not None:
            problems.append(f"{key}: a {kind} glyph has no char")
    return problems


def load_table(path: Path | str) -> GlyphTable:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TableError(f"not valid JSON: {error}") from error
    problems = validate(data)
    if problems:
        extra = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        raise TableError("; ".join(problems[:5]) + extra)
    return GlyphTable(data["glyphs"])


def format_table(table: GlyphTable, description: str = "") -> str:
    """El JSON de la tabla con una entrada por línea (diferencias fáciles de revisar), glifos de un byte primero."""
    keys = sorted(table.entries, key=lambda key: (0 if " " not in key else 1, key))
    lines = ["{", f' "format": {FORMAT_VERSION},', f' "description": {json.dumps(description, ensure_ascii=False)},', ' "glyphs": {']
    for position, key in enumerate(keys):
        entry = json.dumps(table.entries[key], ensure_ascii=False)
        lines.append(f'  "{key}": {entry}{"," if position < len(keys) - 1 else ""}')
    lines += [" }", "}", ""]
    return "\n".join(lines)


def token_key(token: sf.Token) -> str | None:
    if token.kind == "glyph":
        return gf.glyph_key(None, token.code)
    if token.kind == "wide":
        return gf.glyph_key(token.raw[0], token.raw[1])
    return None


def decode_tokens(tokens, table: GlyphTable) -> str:
    """Texto legible: el carácter de cada glifo, ``[KEY]`` si no tiene, y ``<hex>`` por cada comando."""
    parts = []
    for token in tokens:
        key = token_key(token)
        if key is None:
            parts.append("<" + " ".join(f"{byte:02X}" for byte in token.raw) + ">")
        else:
            parts.append(table.char(key) or f"[{key}]")
    return "".join(parts)


def uncovered(usage: Counter[str], table: GlyphTable) -> Counter[str]:
    """Los glifos que el texto usa y la tabla no recoge (con cuántas veces): texto que falta por leer."""
    return Counter({key: count for key, count in usage.items() if key not in table.entries})


def without_char(usage: Counter[str], table: GlyphTable) -> Counter[str]:
    """Los glifos usados que la tabla recoge pero no son un carácter (iconos, cuadros de "glifo no definido")."""
    return Counter({key: count for key, count in usage.items() if key in table.entries and table.char(key) is None})


def read_blob_arg(text: str) -> tuple[int, int]:
    table_text, _, index_text = text.partition("/")
    return int(table_text, 16), int(index_text or "0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tabla de glifos del juego.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="valida la tabla y su cobertura del texto")
    check.add_argument("--table", required=True)
    check.add_argument("--rom", help="ROM original (solo lectura) para medir la cobertura")
    show = commands.add_parser("show", help="escribe un mensaje con la tabla")
    show.add_argument("--table", required=True)
    show.add_argument("--rom", required=True)
    show.add_argument("--blob", required=True, help="DIRECCIÓN_DE_TABLA/ÍNDICE en hexadecimal, p. ej. E2EE73/0")
    arguments = parser.parse_args(argv)

    try:
        table = load_table(arguments.table)
    except (TableError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    review = table.needs_review()
    print(f"{len(table.entries)} glyphs; {len(review)} not closed: {', '.join(review)}")
    if arguments.command == "check" and not arguments.rom:
        return 0
    try:
        rom = Path(arguments.rom).read_bytes()
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if arguments.command == "check":
        usage = gf.glyph_usage(rom)
        missing = uncovered(usage, table)
        unused = [key for key in table.entries if key not in usage]
        print(f"{len(usage)} glyphs in use; {len(unused)} in the table are not used by any message")
        for key, count in missing.most_common():
            print(f"  uncovered: {key} (x{count})")
        for key, count in without_char(usage, table).most_common():
            print(f"  no character: {key} (x{count}) {table.entries[key]['kind']}: {table.entries[key].get('note', '')}")
        return 1 if missing else 0

    try:
        address, index = read_blob_arg(arguments.blob)
        message_table = sf.read_table(rom, address)
        blob = sf.tokenize(sf.read_bytes(rom, message_table.blob_address(index), 512))
    except (ValueError, IndexError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(decode_tokens(blob.tokens, table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
