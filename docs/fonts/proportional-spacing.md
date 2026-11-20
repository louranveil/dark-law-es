# Proportional Spacing

Status: **analysis only**. The renderer was not changed and no proportional text was run in the emulator; the pictures of proportional text in [evaluation.md](evaluation.md) are simulations drawn from the glyph data. The engine facts come from [text-engine.md](../re/text-engine.md) and [latin-font-spike.md](../re/latin-font-spike.md); anything not read from there is marked as a guess.

## Why It Is Worth Studying

With the current hook every letter takes 8 pixels, so the narration window holds 24 letters per row. With the proportional widths of Sweet16 plus 2 pixels of spacing the same row would hold about 28 letters, and plus 1 pixel about 33 (see the table in [evaluation.md](evaluation.md); the sample text is not the game script). Pages that are already near the limit of the Japanese layout (61 of 4394 pages have more than 24 slots) would need to be split less often.

## What The Current Hook Does

- Each 16x16 slot has a 64-byte tile buffer (two top tiles and two bottom tiles) and four tilemap entries. The hook fills it with two 8x16 letters, so a slot is always two whole letters and the letter boundary always coincides with a tile boundary.
- The slot counter `$0A45` counts slots (0 to 23), not pixels; the line break `C3` and the window types derive the row from it (slot 12 for the second row in window type 1).
- Text is encoded as `F9 a b`, three bytes for two letters.

## What A Proportional Renderer Needs

1. **A pixel cursor.** A pen position in pixels inside the 192-pixel row replaces the slot counter as the unit of progress. A letter is drawn at `pen`, covers tile columns `pen >> 3` and possibly the next one, and the pen advances by the letter's width plus the chosen spacing. The slot counter would have to be derived from the pen (`pen >> 4`) for every other piece of code that reads `$0A45`; which pieces those are was not examined and is the main risk (guess: the line break, the page wait, window clearing and the text-speed delay).
2. **A width table.** One byte per letter (111 bytes); the widths of Sweet16 come from `Sweet16_charwidths.txt`, where the width excludes the spacing.
3. **A compositor.** Draw the letter by shifting each of its 16 rows right by `pen & 7` bits and merging it into the current tile column and the next one. The letters carry their own outline, so neighbours overlap in the outline pixels, and a plain OR is wrong: fill is value 1 (`01`) and outline is value 3 (`11`), so OR-ing an outline pixel over a fill pixel turns it into an outline pixel. The merge must let the fill win. Per row, with the two bitplanes `p0` and `p1` of destination `d` and source `s`:

   ```text
   fill    = (d.p0 & ~d.p1) | (s.p0 & ~s.p1)
   any     =  d.p0 | s.p0
   result  : p0 = any, p1 = any & ~fill
   ```

   Because the glyph art already includes the outline, no outline pass is needed at draw time.
4. **Tilemap setup.** Tile columns of a row map to the slot buffers in pairs (columns `2n` and `2n+1` belong to slot `n`); the tilemap entries for the row can be written once when the row starts, since the tile numbers are fixed per slot. Today they are written for each slot as it is drawn.
5. **A one-byte encoding.** In a Latin mode each byte is a letter index, so text costs 1 byte per letter instead of 1.5; the mode needs an opening token and a closing token, because the glyph codes `00`-`BF` are already Japanese. This also changes the script format and the encoder (`tools/script_format.py` treats `F9` as unmeasured today).
6. **Edge cases.** A word that does not fit in the rest of the row (line breaks are explicit `C3` commands, so the translator or a tool decides where to break; the tool would need the width table), a letter that would cross the right edge of the row, the page-wait indicator and any glyph the engine draws after the text.

## Cost And Risk

- CPU: shifting 16 rows of 2 bpp for each letter is more work than copying 64 bytes; how much slower the text appears depends on the delay the engine already inserts per character, which was not measured (guess: acceptable, since the delay is per glyph and dozens of cycles of compositing are small against a frame).
- Code size: the hook of the spike is about 400 bytes; a compositor with the shift and merge would be a few hundred more, well inside the 16 KiB of free space.
- Windows: only the narration window was measured. Other window types may not share the 24-tile row, so the pen limit would be per window type.
- Fallback: keep the fixed-cell hook; both could coexist, with a token choosing the mode per page.

## Which Font Supports It

Sweet16 is the natural choice: the author ships proportional widths for the same bitmaps, so the glyphs and the 8x16 outline work stay valid. For fixed-pitch fonts of a smaller size (Cozette, Spleen 6x12, Terminus 12, Monogram) the compositor would use a constant advance of 6 pixels, which gives about the density of Sweet16 plus 1 pixel.

## Suggested Order

1. Finish the fixed-cell font (redraw the wide glyphs, check a bright window).
2. Measure the other window types, to know whether 192 pixels per row is general.
3. Read the code that uses `$0A45` and `$0ADE`.
4. Prototype the compositor in the narration window only, behind a token, and compare against the fixed hook in the emulator.
