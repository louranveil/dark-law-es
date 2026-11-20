# Font

Status: **verified** for the storage and the lookup code (read from the ROM and run in MesenCE); the character each glyph shows is **not mapped yet**.

The dialogue font is stored uncompressed as 2 bpp tiles in banks `$D2` and `$D3`. Every glyph is 16x16 pixels, made of 4 tiles of 16 bytes: the two tiles of the top half are 32 contiguous bytes, and the two tiles of the bottom half are the next 32 bytes at `+0x100`. This is the same layout as a 16-tile-wide VRAM sheet, so `snes-tilesheet --bpp 2 --columns 16` renders a page as a readable sheet.

## Lookup

Two routines return the glyph address (X = address, A = bank) for a glyph index; the text engine calls them from `$D1:4548` and `$D1:45EC`.

- `$D2:009C` (single-byte codes `$00`-`$BF`): `address = 0x0129 + (n >> 4) * 0x400 + ((n >> 3) & 1) * 0x200 + (n & 7) * 0x20`, bank `$D2`. The font data starts at `$D2:0129`, right after the routines.
- `$D2:00D2` (two-byte codes): the high byte of the 16-bit glyph value selects a page, the low byte `n` is indexed with the same formula as above. The page table sits at `$D2:011D` (base addresses `3B78 7B78 0000 4000`) and `$D2:0125` (banks `D2 D2 D3 D3`).

| Code in the text | Page value | Base | File offset | Content seen when rendered |
| --- | --- | --- | --- | --- |
| `00`-`BF` (1 byte) | n/a | `$D2:0129` | `0x120129` | Spaces, hiragana, katakana (plain, voiced, small), digits, punctuation, a few symbols. Roughly 190 glyphs, the rest of the 16 KiB area holds other graphics. |
| `FD xx` | `0x00xx` | `$D2:3B78` | `0x123B78` | Kanji page 0 |
| `FC xx` | `0x01xx` | `$D2:7B78` | `0x127B78` | Kanji page 1 |
| `FB xx` | `0x02xx` | `$D3:0000` | `0x130000` | Kanji page 2 |
| `FA xx` | `0x03xx` | `$D3:4000` | `0x134000` | Kanji page 3 |

Each kanji page is `0x4000` bytes, 256 glyphs. The area `$D2:BB78`-`$D2:FFFF` is filled with `0xFF` and is a free-space candidate (see [text-engine.md](text-engine.md)).

How the page value is formed is read from the code at `$D1:45B0`-`$D1:45EB`: the prefix byte decides the high byte (`FA` → `0x03`, `FB` → `0x02`, `FC` → `0x01`, `FD` → `0x00`) and the next byte is the low byte.

## Drawing

For each glyph the engine copies the 32 bytes of the top half and the 32 bytes of the bottom half into a tile buffer (`$D1:4630`-`$D1:465A`), then writes four tilemap entries (`t`, `t+1`, `t+0x10`, `t+0x11`) into the WRAM tilemap shadow, which is later copied to VRAM. A text window holds 24 glyph slots (`$0A45` counts up to `0x18`). The tilemap shadow of the intro text lives at `WRAM $A388` and `$A3C8` (two rows of 20 entries) and the same bytes appear at VRAM `0x9388` and `0x93C8`. Fixed 16x16 glyphs mean a Spanish translation drawn with this routine would show one letter per 16 pixels; fitting Spanish needs a narrower glyph path (see the feasibility notes in [text-engine.md](text-engine.md)).

## Open Items

- Map each glyph index to a character. A suggested method is template matching against a rendered Japanese font, then human review; no table exists yet.
- The menu at the title screen (`最初からはじめる`) is drawn by another path; not analyzed.
