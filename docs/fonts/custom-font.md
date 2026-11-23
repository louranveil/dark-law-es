# Font Of Our Own: Prototype 1

Status: **prototype**, chosen as the project font for now (see [decision.md](decision.md)); verified in MesenCE in the intro narration window (type 1, black) and in the field message window (type 2, brown) with all 111 characters of the game set. The probe builder uses it by default; the translation build does not exist yet. The judgement of how it looks is subjective; the captures are there to make it.

## Why

The evaluations ([evaluation.md](evaluation.md), [evaluation-round-2.md](evaluation-round-2.md)) end with Sweet16mono and Departure Mono as the candidates, both of them fitted to the cell afterwards. [outline.md](outline.md) removed the last reason to design around a 6x14 body: the outline is not needed for legibility, so a font of our own can use the cell as it wishes.

## Constraints That Fix The Design

- **Cell:** 8x16, 2 bpp, fill 1 and outline 3, fixed advance of 8 pixels (24 letters per row in the narration window and 64 per page in the field, see [../re/window-types.md](../re/window-types.md)). Proportional spacing is a renderer change and is out of scope.
- **Glyph set:** the 111 characters of the spike (printable ASCII, `ñÑ¿¡áéíóúüÁÉÍÓÚÜ`) plus four typographic marks that Spanish dialogue wants, `— … « »`, appended at indexes 111-114 so the earlier indexes do not move: 115 letters in all (`CORE_CHARS` and `EXTRA_CHARS` in `tools/build_custom_font.py`). The dotless `ı`, used as a base for `í`, is in the source but not in the set.
- **Outline:** generated from the ink by the build tool, not drawn. It is optional (`--outline none`) and clipped by the cell where the ink touches an edge.
- **Vertical metrics:** capitals and ascenders in rows 3-12 (10 pixels), x-height from row 6 (7 pixels), descenders to row 15, accents on capitals in rows 0-1 and on lowercase letters in rows 3-4, always with an empty row between the mark and the letter. Cap height and x-height equal those of Sweet16mono, so the two are comparable at the same size.
- **Horizontal metrics:** capitals 6 pixels wide (columns 1-6), lowercase 5 (columns 1-5), so that a full outline fits in the cell on both sides.
- **Licence:** original work of this project, under the MIT licence of the repository. No glyph was copied from another font; the shapes follow the usual conventions of one-pixel monospaced bitmap fonts.

## Files

- `assets/font/latin-8x16.txt`: the source. Only ink is drawn (`X`), by hand, with `top` and `left` placing each block in the cell; marks are pixel lists; `compose`, `flip` and `rotate` build the accented letters, `¡` and `¿` from the base glyphs. The comment at the top of the file describes the format.
- `tools/build_custom_font.py`: reads the source, composes, generates the outline and writes the font art that `build_latin_probe.py --font-art` reads. It reports coverage of the game set and the glyphs whose outline the cell clips. Tests: `tests/test_build_custom_font.py` (parsing, composition, outline, coverage of the real source and acceptance by the probe builder).

```text
python tools/build_custom_font.py --source assets/font/latin-8x16.txt --out <art.txt> [--outline full|none]
python tools/build_latin_probe.py --rom <original.sfc> --asar <asar> --font-art <art.txt> --text "..." --out <probe.sfc>
```
- `tools/export_font.py`: exports the same source as a TrueType font, `assets/font/dark-law-latin.ttf` (see the next section). Tests: `tests/test_export_font.py`.

## TrueType Export

`assets/font/dark-law-latin.ttf` is the font in the usual format, to type with, preview and share it in any editor, and to compare it with other fonts. It is **generated** from the source and can be rebuilt at any time:

```text
pip install fonttools
python tools/export_font.py --source assets/font/latin-8x16.txt --out assets/font/dark-law-latin.ttf [--version 0.2]
```

- **Content:** the fill only, 116 glyphs (the 111 of the game set and `— … « »` and the dotless `ı`) and a hollow-box `.notdef`. The game outline is not part of it; `build_custom_font.py` adds it for the ROM.
- **Metrics:** 1600 units per em, 100 per pixel; advance 800 (8 px), ascent 1300, descent 300, so the em is the 16-pixel line of the game cell; monospaced; cap height 1000 and x-height 700. Family "Dark Law Latin", MIT licence like the repository.
- **Outlines:** every pixel is a square of the vector outline, merged into polygons (diagonal pixels share one contour, holes run the other way).
- **Sizes:** exact at 16 px and at whole multiples of it (32, 48, 64...) with no anti-aliasing; at any other size it is blurry or uneven, as every pixel font. Use a bilevel (non-anti-aliased) rendering.
- **FreeType:** without instructions, FreeType's auto-hinter moved the top pixel of the acute accent up one row in the first export. The font carries empty `fpgm` and `prep` programs and a `gasp` table (grid-fit, no smoothing) so that it keeps its coordinates. With Pillow (FreeType) the 116 glyphs render pixel-exact at 16, 32, 48, 64 and 160 px, and a test checks it at 16, 32 and 48 px.
- **Checked:** FreeType through Pillow (the pixel-exact test above) and the Windows font viewer, which opens the file as "Dark Law Latin Regular (TrueType)", version 0.1 (the first export), and draws the specimen at 12 to 72 pt (the user's screenshot of 2026-11-20). **Not checked:** macOS, browsers, and the font installed and used in an editor.
- `images/charts/custom-ttf-specimen.png` shows the font at 32 and 16 px (drawn from the TTF, not an emulator capture).
- **Dependency:** `fontTools` is optional and imported late, like Pillow in `bitmap_font.py`. Without it `export_font.py` exits with code 1 and the tests that need it are skipped; `build_custom_font.py` and the ROM probes do not use it.

## Result

Numbers from the sources and from the build report (`build_custom_font.py` and the font-art metrics of the earlier rounds):

| | Our font, prototype 1 | Sweet16mono |
| --- | --- | --- |
| Characters of the game set | 115 of 115 | 113 of 115 (dash and ellipsis missing) |
| Cap height / x-height | 10 / 7 | 10 / 7 |
| Mean ink width of the letters | 5.3 pixels | 6.1 pixels |
| Mean ink pixels per letter | 19.3 | 19.9 |
| Glyphs with the outline clipped by the cell | 12 (`_gjpqy` and `ÁÉÍÑÓÚ`: the cell edge at the top and the bottom; none at the sides) | 17, plus 12 glyphs wider than the cell (round-1 fit report, [evaluation.md](evaluation.md)) |
| Ink lost to the cell | 0 | see the fit report of round 1 |
| Letters per 192-pixel row | 24 | 24 |

The captures, all in `images/`:

- `in-game/in-game-custom-pages.png`: the four test pages in the intro window (every character of the set, the mixed pages and the Spanish sentences).
- `in-game/in-game-custom-field.png`: the field window with the same text, from top to bottom: our font with outline, without outline, the bold experiment (below) and Sweet16mono.
- `native/field-custom-*-native.png` and `native/custom-intro-native.png`: the raw frames.

What the captures show:

- **Legibility.** Every letter of the test lines reads, including `wmWM`, `jgpqy`, `ñ`, the accented capitals and the inverted marks. The mixed capitals (`MWTVY`) and `mvwx` are distinct; `Q` and `O`, `0` and `O`, `1` and `l` are told apart by the shapes alone.
- **Weight.** One-pixel strokes with the game outline look lighter than the Japanese text of the same window, the same as in the other fonts, and a little narrower than Sweet16mono, whose letters average 6.1 pixels of ink against 5.3. Without the outline the text is thin but clear on the brown panel, in line with [outline.md](outline.md).
- **Accents.** The two-pixel acute, the two dots and the tilde are small but visible in both windows and never touch the letter. Capitals take rows 0-1, so on the first row of a window their accent sits at the very top of the glyph cell.
- **Spacing.** With 5 to 6 pixels of ink in 8, the gap between letters is 2 to 3 pixels: airy, and a full outline leaves a dark band between neighbours instead of merged letters.
- **Bold experiment (discarded).** Smearing every glyph one pixel to the right to get two-pixel strokes fills the counters of `m`, `w`, `M` and `W` into blocks (`wmWM` becomes unreadable). Heavier strokes need glyphs drawn for them, not a filter.
- **Weakest glyphs, retouched.** The first draft left `# $ % & @ ~ ^ { }`, `* < >` and `¡` rough. Seen at 8x and in the game, the second pass changed: `#` to the full cap height with its bars centred; `$` into a plain `S` with a tick above and below instead of a two-pixel stem through the body; `%` into two small round marks joined by a clean diagonal (it was one row short and lumpy); `&` redrawn with a closed upper loop and an open tail; `@` kept with a cleaner right edge of the inner letter; `{ }` redrawn four pixels wide with a point in the middle, like `( )` but distinct; `< >` enlarged from 5 to 7 rows and 4 pixels wide; `~` widened to 6 pixels; `!` and so `¡` with the stem shortened to six rows and two empty rows before the dot, which lightens the block that looked like a bold `i`. `^` and `*` were left as they were. All of them still read as weaker than the letters, but they were then put in the field window with real text (`in-game/in-game-custom-symbols.png`: `Tom & Mia: 50% de MW, Q&A @casa` and `WQMN OQ0 &&@@ %%50 MWMW {x} <y>`): `&`, `@` and `%` read in a sentence, `O`, `Q` and `0` are told apart, and `M`, `W` and `N` too. At 1x `%` is the closest to an `x` with dots; nothing was changed after seeing it. The row holds 32 letters, so the ends of the two lines (` #1`, ` $9`) fell outside the window: that is the field window width ([../re/window-types.md](../re/window-types.md)), not the font.

## Limits

- The source is a first draft by one author with no typographic review; the quality of the symbols is below that of the letters.
- Only two windows were rendered with it (type 1 and type 2). The other windows and the menus that draw glyphs through other routines were not tested; a light window was not found.
- The four extra marks work in the hook (`in-game/in-game-custom-extras.png`: both windows, the intro line lost its last character only because it had 25 letters in a 24-letter row). A font passed with `--font-art` that lacks them gets a hollow box in their place.
- The comparison with Sweet16mono and the other candidates is visual and from one test text; no reader tested it.
- The throwaway scripts that built the pages, drove the emulator and composed the images are not in the repository; the build tools and the probe and capture tools are.

## Next Steps

1. Show the retouched symbols to a second reader; `%` is the weakest at 1x.
2. Decide the stroke weight with the user (1 pixel as drawn, or a second source drawn for 2 pixels) and whether to keep the outline in all windows.
3. Write the pipeline that turns the Spanish script into `F9 a b` tokens with this set (see [decision.md](decision.md)).
