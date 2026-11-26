#!/usr/bin/env python3
"""Construye la ROM de marcadores (etapa 3 del pipeline, docs/specs/translation-pipeline.md).

Cada tramo de texto de las entradas ``ok`` del extractor se sustituye por un marcador legible con el
identificador de la entrada, escrito con la ficha latina ``F9 a b`` del gancho (asm/latin_pair_hook.asm) y la
fuente de 115 letras. Por ejemplo, el tramo 1 del blob ``E2:EE93`` se lee ``E2EE93.1``. El esqueleto (los
comandos) no se toca. Además de la ROM se escribe un mapa (JSON) con la dirección de cada tramo, que usa
``tools/tour_messages.py`` para saber desde la RAM qué marcador se ha alcanzado.

Colocación, por entrada:

* **En el sitio** (por defecto): el marcador de cada tramo nunca ocupa más bytes que el texto original, así que
  el blob nunca crece. Se escribe en su sitio y el sobrante se rellena con ``FF`` (detrás del terminador nada
  lo lee). Si el tramo es demasiado corto para el marcador completo se usa uno más corto (8, 6, 4 o 2 letras;
  el mapa siempre da la identidad exacta) y, si no caben ni dos letras (menos de 3 bytes), el tramo se deja
  tal cual y se anota como sin marcar.
* **Regla** (``--ruler ID``): el tramo se rellena con una regla de dígitos hasta ``--ruler-letters`` letras, para
  medir cuántas celdas admite la ventana. El blob crece, así que se reubica en el hueco libre verificado de su
  banco y se repuntan todas sus ranuras. Solo hay huecos verificados en ``VERIFIED_FREE``; si no cabe, falla.

Por defecto se hace el corte vertical: las tablas ``$E2:EE73`` (mensajes del intro) y ``$E7:362B`` (mensajes del
campo). Con ``--all`` se marcan todas las entradas ``ok`` de mensajes. Toda escritura pasa por ``RomPatcher``;
tras instalar el gancho con asar, cualquier byte cambiado debe estar en el registro o en las regiones del
gancho, del código o de la fuente, y si no es así falla. La ROM se escribe fuera del repositorio.

Uso::

    python tools/build_marker_rom.py --rom <original.sfc> --asar <asar.exe> --table tbl/original.json \\
        --out <marker.sfc> [--all] [--ruler E2:EE93 --ruler E7:372B]

Con ``--map-only`` solo se escribe el mapa de los tramos de la ROM original (para repetir el recorrido sobre el
juego sin tocar y comparar). Códigos de salida: 0 ROM y mapa escritos, 1 la construcción falló, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import build_latin_probe as probe
import extract_script as ex
import glyph_table as gt
import script_format as sf
from script_builder import FreeSpace, PatchError, RomPatcher

REPO = Path(__file__).resolve().parents[1]
MAP_FORMAT = 1
SLICE_TABLES = (0xE2EE73, 0xE7362B)  # mensajes del intro y del campo
FILLER = 0xFF
# Huecos de relleno 0xFF que ya se usaron en las ROM de prueba y se comprobaron enteros a 0xFF (docs/re/text-engine.md,
# "Free Space", y docs/re/latin-font-spike.md): final de cada banco de texto. Que nada más los use no está verificado.
VERIFIED_FREE = {
    0xE2: (0xE2F8A6, 0xE30000),
    0xE7: (0xE7FC81, 0xE80000),
}
RULER_DEFAULT_LETTERS = 80  # 40 celdas: más que las 24 de la ventana 1 y que las 32 de la ventana 2, para ver que el contador se satura
BYTES_PER_PAIR = 3
IGNORED_FOR_SKELETON = frozenset({probe.PAIR_TOKEN, probe.LINE_BREAK, ex.INDENT})


def format_address(address: int) -> str:
    return f"{address >> 16:02X}:{address & 0xFFFF:04X}"


def parse_entry_id(text: str) -> int:
    bank, _, offset = text.partition(":")
    return int(bank, 16) << 16 | int(offset, 16)


def marker_candidates(entry_id: str, run_number: int) -> list[str]:
    """Marcadores del tramo, del más completo al más corto (8, 6, 4 y 2 letras para los tramos de 0 a F; siempre de longitud par)."""
    bank, offset = entry_id.split(":")
    digit = f"{run_number:X}"
    candidates = [f"{bank}{offset}.{digit}", f"{offset}.{digit}", f"{offset[2:]}.{digit}", digit.rjust(2, "#")]
    return [text if len(text) % 2 == 0 else text + " " for text in candidates]  # una cifra más deja la longitud impar: se completa con un espacio


def ruler_text(marker: str, letters: int) -> str:
    """El marcador seguido de dígitos que cuentan la posición (la letra ``i`` es ``i % 10``), hasta ``letters`` letras."""
    if letters < len(marker) or letters % 2:
        raise PatchError(f"a ruler of {letters} letters cannot hold the marker {marker!r} (needs an even count)")
    return marker + "".join(str(position % 10) for position in range(len(marker), letters))


def choose_marker(entry_id: str, run_number: int, available: int) -> str | None:
    """El marcador más largo que cabe en ``available`` bytes, o ``None`` si no caben ni dos letras."""
    for text in marker_candidates(entry_id, run_number):
        if len(text) // 2 * BYTES_PER_PAIR <= available:
            return text
    return None


def run_slot_rows(raw: bytes) -> list[int]:
    """Celdas de cada línea de un tramo original: ``C3`` abre una línea nueva y ``E5 nn`` salta ``nn`` celdas."""
    rows = [0]
    for token in sf.tokenize(raw + b"\xff").tokens[:-1]:
        if token.kind in ("glyph", "wide"):
            rows[-1] += 1
        elif token.code == probe.LINE_BREAK:
            rows.append(0)
        elif token.code == ex.INDENT:
            rows[-1] += token.raw[1]
    return rows


@dataclass
class MarkedRun:
    number: int
    start: int  # desplazamiento dentro del blob nuevo
    length: int
    text: str | None  # texto latino escrito (marcador, o marcador y regla); None: el tramo se dejó como estaba
    marker: str | None  # el marcador con la identidad del tramo (el principio de la regla)
    original_bytes: int
    original_rows: list[int]
    ruler: bool


@dataclass
class MarkedBlob:
    data: bytes
    runs: list[MarkedRun] = field(default_factory=list)


def build_marked_blob(entry: dict, ruler_letters: int | None = None) -> MarkedBlob:
    """El blob de una entrada con sus tramos sustituidos por marcadores; el esqueleto se copia tal cual."""
    out = bytearray()
    runs: list[MarkedRun] = []
    position = 0
    skeleton = entry["skeleton"]
    while position < len(skeleton):
        match = ex.TOKEN_RE.match(skeleton, position)
        if not match:
            raise PatchError(f"{entry['id']}: bad skeleton at {position}")
        position = match.end()
        if match.group(1):
            out += bytes(int(part, 16) for part in match.group(1).split())
            continue
        number = int(match.group(2))
        original = bytes(int(part, 16) for part in entry["runs"][number]["raw"].split())
        if ruler_letters is not None:
            marker = choose_marker(entry["id"], number, 1 << 16)
            text: str | None = ruler_text(marker, ruler_letters)
        else:
            marker = text = choose_marker(entry["id"], number, len(original))
        encoded = original if text is None else probe.encode_latin(text)
        runs.append(MarkedRun(number, len(out), len(encoded), text, marker, len(original), run_slot_rows(original), ruler_letters is not None))
        out += encoded
    return MarkedBlob(bytes(out), runs)


def command_sequence(blob: bytes) -> list[bytes]:
    """Los comandos del blob sin las fichas de texto (``F9``, saltos de línea y sangrías), para comparar esqueletos."""
    return [token.raw for token in sf.tokenize(blob).tokens if token.kind == "command" and token.code not in IGNORED_FOR_SKELETON]


def check_skeleton_preserved(original: bytes, marked: bytes, entry_id: str) -> None:
    if not sf.tokenize(marked).complete:
        raise PatchError(f"{entry_id}: the marker blob does not close with a terminator")
    if command_sequence(marked) != command_sequence(original):
        raise PatchError(f"{entry_id}: the marker blob changed the command skeleton")


def select_entries(entries: list[ex.Entry], tables: tuple[int, ...] | None, roles: tuple[str, ...] = ("messages",)) -> list[ex.Entry]:
    """Las entradas ``ok`` con texto del rol dado que apuntan alguna de ``tables`` (todas si es ``None``)."""
    wanted = None if tables is None else {f"{table:06X}" for table in tables}
    return [
        entry
        for entry in entries
        if entry.status == "ok"
        and entry.runs
        and entry.role in roles
        and (wanted is None or any(slot.split("#")[0] in wanted for slot in entry.slots))
    ]


def verified_free_space(rom: bytes) -> dict[int, FreeSpace]:
    """Los huecos verificados, comprobando de nuevo que siguen enteros a ``FF`` en esta ROM."""
    spaces = {}
    for bank, (low, high) in VERIFIED_FREE.items():
        region = rom[sf.cpu_to_offset(low) : sf.cpu_to_offset(high)]
        if region.count(FILLER) != len(region):
            raise PatchError(f"free space 0x{low:06X}-0x{high:06X} is not all 0xFF in this ROM")
        spaces[bank] = FreeSpace(low, high)
    return spaces


def repoint_slots(patcher: RomPatcher, entry: ex.Entry, new_address: int) -> None:
    """Repunta todas las ranuras de la entrada (varias tablas o índices pueden compartir el blob)."""
    for slot in entry.slots:
        table_text, index_text = slot.split("#")
        table = int(table_text, 16)
        if table >> 16 != new_address >> 16:
            raise PatchError(f"{entry.id}: slot {slot} lies in another bank than the new blob")
        offset = sf.cpu_to_offset(table + 2 * int(index_text))
        current = int.from_bytes(patcher.original[offset : offset + 2], "little")
        if current != entry.address & 0xFFFF:
            raise PatchError(f"{entry.id}: slot {slot} does not hold the extracted address")
        patcher.write(offset, (new_address & 0xFFFF).to_bytes(2, "little"), reason=f"pointer {slot} of {entry.id}")


def place_entries(
    patcher: RomPatcher, entries: list[ex.Entry], ruler_ids: set[str], ruler_letters: int
) -> list[dict]:
    """Escribe los blobs de marcadores (en el sitio o reubicados) y devuelve el mapa de entradas."""
    spaces = verified_free_space(bytes(patcher.original))
    mapped = []
    for entry in entries:
        data = entry.to_json()
        ruler = entry.id in ruler_ids
        marked = build_marked_blob(data, ruler_letters if ruler else None)
        original = bytes(patcher.original[sf.cpu_to_offset(entry.address) : sf.cpu_to_offset(entry.address) + entry.size])
        check_skeleton_preserved(original, marked.data, entry.id)
        if len(marked.data) <= entry.size:
            address = entry.address
            patcher.write(
                sf.cpu_to_offset(address),
                marked.data + bytes([FILLER]) * (entry.size - len(marked.data)),
                reason=f"marker blob {entry.id} in place",
            )
        else:
            space = spaces.get(entry.address >> 16)
            if space is None:
                raise PatchError(f"{entry.id}: needs {len(marked.data)} bytes but bank ${entry.address >> 16:02X} has no verified free space")
            try:
                address = space.allocate(len(marked.data))
            except PatchError as error:
                raise PatchError(f"{entry.id}: {error} (needs {len(marked.data)} bytes)") from error
            patcher.write(sf.cpu_to_offset(address), marked.data, reason=f"marker blob {entry.id} relocated")
            repoint_slots(patcher, entry, address)
        mapped.append(
            {
                "id": entry.id,
                "role": entry.role,
                "slots": entry.slots,
                "original_address": format_address(entry.address),
                "address": format_address(address),
                "original_size": entry.size,
                "size": len(marked.data),
                "relocated": address != entry.address,
                "skeleton": entry.skeleton,
                "runs": [
                    {
                        "number": run.number,
                        "start": format_address(address + run.start),
                        "end": format_address(address + run.start + run.length),
                        "marker": run.marker,
                        "letters": None if run.text is None else len(run.text),
                        "ruler": run.ruler,
                        "original_bytes": run.original_bytes,
                        "original_rows": run.original_rows,
                    }
                    for run in marked.runs
                ],
            }
        )
    patcher.verify_log_covers_changes()
    return mapped


def asm_regions() -> list[tuple[int, int]]:
    """Regiones de fichero que instala asar: los dos ganchos, el código y la fuente."""
    ranges = list(probe.HOOK_RANGES) + [probe.CODE_RANGE, (probe.FONT_START, probe.FONT_END)]
    return [(sf.cpu_to_offset(low), sf.cpu_to_offset(high)) for low, high in ranges]


def check_final_changes(original: bytes, final: bytes, log_ranges: list[tuple[int, int]]) -> None:
    """Todo byte cambiado debe estar en una escritura registrada o en las regiones de asar."""
    allowed = bytearray(len(original))
    for low, high in log_ranges + asm_regions():
        allowed[low:high] = b"\x01" * (high - low)
    for start, end in probe.changed_ranges(original, final):
        if not all(allowed[start:end]):
            first = next(offset for offset in range(start, end) if not allowed[offset])
            raise PatchError(f"unexpected change at 0x{first:06X} (outside the write log and the asar regions)")


def build_marker_rom(
    rom: bytes,
    glyph_table: gt.GlyphTable,
    art: dict[str, list[str]],
    asar: Path,
    scratch: Path,
    tables: tuple[int, ...] | None = SLICE_TABLES,
    ruler_ids: tuple[str, ...] = (),
    ruler_letters: int = RULER_DEFAULT_LETTERS,
    roles: tuple[str, ...] = ("messages",),
) -> tuple[bytes, dict]:
    """Devuelve la ROM de marcadores y su mapa. ``scratch`` es el fichero temporal sobre el que trabaja asar."""
    for low, high in (probe.CODE_RANGE, (probe.FONT_START, probe.FONT_END)):
        region = rom[sf.cpu_to_offset(low) : sf.cpu_to_offset(high)]
        if region.count(FILLER) != len(region):
            raise PatchError(f"free space 0x{low:06X}-0x{high:06X} is not all 0xFF in this ROM")
    entries, _ = ex.build_entries(rom, glyph_table)
    selected = select_entries(entries, tables, roles)
    known = {entry.id for entry in selected}
    unknown = [ruler for ruler in ruler_ids if ruler not in known]
    if unknown:
        raise PatchError(f"--ruler names entries that are not selected for the build: {', '.join(unknown)}")
    patcher = RomPatcher(rom)
    mapped = place_entries(patcher, selected, set(ruler_ids), ruler_letters)
    scratch.write_bytes(bytes(patcher.data))
    probe.run_asar(asar, scratch, probe.font_binary(art))
    final = scratch.read_bytes()
    check_final_changes(rom, final, [(record.offset, record.offset + len(record.new)) for record in patcher.log])
    summary = summarize(mapped)
    document = {
        "format": MAP_FORMAT,
        "original_sha1": hashlib.sha1(rom).hexdigest().upper(),
        "scope": "all" if tables is None else [f"{table:06X}" for table in tables],
        "summary": summary,
        "entries": mapped,
    }
    return final, document


def original_map(entries: list[ex.Entry]) -> list[dict]:
    """El mapa de tramos de la ROM original (sin marcadores), para repetir el recorrido sobre el juego sin tocar."""
    mapped = []
    for entry in entries:
        runs = []
        offset = 0
        position = 0
        while position < len(entry.skeleton):
            match = ex.TOKEN_RE.match(entry.skeleton, position)
            if not match:
                raise PatchError(f"{entry.id}: bad skeleton at {position}")
            position = match.end()
            if match.group(1):
                offset += len(match.group(1).split())
                continue
            number = int(match.group(2))
            raw = bytes(int(part, 16) for part in entry.runs[number]["raw"].split())
            runs.append(
                {
                    "number": number,
                    "start": format_address(entry.address + offset),
                    "end": format_address(entry.address + offset + len(raw)),
                    "marker": None,
                    "letters": None,
                    "ruler": False,
                    "original_bytes": len(raw),
                    "original_rows": run_slot_rows(raw),
                }
            )
            offset += len(raw)
        address = format_address(entry.address)
        mapped.append(
            {"id": entry.id, "role": entry.role, "slots": entry.slots, "original_address": address, "address": address,
             "original_size": entry.size, "size": entry.size, "relocated": False, "skeleton": entry.skeleton, "runs": runs}
        )
    return mapped


def summarize(mapped: list[dict]) -> dict:
    runs = [run for entry in mapped for run in entry["runs"]]
    return {
        "entries": len(mapped),
        "relocated entries": sum(entry["relocated"] for entry in mapped),
        "runs": len(runs),
        "runs marked": sum(run["marker"] is not None for run in runs),
        "runs left as they were (under 3 bytes)": sum(run["marker"] is None for run in runs),
        "runs with a full marker": sum(run["marker"] is not None and len(run["marker"]) >= 8 for run in runs),
    }


def inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO)
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
    parser.add_argument("--asar", default=os.environ.get("ASAR"), help="ejecutable de asar (o ASAR)")
    parser.add_argument("--table", required=True, help="tabla de glifos (tbl/original.json)")
    parser.add_argument("--out", required=True, type=Path, help="ROM de marcadores (fuera del repositorio); con --map-only, el mapa")
    parser.add_argument("--map", type=Path, help="mapa JSON de los tramos (por defecto <out>.map.json)")
    parser.add_argument("--map-only", action="store_true", help="solo el mapa de tramos de la ROM original, sin escribir ninguna ROM")
    parser.add_argument("--all", action="store_true", help="todas las entradas ok de mensajes, no solo el corte vertical")
    parser.add_argument("--roles", default="messages", help="roles de las entradas que se marcan, separados por comas: messages, events, global (por defecto messages)")
    parser.add_argument("--ruler", action="append", default=[], metavar="ID", help="entrada que lleva regla (reubicada), por ejemplo E2:EE93")
    parser.add_argument("--ruler-letters", type=int, default=RULER_DEFAULT_LETTERS, help="letras de la regla (par)")
    parser.add_argument("--font-art", help="arte de otra fuente latina; por defecto la del proyecto")
    arguments = parser.parse_args(argv)
    if not arguments.rom or not (arguments.asar or arguments.map_only):
        print("error: pass --rom and --asar, or set DARK_LAW_ROM and ASAR", file=sys.stderr)
        return 2
    roles = tuple(role.strip() for role in arguments.roles.split(",") if role.strip())
    if not roles or not set(roles) <= {"messages", "events", "global", "called scripts"}:
        print("error: --roles takes a comma-separated list of messages, events, global, called scripts", file=sys.stderr)
        return 2
    out = arguments.out
    map_path = out if arguments.map_only else arguments.map or out.with_name(out.name + ".map.json")
    if inside_repository(out) or inside_repository(map_path):
        print("error: the marker ROM and its map must be written outside the repository", file=sys.stderr)
        return 2
    try:
        glyph_table = gt.load_table(arguments.table)
        rom = Path(arguments.rom).read_bytes()
        art = probe.parse_font_art(Path(arguments.font_art).read_text(encoding="utf-8")) if arguments.font_art else probe.project_font_art()
    except (gt.TableError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if arguments.map_only:
        entries, _ = ex.build_entries(rom, glyph_table)
        mapped = original_map(select_entries(entries, None if arguments.all else SLICE_TABLES, roles))
        document = {"format": MAP_FORMAT, "original_sha1": hashlib.sha1(rom).hexdigest().upper(), "scope": "original", "summary": summarize(mapped), "entries": mapped}
        map_path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"map of the original ROM: {map_path}")
        return 0
    try:
        final, document = build_marker_rom(
            rom, glyph_table, art, Path(arguments.asar), out, None if arguments.all else SLICE_TABLES, tuple(arguments.ruler), arguments.ruler_letters, roles
        )
    except (PatchError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        out.unlink(missing_ok=True)
        return 1
    out.write_bytes(final)
    map_path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
    for name, value in document["summary"].items():
        print(f"{name}: {value}")
    print(f"ROM: {out}\nmap: {map_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
