# pplx

Quick-ask Perplexity search from the Omarchy bar. Type a question, get grounded
results with sources, click to open — without leaving the desktop.

Wraps [perplexityai/perplexity-cli](https://github.com/perplexityai/perplexity-cli)
(Apache-2.0), the `pplx` CLI for the Perplexity Search API. **BYOK** — you supply
your own API key; usage bills to your Perplexity account.

## Install

1. Install the `pplx` binary from the upstream
   [releases](https://github.com/perplexityai/perplexity-cli/releases) —
   `aarch64-linux-gnu` / `x86_64-linux-gnu`, place it on your PATH
   (e.g. `~/.local/bin`).

   Note: this plugin targets Perplexity's Go `perplexity-cli` binary. Other
   tools named `pplx` (e.g. the Node `pplx-cli`) have a different CLI surface —
   the plugin will show a setup hint rather than run the wrong one.

2. Provide a key — either:

```bash
export PERPLEXITY_API_KEY=pplx-...   # in your shell profile / session env
```

   or, if you use [OmaSeal](https://github.com/duketopceo/OmaSeal):

```bash
omaseal set perplexity default
```

   The plugin resolves `omaseal://perplexity/default` at query time. The key is
   injected into the pplx child process environment only — never on the command
   line, never logged, never rendered.

3. Then:

```bash
omarchy plugin add https://github.com/duketopceo/omarchy-pplx
omarchy plugin enable io.github.duketopceo.pplx
```

## Features

- Search-glyph bar button; dropdown with a quick-ask field
- Results list: title, domain, date, snippet — click opens via `xdg-open`
- Status probe distinguishes not-installed / needs-key / ready
- Setup panes guide install and key configuration — no dead calls

## Privacy & security posture

- Queries go to the Perplexity Search API via the upstream `pplx` binary; the
  plugin adds no telemetry
- Subprocess runs with a scrubbed environment, fixed tool paths, bounded output
  (256KiB cap), and hard deadlines (12s API budget, 15s whole-job, 2s keyring
  probe)
- API key travels only in the child process env; it cannot leak through argv,
  logs, or the rendered output
- External strings render as plain text — no markup interpretation

## External dependencies

- `pplx` binary (upstream releases; amd64 + arm64)
- A Perplexity API key (upstream account; API usage may incur cost)
- Optional: `omaseal` for keyring-backed key storage

## Remove

```bash
omarchy plugin disable io.github.duketopceo.pplx
omarchy plugin remove io.github.duketopceo.pplx
```

MIT — see [LICENSE](LICENSE). Upstream: Apache-2.0 (Perplexity).
