"""Escritura segura sobre la ROM: registro de escrituras y reubicación de blobs.

Toda modificación pasa por ``RomPatcher.write``, que comprueba que los bytes que se
sustituyen son los de la ROM original (nunca los del búfer de trabajo), que no hay
solapes y que cada escritura queda registrada. ``relocate_blob`` mueve un blob a un
hueco libre del mismo banco y actualiza el puntero de 16 bits de la tabla.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from script_format import MessageTable, cpu_to_offset


@dataclass(frozen=True)
class WriteRecord:
    offset: int
    old: bytes
    new: bytes
    reason: str


class PatchError(Exception):
    """Una escritura incumple las reglas de seguridad."""


class RomPatcher:
    def __init__(self, original: bytes):
        self.original = original
        self.data = bytearray(original)
        self.log: list[WriteRecord] = []

    def write(self, offset: int, new: bytes, expected: bytes | None = None, reason: str = "") -> None:
        """Escribe ``new`` en ``offset``. ``expected`` son los bytes originales que se sustituyen (por defecto, los de la ROM original)."""
        end = offset + len(new)
        if offset < 0 or end > len(self.data):
            raise PatchError(f"write outside the ROM at 0x{offset:06X}")
        old = self.original[offset:end]
        if expected is not None and expected != old:
            raise PatchError(f"unexpected original bytes at 0x{offset:06X}")
        for record in self.log:
            if offset < record.offset + len(record.new) and record.offset < end:
                raise PatchError(f"write at 0x{offset:06X} overlaps a previous write at 0x{record.offset:06X}")
        self.data[offset:end] = new
        self.log.append(WriteRecord(offset, old, new, reason))

    def changed_offsets(self) -> set[int]:
        return {i for i, (a, b) in enumerate(zip(self.original, self.data)) if a != b}

    def verify_log_covers_changes(self) -> None:
        """Falla si algún byte cambió sin una escritura registrada detrás."""
        covered: set[int] = set()
        for record in self.log:
            covered.update(range(record.offset, record.offset + len(record.new)))
        stray = self.changed_offsets() - covered
        if stray:
            raise PatchError(f"{len(stray)} changed bytes have no logged write, first at 0x{min(stray):06X}")


@dataclass
class FreeSpace:
    """Hueco libre de un banco, en direcciones de CPU; se consume de principio a fin."""

    start: int
    end: int  # exclusivo

    def allocate(self, size: int) -> int:
        if self.start + size > self.end:
            raise PatchError("free space exhausted")
        address = self.start
        self.start += size
        return address


def relocate_blob(patcher: RomPatcher, table: MessageTable, index: int, new_blob: bytes, space: FreeSpace) -> int:
    """Escribe ``new_blob`` en ``space`` y repunta la entrada ``index`` de ``table``; devuelve la dirección nueva.

    Repunta la entrada de la tabla solamente: quien referencie el blob por otra vía (código o
    datos con la dirección inmediata) tiene que comprobarse aparte, ver docs/re/text-engine.md.
    """
    if space.start >> 16 != table.bank or (space.end - 1) >> 16 != table.bank:
        raise PatchError("free space must lie in the bank of the table: the entries are 16-bit")
    slot = cpu_to_offset(table.address + 2 * index)
    (current,) = struct.unpack("<H", patcher.original[slot : slot + 2])
    if current != table.entries[index]:
        raise PatchError("table entry does not match what was extracted")
    address = space.allocate(len(new_blob))
    patcher.write(cpu_to_offset(address), new_blob, reason=f"blob for table ${table.address:06X} index {index}")
    patcher.write(slot, struct.pack("<H", address & 0xFFFF), reason=f"pointer of table ${table.address:06X} index {index}")
    return address
