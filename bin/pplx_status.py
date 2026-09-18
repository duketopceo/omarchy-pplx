#!/usr/bin/python3
"""Lightweight pplx status probe for the io.github.duketopceo.pplx bar icon.

Emits {"installed": bool, "authed": bool, "copy_available": bool,
"history": [...]} on stdout. "authed" means an API key resolves locally —
PERPLEXITY_API_KEY, or the optional omaseal keyring (`omaseal get
omaseal://perplexity/default`). No network call is made and the key value
is never printed, logged, or placed on argv. "history" is the local query
journal written by pplx_search.py
(~/.local/state/omarchy/pplx/history.json), re-emitted newest-first
(max 30) for the panel's History tab. "copy_available" reports whether
/usr/bin/wl-copy exists so the panel can hide its copy action.

`--delete <index>` removes exactly one journal entry by its visible
(newest-first) index and re-emits {"ok","history","error"}; the file is
rewritten atomically at 0600 via the same-dir temp+rename pattern.
Out-of-range or malformed indexes are a no-op with the error field set.

Hardening mirrors pplx_search.py / probe_nexus.py: fixed tool-lookup path,
minimal fixed child env, byte caps and deadline, process-group kill on
timeout, SIGALRM/setsid backstop. No shell — the history file is opened
descriptor-relative and read-capped like the standby/bumblebee cache
readers, and the delete verb writes through the same exclusive-temp +
rename pattern the search helper uses.
"""
import json, os, selectors, shutil, signal, stat, subprocess, sys, time
from pathlib import Path

JOB_DEADLINE_S = 5
OMASEAL_TIMEOUT_S = 2.0    # keyring resolve can block on a prompt — keep tight
MAX_ERR_BYTES = 16384
OMASEAL_CAP = 4096
MAX_KEY = 256
OMASEAL_REF = "omaseal://perplexity/default"

try:
    HOME = Path.home()
except Exception:
    HOME = Path("/")
HISTORY_DIR_REL = ".local/state/omarchy/pplx"
HISTORY_NAME = "history.json"
HISTORY_MAX_BYTES = 64 * 1024   # bounds a hostile/corrupt file
MAX_HISTORY = 30
MAX_HISTORY_QUERY = 120
MAX_HISTORY_AT = 64

# wl-clipboard's copy tool: the panel's per-hit copy action execs this
# fixed path detached; absent -> the button is hidden via copy_available.
WL_COPY = "/usr/bin/wl-copy"

SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
# pplx's installer and omaseal both target ~/.local/bin. TOOL_PATH is still a
# fixed literal list built from our own home dir — the inherited PATH is
# never consulted.
USER_BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")
TOOL_PATH = USER_BIN + ":" + SAFE_PATH

SAFE_ENV = {"PATH": SAFE_PATH, "LC_ALL": "C", "LANG": "C"}
_HOME = os.path.expanduser("~")
if _HOME and _HOME != "~":
    SAFE_ENV["HOME"] = _HOME

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


def _run(argv, timeout=2.0, cap=OMASEAL_CAP, extra_env=None):
    """Run argv (no shell) under a minimal env, hard deadline, byte caps.

    Returns {"rc": int|None, "out", "err", "timeout", "overflow"};
    never raises. extra_env is merged into the fixed env (unused here, kept
    for parity with pplx_search._run).
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


# --- history read: descriptor-relative, capped (standby/bumblebee pattern) ---

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


def _history_entry(raw):
    """Normalize one journal entry for the panel; None to drop it."""
    if not isinstance(raw, dict):
        return None
    query = raw.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    hits_count = raw.get("hits_count")
    elapsed_ms = raw.get("elapsed_ms")
    at = raw.get("at")
    return {
        "query": query[:MAX_HISTORY_QUERY],
        "hits_count": hits_count if isinstance(hits_count, int) and hits_count >= 0 else 0,
        "elapsed_ms": elapsed_ms if isinstance(elapsed_ms, int) and elapsed_ms >= 0 else 0,
        "at": at[:MAX_HISTORY_AT] if isinstance(at, str) else "",
    }


def _normalized_history(dirfd, cap=None):
    """Normalize every journal entry (newest first); cap=None keeps all."""
    raw = _read_capped(dirfd, HISTORY_NAME, HISTORY_MAX_BYTES)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for entry in data:
        clean = _history_entry(entry)
        if clean is not None:
            out.append(clean)
        if cap is not None and len(out) >= cap:
            break
    return out


def _read_history(state_dir=None):
    """Newest-first entry list (max MAX_HISTORY); [] on missing/corrupt."""
    try:
        state_dir = (Path(state_dir) if state_dir is not None
                     else HOME / HISTORY_DIR_REL)
        dirfd = _open_dir(state_dir)
    except (OSError, PermissionError):
        return []
    try:
        return _normalized_history(dirfd, cap=MAX_HISTORY)
    finally:
        os.close(dirfd)


def delete_history(index, state_dir=None):
    """Remove exactly one journal entry by visible index; atomic 0600 rewrite.

    Emits {"ok","history","error"} — history is the updated newest-first
    list (panel-capped). The rewrite preserves order and drops nothing
    else: every normalized entry is written back, not just the first 30.
    """
    try:
        state_dir = (Path(state_dir) if state_dir is not None
                     else HOME / HISTORY_DIR_REL)
        dirfd = _open_dir(state_dir)
    except (OSError, PermissionError):
        return {"ok": False, "history": [], "error": "history not readable"}
    try:
        entries = _normalized_history(dirfd)
        if (not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or index >= len(entries)):
            return {"ok": False, "history": entries[:MAX_HISTORY],
                    "error": "history index out of range"}
        del entries[index]
        _publish(dirfd, HISTORY_NAME, json.dumps(entries))
        return {"ok": True, "history": entries[:MAX_HISTORY], "error": None}
    except (OSError, ValueError):
        return {"ok": False, "history": [], "error": "delete failed"}
    finally:
        os.close(dirfd)


def _resolve_key(environ=None, run=None, tool=None):
    """Return the API key (str) or None — env first, then omaseal.

    The returned value is secret material: callers must never print it.
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


def _copy_available(path=None):
    """Whether the fixed-path wl-copy binary exists and is executable."""
    path = WL_COPY if path is None else path
    return os.path.isfile(path) and os.access(path, os.X_OK)


def status(environ=None, run=None, tool=None, state_dir=None, copy_bin=None):
    """{"installed","authed","copy_available","history"} — no API call."""
    run = _run if run is None else run
    tool = _tool if tool is None else tool
    installed = tool("pplx") is not None
    authed = bool(installed and
                  _resolve_key(environ=environ, run=run, tool=tool))
    # The journal outlives installs: read it even when pplx is gone so the
    # History tab still shows past queries.
    return {"installed": installed, "authed": authed,
            "copy_available": _copy_available(copy_bin),
            "history": _read_history(state_dir)}


def main(argv):
    # `pplx_status.py --delete <index>` removes one journal entry and
    # re-emits the updated list; every other invocation is a status probe.
    if len(argv) > 1 and argv[1] == "--delete":
        index = None
        if len(argv) > 2:
            try:
                index = int(argv[2], 10)
            except ValueError:
                index = None
        sys.stdout.write(json.dumps(delete_history(index)) + "\n")
        return 0
    sys.stdout.write(json.dumps(status()) + "\n")
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
    try:
        os.setsid()
    except OSError:
        pass
    signal.signal(signal.SIGALRM, _alrm_exit)
    signal.alarm(JOB_DEADLINE_S)
    sys.exit(main(sys.argv))
