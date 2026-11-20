# Message Window Types

The engine has several message windows. Each one has its own text loop, its own slot counter and its own slot tables, so the capacity of a page and the code that draws it depend on the window. Notation follows [text-engine.md](text-engine.md); the Latin draw hook is in [latin-font-spike.md](latin-font-spike.md).

## Summary

| Loop | Glyph read at | Counter | Slots | Layout | Tables (tilemap / buffer / tile number) | Seen in the game |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `$D1:4571` | `$0A45` | 24 | 2 rows of 12 | `$D1:46AB` / `46DB` / `470B` | **Verified**: window type 1 (intro narration, character creation, the descriptions under menus) |
| 2 | `$D1:4767` | `$0A47` | 32 | 2 rows of 16 | `$D1:4873` / `48B3` / `48F3` | **Verified**: window type 2 (field messages) |
| 3 | `$D1:495F` | `$0A47` | 32 | same tables as loop 2 | `$D1:4873` / `48B3` / `48F3` | Not seen |
| 4 | `$D1:4A97` | `$0A47` | 32 | 2 rows of 16, other VRAM tiles | `$D1:4BA3` / `48B3` / `4BE3` | Not seen |
| 5 | `$D1:4C5B` | `$0A49` | 16 | 1 row of 16 | `$D1:4D70` / `4D90` / `4DB0` | Not seen |

Status of the table: loops 1 and 2 are **verified** by the draw code, by running them in MesenCE (an exec watch on the loop saw the field message go through loop 2 and the narration through loop 1) and by drawing Latin text with a hook in each. Loops 3, 4 and 5 are **read from the code only**: their tables were dumped, but no window was seen using them, so their purpose and screen position are unknown (**guess**: other kinds of boxes, such as a second line of text, a caption, or a choice box).

Each loop has the same shape: read a byte, glyph below `C0`, wide prefixes `FA`-`FD`, `E5` (skip slots), `C3` (line break), the rest handed to the command dispatcher. A glyph is 32 bytes for the top half plus 32 bytes at `+0x100` for the bottom half, copied to a WRAM buffer and shown through four tilemap entries, so the data format is the same in all of them.

## Geometry

Slot tables (all values dumped from the ROM):

- Loop 1: tilemap `A388`-`A3B4` (slots 0-11, 4 bytes apart) and `A408`-`A434` (slots 12-23); tile numbers `22C0`-`22CE`, `22E0`-`22EE`, `2300`-`230E`; each slot writes 4 tilemap entries (`t`, `t+1`, `t+0x10`, `t+0x11` at `+0`, `+2`, `+0x40`, `+0x42`). The window is shown in the 256-dot wide mode of the intro.
- Loop 2: tilemap `A6D4`-`A6F2` and `A754`-`A772`, 2 bytes apart, two entries per slot (`t` at `+0` and `t+0x10` at `+0x40`). The screen is in the 512-dot wide mode (the screenshots are 512 by 448) and each map entry covers 16 dots, which is why a slot is still 16 by 16 dots: the box takes about half the width of the screen. Tile numbers `2240`-`224E`, `2260`-`226E`, `2280`-`228E`, `22A0`-`22AE` (4 rows of 8 slots, so the 32 slots use buffers `B080`-`B760`).
- Loop 4: the same slot positions shifted 2 bytes (`A6D2`-`A770`) and tile numbers `2380`-`23EE`, with the loop 2 buffers.
- Loop 5: tilemap `570C`-`5748` (4 bytes apart, one row), the loop 1 buffers (`AA80`-`AD60`), tile numbers `2180`-`21AE`.

Verified measure of loop 2: the first field message has 13 glyphs on its first row and 10 on its second. At 16 dots a glyph the first row spans 207 of the 512 dots.

## Line Break And Skips

`C3` is handled at `$D1:4E75` by window type (`$0A4C`): type 1 sets slot `$0A45` to 12 (the start of the second row); types 2, 5 and 6 set `$0A47` to `$10` (the start of the second row of loop 2); types 3 and 4 do nothing (**verified** in the code; only types 1 and 2 were run). A page that fills a row exactly and then sends `C3` does not leave a blank row in type 1 (seen in the emulator).

## Where The Types Are Set

`$0A4C` is written by the state machine of the command dispatcher. A scan of the ROM for `STA $0A4C` finds these instructions (the value is the immediate loaded just before): type 1 at `$D1:21EA`, `2BAE`, `2C9B`, `$C1:0064`, `$C4:EFC5`, `$C4:F12C`; type 2 at `$D1:223D`, `2C27`, `2CB6`, `35BA`, `4501`; type 3 at `$D1:0579`, `1AC1`; type 4 at `$D1:220F`, `2C80`, `2CDD`; type 5 at `$D1:2225`, `371C`; type 6 at `$D1:3844`; and a `STZ` (type 0) at `$D1:4453`. A write watch on `$0A4C` shows only the value 1 through the whole intro and the character creation (the writers it reports are the instructions before `$D1:2BB1` and `$D1:2C9E`, the program counter after each store), and the values 0, 1 and 2 during the first minutes of play in the field. Types 3 to 6 were not reached. Which command selects each type is not decoded.

## Other Text Paths

`JSL $D2:009C` and `JSL $D2:00D2` have callers outside these loops: `$C0:BA65`, `BB06`, `BBED`, `$C1:0228`/`0230`, `$C4:462A`/`4632`, `$C4:56A7`, `$C4:F43D`/`F50D`, `$CD:1831`/`1839`, `$CE:0510`/`0518` and `$D1:306C`. They are the other places that draw glyphs (menus, status screens, the name entry grid, battle, shops are the candidates, **guess**); none of them was analyzed. Fixed menu labels drawn from other data may not go through any script at all.

## Open Items

1. Reach windows of types 3 to 6 (and loops 3 to 5): choice boxes, shops, battle, and dialogue with portraits are the likely places.
2. Decode which command selects each type.
3. Analyze the other callers of the glyph routines.
4. A hook for each loop that was not run (the comparison with `E5` is at `$D1:4975`, `$D1:4AAD` and `$D1:4C71`, each followed by a `CMP #$C3`), tested in a window that uses it.
5. The reproducible route to the field: the savestates and scripts used here are throwaway (character creation needs a letter, 決定, the bonus counter at WRAM `$1180` set to 0, and answers to a yes/no box), see [latin-font-spike.md](latin-font-spike.md).
