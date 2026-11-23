# Latin Font Spike

Goal: find out whether Spanish text can be drawn by the engine, and with what limits, before investing in the glyph table and the translation. Notation follows [text-engine.md](text-engine.md) and [font.md](font.md).

## Verdict

Status: **verified** in MesenCE for window types 1 (intro narration) and 2 (field messages); the other window types are described in [window-types.md](window-types.md) and **not tested**.

Two letters of 8x16 pixels per 16x16 glyph cell work. In the intro, a message of two lines of 24 characters each, with accents and `¿`, was drawn, and the text after it (Japanese dialogue) kept drawing normally. In the field, a message of two lines of 29 and 22 characters was drawn in the window of type 2, which has room for 32 letters per row. The cost is a hook of about 420 bytes per text loop plus a font in free space; no change to the layout of the windows was needed. The engine has five text loops, one per window flavour ([window-types.md](window-types.md)); two were hooked and run.

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

Four original bytes change in each hooked loop: `$D1:4587` (`CMP #$E5` / `BEQ $45F6`, loop 1) and `$D1:477D` (`CMP #$E5` / `BEQ $47E0`, loop 2) become a `JML` to the hook of that loop. The hook repeats that comparison for any byte that is not `F9`, so every other path is as before. For `F9` it copies the letters into the slot's tile buffer using the loop's own slot tables and jumps to the part of the loop that writes the tilemap entries and advances the counter (`$D1:465C` for loop 1, `$D1:4851` for loop 2). It pushes Y pointing at the second letter so that the `PLY` / `INY` at the end of the loop lands on the next token. With the counter at its limit (24 and 32 slots), nothing is drawn and the token is consumed. The hook is one assembler macro (`LatinHook`) instantiated once per loop.

Written regions, all checked to be all `0xFF` beforehand and summarized by `tools/build_latin_probe.py`: hook code `$D2:BB80`-`$D2:BECB` (837 bytes for two loops), font `$D2:C000`-`$D2:CDE0` (111 letters, 3552 bytes), and for each scenario the message blob in the free filler of its bank (`$E2:F8A6` for the intro, `$E7:FC81` for the field) with its table entry (`$E2:EE73` and `$E7:362B`).

Not verified: that `$0ADE` (incremented once per token, as the original does once per glyph) has no side effect other than what the original already causes. The code that reads it is at `$D1:4DDD` and in bank `$C3`, and it was not read. Whether the `$D2:BB78`-`$D2:FFFF` filler is used by anything else was not checked beyond the route run here.

## Result In The Emulator

Route: reset, Start, A, then 502 frames to the intro message. Text sent: `Hace trescientos años...` and `¿Quién lo recordará hoy?`, two lines of 24 characters, with `C3` between them. Both lines show whole, in white with outline, on the two rows of the narration window; accents and `¿` render. After the message the game went on to the dialogue scene with Japanese text, drawn correctly. The screens that appear later in the original ROM appear in the test ROM at an earlier frame because the test message has one page instead of three.

`C3` after a full first row (12 slots) did not leave a blank row: the second line started on the second row, in line with the code, which sets the slot to 12 for window type `$0A4C = 1` (`$D1:4E75`). For other values of `$0A4C` (2, 5, 6) it writes `$10` into `$0A47` instead; those window types were not seen.

Field route: from a savestate at the start of the field (created by playing through the character creation), the same random walk of 54 moves (fixed seed) reaches the first field message, `古い神殿のようです・・・`, entry 0 of the table at `$E7:362B` (blob `$E7:372B`, opens with `C1`, ends with `CD 00 C7`). The test ROM replaces it with `Parece un templo muy antiguo...` and `No hay nadie por aquí.`. Both lines show whole in the message box of the field (window type 2, 512-dot wide screen) and the game goes on as in the original: the message waits for a key, the HUD and the map are untouched. The loop that draws it was identified with an exec watch on the glyph read of each of the five loops: only loop 2 ran.

## Capacity Against The Original Text

Status: **corpus** (computed from the exactly-closing message blobs, 1628 unique, 4394 pages) for the Japanese side; the Spanish side is a **guess**.

Glyph slots used per page (a page is the text between `C0`/`C1` and the next wait, end, or new page): mean 14.6, median 15, maximum 27, with 61 pages above 24 slots and none above 36. Wide kanji count as one slot, like kana. The longest line before a `C3` is 17 slots, mean 7.9.

The narration window (loop 1) has 24 slots, so at 2 letters per slot a page holds 48 letters; the field window (loop 2) has 32 slots and holds 64. The corpus maximum of 27 slots per page is above 24, so such pages can only be shown in the windows with 32 slots (**guess**, from the numbers; the window type that each message uses is chosen at run time by the commands around it, not by the message). A page of 15 Japanese glyphs would need about 2.5 to 3 Spanish letters per glyph to fit, which is an expectation, not a measurement: it should be checked against the English reference translation and then against real lines. Pages near the maximum will have to be split into more pages, which the script format allows (text is free-form between page commands).

## Font Source

The spike's first test font came from rendering Consolas at 13 pixels with an outline added; it was a local proof of concept and was never part of this repository. The project font is now one of our own, `assets/font/latin-8x16.txt`, with the 111 characters and accented capitals that fit the 16-row cell (see [../fonts/decision.md](../fonts/decision.md) and [../fonts/custom-font.md](../fonts/custom-font.md)); `tools/build_latin_probe.py` uses it by default.

## Open Items

1. Window types 3 to 6 and loops 3 to 5: see [window-types.md](window-types.md). Reaching them needs more play (choice boxes, shops, battle, dialogue with portraits).
2. Proportional width: letters drawn at pixel offsets inside the 24-tile row, shifting and combining the 2bpp rows of adjacent letters. It would need a per-row pixel cursor, a width table and a change to what `$0A45` counts.
3. Tokenizer and encoder: `tools/script_format.py` treats `F9` as unmeasured; translated blobs need either a Latin mode or the new token in the arity table when the input is a patched ROM.
4. Verify `$0ADE` side effects and the free-space range.
5. Decide whether to keep Japanese glyphs for text that is not translated (the font and its licence are settled, see [../fonts/decision.md](../fonts/decision.md)).
6. Other text paths (menus, item and monster names, battle messages) and whether they use this routine.
7. The Latin glyph table in this spike is `LATIN_CHARS` in `tools/build_latin_probe.py`: ASCII from `0x20` plus `ñÑ¿¡áéíóúüÁÉÍÓÚÜ`.
