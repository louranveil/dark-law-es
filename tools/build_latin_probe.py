#!/usr/bin/env python3
"""Construye una ROM de prueba que muestra texto latino de 8x16 en el intro, dos letras por celda.

Es el spike de la fuente en español (docs/re/latin-font-spike.md): instala el gancho de
asm/latin_pair_hook.asm con asar, escribe una fuente latina en el relleno del banco $D2 y
sustituye el mensaje 0 del intro (reubicado en el relleno del banco $E2) por texto que usa
la ficha ``F9 a b``. La ROM resultante solo sirve para mirarla en el emulador y se escribe
fuera del repositorio.

La fuente se recibe como arte de texto con --font-art (ver ``parse_font_art``); el
repositorio no incluye ninguna: la de las pruebas locales sale de una tipografía del
sistema que no se puede redistribuir.

Códigos de salida: 0 ROM escrita, 2 uso o configuración incorrectos.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from script_builder import FreeSpace, PatchError, RomPatcher, relocate_blob
from script_format import cpu_to_offset, read_all_tables, tokenize

ASM_PATH = Path(__file__).resolve().parents[1] / "asm" / "latin_pair_hook.asm"
TABLE_ADDRESS = 0xE2EE73
MESSAGE_INDEX = 0
MESSAGE_FREE = (0xE2F8A6, 0xE30000)
HOOK_RANGE = (0xD14587, 0xD1458B)  # CMP #$E5 / BEQ: se sustituye por un JML
CODE_RANGE = (0xD2BB80, 0xD2C000)
FONT_START = 0xD2C000
FONT_END = 0xD30000
PAIR_TOKEN = 0xF9
LINE_BREAK = 0xC3
LETTER_BYTES = 32  # tile superior (16) + tile inferior (16)
GLYPH_WIDTH, GLYPH_HEIGHT = 8, 16
PIXEL_VALUES = {".": 0, "-": 1, "+": 2, "#": 3}

# Índice de letra = posición en esta cadena. ASCII imprimible primero, para que índice = código - 0x20.
LATIN_CHARS = "".join(chr(c) for c in range(0x20, 0x7F)) + "ñÑ¿¡áéíóúüÁÉÍÓÚÜ"
# Cola original del mensaje del intro: espera, apagado de pantalla y fin.
MESSAGE_TAIL = bytes.fromhex("c8 80 c8 e0 c5 c8 28 ff")
MESSAGE_HEAD = bytes([0xC0])


def parse_font_art(text: str) -> dict[str, list[str]]:
    """Lee el arte de la fuente: por cada letra, una línea ``U+XXXX`` y 16 líneas de 8 símbolos de ``.-+#``.

    ``.`` es el fondo (0), ``-`` el relleno (1), ``+`` (2) y ``#`` el contorno o trazo (3).
    """
    letters: dict[str, list[str]] = {}
    lines = [line.rstrip() for line in text.splitlines()]
    index = 0
    while index < len(lines):
        header = lines[index]
        index += 1
        if not header or header.startswith("#!"):
            continue
        if not header.startswith("U+"):
            raise ValueError(f"expected a U+XXXX header, got {header!r}")
        rows = lines[index : index + GLYPH_HEIGHT]
        index += GLYPH_HEIGHT
        if len(rows) != GLYPH_HEIGHT or any(len(row) != GLYPH_WIDTH or set(row) - set(PIXEL_VALUES) for row in rows):
            raise ValueError(f"bad glyph art for {header}")
        letters[chr(int(header[2:], 16))] = rows
    return letters


def pack_letter(rows: list[str]) -> bytes:
    """Empaqueta 16 filas de 8 píxeles en 32 bytes de 2 bpp: tile superior (8 filas) y tile inferior."""
    data = bytearray()
    for row in rows:
        plane0 = plane1 = 0
        for column, symbol in enumerate(row):
            value = PIXEL_VALUES[symbol]
            plane0 |= (value & 1) << (7 - column)
            plane1 |= ((value >> 1) & 1) << (7 - column)
        data += bytes([plane0, plane1])
    return bytes(data)


def font_binary(art: dict[str, list[str]]) -> bytes:
    missing = [char for char in LATIN_CHARS if char not in art]
    if missing:
        raise ValueError(f"the font art lacks: {''.join(missing)!r}")
    return b"".join(pack_letter(art[char]) for char in LATIN_CHARS)


def letter_index(char: str) -> int:
    try:
        return LATIN_CHARS.index(char)
    except ValueError:
        raise ValueError(f"no Latin glyph for {char!r}") from None


def encode_latin(text: str) -> bytes:
    """Codifica texto latino como fichas ``F9 a b``; ``\\n`` cierra la línea con ``C3`` y una línea impar se rellena con un espacio."""
    output = bytearray()
    lines = text.split("\n")
    for number, line in enumerate(lines):
        indices = [letter_index(char) for char in line]
        if len(indices) % 2:
            indices.append(letter_index(" "))
        for left, right in zip(indices[::2], indices[1::2]):
            output += bytes([PAIR_TOKEN, left, right])
        if number < len(lines) - 1:
            output.append(LINE_BREAK)
    return bytes(output)


def message_blob(text: str) -> bytes:
    return MESSAGE_HEAD + encode_latin(text) + MESSAGE_TAIL


def run_asar(asar: Path, rom_path: Path, font: bytes) -> None:
    with tempfile.TemporaryDirectory() as work:
        shutil.copy(ASM_PATH, Path(work) / ASM_PATH.name)
        (Path(work) / "latin-font.bin").write_bytes(font)
        result = subprocess.run(
            [str(asar.resolve()), "--fix-checksum=off", ASM_PATH.name, str(rom_path.resolve())],
            cwd=work,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise PatchError(f"asar failed:\n{result.stdout}{result.stderr}")


def changed_ranges(original: bytes, patched: bytes) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = None
    for offset, (a, b) in enumerate(zip(original, patched)):
        if a != b and start is None:
            start = offset
        elif a == b and start is not None:
            ranges.append((start, offset))
            start = None
    if start is not None:
        ranges.append((start, len(original)))
    return ranges


def check_changes_are_expected(ranges: list[tuple[int, int]], message_range: tuple[int, int]) -> None:
    """Todo byte cambiado debe caer en el gancho, el código, la fuente, el blob reubicado o su puntero."""
    allowed = [(cpu_to_offset(a), cpu_to_offset(b)) for a, b in (HOOK_RANGE, CODE_RANGE, (FONT_START, FONT_END))]
    allowed.append(message_range)
    table_offset = cpu_to_offset(TABLE_ADDRESS)
    allowed.append((table_offset, table_offset + 2))
    for start, end in ranges:
        if not any(low <= start and end <= high for low, high in allowed):
            raise PatchError(f"unexpected change at 0x{start:06X}-0x{end:06X}")


def build_probe(rom: bytes, art: dict[str, list[str]], text: str, asar: Path, scratch: Path) -> bytes:
    for low, high in (CODE_RANGE, (FONT_START, FONT_END), MESSAGE_FREE):
        region = rom[cpu_to_offset(low) : cpu_to_offset(high)]
        if region.count(0xFF) != len(region):
            raise PatchError(f"free space 0x{low:06X}-0x{high:06X} is not all 0xFF in this ROM")
    font = font_binary(art)
    blob = message_blob(text)
    if not tokenize(blob).complete:
        raise PatchError("the Latin message does not parse")
    patcher = RomPatcher(rom)
    table = read_all_tables(rom)[TABLE_ADDRESS]
    address = relocate_blob(patcher, table, MESSAGE_INDEX, blob, FreeSpace(*MESSAGE_FREE))
    patcher.verify_log_covers_changes()
    scratch.write_bytes(bytes(patcher.data))
    run_asar(asar, scratch, font)
    patched = scratch.read_bytes()
    message_start = cpu_to_offset(address)
    check_changes_are_expected(changed_ranges(rom, patched), (message_start, message_start + len(blob)))
    return patched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    parser.add_argument("--asar", default=os.environ.get("ASAR"), help="ejecutable de asar (o ASAR)")
    parser.add_argument("--font-art", required=True, help="arte de la fuente latina (ver parse_font_art)")
    parser.add_argument("--text", default="Hace trescientos años...\n¿Quién lo recordará hoy?", help="texto del mensaje")
    parser.add_argument("--out", required=True, help="ruta de la ROM de prueba (fuera del repositorio)")
    arguments = parser.parse_args(argv)
    if not arguments.rom or not arguments.asar:
        print("error: pass --rom and --asar, or set DARK_LAW_ROM and ASAR", file=sys.stderr)
        return 2
    rom = Path(arguments.rom).read_bytes()
    art = parse_font_art(Path(arguments.font_art).read_text(encoding="utf-8"))
    out = Path(arguments.out)
    patched = build_probe(rom, art, arguments.text.replace("\\n", "\n"), Path(arguments.asar), out)
    for start, end in changed_ranges(rom, patched):
        print(f"0x{start:06X}-0x{end:06X} ({end - start} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
