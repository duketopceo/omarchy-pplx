# Perplexity Search design direction: Quiet query line

Status: proposal. **Align with the shared Omarchy-plugin family direction in `duketopceo/omarchy-plugins` `DESIGN.md` once it is merged**; where they disagree, the family file wins and this one should be corrected. Nothing here changes plugin behaviour; no QML was edited in this pass (see section 8).

Method: the `refero-design` research-first method in reduced form (reference lock, decision ledger, anti-slop gate). The Refero MCP was not used in this session, so references are the repo's own code, the landscape note and the Omarchy theme files; none were fetched from a design library.

## 1. Direction

**Quiet query line.** The product is a text field and a list of sources. The design is a command-line feel inside the theme: results are plain rows, sources are the content, chips are small outlined toggles. No logo block inside the panel and no pulsing field.

## 2. Reference lock

```text
Primary direction: the Omarchy shell kit (qs.Commons Color/Style, qs.Ui) for all chrome.
Preserve:
  1. Colours resolve from the active theme; tokens below map onto the theme, never replace it.
  2. Radius = Style.cornerRadius (0 stays 0); spacing = Style.space().
  3. Type = Style.font.family (monospace) at Style.font.* sizes.
  4. Flat surfaces, hairline borders from foreground alpha, no blur, no shadow.
Borrow only: stock Omarchy bar icon sizing and hover behaviour.
Reject: fixed brand hex in the shipped widget, glass cards, gradients, glow, infinite pulses,
  all-caps section titles as decoration, colour-only state.
Media strategy: hand-written SVG mark, real screenshots for the README (TODO where the app cannot run here).
```

## 3. Decision ledger

| Decision | Source | Role rule | Why |
|---|---|---|---|
| All shipped colours come from the Omarchy theme | `Color.*` use already in `Panel.qml`; Omarchy theming | theme owns chrome | the plugin must look installed, not pasted |
| Static brand colours only in README and listing | GitHub `<img>` SVG cannot inherit theme | static media only | |
| State is never colour alone: word or glyph change as well | measured: Vantablack `urgent` vs `accent` 1.33:1 | all status | monochrome themes exist |
| No continuous animation on chrome | audit of `Animation.Infinite` | motion = a state change | calm when ignored |
| Radius and spacing from `Style.cornerRadius` / `Style.space()` | existing code | chrome | square themes stay square |
| Mark in family grammar (16 px, 1.5 px stroke, one accent) | sibling plugin marks | README and listing | one family |

## 4. Tokens (theme mapping)

The widget keeps using theme tokens. Static values apply only to README and listing assets (`assets/brand/README.md`).

| Role | Theme token | Use |
|---|---|---|
| surface | `Color.background` | panel fill |
| text | `Color.foreground` | primary text |
| text-secondary | `Color.muted` (not `Qt.darker(fg, 1.5)`) | captions, domains |
| accent | `Color.accent` | selected tab underline, ready state |
| urgent | `Color.urgent` | failure or exposure, always with a word |
| hairline | foreground at 8 to 10 percent alpha | card borders |

Contrast, computed (WCAG relative luminance) from the theme files in `/usr/share/omarchy/themes` and `~/.config/omarchy/themes` (read only):

| Pair | Vantablack (dark) | Flexoki Light |
|---|---|---|
| foreground on background | 21.0 | 18.62 |
| `muted` on background | 4.89 | **2.00 (fails AA 4.5)** |
| `accent` on background | 6.33 | 6.36 |
| `red` (assumed to be `Color.urgent`) on background | 8.42 | 4.21 (misses 4.5 by 0.29) |
| `red` vs `accent` | **1.33** | 1.51 |

Findings: (a) `muted` is not safe for body text on light themes; (b) urgent and accent are nearly the same luminance on monochrome themes, so state needs a word or glyph change; (c) `Qt.darker(foreground, 1.5)` (used as `dim` in the Panel files) is *darker* than foreground on light themes, inverting hierarchy. I did not verify that `Color.urgent` maps to the theme's `red`; treat that row as assumed.

Type: `Style.font.family`; sizes `Style.font.body`, `bodySmall`, `caption`, `subtitle` as used today. No new sizes.

## 5. Glyph and icon style

16 px grid, 1.5 px stroke, mitred joins, square caps, one weight, outline plus at most one filled accent element. Bar glyphs stay Nerd Font codepoints as the stock bar does; the mark in `assets/brand/` is for the README, listing and social card, not the bar. State change = shape or word change, not tint only.

## 6. Motion rules

- 90 to 200 ms ease-out for colour and opacity changes; no springs needed.
- No `Animation.Infinite` on chrome. A loop may run only while a request is in flight and stops with it.
- Respect reduced motion: replace any animation with the final state.
- No flashing; nothing blinks above 1 Hz.

## 7. Surfaces in this repo

| Surface | File | Design note |
|---|---|---|
| Bar glyph | Panel.qml (bar button) | search glyph tinted by status: dim = unknown or not installed, urgent = needs key, accent = ready |
| Panel: Ask and History tabs | Panel.qml (957 lines) | ask field, recency and context chips, result rows, copy buttons, history list |
| Setup panes | Panel.qml | install and key guidance with no dead calls |
| README / listing | README.md, preview.png | lockup; preview.png is a mock-up (TODO real capture) |

## 8. Audit and what was not done

- README accurate to the code read, including the 8 s / 12 s / 15 s deadlines. No claim removed. Added: preview.png is a mock-up.
- **UI/QML commits were not made.** This repo is a subtree mirror (direct commits are deleted on publish), QML cannot be run or linted outside Omarchy, and this pass was told not to install, restart or reload anything. The UI changes are roadmap units instead, to land in the umbrella with before/after screenshots.
- No before/after screenshots: the widget cannot be rendered here. `preview.png` is a marketplace mock-up, not a capture.

## 9. Anti-slop gate

Accent from the theme (no default indigo): pass. Cards only where there is interaction: pass. No emoji or decorative status dots: pass. No glow or gradient: pass. Where the current code differs (infinite pulse, colour-only state, `dim` inversion) the roadmap names the unit.
