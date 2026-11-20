# Latin Font Evaluation

Status: **verified** for licences, character coverage, geometric fit and the in-game rendering of the narration window of the intro; the visual judgement is subjective. Nothing was replaced in the project: the engine hook and the build tools are the ones from the [latin font spike](../re/latin-font-spike.md), and no final font is chosen yet. Licence details and the attribution each font would need are in [licenses.md](licenses.md); what a proportional renderer would change is in [proportional-spacing.md](proportional-spacing.md).

## Recommendation

Use **Sweet16mono** (Martin Sedlák, Boost Software License 1.0) as the working font and the first candidate for the release.

- Licence: the most permissive of the fonts that fit; it allows derivative works and does not require credit for object code, and the project should credit it anyway.
- Technical fit: native 8x16, one-pixel strokes like the original `#-#` stroke profile of the game font, all 111 Spanish characters present, 94 of 111 characters take a complete one-pixel outline without any change.
- Look: clean, neutral and readable at the game's size; capitals with accents (`ÁÉÍÓÚÜÑ`), `¡` and `¿` are distinct.
- Growth path: the same author publishes a proportional variant with the same drawing style, so the compositor work described in [proportional-spacing.md](proportional-spacing.md) can later reuse the glyph set, and the glyphs that do not fit can be redrawn once for both.

Known defects to fix before shipping: 12 glyphs are 7 or 8 pixels wide and lose part of their outline (`% & @ M T V W Y m v w x`), and the bottom outline of the descenders `g j p q y` is cut by the cell edge. Both are listed under Open Items.

Second choice: **Terminus 16** (OFL-1.1), practically the same fit and look (10 wide glyphs), with licence conditions that need more care (Reserved Font Name, OFL on the glyph bytes). Fallback for a denser text: **Cozette** or **Spleen 6x12** after a proportional or 6-pixel path exists.

## What The Engine Needs

From [latin-font-spike.md](../re/latin-font-spike.md) and [font.md](../re/font.md):

- The game font is 16x16, 2 bpp, with value 1 for the fill and 3 for the outline; value 0 is the background. A stroke is `#-#`, with a one-pixel fill.
- The spike hook draws two 8x16 letters in one 16x16 slot (token `F9 a b`). A letter is 32 bytes: the top tile and the bottom tile of an 8x16 column. The tool reads letters as text art, 16 rows of 8 symbols (`.` 0, `-` 1, `+` 2, `#` 3).
- An 8x16 cell with a one-pixel outline on every side leaves a **6x14 body**: at most 6 pixels of ink across and 14 rows of ink from the top of the tallest accent to the bottom of the deepest descender.
- The narration window of the intro is 2 rows of 12 slots, so 24 letters per row with a fixed 8-pixel advance.
- Free space for the font: `$D2:C000`-`$D2:FFFF` (16 KiB); 111 letters take 3552 bytes.

## Method

1. Licences were read from the official sources (see [licenses.md](licenses.md)).
2. Each font was loaded as a bitmap: BDF for Spleen, Terminus, Cozette, Monogram and Orp; the author's `.f8` for Sweet16; `.hex` for Unscii; Pixel Operator is a vector TTF made of pixel squares and was rasterized at its native size without antialiasing.
3. `tools/convert_font_art.py` places each of the 111 characters of the Spanish set (`LATIN_CHARS` of `build_latin_probe.py`: ASCII from `0x20` plus `ñÑ¿¡áéíóúüÁÉÍÓÚÜ`) in the 8x16 cell with fill 1 and a one-pixel outline of value 3 (eight-neighbour, like the original glyphs). One origin column and one baseline row are shared by all letters and are chosen to lose the least ink first and the least outline second; no glyph is moved individually unless `--allow-shift` is given.
4. The same tool reports the missing characters, the widest ink, the ink height of the whole set and the characters that lose outline. The numbers below come from that report.
5. `tools/build_latin_probe.py` built one test ROM per font (a ROM in the workspace `roms/font-eval/`, never in the repository) with the same two lines of text, and `tools/capture_font_probe.py` ran each one in MesenCE through the intro route (reset, 600 frames, Start, A, 500 frames) and saved the frame. The text exercises every difficult glyph: `¡Él, Ángel, ñoño! ¿Qué?` and `Mi vida: wmWM jgpqy ÚÜÑ.`.
6. `tools/measure_text_width.py` compared fixed and proportional spacing on a Spanish sample of 794 letters (`docs/fonts/sample-text.txt`, written for this evaluation; it is not the game script).

## Comparison

"Wide" is the number of the 111 characters whose ink is 7 or more pixels wide, so a full outline does not fit horizontally. "Outline cut" is the number whose outline is clipped by the cell after the best common placement. No font lost ink.

| Font | Native size | Stroke | Missing | Ink width max | Ink height (set) | Wide | Outline cut | Licence | Looks in game |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sweet16mono | 8x16 | 1 px | none | 8 | 15 | 12 | 17 | BSL-1.0 | Clean, light, good accents |
| Spleen 8x16 | 8x16 | **2 px** | none | 8 | 15 | 78 | 79 | BSD-2-Clause | Heavy; the outline sticks to the left edge |
| Terminus 16 | 8x16 | 1 px | none | 7 | 15 | 10 | 15 | OFL-1.1 (RFN) | Clean, a little more upright than Sweet16 |
| Spleen 6x12 | 6x12 | 1 px | none | 6 | 12 | 0 | 0 | BSD-2-Clause | Clean, small, airy in an 8 px cell |
| Terminus 12 | 6x12 | 1 px | none | 6 | 12 | 0 | 0 | OFL-1.1 (RFN) | Like Terminus 16, smaller |
| Cozette | 6x13 | 1 px | none | 6 | 13 | 0 | 0 | MIT (provenance caveat) | Rounded, friendly, readable |
| Monogram | 5x9 | 1 px | none | 5 | 12 | 0 | 0 | CC0-1.0 | Charming but small and thin |
| Orp medium | 6x12 | 1 px | none | 6 | 12 | 0 | 0 | **unclear** | Readable |
| Unscii 16 | 8x16 | 2 px | none | 8 | 16 | 25 | 37 | Public domain | Heavy, blocky |
| Pixel Operator | 16 px | 1 px | none | 7 | 15 | 6 | 13 | CC0-1.0 (single source) | Light, but the acute accent reads as a dot (`É` looks like `Ė`) |
| Pixel Operator Mono | 16 px | 1 px | none | 8 | 15 | 7 | 13 | CC0-1.0 (single source) | Same accent problem |

The captures are in `docs/fonts/images/`: `in-game-priority.png` (Sweet16mono, Spleen 8x16, Terminus 16), `in-game-compact.png` (Spleen 6x12, Terminus 12, Cozette, Monogram, Orp) and `in-game-other.png` (Unscii, Pixel Operator). They are crops of the text window at 3x.

### Why The Wide Fonts Are Judged On Stroke And Outline

An 8-pixel cell with an outline on both sides can hold 6 pixels of ink. Fonts designed for an 8-pixel advance (Spleen 8x16, Terminus 16, Sweet16mono, Unscii) normally use 6 or 7 columns of ink plus a gap, so some outline is always lost. With a 1-pixel stroke (`Sweet16mono`, `Terminus 16`) the common letters take 6 columns and fit; only a dozen wide letters lose their outline on one side. With a 2-pixel stroke (`Spleen 8x16`, `Unscii`) almost every letter is 7 columns wide and the outline is lost on the left of nearly all of them, and the fill value 1 plus the outline makes strokes four pixels thick, much heavier than the original three-pixel `#-#`. That is why Spleen 8x16, the second font in the requested priority list, is not recommended even though its licence is fine.

### What Was And Was Not Verified In The Game

- Verified: all 11 test ROMs run, and the same hook draws every font; every Spanish character in the test lines renders, including `¡ ¿ ñ Ñ`, the acute accents on capitals, `ü Ü`, and descenders. The probe builder changes only the allowed regions.
- Not verified: the intro window is black, so the outline (value 3, dark) cannot be seen in the captures. The outline was checked with a simulation drawn from the same glyph data over a light background, `images/simulated-light-background.png`, which is not an emulator capture. A window over a bright background in the real game is still to be looked at.
- Not verified: windows other than the intro narration (portrait dialogue, menus, battle messages) and the Japanese text after the message; the spike checked the latter for the first font only.
- The test text was drawn only in fixed 8-pixel cells; the proportional variants were never run in the emulator because the renderer does not support them.

## Spacing

Letters per 192-pixel row and rows needed for the 794-letter Spanish sample, wrapping at word boundaries (from `tools/measure_text_width.py`; the sample is not the game script, so read these as ratios):

| Spacing | Px per letter | Letters per row | Rows for the sample |
| --- | --- | --- | --- |
| Fixed 8 px (current engine) | 8.00 | 24.0 | 36 |
| Sweet16 proportional, width + 3 px | 7.88 | 24.4 | 36 |
| Sweet16 proportional, width + 2 px | 6.88 | 27.9 | 32 |
| Sweet16 proportional, width + 1 px | 5.88 | 32.7 | 28 |
| Fixed 6 px (Cozette, Monogram, Spleen 6x12 advance) | 6.00 | 32.0 | 29 |

Width + 2 px (a one-pixel gap between the ink of neighbours plus the shared outline) is the legible setting in `images/simulated-light-background.png`; width + 1 px is denser but the outlines merge into a single dark pixel between letters. The gain is about 16 percent of text per row at +2 and about 36 percent at +1, against a hook that needs a pixel-level compositor (see [proportional-spacing.md](proportional-spacing.md)). A 6-pixel fixed pitch would give about the same density as +1 but needs the same compositor, because the engine places letters in 8-pixel cells.

## Discarded Or Deferred

| Font | Decision | Reason |
| --- | --- | --- |
| Spleen 8x16 | Discarded as the main font | 2-pixel strokes, 78 wide glyphs; outline cut on 79 |
| Unscii 16 | Discarded | 2-pixel strokes, 25 wide glyphs; also its `-full` variant is GPL and must not be used |
| Pixel Operator | Discarded | The acute accent is one pixel and reads as a dot over the capital; the primary site and repository are gone, so the CC0 statement has a single source |
| Orp | Discarded | No licence file; derived from ProFont (MIT) while declared public domain |
| Monogram | Deferred | CC0 and clean, but 5x9 leaves four unused rows in a 16-row cell and is thin; it would suit a compact path |
| Cozette, Spleen 6x12, Terminus 12 | Deferred | Fit with a full outline but waste the 8x16 cell; they pay off only with a denser path. Cozette's licence chain (Dina, Proggy) was not verified |

## Reproduce

The font files are not in the repository; download them from the sources in [licenses.md](licenses.md) into a scratch directory, then, with the workspace virtual environment:

```text
python tools/convert_font_art.py --format f8 --font Sweet16mono.f8 --name sweet16mono --out sweet16mono.txt --report
python tools/convert_font_art.py --format bdf --font spleen-8x16.bdf --name spleen8x16 --out spleen8x16.txt --report
python tools/convert_font_art.py --format bdf --font ter-u16n.bdf --encoding latin-1 --name terminus16 --out terminus16.txt --report
python tools/build_latin_probe.py --rom "$DARK_LAW_ROM" --asar "$ASAR" --font-art sweet16mono.txt --out ../../roms/font-eval/sweet16mono.sfc
python tools/capture_font_probe.py ../../roms/font-eval/sweet16mono.sfc --out-dir captures
python tools/measure_text_width.py --text-file docs/fonts/sample-text.txt --fixed 8 6 --charwidths Sweet16_charwidths.txt --spacing 1 2 3
```

`capture_font_probe.py` needs `MESEN_BIN` and `MESEN_FOR_AI_DIR` (see `tools/README.md` of the workspace). Pixel Operator needs Pillow (`--format ttf --pixel-size 16`); everything else uses the standard library.

## Open Items

1. Redraw the 12 wide glyphs of Sweet16mono (`% & @ M T V W Y m v w x`) to 6 pixels or less, and decide what to do with the bottom outline of `g j p q y`: moving the baseline up one row would cut the outline of the capital accents instead. Sweet16 licence permits derivative works.
2. Look at a window over a bright background, and at the other window types once the sizes are known (the other session is measuring them).
3. Characters the Spanish script may need beyond the evaluated set: the dialogue dash `—`, `«` `»` and `…`. Sweet16 covers U+0000-U+017F, so `«` and `»` exist but the dash and the ellipsis do not.
4. Decide whether the proportional path is worth building; see [proportional-spacing.md](proportional-spacing.md).
5. Verify `$0ADE` side effects and the free-space range, as already noted in the spike.
6. The tools in `tools/bitmap_font.py` and `tools/convert_font_art.py` do not depend on Dark Law except for the output format; they are candidates for a generic repository, to be proposed when it is clear that other projects need them.
