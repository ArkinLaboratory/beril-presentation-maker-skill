# KBase brand extract for beril-presentation-maker

**Source:** *KBase Style Guidelines — PRINT & PRESENTATION, Updated June
2022.* Authoritative copy:
https://docs.google.com/document/d/1x7jjZxMvnDrbUtfZzNj2XIgGvCFG_Zv12Rh8FIWQXYI/edit?tab=t.0

This document extracts the brand tokens (color, typography, contrast
minima, layout discipline) from the KBase Style Guide that informed
SPEC §6.3 (density discipline), §14.1 (master template), and the
shipped `references/kbase-brand-tokens.json`.

If the upstream style guide is updated, regenerate
`kbase-brand-tokens.json` from the new canonical source and re-run
`tools/build_master.py` to refresh
`kbase-presentation-master.pptx`. (D-015: KBase style guide is
binding for color and typography.)

---

## 1. Logo (quoted)

> "The preferred logo (shown here) should be used on all internal and
> external communications whenever possible."

Available variants per the guide: preferred (with tagline), stacked,
symbol-with-text, symbol-only, social-media avatar, dark-background
reverses.

**v0.1 master template uses:** preferred-with-tagline on the title
slide; symbol-only on a fixed footer position for content slides;
acknowledgments slide carries the stacked-with-tagline variant.

### Spacing and sizing (quoted)

> "Be sure to leave 0.5x amount of room around all edges of the KBase
> logo to not crowd the logo. ... The clear space is derived from x,
> which is measured by the height of the symbol."

> "Minimum height of the symbol needs to be 0.5 in or 36 pt.
> Therefore, x ≥ 0.5 in (36 pt)."

**Informs SPEC §6** master-template footer height: ≥ 36 pt logo +
clear-space × 0.5 each side = footer-band height ≥ 54 pt total.

---

## 2. Primary color palette (quoted hex values)

The "core" palette: three "bright circles representing our ties to
microbes, plants, and communities" plus three derived companion
colors.

| Token | Pantone | CMYK | RGB | Hex |
|---|---|---|---|---|
| `microbe_orange` | 021 U | 0 / 53 / 100 / 0 | 247 / 142 / 30 | `#F78E1E` |
| `grass_green` | 370 U | 56 / 0 / 100 / 27 | 94 / 151 / 50 | `#5E9732` |
| `freshwater_blue` | 285 U | 89 / 43 / 0 / 0 | 0 / 125 / 195 | `#007DC3` |
| `golden_yellow` | 129 C | 0 / 16 / 100 / 0 | 255 / 210 / 0 | `#FFD200` |
| `spring_green` | 390 M | 22 / 0 / 100 / 8 | 193 / 205 / 35 | `#C1CD23` |
| `ocean_blue` | 319 U | 52 / 0 / 19 / 0 | 114 / 204 / 210 | `#72CCD2` |

These six are the v0.1 primary palette in
`kbase-brand-tokens.json` under `palette.primary`.

The style guide ships 80 % / 60 % / 40 % / 20 % tints per primary
color (e.g., `microbe_orange.t80 = #F9A455`). v0.1 brand tokens
include the tints; the slide-compose prompt prefers the base hue for
emphasis and the 60 % / 40 % tints for backgrounds.

---

## 3. Secondary palette (quoted hex values)

The "secondary palette ... contrasting vibrant and deep values—adding
variety to keep materials from looking homogeneous."

| Token | CMYK | RGB | Hex |
|---|---|---|---|
| `cyanobacteria_teal` | 84 / 19 / 54 / 2 | 0 / 150 / 136 | `#009688` |
| `lupine_purple` | 72 / 85 / 0 / 0 | 102 / 72 / 157 | `#66489D` |
| `frost_blue` | 20 / 7 / 1 / 0 | 199 / 219 / 138 | `#C7DBEE` |
| `rainier_cherry_red` | 15 / 100 / 100 / 0 | 210 / 35 / 42 | `#D2232A` |
| `graphite_gray` | 40 / 38 / 44 / 3 | 157 / 146 / 135 | `#9D9389` |

These five are v0.1 secondary palette in
`kbase-brand-tokens.json` under `palette.secondary`.

**Note:** the style guide labels `frost_blue` (`#C7DBEE`) as a "frost
blue" with HSL 209 53% 86%. The hex is correct; the label is at
odds with the hue (which is more pale-blue than frost). Brand tokens
preserve the guide's name to match the canonical document.

---

## 4. Typography (quoted)

Primary face: **Oxygen** (sans-serif).

> "The official KBase typeface is Oxygen. ... It's our preferred
> typeface and should be used whenever possible. Use only the cuts
> and weights shown. Italics should be used sparingly, for emphasis
> and scientific species names only."

Allowed weights: Regular, Bold, Italic, Bold Italic.

Fallback face: **Calibri** (sans-serif).

> "When Oxygen is not accessible i.e., Google Drive, etc."

Allowed Calibri variants: Regular, Light, Italic, Bold.

Code / `in silico` text: **Courier**, Regular and Bold.

### Sizes (quoted size scale)

The guide ships a typography scale: 96 / 60 / 48 / 34 / 24 / 19 / 16 /
14 px (60 / 42 / 36 / 24 / 18 / 14 / 12 / 10.5 pt).

**v0.1 master template uses** (informs §6.3 density discipline):

- **Title type (`title` layout):** 60 pt Oxygen Bold.
- **Section divider punchline:** 48 pt Oxygen Bold.
- **Big idea / big number title:** 60 pt Oxygen Bold.
- **Content slide title:** 36 pt Oxygen Bold (per Style Guide minimum
  for legibility in a presentation room).
- **Body text:** 24 pt Oxygen Regular (per Style Guide minimum).
- **Caption / footer:** 14 pt Oxygen Regular.
- **AI-generated illustration disclosure:** 8 pt Oxygen Regular,
  graphite-gray.

These sizes drive validator P10 (density: ≥ 24 pt body, ≥ 36 pt title).

---

## 5. Accessibility and contrast (quoted)

> "Check contrast ratios for text over colors to be at least WCAG AA
> compliant (4.5:1 for Normal font sizes). In the color palette, the
> colors that need white text for Normal font size use white text."

Quoted contrast ratios:

> "Normal fonts (< 19px) AA compliant: 4.5:1 / AAA compliant: 7:1"
> "Large fonts (19px +) AA compliant: 3:1 / AAA compliant: 4.5:1"

**Informs SPEC §13** validator P5 (contrast ≥ WCAG AA: 4.5:1 for body,
3:1 for large title text).

### Color-blindness warning (quoted)

> "Avoid Using Spring Green and Golden Yellow as contrasting colors."

The style guide also notes the palette under deuteranopia /
protanopia / tritanopia simulations.

**Informs slide-compose prompt** color-pair selection. The prompt is
forbidden from pairing `spring_green` with `golden_yellow` for fg/bg
contrast; the brand-tokens JSON marks these as
`contrast_safe_against = []` and the slide compose prompt enforces.

---

## 6. brand-tokens JSON shape (planned for `references/kbase-brand-tokens.json`)

```json
{
  "version": "1.0",
  "source": "KBase Style Guidelines — PRINT & PRESENTATION, June 2022",
  "palette": {
    "primary": {
      "microbe_orange":  {"hex": "#F78E1E", "rgb": [247,142,30],  "tints": {"80": "#F9A455", "60": "#F9A456", "40": "#FD0000", "20": "#FFE5CB"}},
      "grass_green":     {"hex": "#5E9732", "rgb": [94,151,50],   "tints": {"80": "#7EAC5B", "60": "#9EC184", "40": "#BED5AD", "20": "#DFEAD6"}},
      "freshwater_blue": {"hex": "#007DC3", "rgb": [0,125,195],   "tints": {"80": "#3397CF", "60": "#66B1DB", "40": "#99CBE7", "20": "#CCE5F3"}},
      "golden_yellow":   {"hex": "#FFD200", "rgb": [255,210,0],   "tints": {"80": "#FFDB33", "60": "#FFE466", "40": "#FFED99", "20": "#FFF6CC"}},
      "spring_green":    {"hex": "#C1CD23", "rgb": [193,205,35],  "tints": {"80": "#CDD659", "60": "#DAE183", "40": "#E6EBAC", "20": "#F3F5D6"}},
      "ocean_blue":      {"hex": "#72CCD2", "rgb": [114,204,210], "tints": {"80": "#8ED6DB", "60": "#AAE0E4", "40": "#C6EAED", "20": "#E3F5F6"}}
    },
    "secondary": {
      "cyanobacteria_teal": {"hex": "#009688", "rgb": [0,150,136]},
      "lupine_purple":      {"hex": "#66489D", "rgb": [102,72,157]},
      "frost_blue":         {"hex": "#C7DBEE", "rgb": [199,219,238]},
      "rainier_cherry_red": {"hex": "#D2232A", "rgb": [210,35,42]},
      "graphite_gray":      {"hex": "#9D9389", "rgb": [157,146,135]}
    },
    "neutral": {
      "white": {"hex": "#FFFFFF"},
      "black": {"hex": "#000000"}
    },
    "contrast_warnings": [
      {"pair": ["spring_green", "golden_yellow"],
       "reason": "Style Guide explicitly forbids as contrasting colors."}
    ]
  },
  "typography": {
    "primary": {"family": "Oxygen", "weights": ["Regular", "Bold", "Italic", "Bold Italic"]},
    "fallback": {"family": "Calibri", "weights": ["Regular", "Light", "Italic", "Bold"]},
    "code": {"family": "Courier", "weights": ["Regular", "Bold"]},
    "sizes_pt": {
      "deck_title": 60,
      "section_divider": 48,
      "big_idea": 60,
      "big_number": 96,
      "content_title": 36,
      "body": 24,
      "caption": 14,
      "ai_disclosure": 8
    }
  },
  "logo": {
    "min_height_pt": 36,
    "clear_space_x_factor": 0.5
  },
  "contrast_minima_wcag": {
    "body_text_aa_ratio": 4.5,
    "body_text_aaa_ratio": 7.0,
    "large_text_aa_ratio": 3.0,
    "large_text_aaa_ratio": 4.5
  }
}
```

Above is the planned shape. Actual file lands with v0.1.0-master-draft
phase (D-024).

---

## 7. Brand discipline notes for the slide-compose prompt

The slide-compose prompt is constrained by:

- **Use only the palette colors (primary + secondary + neutrals).** No
  off-palette accents.
- **No two-color title gradients.** Solid fills only.
- **Logo on every content slide.** symbol-only, in the footer band.
- **AI-generated illustrations carry a disclosure footer in
  `graphite_gray` 8 pt** (per SPEC §8.3). Disclosure footer is on
  the master `concept_illustration` layout; the prompt cannot omit it.
- **Title contrast:** title text must be `white` on dark backgrounds
  or `graphite_gray` darker than `#5C5550` on light backgrounds.

---

## 8. Items NOT covered in v0.1

- **Print poster grid templates beyond KBase's two.** v0.1 ships
  `poster-h` (48×36 in) and `poster-v` (36×48 in) only, derived from
  Adam's user-supplied poster .pptx files (D-013).
- **Reverse / dark-mode master.** v0.1 ships light-mode master only.
  Adam's .potx contains a dark-mode master variant; deferred to v1.x.
- **Logo placement on the title slide.** v0.1 places the
  preferred-with-tagline logo at top-right of the title slide; the
  Style Guide's "Spacing and Sizing" section governs the clear-space
  buffer.

---

## 9. Provenance notes

The Style Guide PDF was provided to Adam's project workspace as a
synced Google Doc. The hex values, font names, and size scale above
are quoted verbatim from that document. Pantone matching numbers
(021 U, 285 U, etc.) are quoted as-is and not independently
verified; print runs that need exact Pantone matching should consult
the style guide directly.
