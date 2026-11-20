# Header And Address Mapping

All offsets assume the verified dump in [rom-identity.md](rom-identity.md): 4 MiB, no copier header. Notation: a file offset is written `file 0x123456`, a CPU address `$BB:AAAA` (bank, address), and a RAM address `$7E:AAAA` or `WRAM $AAAA`.

## Internal Header

Status: **verified** by reading the bytes of the file and by loading the ROM in MesenCE.

| Field | Value | Meaning |
| --- | --- | --- |
| Location | file `0xFFC0` | HiROM. The LoROM location (`0x7FC0`) holds garbage: its checksum pair does not add up. |
| Title | `ASCII DARK LAW` (space padded to 21 bytes) | |
| Map mode | `0x31` | HiROM, FastROM |
| Cartridge type | `0x02` | ROM, RAM, battery |
| ROM size | `0x0C` | 4 MiB |
| RAM size | `0x03` | 8 KiB of battery SRAM |
| Destination | `0x00` | Japan |
| Developer ID | `0x33` | An extended header is present at file `0xFFB0` |
| Extended header | `42 31 41 44 55 4A` | Maker code `B1`, game code `ADUJ` |
| Version | `0` | |
| Checksum complement / checksum | `0x4537` / `0xBAC8` | They add up to `0xFFFF`, and the sum of all bytes modulo `0x10000` is `0xBAC8`, so the checksum is correct for this dump. |

Vectors: native NMI `$00:05C5`, IRQ `$00:05C9`, BRK `$00:05CD` (these three point into the WRAM mirror at `$00:0000`-`$1FFF`, so the game presumably copies small stubs there at boot; **guess**, the stubs were not read); emulation RESET `$00:FF81`. The code at `$C0:FF81` is `SEI; CLC; XCE; JML $C00012`, so the game runs from banks `$C0`-`$FF`.

The SNES checksum must be recomputed for any modified ROM; it lives at file `0xFFDC` (complement) and `0xFFDE` (checksum). `bps.py` in the translate-retro-game scripts can do it.

## Address Conversion

Status: **verified** in MesenCE on this dump. For 10 CPU addresses in banks `$C0`, `$C1`, `$D1`, `$D2`, `$D3`, `$E2`, `$EF`, and `$FF` (the last 32 bytes of each), the bytes read through the CPU bus (`snesMemory`), through the raw cartridge (`snesPrgRom` at the computed file offset), and from the ROM file were identical. The instruction bytes that the CPU executed at `$D1:4571` and `$D1:4660` also matched the file offsets `0x114571` and `0x114660`.

```
file_offset = ((bank & 0x3F) << 16) | address          banks $C0-$FF (and $40-$7D, and $80-$BF with address >= $8000)
cpu_address = 0xC00000 | file_offset                   canonical form used in these documents
```

radare2 (`r2mcp`) maps the file with LoROM-style virtual addresses and does not follow this formula. Work in file offsets there.

## Open Items

- The ROM was only run from reset, and from savestates taken at the title and the intro. Other mappers or bank-switching tricks have not been looked for; none were needed so far.
