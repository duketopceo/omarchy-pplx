# Upstream dependency: pplx (Perplexity CLI)

This plugin is a thin Omarchy shell wrapper around Perplexity's **pplx**
CLI (`perplexity-cli`). It does not vendor, bundle, or reimplement pplx —
it resolves your API key, runs `pplx search web`, and renders results.

| | |
|---|---|
| Tool | `pplx` — Perplexity Search CLI |
| Repository | https://github.com/perplexityai/perplexity-cli |
| License | Apache-2.0 (upstream) |
| Plugin repo | https://github.com/duketopceo/omarchy-pplx |

## What the tool does vs. what the plugin does

- **pplx** performs web searches against the Perplexity Search API
  (`pplx search web`), with flags for recency, context size, domain
  filters, result limits, and token budgets.
- **This plugin** provides the bar quick-ask UI, resolves your API key
  (env `PERPLEXITY_API_KEY` or `omaseal get omaseal://perplexity/default`),
  injects it into the child process environment only, keeps a bounded
  local query history, and exposes a small allowlisted subset of the
  search flags as UI chips.

The plugin is strictly on-demand: it never polls the API, never runs
background searches, and performs no network I/O during status checks.

## Install the tool

Download a release tarball for your architecture and place `pplx` on your
`PATH` (e.g. `~/.local/bin`):

```bash
# x86_64
curl -L https://github.com/perplexityai/perplexity-cli/releases/latest/download/pplx-x86_64-unknown-linux-gnu.tar.gz | tar xz -C ~/.local/bin pplx

# aarch64 (Omarchy ARM / Asahi)
curl -L https://github.com/perplexityai/perplexity-cli/releases/latest/download/pplx-aarch64-unknown-linux-gnu.tar.gz | tar xz -C ~/.local/bin pplx
```

Asset names vary by release — check the release page if the exact name
differs: https://github.com/perplexityai/perplexity-cli/releases

## Configure a key

Either:

```bash
export PERPLEXITY_API_KEY="pplx-..."   # in your shell profile
```

or store it in the system keyring:

```bash
omaseal set perplexity default        # then the plugin resolves it via omaseal get
```

Verify with `pplx search web "test" -n 1`.
