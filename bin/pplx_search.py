#!/usr/bin/python3
"""Perplexity Search helper for the io.github.duketopceo.pplx panel.

Wraps the pplx CLI (perplexityai/perplexity-cli — `pplx search web <query>`)
and emits one compact JSON line on stdout for the QML panel:

    {"ok": bool, "needs_key": bool, "installed": bool,
     "hits": [{"title","url","domain","snippet","date"}],
     "error": string|null, "elapsed_ms": int}

API key resolution order (KTD5): PERPLEXITY_API_KEY env var, then the
optional `omaseal` keyring (`omaseal get omaseal://perplexity/default`).
The key is only ever injected into the child's environment — never on argv,
never in stdout JSON, never logged. `pplx auth login` is TTY-only and is
never invoked.

Hardening mirrors probe_nexus.py: fixed tool-lookup path, minimal fixed
child env, per-call byte caps and deadline, process-group kill on timeout,
SIGALRM/setsid backstop. No shell. The only write is a best-effort journal:
each successful search prepends one entry to
~/.local/state/omarchy/pplx/history.json (descriptor-relative, atomic 0600
temp+rename — the standby/bumblebee pattern) for the panel's History tab; a
history failure never changes the stdout emit. pplx-controlled strings are
control-char-normalized and length-clipped before they reach QML.

Search options (KTD4): the panel passes --recency/--context/--limit pairs
ahead of the query. Each value is matched against a strict allowlist —
recency {hour,day,week,month,year} -> --recency-filter, context
{low,medium,high} -> --search-context-size, limit int 1..20 -> -n. Any
other value produces no flag at all; unrecognized tokens are never
forwarded to pplx (they can only become query text after `--`).
"""
import json, os, re, selectors, shutil, signal, stat, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
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
OMASEAL_REF = "omaseal://perplexity/default"

# Allowlisted search modifiers (KTD4). Only these exact values ever become
# pplx argv — anything else is silently dropped to the default flag set.
RECENCY_ALLOW = frozenset(("hour", "day", "week", "month", "year"))
CONTEXT_ALLOW = frozenset(("low", "medium", "high"))
MAX_LIMIT = 20

# Query history journal: newest-first list, bounded file, read back by
# pplx_status.py for the panel. Nothing secret lands here — the query text
# is the user's own input, the API key never is.
try:
    HOME = Path.home()
except Exception:
    HOME = Path("/")
HISTORY_DIR_REL = ".local/state/omarchy/pplx"
HISTORY_NAME = "history.json"
HISTORY_MAX_BYTES = 64 * 1024   # far above 30 small entries; bounds a hostile file
MAX_HISTORY = 30
MAX_HISTORY_QUERY = 120

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


def _search_flags(opts):
    """Map panel option state onto the allowlisted pplx flag argv (KTD4).

    opts is {"recency","context","limit": raw strings}. Only exact
    allowlist matches emit a flag — anything else contributes nothing.
    """
    flags = ["-n", str(MAX_HITS)]
    if not isinstance(opts, dict):
        return flags
    limit = opts.get("limit")
    try:
        n = int(str(limit), 10) if limit is not None else None
    except (TypeError, ValueError):
        n = None
    if n is not None and 1 <= n <= MAX_LIMIT:
        flags[1] = str(n)
    recency = opts.get("recency")
    if isinstance(recency, str) and recency in RECENCY_ALLOW:
        flags += ["--recency-filter", recency]
    context = opts.get("context")
    if isinstance(context, str) and context in CONTEXT_ALLOW:
        flags += ["--search-context-size", context]
    return flags


def _parse_args(argv):
    """Split leading `--recency/--context/--limit <value>` pairs from the
    query tail. Unknown tokens (and a dangling flag with no value) stay in
    the tail — they can only ever become query text, never pplx flags.
    A literal `--` ends option parsing, like the one pplx gets itself.
    """
    opts = {}
    i = 0
    while i + 1 < len(argv) and argv[i] in ("--recency", "--context", "--limit"):
        opts[argv[i][2:]] = argv[i + 1]
        i += 2
    if i < len(argv) and argv[i] == "--":
        i += 1
    return opts, argv[i:]


def _resolve_key(environ=None, run=None, tool=None):
    """Return the API key (str) or None.

    Order: PERPLEXITY_API_KEY, then `omaseal get` when omaseal is
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
    res = run([omaseal, "get", OMASEAL_REF],
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


# --- history: descriptor-relative read, atomic republish (standby pattern) ---

def _open_dir(path):
    """Descriptor for a directory — no symlinks, must be ours."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        os.close(fd)
        raise PermissionError("%s is not a user-owned real directory" % path)
    return fd


def _read_capped(dirfd, name, limit):
    """Bounded, no-follow, regular-file read; None on any anomaly."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_size > limit:
            return None
        return os.read(fd, limit)
    finally:
        os.close(fd)


def _publish(dirfd, name, data):
    """Write via exclusive same-dir temp file + atomic rename, mode 0600."""
    tmp = ".%s.%d.tmp" % (name, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=dirfd)
    try:
        os.write(fd, data.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)


def _read_history(dirfd):
    """history.json as a list of entry dicts (newest first); [] if unusable."""
    raw = _read_capped(dirfd, HISTORY_NAME, HISTORY_MAX_BYTES)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


def _record_history(query, result, state_dir=None):
    """Prepend one entry to history.json (newest first, cap MAX_HISTORY).

    The journal is a convenience for the panel's History tab — every error
    path just returns, so a filesystem problem can never change the emit.
    """
    try:
        entry = {
            "query": _clean(query, MAX_HISTORY_QUERY),
            "hits_count": len(result.get("hits") or []),
            "elapsed_ms": int(result.get("elapsed_ms") or 0),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        state_dir = (Path(state_dir) if state_dir is not None
                     else HOME / HISTORY_DIR_REL)
        state_dir.mkdir(parents=True, exist_ok=True)
        dirfd = _open_dir(state_dir)
        try:
            hist = _read_history(dirfd)
            hist.insert(0, entry)
            _publish(dirfd, HISTORY_NAME, json.dumps(hist[:MAX_HISTORY]))
        finally:
            os.close(dirfd)
    except Exception:
        pass


def search(query, environ=None, run=None, tool=None, state_dir=None, opts=None):
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
                           "or `omaseal set perplexity default`")
        return _finish(result, started)
    try:
        argv = [pplx, "search", "web"] + _search_flags(opts) + ["--", query]
        res = run(argv, timeout=PPLX_TIMEOUT_S, cap=MAX_OUT_BYTES,
                  extra_env={"PERPLEXITY_API_KEY": key})
        result = _result_from_run(res, key, result)
    finally:
        key = None  # drop the secret reference; it lives nowhere else
    result = _finish(result, started)
    if result["ok"]:
        # Journal the query for the History tab. Best-effort only: a write
        # failure must never reach the stdout contract.
        _record_history(query, result, state_dir=state_dir)
    return result


def main(argv):
    opts, tail = _parse_args(argv[1:])
    query = " ".join(tail).replace("\x00", " ").strip()
    if not query:
        sys.stdout.write(json.dumps({
            "ok": False, "needs_key": False, "installed": False,
            "hits": [], "elapsed_ms": 0,
            "error": ("usage: pplx_search.py [--recency <v>] [--context <v>] "
                      "[--limit <n>] [--] <query>")}) + "\n")
        return 2
    sys.stdout.write(json.dumps(search(query, opts=opts))[:MAX_OUT_BYTES] + "\n")
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
