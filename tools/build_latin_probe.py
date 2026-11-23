#!/usr/bin/env python3
"""Construye una ROM de prueba que muestra texto latino de 8x16, dos letras por celda.

Es el spike de la fuente en español (docs/re/latin-font-spike.md): instala el gancho de
asm/latin_pair_hook.asm con asar, escribe una fuente latina en el relleno del banco $D2 y
sustituye un mensaje (reubicado en el relleno de su banco) por texto que usa la ficha
``F9 a b``. Hay dos escenarios: ``intro`` (mensaje 0 del intro, ventana de tipo 1) y
``field`` (primer mensaje del campo, ventana de tipo 2). La ROM resultante solo sirve para
mirarla en el emulador y se escribe fuera del repositorio.

La fuente es la del proyecto (assets/font/latin-8x16.txt, ver docs/fonts/decision.md) con
su contorno; con --font-art se sustituye por otro arte de texto (ver ``parse_font_art``),
por ejemplo para comparar tipografías candidatas.

Códigos de salida: 0 ROM escrita, 2 uso o configuración incorrectos.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import build_custom_font
from script_builder import FreeSpace, PatchError, RomPatcher, relocate_blob
from script_format import cpu_to_offset, read_all_tables, tokenize

ASM_PATH = Path(__file__).resolve().parents[1] / "asm" / "latin_pair_hook.asm"
HOOK_RANGES = (
    (0xD14587, 0xD1458B),  # bucle 1: CMP #$E5 / BEQ, se sustituye por un JML
    (0xD1477D, 0xD14781),  # bucle 2: igual
)
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


@dataclass(frozen=True)
class Scenario:
    """Qué mensaje se sustituye y con qué comandos de cabecera y cola se conserva su estructura."""

    table_address: int
    index: int
    free: tuple[int, int]  # relleno 0xFF al final del banco de la tabla
    head: bytes
    tail: bytes
    text: str


SCENARIOS = {
    # Mensaje 0 del intro ("300年前・・・"): abre con C0; la cola es espera, apagado de pantalla y fin.
    "intro": Scenario(
        0xE2EE73, 0, (0xE2F8A6, 0xE30000), bytes([0xC0]), bytes.fromhex("c8 80 c8 e0 c5 c8 28 ff"),
        "Hace trescientos años...\n¿Quién lo recordará hoy?",
    ),
    # Primer mensaje del campo, "古い神殿のようです・・・": abre con C1, termina con CD 00 y C7.
    "field": Scenario(
        0xE7362B, 0, (0xE7FC81, 0xE80000), bytes([0xC1]), bytes.fromhex("cd 00 c7"),
        "Parece un templo muy antiguo...\nNo hay nadie por aquí.",
    ),
}


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


PROJECT_FONT_SOURCE = Path(__file__).resolve().parents[1] / "assets" / "font" / "latin-8x16.txt"


def project_font_art(source: Path = PROJECT_FONT_SOURCE) -> dict[str, list[str]]:
    """Arte de la fuente del proyecto: la fuente de tinta con el contorno del juego (valor 3)."""
    glyphs = build_custom_font.parse_source(source.read_text(encoding="utf-8"))
    return build_custom_font.build_art(glyphs, with_outline=True)


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


def message_blob(scenario: Scenario, text: str | None = None) -> bytes:
    return scenario.head + encode_latin(scenario.text if text is None else text) + scenario.tail


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


def allowed_regions(message_range: tuple[int, int], pointer_offset: int) -> list[tuple[str, int, int]]:
    """Regiones de la ROM que la prueba puede tocar, como ``(nombre, desde, hasta)`` en offsets de fichero."""
    regions = [(f"hook {n}", cpu_to_offset(a), cpu_to_offset(b)) for n, (a, b) in enumerate(HOOK_RANGES, start=1)]
    regions.append(("hook code", cpu_to_offset(CODE_RANGE[0]), cpu_to_offset(CODE_RANGE[1])))
    regions.append(("font", cpu_to_offset(FONT_START), cpu_to_offset(FONT_END)))
    regions.append(("message blob", *message_range))
    regions.append(("table pointer", pointer_offset, pointer_offset + 2))
    return regions


def check_changes_are_expected(ranges: list[tuple[int, int]], message_range: tuple[int, int], pointer_offset: int) -> None:
    """Todo byte cambiado debe caer en los ganchos, el código, la fuente, el blob reubicado o su puntero."""
    regions = allowed_regions(message_range, pointer_offset)
    for start, end in ranges:
        if not any(low <= start and end <= high for _, low, high in regions):
            raise PatchError(f"unexpected change at 0x{start:06X}-0x{end:06X}")


def summarize_changes(ranges: list[tuple[int, int]], message_range: tuple[int, int], pointer_offset: int) -> dict[str, int]:
    """Bytes cambiados por región, en el orden de ``allowed_regions``."""
    totals = {name: 0 for name, _, _ in allowed_regions(message_range, pointer_offset)}
    for start, end in ranges:
        for name, low, high in allowed_regions(message_range, pointer_offset):
            if low <= start and end <= high:
                totals[name] += end - start
                break
    return totals


def build_probe(rom: bytes, art: dict[str, list[str]], scenario: Scenario, text: str | None, asar: Path, scratch: Path) -> bytes:
    for low, high in (CODE_RANGE, (FONT_START, FONT_END), scenario.free):
        region = rom[cpu_to_offset(low) : cpu_to_offset(high)]
        if region.count(0xFF) != len(region):
            raise PatchError(f"free space 0x{low:06X}-0x{high:06X} is not all 0xFF in this ROM")
    font = font_binary(art)
    blob = message_blob(scenario, text)
    if not tokenize(blob).complete:
        raise PatchError("the Latin message does not parse")
    patcher = RomPatcher(rom)
    table = read_all_tables(rom)[scenario.table_address]
    address = relocate_blob(patcher, table, scenario.index, blob, FreeSpace(*scenario.free))
    patcher.verify_log_covers_changes()
    scratch.write_bytes(bytes(patcher.data))
    run_asar(asar, scratch, font)
    patched = scratch.read_bytes()
    message_start = cpu_to_offset(address)
    pointer_offset = cpu_to_offset(scenario.table_address) + 2 * scenario.index
    ranges = changed_ranges(rom, patched)
    check_changes_are_expected(ranges, (message_start, message_start + len(blob)), pointer_offset)
    return patched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    parser.add_argument("--asar", default=os.environ.get("ASAR"), help="ejecutable de asar (o ASAR)")
    parser.add_argument("--font-art", help="arte de otra fuente latina (ver parse_font_art); por defecto la del proyecto")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="intro", help="mensaje que se sustituye")
    parser.add_argument("--text", help="texto del mensaje (por defecto el del escenario; \\n separa las líneas)")
    parser.add_argument("--out", required=True, help="ruta de la ROM de prueba (fuera del repositorio)")
    arguments = parser.parse_args(argv)
    if not arguments.rom or not arguments.asar:
        print("error: pass --rom and --asar, or set DARK_LAW_ROM and ASAR", file=sys.stderr)
        return 2
    rom = Path(arguments.rom).read_bytes()
    if arguments.font_art:
        art = parse_font_art(Path(arguments.font_art).read_text(encoding="utf-8"))
    else:
        art = project_font_art()
    out = Path(arguments.out)
    text = None if arguments.text is None else arguments.text.replace("\\n", "\n")
    patched = build_probe(rom, art, SCENARIOS[arguments.scenario], text, Path(arguments.asar), out)
    scenario = SCENARIOS[arguments.scenario]
    pointer_offset = cpu_to_offset(scenario.table_address) + 2 * scenario.index
    new_start = cpu_to_offset(scenario.free[0])
    new_range = (new_start, new_start + len(message_blob(scenario, text)))
    for region, total in summarize_changes(changed_ranges(rom, patched), new_range, pointer_offset).items():
        print(f"{region:14s} {total:5d} bytes cambiados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
