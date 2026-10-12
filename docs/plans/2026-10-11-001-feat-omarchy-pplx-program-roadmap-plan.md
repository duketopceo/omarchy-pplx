---
title: "Perplexity Search program roadmap"
type: feat
status: proposed
date: 2026-10-11
---

# Perplexity Search program roadmap

Written directly (not through `ce-plan`): a one-widget plugin does not need the pipeline. Required fields (U-IDs, Now/Next/Later, status, evidence, dependencies, verification, difficulty, feasibility, simpler alternative) are all present.

**Provenance constraint.** This repo is the `git subtree split` of `duketopceo/omarchy-plugins` at `plugins/io.github.duketopceo.pplx/`; `scripts/publish.sh` fast-forwards `main`, so direct commits here are deleted on the next publish. Every unit lands in the umbrella and arrives here by publish (U1).

**Family direction.** Design units align with the shared Omarchy-plugin direction in `duketopceo/omarchy-plugins` `DESIGN.md` once merged.

## Units

### U1. Move this docs/brand pass into the `omarchy-plugins` umbrella

- **Horizon:** Now
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** easy. Copy to `plugins/io.github.duketopceo.pplx/`.
- **Feasibility:** None.
- **Simpler alternative:** Mirror repo.
- **Dependencies:** none
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

### U2. Stop the infinite 1400 ms pulse on the status glyph and field (`Panel.qml:109-111, 459, 686`); pulse only while a search is in flight and honour reduced motion

- **Horizon:** Now
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** easy. One `running:` binding.
- **Feasibility:** None.
- **Simpler alternative:** Static `searching…` text instead of animation.
- **Dependencies:** U1 for where the change lands (umbrella)
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

### U3. Fix `dim = Qt.darker(foreground, 1.5)` (`Panel.qml:41`): on light themes it is darker than the foreground

- **Horizon:** Now
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** easy. Swap for a foreground alpha; check Vantablack and Flexoki Light.
- **Feasibility:** None.
- **Simpler alternative:** One property.
- **Dependencies:** U1 for where the change lands (umbrella)
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

### U4. Keyboard path through result rows (up/down, Enter opens, Ctrl+C copies)

- **Horizon:** Next
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** medium. Panel already has `KeyboardPanel` tab handling.
- **Feasibility:** Must not steal keys while the field has focus (already handled by `blocked`).
- **Simpler alternative:** Extend the existing key catcher.
- **Dependencies:** U1 for where the change lands (umbrella)
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

### U5. Drop the `pplx` binary dependency: call the Search API from `bin/pplx_search.py` with `urllib`

- **Horizon:** Next
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** hard. Rewrite the allowlist layer; keep the same JSON contract.
- **Feasibility:** Upstream CLI flags and API may change; the plugin would then track the API directly.
- **Simpler alternative:** Keep the binary; this only pays off if upstream breaks again (see `UPSTREAM.md`).
- **Dependencies:** U1 for where the change lands (umbrella)
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

### U6. Real screenshot with a stubbed `pplx` (no paid call)

- **Horizon:** Later
- **Status:** not started
- **Evidence:** read of `Panel.qml`/`manifest.json`/`AGENTS.md` in this repo (2026-10-11)
- **Difficulty:** medium. A fake `pplx` on PATH returning fixture JSON.
- **Feasibility:** None.
- **Simpler alternative:** Capture the setup pane instead.
- **Dependencies:** U1 for where the change lands (umbrella)
- **Verification:** structural tests in the umbrella (`python3 scripts/validate-manifests.py`, `python3 -m pytest tests/`), then a manual check in a live Omarchy session; QML cannot be run outside Omarchy.

