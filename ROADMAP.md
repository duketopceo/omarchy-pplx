# Roadmap

## Plans

1. [docs/plans/2026-10-11-001-feat-omarchy-pplx-program-roadmap-plan.md](docs/plans/2026-10-11-001-feat-omarchy-pplx-program-roadmap-plan.md) (2026-10-11): program roadmap. Units land in the `omarchy-plugins` umbrella, then arrive here via `scripts/publish.sh`.

| Horizon | Unit | Difficulty |
|---|---|---|
| Now | U1 Move this docs/brand pass into the `omarchy-plugins` umbrella | easy |
| Now | U2 Stop the infinite 1400 ms pulse on the status glyph and field (`Panel.qml:109-111, 459, 686`); pulse only while a search is in flight and honour reduced motion | easy |
| Now | U3 Fix `dim = Qt.darker(foreground, 1.5)` (`Panel.qml:41`): on light themes it is darker than the foreground | easy |
| Next | U4 Keyboard path through result rows (up/down, Enter opens, Ctrl+C copies) | medium |
| Next | U5 Drop the `pplx` binary dependency: call the Search API from `bin/pplx_search.py` with `urllib` | hard |
| Later | U6 Real screenshot with a stubbed `pplx` (no paid call) | medium |

Design direction: [DESIGN.md](DESIGN.md). Landscape: [docs/research/2026-10-10-landscape.md](docs/research/2026-10-10-landscape.md).
