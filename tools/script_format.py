"""Formato de los guiones de Dark Law: tablas de mensajes, blobs y tokens.

Todo lo que se sabe del formato está en docs/re/text-engine.md; este módulo solo lo
implementa. La ROM se recibe como ``bytes`` (sin cabecera de copiador); nunca se lee
de una ruta fija.

Estructura (HiROM, direcciones de CPU ``$BB:AAAA``):

* ``$EF:0000``: directorio de 32 áreas, 3 bytes (puntero largo) por área, que apunta
  a un registro de 9 bytes.
* Registro: tres punteros largos a tablas de punteros de 16 bits (relativos al banco
  de la tabla). La primera sirve a los identificadores ``< 0x200`` (mensajes), la
  segunda a ``0x200``-``0x3FF`` (guiones de evento) y la tercera a ``>= 0x400``
  (tabla global compartida por todas las áreas).
* Cada entrada de una tabla apunta a un blob: una secuencia de tokens que termina en
  un comando terminador (``C7`` o ``FF``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import Enum

DIRECTORY_ADDRESS = 0xEF0000
CALLED_SCRIPTS_TABLE = 0xEE0000  # comando D8: "llamar al script N", independiente de las áreas
AREA_COUNT = 32
USED_AREA_COUNT = 16  # las áreas 16-31 apuntan a $E5:0000, que no es un registro
RECORD_SIZE = 9
TERMINATORS = frozenset({0xC2, 0xC7, 0xF0, 0xFF})
FIRST_COMMAND = 0xC0
WIDE_PREFIXES = {0xFA: 0x0300, 0xFB: 0x0200, 0xFC: 0x0100, 0xFD: 0x0000}


class Evidence(Enum):
    """Cómo se conoce el número de argumentos de un comando."""

    MEASURED = "measured"  # sonda de ejecución forzada: se observó dónde lee el motor el siguiente comando
    CORPUS = "corpus"  # solo respaldado por patrones de los datos (no observado en el motor)
    UNKNOWN = "unknown"  # sin evidencia suficiente; se asume 0 y se marca


# código -> (argumentos, evidencia). Ver docs/re/text-engine.md para el detalle de cada uno.
COMMAND_ARGUMENTS: dict[int, tuple[int, Evidence]] = {
    0xC0: (0, Evidence.MEASURED),
    0xC1: (0, Evidence.MEASURED),
    0xC2: (4, Evidence.CORPUS),
    0xC3: (0, Evidence.MEASURED),
    0xC4: (0, Evidence.CORPUS),
    0xC5: (0, Evidence.MEASURED),
    0xC6: (0, Evidence.MEASURED),
    0xC7: (0, Evidence.CORPUS),
    0xC8: (1, Evidence.MEASURED),
    0xC9: (1, Evidence.MEASURED),
    0xCA: (0, Evidence.MEASURED),
    0xCB: (1, Evidence.UNKNOWN),
    0xCC: (0, Evidence.MEASURED),
    0xD5: (2, Evidence.MEASURED),
    0xD8: (1, Evidence.MEASURED),
    0xD9: (2, Evidence.CORPUS),
    0xDA: (1, Evidence.UNKNOWN),
    0xDB: (1, Evidence.UNKNOWN),
    0xDC: (4, Evidence.MEASURED),
    0xDD: (2, Evidence.MEASURED),
    0xE3: (2, Evidence.MEASURED),
    0xE4: (1, Evidence.MEASURED),
    0xE5: (1, Evidence.MEASURED),
    0xE6: (2, Evidence.UNKNOWN),
    0xE7: (2, Evidence.MEASURED),
    0xE8: (1, Evidence.UNKNOWN),
    0xE9: (1, Evidence.MEASURED),
    0xEA: (1, Evidence.MEASURED),
    0xEB: (1, Evidence.MEASURED),
    0xEC: (0, Evidence.UNKNOWN),
    0xED: (0, Evidence.UNKNOWN),
    0xEE: (2, Evidence.MEASURED),
    0xEF: (1, Evidence.MEASURED),
    0xF0: (0, Evidence.CORPUS),
    0xF1: (0, Evidence.CORPUS),
    0xF2: (5, Evidence.MEASURED),
    0xF3: (2, Evidence.CORPUS),
    0xF4: (2, Evidence.MEASURED),
    0xF5: (0, Evidence.MEASURED),
    0xF6: (1, Evidence.MEASURED),
    0xFE: (2, Evidence.MEASURED),
    0xFF: (0, Evidence.CORPUS),
}
for _code in range(0xCD, 0xD5):  # CD-D4: un argumento
    COMMAND_ARGUMENTS[_code] = (1, Evidence.MEASURED)
for _code in (0xD6, 0xD7):
    COMMAND_ARGUMENTS[_code] = (1, Evidence.MEASURED)
for _code in range(0xDE, 0xE3):  # DE-E2: tres argumentos
    COMMAND_ARGUMENTS[_code] = (3, Evidence.MEASURED)


def command_arguments(code: int) -> tuple[int, Evidence]:
    """Argumentos y evidencia del comando ``code``; los códigos sin entrada se asumen de 0 argumentos."""
    return COMMAND_ARGUMENTS.get(code, (0, Evidence.UNKNOWN))


@dataclass(frozen=True)
class Token:
    """Un elemento de un blob. ``kind`` es ``glyph``, ``wide`` (prefijo FA-FD y su byte) o ``command``."""

    kind: str
    raw: bytes

    @property
    def code(self) -> int:
        return self.raw[0]


@dataclass(frozen=True)
class ParsedBlob:
    tokens: tuple[Token, ...]
    complete: bool  # termina en un terminador dentro de los bytes dados
    unresolved: frozenset[int]  # comandos usados cuya aridad no está medida

    @property
    def length(self) -> int:
        return sum(len(token.raw) for token in self.tokens)


def tokenize(data: bytes) -> ParsedBlob:
    """Divide ``data`` en tokens hasta el primer terminador (inclusive).

    Si los bytes se acaban antes de un terminador, o un prefijo o los argumentos de un
    comando quedan cortados, ``complete`` es falso y el último token es el que no cupo.
    """
    tokens: list[Token] = []
    unresolved: set[int] = set()
    position = 0
    while position < len(data):
        code = data[position]
        if code < FIRST_COMMAND:
            tokens.append(Token("glyph", data[position : position + 1]))
            position += 1
        elif code in WIDE_PREFIXES:
            if position + 2 > len(data):
                return ParsedBlob(tuple(tokens), False, frozenset(unresolved))
            tokens.append(Token("wide", data[position : position + 2]))
            position += 2
        else:
            arguments, evidence = command_arguments(code)
            if evidence is not Evidence.MEASURED:
                unresolved.add(code)
            size = 1 + arguments
            if position + size > len(data):
                return ParsedBlob(tuple(tokens), False, frozenset(unresolved))
            tokens.append(Token("command", data[position : position + size]))
            position += size
            if code in TERMINATORS:
                return ParsedBlob(tuple(tokens), True, frozenset(unresolved))
    return ParsedBlob(tuple(tokens), False, frozenset(unresolved))


def encode(tokens: tuple[Token, ...] | list[Token]) -> bytes:
    return b"".join(token.raw for token in tokens)


def cpu_to_offset(address: int) -> int:
    """Dirección de CPU HiROM (bancos $C0-$FF) a desplazamiento de fichero."""
    return ((address >> 16) & 0x3F) << 16 | (address & 0xFFFF)


def read_bytes(rom: bytes, address: int, length: int) -> bytes:
    offset = cpu_to_offset(address)
    if offset + length > len(rom):
        raise ValueError(f"read past the end of the ROM at ${address:06X}")
    return rom[offset : offset + length]


def read_long(rom: bytes, address: int) -> int:
    low, middle, bank = read_bytes(rom, address, 3)
    return low | middle << 8 | bank << 16


@dataclass(frozen=True)
class MessageTable:
    """Tabla de punteros de 16 bits relativos a su banco; ``entries`` son las direcciones dentro del banco."""

    address: int  # dirección larga de la tabla
    entries: tuple[int, ...]

    @property
    def bank(self) -> int:
        return self.address >> 16

    def blob_address(self, index: int) -> int:
        return self.bank << 16 | self.entries[index]


@dataclass
class Area:
    index: int
    record: int
    table_addresses: tuple[int, int, int]


def read_areas(rom: bytes) -> list[Area]:
    areas = []
    for index in range(USED_AREA_COUNT):
        record = read_long(rom, DIRECTORY_ADDRESS + 3 * index)
        raw = read_bytes(rom, record, RECORD_SIZE)
        tables = tuple(raw[i] | raw[i + 1] << 8 | raw[i + 2] << 16 for i in (0, 3, 6))
        areas.append(Area(index, record, tables))  # type: ignore[arg-type]
    return areas


def read_table(rom: bytes, address: int, limit: int = 4096) -> MessageTable:
    """Lee una tabla de punteros. Termina donde empieza el primer blob (el menor puntero por encima de la tabla)."""
    base = address & 0xFFFF
    bank = address & 0xFF0000
    entries: list[int] = []
    lowest = 0x10000
    while base + 2 * len(entries) < lowest and len(entries) < limit:
        (word,) = struct.unpack("<H", read_bytes(rom, bank | base + 2 * len(entries), 2))
        entries.append(word)
        if word >= base + 2:
            lowest = min(lowest, word)
    return MessageTable(address, tuple(entries))


def read_all_tables(rom: bytes) -> dict[int, MessageTable]:
    """Todas las tablas distintas: las de los registros de área y la de scripts llamables, por dirección de tabla."""
    tables: dict[int, MessageTable] = {CALLED_SCRIPTS_TABLE: read_table(rom, CALLED_SCRIPTS_TABLE)}
    for area in read_areas(rom):
        for address in area.table_addresses:
            if address not in tables:
                tables[address] = read_table(rom, address)
    return tables


@dataclass
class BlobReport:
    table: int
    index: int
    address: int
    parsed: ParsedBlob
    next_start: int | None  # inicio del siguiente blob de la misma tabla (por encima de este)
    problems: list[str] = field(default_factory=list)


def check_table(rom: bytes, table: MessageTable) -> list[BlobReport]:
    """Tokeniza cada blob distinto de la tabla y comprueba que cierra antes del siguiente."""
    starts = sorted(set(table.entries))
    reports = []
    for position, start in enumerate(starts):
        following = starts[position + 1] if position + 1 < len(starts) else None
        window = 0x10000 - start if following is None else following - start
        data = read_bytes(rom, table.bank << 16 | start, min(window, 0x2000))
        parsed = tokenize(data)
        report = BlobReport(table.address, table.entries.index(start), table.bank << 16 | start, parsed, following)
        if not parsed.complete:
            report.problems.append("no terminator before the next blob")
        elif following is not None and parsed.length != following - start:
            report.problems.append(f"ends {following - start - parsed.length} bytes before the next blob")
        if parsed.unresolved:
            report.problems.append("uses commands with unmeasured argument counts")
        reports.append(report)
    return reports
