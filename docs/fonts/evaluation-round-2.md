# Font Evaluation, Second Round

Status: **verified** for licences (read at the sources listed in [licenses.md](licenses.md) on 2026-11-20), character coverage, geometric fit and the in-game rendering of the narration window of the intro; **not verified** for other windows, bright backgrounds and any proportional rendering. The visual judgement is subjective. Nothing was replaced in the project: the engine hook and the build tools are the ones from the [latin font spike](../re/latin-font-spike.md), and no final font is chosen. The first round, with Sweet16mono, Spleen 8x16, Terminus and others, is in [evaluation.md](evaluation.md); this round uses the same method, the same tools and the same text so the results can be compared.

The project later took a font of its own instead of either candidate, see [decision.md](decision.md).

## What Was Evaluated

Priority: Royalty Mono, Scientifica, GohuFont (6x11), Pixelzone and Departure Mono. Additional: Fairfax SM, Dylex Terminal, Quest Square, Not Jam Novel and Cairopixel. They were compared with Sweet16mono, Terminus 16 and Spleen 8x16 from the first round.

## Method

1. **Licences** were read at the official source of each font (author site, repository or itch.io page); the result, the files used with their SHA-256 and the obligations are in [licenses.md](licenses.md). The itch.io downloads of SpicyGame and GGBotNet answered HTTP 429 to an automated request and were not retried, so the BDF of Royalty Mono, Quest Square, Pixelzone, Fairfax SM, Dylex Terminal, Not Jam Novel and Cairopixel comes from the FontPixel catalogue; this is a convenience copy that was not compared with the author's files.
2. **Conversion and fit** use the tools of the first round, unchanged: `tools/convert_font_art.py` places the 111 characters of the Spanish set (ASCII from `0x20` plus `ñÑ¿¡áéíóúüÁÉÍÓÚÜ`) in the 8x16 cell with fill 1 and an eight-neighbour outline of value 3, with one shared origin and baseline, and reports wide glyphs, clipped outlines and lost ink. Departure Mono is an OpenType file and was rasterized with `--format ttf --pixel-size 11`, the size of its design grid.
3. **Rendering in MesenCE** used `tools/build_latin_probe.py` and `tools/capture_font_probe.py` with the same route (reset, 600 frames, Start, A, 500 frames) and the same two lines as the first round: `¡Él, Ángel, ñoño! ¿Qué?` and `Mi vida: wmWM jgpqy ÚÜÑ.`. The three reference fonts were captured again in the same run. Departure Mono, GohuFont 11 and Royalty Mono were also built on four pages that cover all 111 characters.
4. The folders of `images/` are explained in [images/README.md](images/README.md). The captures are in `images/native/` at the native resolution of the emulator (256x224); the images in `images/in-game/` and `images/in-game-fullscreen/` are the same frames cropped or enlarged with nearest-neighbour. The charts in `images/charts/` (`*-chart-light.png`, `*-chart-diagnostic.png`) are drawn from the glyph data and are not emulator captures: the first shows the cell over a light green background, the second marks in red the outline pixels that fall outside the cell. They, and the stacked comparisons, were made with throwaway scripts that call `bitmap_font.py` and are not in the repository.

## Fit In The 8x16 Cell

"Clean" counts the glyphs that have neither a missing side outline nor a clipped outline. Heights are in pixels of the source bitmap.

| Font | Cap height | x-height | Widest ink x tallest ink | Wide glyphs | Outline clipped | Clean of 111 |
| --- | --- | --- | --- | --- | --- | --- |
| Sweet16mono (reference) | 10 | 7 | 8 x 15 | 12 | 17 | 94 |
| Terminus 16 (reference) | 10 | 7 | 7 x 15 | 10 | 15 | 96 |
| Spleen 8x16 (reference) | 10 | 7 | 8 x 15 | 78 | 79 | 32 |
| Departure Mono (11 px) | 8 | 6 | 7 x 13 | 1 (`#`) | 2 (`# {`) | 109 |
| GohuFont 11 | 8 | 5 | 6 x 11 | 0 | 0 | 111 |
| Fairfax SM | 7 | 5 | 5 x 12 | 0 | 0 | 111 |
| Royalty Mono | 6 | 5 | 5 x 11 | 0 | 0 | 111 |
| Scientifica | 7 | 5 | 5 x 11 | 0 | 0 | 111 |
| Pixelzone | 9 | 7 | 5 x 13 | 0 | 0 | 111 |
| Quest Square | 7 | 5 | 7 x 12 | 1 (`#`) | 4 (`# , ; j`) | 107 |
| Dylex Terminal 7x13 | 8 | 6 | 7 x 13 | 9 | 11 | 100 |
| Cairopixel | 7 | 5 | 9 x 12 | 24 | 107 | 1 |
| Not Jam Novel 16 | 10 | 7 | 9 x 16 | 12 | 105 | 1 |

Notes:

- All fonts cover the Spanish set, except **Not Jam Novel 13**, which lacks `ñÑáéíóúüÁÉÍÓÚÜ` (14 of 111 characters).
- A full outline needs ink of 6 pixels or less across and 14 or less down. Royalty Mono, Scientifica, Fairfax SM, GohuFont 11 and Pixelzone fit it for every character; Departure Mono needs two glyphs redrawn.
- A fit with no clipping is not the same as good use of the cell. The cap height is the measure of how large the text looks in a 16-pixel line: Sweet16mono and Terminus 16 draw 10-pixel capitals, Departure Mono and GohuFont 11 draw 8, and Royalty Mono draws 6. The Japanese glyphs of the game are 16x16 (the original glyph shapes were not compared in this round).

## What The Captures Show

Images, all in `images/in-game/`: `in-game-new-priority.png` (five new fonts and the three references), `in-game-new-extra.png`, and `in-game-departure-mono-pages.png`, `in-game-gohufont-11-pages.png`, `in-game-royalty-mono-pages.png` (all 111 characters). The outline in the intro window is a dark grey `(33,33,33)` on black, as in the first round, so the judgement below is about the letter shapes.

- **Departure Mono.** Every letter is distinct, including `M N W V X` and `m n w v`, and the accents, `ñ`, `¡` and `¿` read well. The stroke is light and the capitals are 8 pixels, so the text looks smaller and thinner than Sweet16mono. `#` and `{` lose some outline.
- **GohuFont 11.** Also distinct and plain, with complete outlines on every glyph; smaller (6x11 ink) and with a 5-pixel x-height, which makes lowercase look small in a 16-pixel line.
- **Fairfax SM.** Clean and readable like GohuFont, smaller still (capitals of 7).
- **Royalty Mono.** The slab-serif look is pleasant and suits a fantasy setting, but at 5 pixels of ink across the capitals and lowercase of similar letters merge: `M N W V X` on page 1 and `wmWM` on page 4 of `images/in-game/in-game-royalty-mono-pages.png` are hard to tell apart, and `M` and `W` look like blots. The 6-pixel capitals are also the smallest of the set. It fits the outline perfectly and fails on legibility.
- **Scientifica.** Letters of 4 to 5 pixels in a cell of 8 leave wide gaps, and `M W m w` lose their shapes. Too small.
- **Pixelzone.** A very tall and narrow face (letters of 3 to 4 pixels across, 9 tall): in a fixed cell it wastes the width, and the tilde of `ñ` is a flat bar. It reads as a condensed technical face and not as a fantasy one.
- **Quest Square.** Selective stencil breaks make body text harder to read; `#` is clipped.
- **Dylex Terminal 7x13.** Readable, but it is the classic X11 look with 7-pixel letters: 9 wide glyphs and 11 clipped outlines.
- **Cairopixel and Not Jam Novel.** Letters of 9 pixels across (and 16 tall in Not Jam Novel 16): they lose ink in the 8-pixel cell. Discarded without a rendering.

Coverage of the punctuation a Spanish script needs besides the Spanish set (present in the font, not fitted to the cell): Departure Mono, Terminus 16, Spleen 8x16, Fairfax SM, Royalty Mono, Scientifica and Pixelzone have `— « » … “ ” ‘ ’`; Sweet16mono and GohuFont 11 have `« »` and lack the dash, the ellipsis and the curly quotes.

## Proportional Spacing

The renderer was not changed, so this is an estimate with `tools/measure_text_width.py` on the same 794-letter sample of the first round (not the game script), with a row of 192 pixels.

| Advance | Letters per row | Source |
| --- | --- | --- |
| 8 px (current hook) | 24.0 | fixed cell |
| 7 px | 27.4 | Departure Mono |
| 6 px | 32.0 | GohuFont 11, Fairfax SM, Royalty Mono |
| 5 px | 38.4 | Scientifica |
| 4.9 px average | 39.1 | Quest Square (proportional) |
| 3.5 px average | 54.3 | Pixelzone (proportional) |
| 5.9 px average | 32.7 | Sweet16 widths + 1 px |
| 6.9 px average | 27.9 | Sweet16 widths + 2 px |

Only Pixelzone and Quest Square bring proportional widths of their own, and they bring them with the legibility problems described above; Pixelzone's 54 letters per row come from 3-pixel letters, which is the kind of density bought with clarity that this round was asked to avoid. Sweet16 keeps the best proportional path, because its widths belong to the same bitmaps that were already fitted. Departure Mono is monospaced; a 7-pixel pitch would be possible only with the compositor described in [proportional-spacing.md](proportional-spacing.md).

## Comparison And Ranking

The criteria are, in this order: legibility in the captures, completeness of the outline, size of the text in the line, compatibility with the current hook (every font converts with the same tool and the same 3552-byte block) and the licence burden. Aesthetic fidelity to Dark Law is a judgement of taste; the original is a Japanese font and the images are the evidence to judge it.

| Rank | Font | Why |
| --- | --- | --- |
| 1 | Sweet16mono | The largest and boldest letters (capitals of 10); clear in all pages. 17 glyphs to retouch. The simplest licence (BSL-1.0) and the only proportional path with ready widths. Lacks the dash, the ellipsis and the curly quotes. |
| 2 | Departure Mono | Almost complete outline (109 of 111), distinct letters, all the punctuation. Lighter and smaller than Sweet16mono (capitals of 8). OFL-1.1: the converted glyphs stay under the OFL and the licence text must ship. |
| 3 | Terminus 16 | Same size as Sweet16mono and complete punctuation, with 15 glyphs to retouch and letters that nearly touch each other in the capture; OFL with a Reserved Font Name. |
| 4 | GohuFont 11 | Complete outline on all glyphs and clear, but small and light; WTFPL. Lacks the dash and the ellipsis. A reserve if text of 8-pixel capitals is acceptable. |
| 5 | Fairfax SM | Complete and readable, smaller than GohuFont; OFL; the BDF comes from a mirror. |
| 6 | Pixelzone | Complete outline and CC0, but narrow and tall, with a flat `ñ`. |
| 7 | Spleen 8x16 | Heavy and wide: 78 wide glyphs. Not recommended in the first round. |
| 8 | Dylex Terminal 7x13 | Readable, but 11 clipped outlines and no advantage over the first three. |
| 9 | Quest Square | Stencil breaks make it unfit for body text. |
| 10 | Royalty Mono | Pleasant, but `M N W V X` and `m n w` merge and the capitals are 6 pixels tall. |
| 11 | Scientifica | Too small and condensed; provenance caveat on the licence. |
| - | Cairopixel, Not Jam Novel 16 and 13 | Discarded: they do not fit the 8-pixel cell; Not Jam Novel 13 also lacks the accents. |

## Recommendation For The Next Phase

- **Take to integration: Sweet16mono and Departure Mono.** They are the two that combine legible letters with a fit that can be repaired by hand: twelve wide glyphs and five descenders in Sweet16mono, two glyphs in Departure Mono. The choice between them is size and weight against licence and punctuation: Sweet16mono is larger and bolder, Departure Mono is cleaner in the outline and has the dash and the ellipsis that dialogue needs (those two would have to be drawn by hand in Sweet16mono).
- **Keep Terminus 16 as the fallback** it already was, and GohuFont 11 as a reserve with complete outlines.
- **Royalty Mono should not go on**, despite its look: the problem is the 5-pixel width of its letters, which no conversion of the outline can fix. If its style is wanted for something else, such as a title, it is a separate question, because titles are not drawn with the hook.
- **Before choosing between the two**, the open items of the first round matter more than a third font. The question of the outline has since been tested in the real field window: it is not needed for legibility and does not force any retouch, see [outline.md](outline.md). What remains open is a window with a light background (none was found) and the other window types.

## Limits Of This Round

- Only the narration window of the intro was rendered in the emulator. Its outline colour is a very dark grey on black; other windows were not captured.
- The BDF of seven fonts comes from a catalogue and was not compared with the authors' files; GohuFont, Departure Mono and Scientifica come from the authors' own repositories or releases.
- Departure Mono was rasterized at 11 px only; other multiples of its grid were not tried.
- The proportional figures are estimates on a sample text, not the game script, and nothing proportional was run in the emulator.
- The comparison of style with the original Japanese font is by eye and was not measured.

## Reproduction

```text
python tools/convert_font_art.py --format bdf --font royalty-mono.bdf --name royalty-mono --out art.txt --report
python tools/convert_font_art.py --format ttf --pixel-size 11 --font DepartureMono-Regular.otf --name departure-mono --out art.txt --report
python tools/build_latin_probe.py --rom "$DARK_LAW_ROM" --asar "$ASAR" --font-art art.txt --text "<two lines>" --out ../../roms/font-eval/departure-mono.sfc
python tools/capture_font_probe.py ../../roms/font-eval/departure-mono.sfc --out-dir captures --frames 500
python tools/measure_text_width.py --text-file docs/fonts/sample-text.txt --fixed 8 7 6 --bdf pixelzone.bdf --charwidths Sweet16_charwidths.txt
```

The test ROMs live in the workspace `roms/font-eval/` and are never committed. `capture_font_probe.py` needs `MESEN_BIN` and `MESEN_FOR_AI_DIR`; the TTF conversion needs Pillow.
