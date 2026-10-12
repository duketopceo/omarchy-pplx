# Perplexity Search brand assets (proposal)

Status: **proposal.** The owner signs off logos; nothing here is final. Hand-written SVG, no raster source, no AI image generation, no stock icons.

## Construction

A magnifier on a 16 px grid, 1.5 px stroke: ring in ink, handle in the accent. It does not imitate Perplexity's own mark (the plugin is unofficial).

Family rules (shared with the other Omarchy plugin marks): 16 px grid, 1.5 px stroke, mitred joins, square caps, one ink colour plus one accent, no gradients.

| File | Use |
|---|---|
| `logo.svg` / `logo-dark.svg` | mark for light / dark backgrounds |
| `lockup.svg` / `lockup-dark.svg` | mark plus wordmark (README header) |
| `wordmark.svg` | text only; uses a monospace font stack, so the system font renders it |
| `bar-sizes.svg` | the mark at 16, 24, 32 px, both backgrounds |
| `social-card.svg` | 1280x640 repository social card |
| `preview/*.png` | resvg renders, oxipng-optimised |

## Colours (static, README and listing only)

The shipped widget does **not** use these: it takes every colour from the active Omarchy theme (`Color.*`). They exist because a GitHub `<img>` SVG cannot inherit theme colours.

| Role | Light bg | Dark bg |
|---|---|---|
| Ink | `#24292f` | `#e6edf3` |
| Accent | `#0a6c8f` (on `#ffffff`: 5+:1) | `#56c8ea` (on `#0d1117`: 7+:1) |

Both pass WCAG AA for graphics and text. Wordmark ink is 15:1 or better on its background.
