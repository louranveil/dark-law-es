# Is The Outline Needed

Status: **verified** in MesenCE for the field message window (window type 2) and, from the earlier rounds, for the intro narration window (type 1); **not verified** for any window with a light background, because none was found, and for window types 3 to 6. The visual judgement is subjective; the contrast numbers are computed from the captures.

## Question

The game draws its glyphs with fill value 1 and outline value 3, and the font evaluation in [evaluation.md](evaluation.md) and [evaluation-round-2.md](evaluation-round-2.md) fitted every font into the 8x16 cell with a one-pixel outline. That requirement is what clips the wide letters and the descenders of Sweet16mono and Terminus 16. If the outline is not needed, the requirement can go.

## What The Real Windows Look Like

The intro narration window is black, so it says nothing about the outline. The windows of the field and of the menus are a **brown textured panel**, as the first of the captures below shows with the original Japanese text. This was measured on the field message window:

- The outline colour is the same dark grey `(33,33,33)` in the original Japanese glyphs and in the Latin test fonts (4215 and 6677 pixels next to white respectively in the two crops), so the converted fonts reproduce the colour the game uses.
- The window is dark where the text sits. Contrast ratios (WCAG formula) of the white fill and of the outline against the background texture of the text area:

| Background of the text area | White fill against it | Outline against it |
| --- | --- | --- |
| Darker tenth of the pixels `(33,0,0)` | 19.7 : 1 | 1.2 : 1 |
| Median `(74,33,0)` | 13.9 : 1 | 1.2 : 1 |
| Brighter tenth `(115,82,41)` | 7.1 : 1 | 2.3 : 1 |
| Brightest 1 percent `(148,107,41)` | 4.8 : 1 | 3.4 : 1 |

White against the brown never goes below 4.8 : 1, so the fill carries the legibility by itself. The outline is hardly distinguishable from the background for most of the window (about 1.2 : 1) and only separates the letters in the lighter streaks of the texture.

## Test

The test ROMs replace the field messages with the two test lines (`¡Él, Ángel, ñoño! ¿Qué?` and `Mi vida: wmWM jgpqy ÚÜÑ.`); the probe builder replaces one entry of the message table, so for the capture every entry of the table at `$E7:362B` was pointed to that text in the test ROMs, to make the result independent of which message the game picks. The route is driven from RAM and not from pixels (see the last item of [../re/window-types.md](../re/window-types.md)): from the field savestate, 18 steps down and 4 steps left open the field message window, detected by `$0A4C` going from 1 to 2, and the frame is taken 420 frames later. All the ROMs opened the window at the same step and position. A second set of ROMs was built from the same art with every outline pixel set to background, nothing else changed.

Images, all in `images/in-game/` and `images/native/`:

- `in-game-field-window.png`: the original Japanese message and the same window with Sweet16mono, Terminus 16, Departure Mono and GohuFont 11, with outline.
- `in-game-field-outline-compare.png`: Sweet16mono and Departure Mono with and without outline, same window and same text.
- `native/field-*-native.png`: the full 512x448 frames (the field is drawn in high resolution).

## Result

- **The outline is not needed for legibility** in this window. Without it, every letter of the test lines, including `wmWM`, `jgpqy`, `ñ` and the accented capitals, reads as well as with it; the white strokes stand out from the brown on their own.
- **The outline changes the weight and the look, not the readability.** With it the text is heavier and closer to the Japanese glyphs, which have the same dark halo; without it the strokes are thin (1 pixel) and the text looks lighter and smaller. That is a matter of taste, and the captures are there to judge it.
- **The clipped outlines are not a defect to repair.** The wide letters and the descenders that lose part of the halo (12 and 5 glyphs in Sweet16mono) look fine in the captures with the current fit, so redrawing them is optional.

## Consequences For The Font Choice

- Fit is no longer a reason to prefer a smaller font. Without the outline requirement Sweet16mono and Terminus 16 fit completely (no ink is lost in either of them), and the ranking of [evaluation-round-2.md](evaluation-round-2.md) is decided by letter shapes, size, punctuation coverage and licence. Departure Mono keeps its advantage in punctuation and loses its advantage in outline fit; Sweet16mono keeps the largest letters (capitals of 10 pixels against 8).
- The recommendation to take Sweet16mono and Departure Mono to the integration phase stands. What changes is that neither needs a glyph retouch before the integration, and the outline can be chosen per glyph: keep it where it fits, and let it go where it would clip.
- A font of our own, discussed after the second round, would not need to be designed around a 6x14 body, and could use the full 8x16 cell.

## Limits

- Only two windows were rendered with the Latin fonts, the black intro window and the field message window. The menu windows and the status screen share the brown texture in the original captures, but no Latin text was drawn in them. A window with a light background was not found; the contrast numbers say that the fill would stand out less there, and nothing else is known.
- The outline colour is read from the palette of the field window; other windows may use other palettes.
- The measurement uses the text area of the field window (the crop `x 140-400, y 296-368` of the 512x448 frame), which contains only the text and the panel.
- The inputs that open the field message come from a throwaway savestate (`field-start`, outside the repository). The throwaway scripts that drive the emulator and draw the images are not in the repository either.
