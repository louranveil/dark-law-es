#!/usr/bin/env python3
"""Comprueba que los guiones de la ROM se pueden leer y volver a escribir sin cambiar un byte.

Hace tres cosas sobre la ROM original: (1) recorre el directorio, las tablas y los blobs;
(2) cuenta cuántos blobs cierran exactamente donde empieza el siguiente (cobertura) y
cuáles necesitan revisión; (3) reconstruye la ROM escribiendo cada blob tokenizado en su
dirección original, y exige que el resultado sea idéntico byte a byte (construcción
identidad).

La ROM se recibe con --rom o con la variable DARK_LAW_ROM.

Códigos de salida: 0 todo correcto, 1 la construcción identidad o algún blob falló,
2 uso o configuración incorrectos.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from script_builder import RomPatcher
from script_format import CALLED_SCRIPTS_TABLE, MessageTable, check_table, cpu_to_offset, encode, read_all_tables, read_areas

EXPECTED_ROM_SIZE = 4194304


@dataclass
class ScriptReport:
    tables: int
    blobs: int
    exact: int  # cierran justo antes del siguiente blob
    needs_review: int
    identity_ok: bool
    problems: Counter
    by_role: dict[str, Counter]


def table_roles(rom: bytes) -> dict[int, str]:
    names = ("messages", "events", "global")
    roles: dict[int, str] = {CALLED_SCRIPTS_TABLE: "called scripts"}
    for area in read_areas(rom):
        for slot, address in enumerate(area.table_addresses):
            roles.setdefault(address, names[slot])
    return roles


def identity_build(rom: bytes, tables: dict[int, MessageTable]) -> bytes:
    """Escribe cada blob que cierra exactamente en su dirección original; el resultado debe igualar a ``rom``."""
    patcher = RomPatcher(rom)
    written: set[int] = set()
    for table in tables.values():
        for report in check_table(rom, table):
            if [p for p in report.problems if "unmeasured" not in p] or report.address in written:
                continue
            written.add(report.address)
            offset = cpu_to_offset(report.address)
            patcher.write(offset, encode(report.parsed.tokens), expected=rom[offset : offset + report.parsed.length], reason="identity")
    return bytes(patcher.data)


def analyze(rom: bytes) -> ScriptReport:
    tables = read_all_tables(rom)
    roles = table_roles(rom)
    problems: Counter = Counter()
    by_role: dict[str, Counter] = {}
    blobs = exact = 0
    for address, table in tables.items():
        counter = by_role.setdefault(roles[address], Counter())
        for report in check_table(rom, table):
            blobs += 1
            real = [p for p in report.problems if "unmeasured" not in p]
            if real:
                problems["terminator before the end of the gap" if real[0].startswith("ends") else "no terminator"] += 1
                counter["review"] += 1
            else:
                exact += 1
                counter["exact"] += 1
    identical = identity_build(rom, tables) == rom
    return ScriptReport(len(tables), blobs, exact, blobs - exact, identical, problems, by_role)


def format_report(report: ScriptReport) -> str:
    lines = [
        f"tables: {report.tables}",
        f"blobs: {report.blobs}, closing exactly before the next blob: {report.exact}, needing review: {report.needs_review}",
    ]
    for role, counter in sorted(report.by_role.items()):
        lines.append(f"  {role}: {counter['exact']} exact, {counter['review']} review")
    for problem, count in report.problems.most_common():
        lines.append(f"  review reason: {problem}: {count}")
    lines.append(f"identity build identical to the original: {report.identity_ok}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    arguments = parser.parse_args(argv)
    if not arguments.rom:
        print("error: pass --rom or set DARK_LAW_ROM", file=sys.stderr)
        return 2
    rom = Path(arguments.rom).read_bytes()
    if len(rom) != EXPECTED_ROM_SIZE:
        print(f"error: expected {EXPECTED_ROM_SIZE} bytes, got {len(rom)}", file=sys.stderr)
        return 2
    print(f"ROM SHA-1 {hashlib.sha1(rom).hexdigest().upper()}")
    report = analyze(rom)
    print(format_report(report))
    return 0 if report.identity_ok else 1


if __name__ == "__main__":
    sys.exit(main())
