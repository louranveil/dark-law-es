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
TERMINATORS = frozenset({0xC7, 0xF0, 0xFF})  # el motor deja de leer el guion
FIRST_COMMAND = 0xC0
WIDE_PREFIXES = {0xFA: 0x0300, 0xFB: 0x0200, 0xFC: 0x0100, 0xFD: 0x0000}
DEAD_TERMINATORS = frozenset({0xC7, 0xFF})
MAX_DEAD_TAIL = 2  # bytes C7/FF que algunos blobs llevan detrás de su final real y que el motor nunca lee


class Evidence(Enum):
    """Cómo se conoce el número de argumentos de un comando."""

    MEASURED = "measured"  # sonda de ejecución forzada: se observó dónde lee el motor el siguiente comando o el último argumento
    CODE = "code"  # leído en el código del manejador (llamadas a los ayudantes de lectura), sin medirlo en el motor
    CORPUS = "corpus"  # solo respaldado por los datos (los blobs cierran con este valor) o con una lectura de código que lo contradice
    UNKNOWN = "unknown"  # sin evidencia suficiente; se asume 0 y se marca


M, C, K, U = Evidence.MEASURED, Evidence.CODE, Evidence.CORPUS, Evidence.UNKNOWN


@dataclass(frozen=True)
class SubCommand:
    """Un subcomando de un comando selector (``FE v``, ``D7 s``): los argumentos son los bytes que siguen al selector."""

    arguments: int
    evidence: Evidence
    leaves: bool = False  # el motor no vuelve a leer este guion después de los argumentos: un blob puede acabar ahí
    note: str = ""


# código -> (argumentos, evidencia). Ver docs/re/text-engine.md para el detalle de cada uno.
COMMAND_ARGUMENTS: dict[int, tuple[int, Evidence]] = {
    0xC0: (0, M),
    0xC1: (0, M),
    0xC2: (4, C),  # elección Sí/No: dos identificadores de mensaje de 16 bits; salta a uno de ellos
    0xC3: (0, M),
    0xC4: (0, K),
    0xC5: (0, M),
    0xC6: (0, M),
    0xC7: (0, K),
    0xC8: (1, M),
    0xC9: (1, M),
    0xCA: (0, M),
    0xCB: (1, C),
    0xCC: (0, M),
    0xD5: (2, M),
    0xD7: (1, M),  # solo el selector; el resto depende del subcomando (D7_SUBCOMMANDS)
    0xD8: (1, M),
    0xD9: (2, C),  # cambio de mapa
    0xDA: (1, C),
    0xDB: (1, C),
    0xDC: (4, M),
    0xDD: (2, M),
    0xE3: (2, M),
    0xE4: (1, M),
    0xE5: (1, M),
    0xE6: (2, C),
    0xE7: (2, M),
    0xE8: (5, C),  # salto a uno de dos mensajes: selector y dos identificadores de 16 bits
    0xE9: (1, M),
    0xEA: (1, M),
    0xEB: (1, M),
    0xEC: (2, M),  # cambio de mapa
    0xED: (0, M),
    0xEE: (2, M),
    0xEF: (1, M),
    0xF0: (0, K),
    0xF1: (0, C),
    0xF2: (5, M),
    0xF3: (2, C),  # cambio de mapa
    0xF4: (2, M),
    0xF5: (0, M),
    0xF6: (1, M),
    0xFE: (1, M),  # solo el selector; el resto depende del subcomando (FE_SUBCOMMANDS)
    0xFF: (0, K),
}
for _code in range(0xCD, 0xD5):  # CD-D4: un argumento
    COMMAND_ARGUMENTS[_code] = (1, M)
COMMAND_ARGUMENTS[0xD6] = (1, M)
for _code in range(0xDE, 0xE3):  # DE-E2: tres argumentos
    COMMAND_ARGUMENTS[_code] = (3, M)

# Comandos tras cuyos argumentos el motor no vuelve a leer este guion (continúa en otro mensaje o cambia el modo de juego).
# Un blob puede acabar justo detrás de ellos sin terminador.
LEAVING_COMMANDS = frozenset({0xC2, 0xD9, 0xE8, 0xEC, 0xF3})

# FE v. ``arguments`` cuenta los bytes tras ``v``. Los valores que el motor lee con un número fijo de bytes van sin nota.
FE_SUBCOMMANDS: dict[int, SubCommand] = {
    0x00: SubCommand(1, M),
    0x01: SubCommand(1, M),
    0x02: SubCommand(1, M),
    0x03: SubCommand(6, M),
    0x04: SubCommand(6, M),
    0x05: SubCommand(7, M),
    0x06: SubCommand(7, M),
    0x07: SubCommand(1, M),
    0x08: SubCommand(4, M),
    0x09: SubCommand(5, M),
    0x0A: SubCommand(0, C, note="manejador que solo saca un nivel de la pila de punteros; ningún blob lo usa"),
    0x0B: SubCommand(1, M),
    0x0C: SubCommand(3, M, leaves=True, note="cambio de mapa: tres argumentos, el último par se lee tras un fundido"),
    0x16: SubCommand(1, M),
    0x17: SubCommand(1, M),
    0x18: SubCommand(0, M),
    0x19: SubCommand(6, M),
    0x1A: SubCommand(0, M),
    0x1B: SubCommand(0, M),
    0x1C: SubCommand(0, M),
    0x1D: SubCommand(3, M),
    0x1E: SubCommand(3, M, note="salto condicional: ambos caminos consumen los mismos tres bytes"),
    0x1F: SubCommand(0, M),
    0x20: SubCommand(0, M),
    0x21: SubCommand(0, C, leaves=True, note="el motor no vuelve a leer el guion; ningún blob lo usa"),
    0x22: SubCommand(1, M, leaves=True),
    0x23: SubCommand(0, M),
    0x24: SubCommand(1, C),
    0x25: SubCommand(0, M),
    0x26: SubCommand(0, C),
    0x27: SubCommand(0, M),
    0x28: SubCommand(3, M),
    0x29: SubCommand(2, M),
    0x2A: SubCommand(2, M),
    0x2B: SubCommand(2, M),
    0x2C: SubCommand(3, M),
    0x2D: SubCommand(6, K, note="código: 7 argumentos con el miembro del grupo presente (medido con la sonda) y 3 sin él; el único blob que lo usa cierra con 6"),
    0x2E: SubCommand(6, M),
    0x2F: SubCommand(0, M),
    0x30: SubCommand(0, M),
    0x31: SubCommand(0, C),
    0x32: SubCommand(1, C, leaves=True, note="espera y saca el nivel de la pila: cierra el guion"),
    0x33: SubCommand(2, M),
    0x34: SubCommand(0, U, note="el manejador pasa a un estado de espera que quizá lea más; ningún blob lo usa"),
    0x35: SubCommand(0, M),
    0x36: SubCommand(0, M),
    0x37: SubCommand(6, C),
    0x38: SubCommand(0, M),
    0x39: SubCommand(0, C),
    0x3A: SubCommand(0, C),
    0x3B: SubCommand(0, C, note="el manejador cede el control al motor; el blob que lo usa se decide por el corpus"),
    0x3C: SubCommand(6, M, note="salto condicional; ningún blob lo usa"),
    0x3D: SubCommand(0, M),
    0x3E: SubCommand(0, M),
    0x3F: SubCommand(6, M),
    0x40: SubCommand(8, C, leaves=True, note="salta a uno de cuatro mensajes (identificadores de 16 bits)"),
    0x41: SubCommand(0, M),
    0x42: SubCommand(2, M),
    0x43: SubCommand(4, M),
    0x44: SubCommand(8, C, leaves=True, note="como FE 40"),
    0x45: SubCommand(8, C, leaves=True, note="como FE 40"),
    0x46: SubCommand(0, C, leaves=True),
    0x47: SubCommand(0, M),
    0x48: SubCommand(1, M),
    0x49: SubCommand(0, C),
}
# Selector fuera de la tabla de manejadores (``FE v`` con v >= 0x4A). Solo ``FE F4`` aparece en los datos (9 veces, siempre con dos
# argumentos detrás: ``FE F4 FE 02``, ``FE F4 FD 02``...) y la sonda confirmó que el motor lo ejecuta como ``F4`` con sus 2 argumentos.
FE_SUBCOMMANDS[0xF4] = SubCommand(2, M, note="fuera de la tabla de manejadores; el motor lo ejecuta como F4 (dos argumentos)")
for _selector in range(0x0D, 0x16):  # copian una cadena al búfer de texto y la ejecutan: sin argumentos
    FE_SUBCOMMANDS[_selector] = SubCommand(0, M)

# D7 s: la tabla de manejadores está en $D1:4EF1 (157 entradas). Argumentos tras el selector leídos en el código de cada manejador.
D7_SUBCOMMANDS: dict[int, SubCommand] = {selector: SubCommand(0, C) for selector in range(0x9D)}
D7_SUBCOMMANDS.update(
    {
        0x19: SubCommand(5, C),
        0x48: SubCommand(2, C),
        0x6A: SubCommand(6, C),
        0x6B: SubCommand(1, C),
        0x8C: SubCommand(1, C),
        0x92: SubCommand(1, C),
    }
)
# Manejadores de varias fases (``JMP (tabla,x)`` sobre un estado propio): en qué fase leen argumentos no se ha seguido.
# Los blobs del corpus que los usan cierran con 0 argumentos, así que solo lo respalda el corpus.
for _selector in (0x24, 0x28, 0x3E, 0x3F, 0x44, 0x45, 0x46, 0x47, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x5D, 0x76):
    D7_SUBCOMMANDS[_selector] = SubCommand(0, K, note="manejador de varias fases: sin argumentos según el corpus; el código no se siguió entero")

SELECTOR_COMMANDS: dict[int, dict[int, SubCommand]] = {0xFE: FE_SUBCOMMANDS, 0xD7: D7_SUBCOMMANDS}
UNKNOWN_SUBCOMMAND = SubCommand(0, U, note="selector fuera de la tabla de manejadores")


def subcommand(code: int, selector: int) -> SubCommand:
    """Subcomando ``selector`` del comando selector ``code`` (``FE`` o ``D7``)."""
    return SELECTOR_COMMANDS[code].get(selector, UNKNOWN_SUBCOMMAND)


def command_arguments(code: int) -> tuple[int, Evidence]:
    """Argumentos y evidencia de ``code``.

    ``code`` es un comando (``C0``-``FF``) o, para un subcomando, ``comando << 8 | selector`` (por ejemplo ``0xFE2D``) y
    entonces los argumentos son los que siguen al selector. Para ``FE`` y ``D7`` a secas solo cuenta el selector (1).
    Los códigos sin entrada se asumen de 0 argumentos y evidencia desconocida.
    """
    if code > 0xFF:
        sub = subcommand(code >> 8, code & 0xFF)
        return sub.arguments, sub.evidence
    return COMMAND_ARGUMENTS.get(code, (0, U))


@dataclass(frozen=True)
class CommandInfo:
    """El comando que empieza en una posición: su tamaño total, su clave, la evidencia de su longitud y si cierra el guion."""

    size: int | None  # None si falta el byte selector
    key: int  # ``code`` o ``code << 8 | selector``
    evidence: Evidence
    ends: bool  # terminador o comando tras el que el motor no vuelve a leer el guion


def command_info(data: bytes, position: int) -> CommandInfo:
    """Describe el comando de ``data[position]`` (``C0``-``FF`` y no un prefijo de glifo)."""
    code = data[position]
    if code in SELECTOR_COMMANDS:
        if position + 1 >= len(data):
            return CommandInfo(None, code, M, False)
        selector = data[position + 1]
        sub = subcommand(code, selector)
        return CommandInfo(2 + sub.arguments, code << 8 | selector, sub.evidence, sub.leaves)
    arguments, evidence = command_arguments(code)
    return CommandInfo(1 + arguments, code, evidence, code in TERMINATORS or code in LEAVING_COMMANDS)


@dataclass(frozen=True)
class Token:
    """Un elemento de un blob. ``kind`` es ``glyph``, ``wide`` (prefijo FA-FD y su byte) o ``command``."""

    kind: str
    raw: bytes

    @property
    def code(self) -> int:
        return self.raw[0]

    @property
    def key(self) -> int:
        """``code`` o, en un comando selector, ``code << 8 | selector``."""
        if self.kind == "command" and self.raw[0] in SELECTOR_COMMANDS and len(self.raw) > 1:
            return self.raw[0] << 8 | self.raw[1]
        return self.raw[0]


@dataclass(frozen=True)
class ParsedBlob:
    tokens: tuple[Token, ...]
    complete: bool  # termina en un terminador o en un comando de salida dentro de los bytes dados
    unresolved: frozenset[int]  # claves (``code`` o ``code << 8 | selector``) de los comandos usados cuya longitud no está medida

    @property
    def length(self) -> int:
        return sum(len(token.raw) for token in self.tokens)


def tokenize(data: bytes) -> ParsedBlob:
    """Divide ``data`` en tokens hasta el primer terminador o comando de salida (inclusive).

    Si los bytes se acaban antes de un final, o un prefijo o los argumentos de un
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
            info = command_info(data, position)
            if info.evidence is not Evidence.MEASURED:
                unresolved.add(info.key)
            if info.size is None or position + info.size > len(data):
                return ParsedBlob(tuple(tokens), False, frozenset(unresolved))
            tokens.append(Token("command", data[position : position + info.size]))
            position += info.size
            if info.ends:
                return ParsedBlob(tuple(tokens), True, frozenset(unresolved))
    return ParsedBlob(tuple(tokens), False, frozenset(unresolved))


def absorb_dead_tail(parsed: ParsedBlob, tail: bytes) -> ParsedBlob:
    """Añade a un blob completo los bytes ``tail`` que lo siguen si son solo ``C7``/``FF`` (como mucho dos).

    Algunos blobs llevan uno o dos de estos bytes detrás de su final real (por ejemplo ``EC 0D 00 FF FF``);
    el motor nunca los lee, pero pertenecen al hueco del blob y hay que conservarlos al reconstruir.
    """
    if not parsed.complete or not 0 < len(tail) <= MAX_DEAD_TAIL or any(byte not in DEAD_TERMINATORS for byte in tail):
        return parsed
    return ParsedBlob(parsed.tokens + tuple(Token("command", bytes([byte])) for byte in tail), True, parsed.unresolved)


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
        if following is not None and parsed.complete:
            parsed = absorb_dead_tail(parsed, data[parsed.length:])
        report = BlobReport(table.address, table.entries.index(start), table.bank << 16 | start, parsed, following)
        if not parsed.complete:
            report.problems.append("no terminator before the next blob")
        elif following is not None and parsed.length != following - start:
            report.problems.append(f"ends {following - start - parsed.length} bytes before the next blob")
        if parsed.unresolved:
            report.problems.append("uses commands with unmeasured argument counts")
        reports.append(report)
    return reports
