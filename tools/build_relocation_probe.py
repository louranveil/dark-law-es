#!/usr/bin/env python3
"""Construye una ROM de prueba que alarga el primer mensaje del intro y lo reubica.

Es la prueba de reinserción de la primera etapa: toma el mensaje 0 de la tabla
$E2:EE73 (el texto "300年前・・・" del intro), le añade tres puntos medios, lo escribe en
el hueco de relleno $E2:F8A6 y repunta la entrada de la tabla. Si el motor lee el blob
nuevo, el intro muestra seis puntos en vez de tres; el resto del juego no cambia.

No es una traducción ni un parche para distribuir: la ROM resultante solo sirve para
comprobar en el emulador que la reubicación funciona. Se escribe fuera del repositorio.

Códigos de salida: 0 ROM escrita, 2 uso o configuración incorrectos.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from script_builder import FreeSpace, PatchError, RomPatcher, relocate_blob
from script_format import (
    MessageTable,
    Token,
    check_table,
    cpu_to_offset,
    encode,
    read_all_tables,
    tokenize,
)

TABLE_ADDRESS = 0xE2EE73
MESSAGE_INDEX = 0
FREE_START, FREE_END = 0xE2F8A6, 0xE30000  # relleno 0xFF hasta el final del banco
MIDDLE_DOT = 0x9E  # glifo "・" de la página de un byte
EXTRA_DOTS = 3


def lengthened_blob(rom: bytes, table: MessageTable, index: int) -> bytes:
    """El blob original con ``EXTRA_DOTS`` puntos medios más, justo antes de su primer ``C8``."""
    report = next(r for r in check_table(rom, table) if r.address == table.blob_address(index))
    tokens = list(report.parsed.tokens)
    wait = next(i for i, token in enumerate(tokens) if token.kind == "command" and token.code == 0xC8)
    extra = [Token("glyph", bytes([MIDDLE_DOT]))] * EXTRA_DOTS
    return encode(tokens[:wait] + extra + tokens[wait:])


def build_probe(rom: bytes) -> tuple[bytes, RomPatcher]:
    table = read_all_tables(rom)[TABLE_ADDRESS]
    free = rom[cpu_to_offset(FREE_START) : cpu_to_offset(FREE_END)]
    if free.count(0xFF) != len(free):
        raise PatchError("the free-space candidate is not all 0xFF in this ROM")
    new_blob = lengthened_blob(rom, table, MESSAGE_INDEX)
    if not tokenize(new_blob).complete:
        raise PatchError("the lengthened blob does not parse")
    patcher = RomPatcher(rom)
    relocate_blob(patcher, table, MESSAGE_INDEX, new_blob, FreeSpace(FREE_START, FREE_END))
    patcher.verify_log_covers_changes()
    return bytes(patcher.data), patcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    parser.add_argument("--out", required=True, help="ruta de la ROM de prueba (fuera del repositorio)")
    arguments = parser.parse_args(argv)
    if not arguments.rom:
        print("error: pass --rom or set DARK_LAW_ROM", file=sys.stderr)
        return 2
    rom = Path(arguments.rom).read_bytes()
    patched, patcher = build_probe(rom)
    Path(arguments.out).write_bytes(patched)
    for record in patcher.log:
        print(f"0x{record.offset:06X} {len(record.new):4d} bytes  {record.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
