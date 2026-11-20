# Latin Font Spike

Goal: find out whether Spanish text can be drawn by the engine, and with what limits, before investing in the glyph table and the translation. Notation follows [text-engine.md](text-engine.md) and [font.md](font.md).

## Verdict

Status: **verified** in MesenCE for the narration window of the intro; other window types are **not measured**.

Two letters of 8x16 pixels per 16x16 glyph cell work. A message of two lines of 24 characters each, with accents and `¿`, was drawn in the intro, and the text after it (Japanese dialogue) kept drawing normally. The cost is a hook of about 400 bytes of code plus a font in free space; no change to the layout of the windows was needed.

Limits of this design:

- 24 letters per row and 48 per page in the narration window (12 slots per row, 2 rows, 2 letters per slot).
- Fixed width: every letter takes 8 pixels, so `i` and `m` cost the same. A proportional path would fit about 30-40 percent more text but needs a pixel-level compositor (see Open Items).
- Each pair costs 3 bytes (`F9 a b`), 1.5 bytes per letter. Moving blobs to free space makes this affordable.

## How The Engine Draws A Slot

Status: **verified** (code read at `$D1:460B`-`$D1:468E` and run).

The slot index is `$0A45` (0..23). For each slot the engine reads three words from tables in bank `$D1`:

| Table | Content | Values |
| --- | --- | --- |
| `$D1:46AB` | WRAM address of the slot's first tilemap entry (`$0D`) | `A388`, `A38C` ... `A3B4` for slots 0-11 (row 1, 4 bytes apart); `A408` ... `A434` for 12-23 (row 2) |
| `$D1:46DB` | WRAM address of the slot's tile buffer (`$0B`) | `AA80`, `AAA0` ... `AB60` for slots 0-7; `AC80` ... `ACE0` for 8-11; `AD00` ... `AD60` for 12-15; `AE80` ... `AF60` for 16-23 |
| `$D1:470B` | Tile number to write into the tilemap (`$0F`) | `22C0`, `22C2` ... `22CE`, `22E0` ... `22EE`, `2300` ... `230E` |

It then copies 32 bytes from the glyph source to the buffer (two top tiles), adds `0x100` to both pointers and copies 32 more (two bottom tiles), and writes four tilemap entries: `t`, `t+1`, `t+0x10`, `t+0x11` at `$0D`, `$0D+2`, `$0D+0x40`, `$0D+0x42`. A 16x16 glyph is therefore the two tiles `t` (left) and `t+1` (right) on top and `t+0x10`, `t+0x11` below, in a VRAM sheet 16 tiles wide. That makes "two 8x16 letters" the same data as one glyph whose left column is letter A and right column is letter B: top 32 bytes = `A.top (16) + B.top (16)`, bottom 32 bytes = `A.bottom (16) + B.bottom (16)`.

The game's own glyphs use pixel value 1 for the white fill and 3 for the dark outline (`#-#` for a stroke); value 0 is the background. A font that uses 3 for the strokes shows grey text.

## The Hook

Status: **verified** (built with asar, run in MesenCE).

Source: `asm/latin_pair_hook.asm`. It adds one token to the text loop: `F9 a b` draws the letters `a` and `b` (indices into a table of 32-byte letters) into the current slot. `F9` was chosen because the dispatcher treated it as invalid and the data never uses it (**guess**, from the measurement in text-engine.md; no occurrence of `F9` was found as a command in the tokenized blobs).

Only 4 original bytes change: `$D1:4587` (`CMP #$E5` / `BEQ $45F6`) becomes `JML LatinPairHook`. The hook repeats that comparison for any byte that is not `F9`, so every other path is as before. For `F9` it copies the letters into the slot's tile buffer using the same tables as the original and jumps to `$D1:465C`, which writes the tilemap entries and advances `$0A45`. It pushes Y pointing at the second letter so that the `PLY` / `INY` at `$D1:468E` lands on the next token. With the slot at 24 or more, nothing is drawn and the token is consumed.

Written regions, all checked to be all `0xFF` beforehand and listed by `tools/build_latin_probe.py`: hook code `$D2:BB80`-`$D2:BD29` (about 0x1A9 bytes), font `$D2:C000`-`$D2:CDE0` (111 letters, 3552 bytes), message blob `$E2:F8A6`, its table entry at `$E2:EE73`.

Not verified: that `$0ADE` (incremented once per token, as the original does once per glyph) has no side effect other than what the original already causes. The code that reads it is at `$D1:4DDD` and in bank `$C3`, and it was not read. Whether the `$D2:BB78`-`$D2:FFFF` filler is used by anything else was not checked beyond the route run here.

## Result In The Emulator

Route: reset, Start, A, then 502 frames to the intro message. Text sent: `Hace trescientos años...` and `¿Quién lo recordará hoy?`, two lines of 24 characters, with `C3` between them. Both lines show whole, in white with outline, on the two rows of the narration window; accents and `¿` render. After the message the game went on to the dialogue scene with Japanese text, drawn correctly. The screens that appear later in the original ROM appear in the test ROM at an earlier frame because the test message has one page instead of three.

`C3` after a full first row (12 slots) did not leave a blank row: the second line started on the second row, in line with the code, which sets the slot to 12 for window type `$0A4C = 1` (`$D1:4E75`). For other values of `$0A4C` (2, 5, 6) it writes `$10` into `$0A47` instead; those window types were not seen.

## Capacity Against The Original Text

Status: **corpus** (computed from the exactly-closing message blobs, 1628 unique, 4394 pages) for the Japanese side; the Spanish side is a **guess**.

Glyph slots used per page (a page is the text between `C0`/`C1` and the next wait, end, or new page): mean 14.6, median 15, maximum 27, with 61 pages above 24 slots and none above 36. Wide kanji count as one slot, like kana. The longest line before a `C3` is 17 slots, mean 7.9.

The narration window has 24 slots, so at 2 letters per slot a page holds 48 letters. A page of 15 Japanese glyphs would need about 2.5 to 3 Spanish letters per glyph to fit, which is an expectation, not a measurement: it should be checked against the English reference translation and then against real lines. Pages near the maximum will have to be split into more pages, which the script format allows (text is free-form between page commands). Whether every dialogue window has the same 12 by 2 layout is unknown: the draw tables cover 24 slots, but other window types set `$0A4C` differently.

## Font Source

The test font comes from rendering Consolas at 13 pixels with an outline added. It is a local proof-of-concept artifact, not included in this repository, and it cannot be redistributed. The final font must be drawn for the project or taken from one with a free licence, with accented capitals fitting the 16-row cell (they touch the top row here).

## Open Items

1. Window types: find where `$0A4C` is set, which values exist, and the rows and columns of each (dialogue with portraits, menus, battle). Needs a savestate inside the game or a scripted route beyond the intro.
2. Proportional width: letters drawn at pixel offsets inside the 24-tile row, shifting and combining the 2bpp rows of adjacent letters. It would need a per-row pixel cursor, a width table and a change to what `$0A45` counts.
3. Tokenizer and encoder: `tools/script_format.py` treats `F9` as unmeasured; translated blobs need either a Latin mode or the new token in the arity table when the input is a patched ROM.
4. Verify `$0ADE` side effects and the free-space range.
5. A real font, with its licence, and a decision on whether to keep Japanese glyphs for text that is not translated.
6. Other text paths (menus, item and monster names, battle messages) and whether they use this routine.
7. The Latin glyph table in this spike is `LATIN_CHARS` in `tools/build_latin_probe.py`: ASCII from `0x20` plus `ñÑ¿¡áéíóúüÁÉÍÓÚÜ`.
