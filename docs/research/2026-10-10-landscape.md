# Perplexity Search: landscape (2026-10-11)

Scope note: a short pass for a small plugin. One to three web searches, results read from search summaries only, not full pages. Items marked "not re-fetched" were not opened. Treat as a starting point, not a survey.

## Who else does this

| Project | What it does (as found) |
|---|---|
| [Perplexity Search API in Open WebUI](https://docs.openwebui.com/features/chat-conversations/web-search/providers/perplexity_search.md) | Uses the API as a search provider with a key; shows the API is a plain search engine, not the answer models. |
| [Raycast-compatible launcher for Linux](https://git.joshthomas.dev/mirrors/raycast-linux/src/commit/c34f264a35225049f3d28833615a5435670fd9f7) | Hobby launcher; no Perplexity extension was found. |
| [Quick Perplexes (Firefox)](https://firefox.marketplace.browsertotal.com/en-GB/firefox/addon/quick-perplexes/) | In-browser overlay on Ctrl+`; not system-wide. |
| [perplexityai/perplexity-cli](https://github.com/perplexityai/perplexity-cli) | The upstream CLI this plugin wraps. |

## What they do better and worse

Browser add-ons are tied to a browser; Raycast-style launchers are heavy. None found that are a native Wayland bar dropdown.

## What users expect

One shortcut, type, read sources, open or copy.

## What is unique here

Native bar dropdown with a strict allowlist over the upstream CLI flags, key kept in the child environment only, plain-text rendering of external strings.

## Code facts used

Read directly from this repo: `Panel.qml` colour use (`Color.*`, `Style.*`), timers, animations and tab structure; `manifest.json`; `AGENTS.md`. See `DESIGN.md` for the audit.
