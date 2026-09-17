#!/usr/bin/python3
"""Perplexity Search helper for the io.github.duketopceo.pplx panel.

Wraps the pplx CLI (perplexityai/perplexity-cli — `pplx search web <query>`)
and emits one compact JSON line on stdout for the QML panel:

    {"ok": bool, "needs_key": bool, "installed": bool,
     "hits": [{"title","url","domain","snippet","date"}],
     "error": string|null, "elapsed_ms": int}

API key resolution order (KTD5): PERPLEXITY_API_KEY env var, then the
optional `omaseal` keyring (`omaseal resolve omaseal://perplexity/api-key`).
The key is only ever injected into the child's environment — never on argv,
never in stdout JSON, never logged. `pplx auth login` is TTY-only and is
never invoked.

Hardening mirrors probe_nexus.py: fixed tool-lookup path, minimal fixed
child env, per-call byte caps and deadline, process-group kill on timeout,
SIGALRM/setsid backstop. No shell, no writes. pplx-controlled strings are
control-char-normalized and length-clipped before they reach QML.
"""
import json, os, re, selectors, shutil, signal, subprocess, sys, time
from urllib.parse import urlparse

JOB_DEADLINE_S = 15
PPLX_TIMEOUT_S = 12.0      # API round-trip budget
OMASEAL_TIMEOUT_S = 2.0    # keyring resolve can block on a prompt — keep tight
MAX_OUT_BYTES = 262144
MAX_ERR_BYTES = 16384
OMASEAL_CAP = 4096
MAX_STR = 200
MAX_URL = 400              # urls stay openable via xdg-open; still bounded
MAX_HITS = 8
MAX_KEY = 256
OMASEAL_REF = "omaseal://perplexity/api-key"

SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
# pplx's installer and omaseal both target ~/.local/bin. TOOL_PATH is still a
# fixed literal list built from our own home dir — the inherited PATH is
# never consulted.
USER_BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")
TOOL_PATH = USER_BIN + ":" + SAFE_PATH

SAFE_ENV = {"PATH": SAFE_PATH, "LC_ALL": "C", "LANG": "C"}
_HOME = os.path.expanduser("~")
if _HOME and _HOME != "~":
    # pplx resolves ~/.config credentials/config under HOME.
    SAFE_ENV["HOME"] = _HOME

_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")

_CHILD_PGID = None  # set while a subprocess runs so the ALRM backstop can reap it


def _tool(name):
    """Absolute path for an external helper, resolved under TOOL_PATH only."""
    return shutil.which(name, path=TOOL_PATH)


def _kill_group(proc):
    # Child is its own process-group leader (start_new_session), so killpg
    # reaches detached grandchildren too.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass


def _run(argv, timeout=2.0, cap=MAX_OUT_BYTES, extra_env=None):
    """Run argv (no shell) under a minimal env, hard deadline, byte caps.

    extra_env vars are merged into the fixed env — the only channel through
    which the API key reaches a child. Returns a dict:
    {"rc": int|None, "out", "err", "timeout", "overflow"}; never raises.
    """
    global _CHILD_PGID
    res = {"rc": None, "out": "", "err": "", "timeout": False, "overflow": False}
    if not argv or not argv[0]:
        return res
    env = dict(SAFE_ENV)
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
    except OSError:
        return res
    _CHILD_PGID = proc.pid
    out = bytearray()
    err = bytearray()
    deadline = time.monotonic() + timeout
    sel = selectors.DefaultSelector()
    try:
        sel.register(proc.stdout, selectors.EVENT_READ, out)
        sel.register(proc.stderr, selectors.EVENT_READ, err)
        pipes = {proc.stdout: cap, proc.stderr: MAX_ERR_BYTES}
        timed_out = False
        while pipes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            events = sel.select(remaining)
            if not events:
                timed_out = True
                break
            for key, _mask in events:
                fobj = key.fileobj
                try:
                    chunk = os.read(fobj.fileno(), 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    try:
                        sel.unregister(fobj)
                    except (KeyError, ValueError, OSError):
                        pass
                    pipes.pop(fobj, None)
                    continue
                buf = key.data
                buf += chunk
                if len(buf) > pipes.get(fobj, 0):
                    res["overflow"] = True
                    try:
                        sel.unregister(fobj)
                    except (KeyError, ValueError, OSError):
                        pass
                    pipes.pop(fobj, None)
        res["timeout"] = timed_out
    finally:
        sel.close()
        if proc.poll() is None:
            _kill_group(proc)
        for fobj in (proc.stdout, proc.stderr):
            try:
                fobj.close()
            except OSError:
                pass
        _CHILD_PGID = None
    res["rc"] = proc.poll()
    res["out"] = out.decode(errors="replace")
    res["err"] = err.decode(errors="replace")
    return res


def _clean(value, limit=MAX_STR):
    """Control-char-normalize, collapse whitespace, clip a derived string."""
    s = _CTRL.sub(" ", str(value if value is not None else ""))
    return " ".join(s.split())[:limit]


def _redact(text, secret):
    if secret and isinstance(text, str) and secret in text:
        return text.replace(secret, "***")
    return text


def _parse_json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _extract_error(data, err_text):
    """(code, message) from pplx's {"error":{"code","message"}} shape.

    Checks parsed stdout first, then stderr. Never returns raw stderr —
    only the structured fields, so nothing that could echo the env leaks.
    """
    for source in (data, _parse_json(err_text.strip() if err_text else "")):
        if not isinstance(source, dict):
            continue
        e = source.get("error")
        if isinstance(e, dict):
            code = e.get("code")
            msg = e.get("message")
            return (_clean(code, 64) if isinstance(code, str) else "",
                    _clean(msg, MAX_STR) if isinstance(msg, str) else "")
        if isinstance(e, str):
            return "", _clean(e, MAX_STR)
    return "", ""


def _compact_hits(raw_hits, redact=None):
    """Normalize pplx hits[] to {title,url,domain,snippet,date}, cap MAX_HITS."""
    hits = []
    for h in raw_hits:
        if len(hits) >= MAX_HITS:
            break
        if not isinstance(h, dict):
            continue
        url = _redact(_clean(h.get("url"), MAX_URL), redact)
        if not url:
            continue
        try:
            domain = urlparse(url).netloc[:128]
        except ValueError:
            domain = ""
        if not domain:
            domain = _clean(h.get("domain"), 128)
        date = ""
        for k in ("date", "published_date", "publishedDate",
                  "last_updated", "lastUpdated", "updated", "timestamp"):
            if h.get(k):
                date = _clean(h.get(k), 64)
                break
        hits.append({
            "title": _redact(_clean(h.get("title")), redact),
            "url": url,
            "domain": domain,
            "snippet": _redact(_clean(h.get("snippet")), redact),
            "date": _redact(date, redact),
        })
    return hits


def _resolve_key(environ=None, run=None, tool=None):
    """Return the API key (str) or None.

    Order: PERPLEXITY_API_KEY, then `omaseal resolve` when omaseal is
    installed (optional dep — absent or unresolved is not an error).
    The returned value is secret material: it may only be injected into a
    child env, never argv/output/logs.
    """
    environ = os.environ if environ is None else environ
    run = _run if run is None else run
    tool = _tool if tool is None else tool
    key = (environ.get("PERPLEXITY_API_KEY") or "").strip()
    if key:
        return key
    omaseal = tool("omaseal")
    if not omaseal:
        return None
    res = run([omaseal, "resolve", OMASEAL_REF],
              timeout=OMASEAL_TIMEOUT_S, cap=OMASEAL_CAP)
    if res.get("rc") == 0 and not res.get("timeout") and not res.get("overflow"):
        for line in (res.get("out") or "").splitlines():
            line = line.strip()
            if line:
                return line[:MAX_KEY]
    return None


def _result_from_run(res, secret, result):
    """Map a _run result onto the emit dict, redacting secret material."""
    if res["timeout"]:
        result["error"] = "timeout"
        return result
    if res["rc"] is None:
        result["error"] = "failed to run pplx"
        return result
    data = _parse_json(res["out"])
    if res["rc"] == 0 and isinstance(data, dict) and isinstance(data.get("hits"), list):
        result["ok"] = True
        result["hits"] = _compact_hits(data["hits"], redact=secret)
        return result
    code, msg = _extract_error(data, res["err"])
    if code == "AUTHENTICATION":
        result["needs_key"] = True
    if msg:
        result["error"] = _redact(msg, secret)
    elif res["overflow"]:
        result["error"] = "pplx output exceeded byte cap"
    elif res["rc"] != 0:
        result["error"] = "search failed (rc=%s)" % res["rc"]
    else:
        result["error"] = "unexpected pplx output"
    return result


def _finish(result, started):
    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


def search(query, environ=None, run=None, tool=None):
    """Run one pplx web search, returning the emit dict (all seams injectable)."""
    run = _run if run is None else run
    tool = _tool if tool is None else tool
    started = time.monotonic()
    result = {"ok": False, "needs_key": False, "installed": False,
              "hits": [], "error": None, "elapsed_ms": 0}
    pplx = tool("pplx")
    if not pplx:
        result["error"] = "pplx not installed"
        return _finish(result, started)
    result["installed"] = True
    key = _resolve_key(environ=environ, run=run, tool=tool)
    if not key:
        result["needs_key"] = True
        result["error"] = ("no Perplexity API key — set PERPLEXITY_API_KEY "
                           "or `omaseal set perplexity api-key`")
        return _finish(result, started)
    try:
        res = run([pplx, "search", "web", "--limit", str(MAX_HITS), "--", query],
                  timeout=PPLX_TIMEOUT_S, cap=MAX_OUT_BYTES,
                  extra_env={"PERPLEXITY_API_KEY": key})
        result = _result_from_run(res, key, result)
    finally:
        key = None  # drop the secret reference; it lives nowhere else
    return _finish(result, started)


def main(argv):
    query = " ".join(argv[1:]).replace("\x00", " ").strip()
    if not query:
        sys.stdout.write(json.dumps({
            "ok": False, "needs_key": False, "installed": False,
            "hits": [], "error": "usage: pplx_search.py <query>",
            "elapsed_ms": 0}) + "\n")
        return 2
    sys.stdout.write(json.dumps(search(query))[:MAX_OUT_BYTES] + "\n")
    return 0


def _alrm_exit(*_):
    # Backstop: if we die with a live child group, take it down too.
    if _CHILD_PGID:
        try:
            os.killpg(_CHILD_PGID, signal.SIGKILL)
        except OSError:
            pass
    os._exit(124)


if __name__ == "__main__":
    # Become a session/group leader so the QML watchdog can SIGKILL this
    # whole job tree via killpg; SIGALRM backstops a hung pipeline.
    try:
        os.setsid()
    except OSError:
        pass
    signal.signal(signal.SIGALRM, _alrm_exit)
    signal.alarm(JOB_DEADLINE_S)
    sys.exit(main(sys.argv))
