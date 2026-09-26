# AGENTS.md — Perplexity Search (`io.github.duketopceo.pplx`)

> This file is the agent entry point for this repo.
> Full agent context lives at: https://github.com/duketopceo/luke-agents

Inherits from [luke-agents/AGENTS.md](https://github.com/duketopceo/luke-agents/blob/main/AGENTS.md). This file specializes; it does not replace.

## What This Repo Does

Quick-ask UI for the Perplexity Search API, in the Omarchy bar. Type a question,
get grounded results with sources, click to open — without leaving the desktop.
The dropdown has a quick-ask field, session-only search-option chips, a results
list (title, domain, date, snippet), and a history tab with re-ask and delete.

## Provenance — edit in the umbrella, not here

This repo is the published subtree of
[`duketopceo/omarchy-plugins`](https://github.com/duketopceo/omarchy-plugins) at
`plugins/io.github.duketopceo.pplx/`. `scripts/publish.sh` runs `git subtree split`
and fast-forwards this repo's `main`. **A commit made directly here is deleted on
the next publish.** Make the change in the umbrella, then `scripts/publish.sh pplx`.

Note the id is `io.github.duketopceo.*`, not `lukedaduke.*` like the rest of the
family. That is intentional and matches the upstream project it tracks. The
manifest `id`, the folder name, and `moduleName` must all agree.

## Upstream

Tracks [`perplexityai/perplexity-cli`](https://github.com/perplexityai/perplexity-cli).
`UPSTREAM.md` records the sync model. Read it before porting an upstream change —
this plugin is a UI around a moving upstream API surface, and a blind merge will
break the option chips.

## Layout

| Path | Role |
|---|---|
| `manifest.json` | Plugin contract. `kinds: ["bar-widget"]` |
| `Panel.qml` | Bar glyph + dropdown: ask field, chips, results, history |
| `bin/pplx_search.py` | Calls the search API, emits bounded JSON |
| `bin/pplx_status.py` | Reports auth/credential state for the UI |
| `UPSTREAM.md` | Upstream sync model |
| `preview.png` | Marketplace listing image |

The panel execs both helpers with the absolute interpreter `/usr/bin/python3`.

## Runtime Contract

- **No build step.** Nothing to compile. `manifest.json` must stay valid JSON.
- **QML cannot be checked outside Omarchy.** `Panel.qml` imports `QtQuick`,
  `Quickshell`, `Quickshell.Io`, `qs.Commons`, and `qs.Ui`. The `qs.*` modules
  come from the host shell at runtime and are absent from a plain checkout, so
  `qmllint` reports unresolvable imports. Not a bug.
- `moduleName` and `ipcTarget` must both equal the manifest `id`
  (`io.github.duketopceo.pplx`).
- **This plugin handles a credential.** Read it the way the helper already does
  and never inline a key, never log it, never echo it into the UI, and never
  commit it. There is no `.env` in this repo and there must not be one.
- The search-option chips are **session-only by design** — they are not persisted.
  Do not add persistence without saying so in the PR.
- History is local. Deleting a row must actually remove it.

## Validation

There is no test suite in this repo. From the umbrella:

```bash
python3 scripts/validate-manifests.py
python3 -m pytest tests/ -q          # includes tests/test_pplx.py
```

Standalone:

```bash
python3 -m py_compile bin/*.py
```

The umbrella suite requires Linux (GNU `head -z`, `/proc/meminfo`), so on macOS
expect unrelated failures from `test_agents.py` / `test_fan_stats.py` while
`test_pplx.py` passes.

Real verification is on Linux with the plugin enabled **and a credential
configured**: a search returns sources, a result opens, the history tab lists and
deletes. State plainly in any PR whether you exercised the live API or only the
UI.

## Runtime Requirements

- `python3` (the panel execs `/usr/bin/python3`)
- `/usr/bin/wl-copy` — Wayland clipboard, used to stage a query
- A configured Perplexity API credential, read by the helpers at runtime
- HTTPS egress to the Perplexity API

## Conventions

- Theme with `qs.Commons` `Color` / `Style` only. No hardcoded palette hex.
- Keep the helpers stdlib-only; no package manifest exists here to carry a
  dependency.
- Keep child `PATH` pinned to a fixed safe list and exec helpers by absolute
  path, so a `PATH`-preceding shadow binary cannot execute.
- Bound the helpers' stdout — the QML side parses them.
- Never edit `/usr/share/omarchy/`.
- Bump `version` in `manifest.json` when shipping a behavior change.
