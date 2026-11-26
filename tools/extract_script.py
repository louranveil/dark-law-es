#!/usr/bin/env python3
"""Extrae los guiones de la ROM a archivos de texto editables (etapa 2 del pipeline de traducción).

Cada blob distinto de las tablas de mensajes pasa a una entrada con su esqueleto (los comandos, que
no se editan) y sus tramos de texto (lo que se traduce). Ver ``docs/specs/translation-pipeline.md``.

Una entrada::

    {"id": "E2:F393", "role": "messages", "slots": ["E2EE73#0"], "size": 79, "status": "ok",
     "problems": [], "skeleton": "<C0>{0}<C8 80>", "runs": [
       {"raw": "00 00 ...", "jp": "　　３００年前・・・", "es": "", "status": "todo", "max": null}]}

* ``skeleton``: cada token que no es texto como ``<hex>`` y cada tramo como ``{n}``.
* Un tramo es una secuencia seguida de glifos con saltos de línea (``C3``) y sangrías (``E5 nn``) en medio;
  debe llevar al menos un glifo visible. En ``jp`` el salto es ``\\n``, la sangría ``<E5 02>`` y un glifo
  sin carácter ``[40]``. ``raw`` son los bytes originales (la fuente de verdad); ``jp`` se deriva de ellos.
* ``status``: ``ok`` si el blob cierra exactamente donde empieza el siguiente; ``review`` si no (no cierra,
  deja huecos), si usa comandos cuya aridad es desconocida o si un tramo sigue a un ``FE``/``E8`` (su aridad
  depende del subcomando y el "texto" puede ser argumentos): se extrae pero no se reescribe sin revisarlo.
  Los comandos de aridad respaldada solo por el corpus (terminadores, ``C4``) no cuentan como duda.
* Solo se escriben las entradas con texto. ``check`` cuenta el resto.

El volcado **nunca sobrescribe una traducción**: sin ``--force`` rechaza escribir sobre un archivo que ya
existe; con ``--force`` conserva ``es``, ``status`` y ``max`` de cada tramo cuya ``raw`` no ha cambiado.

Uso::

    python tools/extract_script.py dump  --rom <original.sfc> --table tbl/original.json --out text [--force]
    python tools/extract_script.py check --rom <original.sfc> --table tbl/original.json

La ROM también puede venir de DARK_LAW_ROM. Códigos de salida: 0 bien, 1 una comprobación falló o se
rechazó sobrescribir, 2 uso incorrecto.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import glyph_font as gf
import glyph_table as gt
import script_format as sf
from check_scripts import table_roles

LINE_BREAK = 0xC3
INDENT = 0xE5
VARIABLE_COMMAND_PROBLEM = "text run right after an FE or E8 command: their argument counts depend on the sub-command, so the run may hold arguments"
TOKEN_RE = re.compile(r"<([0-9A-F]{2}(?: [0-9A-F]{2})*)>|\{(\d+)\}")


@dataclass
class Entry:
    address: int  # dirección larga del blob
    role: str
    slots: list[str]
    size: int
    status: str
    problems: list[str]
    skeleton: str
    runs: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.address >> 16:02X}:{self.address & 0xFFFF:04X}"

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "slots": self.slots,
            "size": self.size,
            "status": self.status,
            "problems": self.problems,
            "skeleton": self.skeleton,
            "runs": self.runs,
        }


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def is_text_token(token: sf.Token) -> bool:
    return token.kind in ("glyph", "wide") or token.code in (LINE_BREAK, INDENT)


def is_visible(token: sf.Token, table: gt.GlyphTable) -> bool:
    """Un glifo que se dibuja: ni el blanco ni un glifo sin carácter (marcadores, iconos)."""
    key = gt.token_key(token)
    if key is None:
        return False
    entry = table.entries.get(key)
    return bool(entry) and entry["kind"] in ("text", "latin") and entry["char"] != "　"


def canonical_keys(table: gt.GlyphTable) -> dict[str, str]:
    """Carácter -> la clave que lo escribe de forma canónica (los de un byte primero); los glifos repetidos usan ``[KEY]``."""
    canonical: dict[str, str] = {}
    for key in sorted(table.entries, key=lambda k: (" " in k, k)):
        char = table.entries[key]["char"]
        if char and char not in canonical:
            canonical[char] = key
    return canonical


def render_run(tokens: list[sf.Token], table: gt.GlyphTable) -> str:
    """El texto de un tramo: caracteres, ``\\n`` por cada ``C3``, ``<E5 nn>`` por las sangrías y ``[KEY]`` si no hay carácter."""
    canonical = canonical_keys(table)
    parts = []
    for token in tokens:
        key = gt.token_key(token)
        if key is None:
            parts.append("\n" if token.code == LINE_BREAK else "<" + hex_bytes(token.raw) + ">")
            continue
        char = table.char(key)
        parts.append(char if char and canonical.get(char) == key and char not in "[<\n\\" else f"[{key}]")
    return "".join(parts)


def parse_run(text: str, table: gt.GlyphTable) -> bytes:
    """Inverso de ``render_run``: vuelve a los bytes. Falla con ``ValueError`` si un carácter no está en la tabla."""
    canonical = canonical_keys(table)
    out = bytearray()
    position = 0
    while position < len(text):
        char = text[position]
        if char == "\n":
            out.append(LINE_BREAK)
            position += 1
        elif char == "<":
            end = text.index(">", position)
            out += bytes(int(part, 16) for part in text[position + 1 : end].split())
            position = end + 1
        elif char == "[":
            end = text.index("]", position)
            prefix, index = gf.parse_key(text[position + 1 : end])
            out += bytes([index]) if prefix is None else bytes([prefix, index])
            position = end + 1
        else:
            key = canonical.get(char)
            if key is None:
                raise ValueError(f"character {char!r} is not in the glyph table")
            prefix, index = gf.parse_key(key)
            out += bytes([index]) if prefix is None else bytes([prefix, index])
            position += 1
    return bytes(out)


def split_entry(tokens: tuple[sf.Token, ...], table: gt.GlyphTable) -> tuple[str, list[dict]]:
    """Esqueleto y tramos de un blob. Un tramo sin glifos visibles se queda en el esqueleto como tokens sueltos."""
    skeleton: list[str] = []
    runs: list[dict] = []
    position = 0
    while position < len(tokens):
        end = position
        while end < len(tokens) and is_text_token(tokens[end]):
            end += 1
        if end > position and any(is_visible(token, table) for token in tokens[position:end]):
            run = list(tokens[position:end])
            skeleton.append(f"{{{len(runs)}}}")
            runs.append(
                {"raw": hex_bytes(sf.encode(run)), "jp": render_run(run, table), "es": "", "status": "todo", "max": None}
            )
            position = end
        else:
            stop = max(end, position + 1)
            skeleton.extend("<" + hex_bytes(token.raw) + ">" for token in tokens[position:stop])
            position = stop
    return "".join(skeleton), runs


def build_entries(rom: bytes, table: gt.GlyphTable) -> tuple[list[Entry], Counter]:
    """Todas las entradas (con y sin texto) y un resumen de lo que se encontró."""
    roles = table_roles(rom)
    by_address: dict[int, Entry] = {}
    summary: Counter = Counter()
    for table_address, message_table in sf.read_all_tables(rom).items():
        for report in sf.check_table(rom, message_table):
            slot = f"{table_address:06X}#{report.index}"
            if report.address in by_address:
                by_address[report.address].slots.append(slot)
                continue
            real = [p for p in report.problems if "unmeasured" not in p]
            guessed = sorted(code for code in report.parsed.unresolved if sf.command_arguments(code)[1] is sf.Evidence.UNKNOWN)
            problems = real + ([f"uses commands with unknown argument counts: {' '.join(f'{c:02X}' for c in guessed)}"] if guessed else [])
            skeleton, runs = split_entry(report.parsed.tokens, table)
            if re.search(r"<(?:FE|E8)[^>]*>\{", skeleton):
                problems.append(VARIABLE_COMMAND_PROBLEM)
            entry = Entry(
                address=report.address,
                role=roles[table_address],
                slots=[slot],
                size=report.parsed.length,
                status="review" if problems else "ok",
                problems=problems,
                skeleton=skeleton,
                runs=runs,
            )
            by_address[report.address] = entry
            summary["blobs"] += 1
            summary["ok" if not problems else "review"] += 1
    # los demás huecos de una tabla compartida: los slots de una misma dirección se ordenan para que el volcado sea estable
    for entry in by_address.values():
        entry.slots.sort()
    entries = sorted(by_address.values(), key=lambda entry: entry.address)
    for entry in entries:
        if entry.runs:
            summary["with text"] += 1
            summary["with text, review" if entry.status == "review" else "with text, ok"] += 1
            summary["runs"] += len(entry.runs)
    return entries, summary


def assemble(entry: dict) -> bytes:
    """Bytes del blob a partir de su esqueleto y de los ``raw`` de sus tramos."""
    out = bytearray()
    position = 0
    skeleton = entry["skeleton"]
    while position < len(skeleton):
        match = TOKEN_RE.match(skeleton, position)
        if not match:
            raise ValueError(f"{entry['id']}: bad skeleton at {position}")
        if match.group(1):
            out += bytes(int(part, 16) for part in match.group(1).split())
        else:
            out += bytes(int(part, 16) for part in entry["runs"][int(match.group(2))]["raw"].split())
        position = match.end()
    return bytes(out)


def verify_round_trip(rom: bytes, entries: list[Entry], table: gt.GlyphTable) -> list[str]:
    """Cada entrada debe reconstruir sus bytes y su ``jp`` debe volver a ``raw``; devuelve los fallos."""
    failures = []
    for entry in entries:
        offset = sf.cpu_to_offset(entry.address)
        original = rom[offset : offset + entry.size]
        data = entry.to_json()
        if assemble(data) != original:
            failures.append(f"{entry.id}: assemble() does not give the original bytes")
        for number, run in enumerate(entry.runs):
            try:
                if parse_run(run["jp"], table) != bytes(int(part, 16) for part in run["raw"].split()):
                    failures.append(f"{entry.id} run {number}: jp does not parse back to raw")
            except ValueError as error:
                failures.append(f"{entry.id} run {number}: {error}")
    return failures


def file_name(table_address: int, role: str) -> str:
    return f"{table_address >> 16:02X}-{table_address & 0xFFFF:04X}-{role.replace(' ', '-')}.json"


def group_by_file(entries: list[Entry]) -> dict[str, list[Entry]]:
    """Las entradas con texto, agrupadas por la primera tabla que las apunta."""
    groups: dict[str, list[Entry]] = {}
    for entry in entries:
        if not entry.runs:
            continue
        table_address = int(entry.slots[0].split("#")[0], 16)
        groups.setdefault(file_name(table_address, entry.role), []).append(entry)
    return groups


def merge_translations(new: list[dict], old: list[dict]) -> list[dict]:
    """Conserva ``es``, ``status`` y ``max`` de los tramos del volcado anterior cuya ``raw`` no cambió."""
    previous = {entry["id"]: entry for entry in old}
    for entry in new:
        before = previous.get(entry["id"])
        if not before:
            continue
        for number, run in enumerate(entry["runs"]):
            if number < len(before["runs"]) and before["runs"][number]["raw"] == run["raw"]:
                for name in ("es", "status", "max"):
                    run[name] = before["runs"][number][name]
    return new


def dump(entries: list[Entry], out_dir: Path, force: bool) -> tuple[list[str], list[str]]:
    """Escribe los archivos de texto; devuelve (escritos, rechazados)."""
    written, refused = [], []
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, group in sorted(group_by_file(entries).items()):
        path = out_dir / name
        data = [entry.to_json() for entry in group]
        if path.exists():
            if not force:
                refused.append(name)
                continue
            data = merge_translations(data, json.loads(path.read_text(encoding="utf-8"))["entries"])
        document = {"format": 1, "entries": data}
        path.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        written.append(name)
    return written, refused


def format_summary(summary: Counter) -> str:
    return "\n".join(
        [
            f"blobs: {summary['blobs']} ({summary['ok']} closing exactly, {summary['review']} needing review)",
            f"with text: {summary['with text']} ({summary['with text, ok']} ok, {summary['with text, review']} review), {summary['runs']} runs",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extrae los guiones de la ROM a archivos de texto.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (("dump", "escribe los archivos de texto"), ("check", "comprueba la extracción sin escribir")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--rom", default=os.environ.get("DARK_LAW_ROM"), help="ROM original (o DARK_LAW_ROM)")
        sub.add_argument("--table", required=True, help="tabla de glifos (tbl/original.json)")
    commands.choices["dump"].add_argument("--out", required=True, help="carpeta de los archivos de texto")
    commands.choices["dump"].add_argument("--force", action="store_true", help="regenerar conservando las traducciones")
    arguments = parser.parse_args(argv)
    if not arguments.rom:
        print("error: pass --rom or set DARK_LAW_ROM", file=sys.stderr)
        return 2
    try:
        table = gt.load_table(arguments.table)
        rom = Path(arguments.rom).read_bytes()
    except (gt.TableError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    entries, summary = build_entries(rom, table)
    print(format_summary(summary))
    failures = verify_round_trip(rom, entries, table)
    print(f"round trip: {'ok' if not failures else str(len(failures)) + ' failures'}")
    for failure in failures[:10]:
        print(f"  {failure}", file=sys.stderr)
    if failures:
        return 1
    if arguments.command == "dump":
        written, refused = dump(entries, Path(arguments.out), arguments.force)
        print(f"wrote {len(written)} files")
        for name in refused:
            print(f"refused to overwrite {name} (use --force to regenerate keeping the translations)", file=sys.stderr)
        return 1 if refused else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
