#!/usr/bin/python3
"""Lightweight pplx status probe for the io.github.duketopceo.pplx bar icon.

Emits {"installed": bool, "authed": bool} on stdout. "authed" means an API
key resolves locally — PERPLEXITY_API_KEY, or the optional omaseal keyring
(`omaseal resolve omaseal://perplexity/api-key`). No network call is made
and the key value is never printed, logged, or placed on argv.

Hardening mirrors pplx_search.py / probe_nexus.py: fixed tool-lookup path,
minimal fixed child env, byte caps and deadline, process-group kill on
timeout, SIGALRM/setsid backstop. No shell, no writes.
"""
import json, os, selectors, shutil, signal, subprocess, sys, time

JOB_DEADLINE_S = 5
OMASEAL_TIMEOUT_S = 2.0    # keyring resolve can block on a prompt — keep tight
MAX_ERR_BYTES = 16384
OMASEAL_CAP = 4096
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
    res = run([omaseal, "resolve", OMASEAL_REF],
              timeout=OMASEAL_TIMEOUT_S, cap=OMASEAL_CAP)
    if res.get("rc") == 0 and not res.get("timeout") and not res.get("overflow"):
        for line in (res.get("out") or "").splitlines():
            line = line.strip()
            if line:
                return line[:MAX_KEY]
    return None


def status(environ=None, run=None, tool=None):
    """{"installed": bool, "authed": bool} — no API call, all seams injectable."""
    run = _run if run is None else run
    tool = _tool if tool is None else tool
    installed = tool("pplx") is not None
    authed = bool(installed and
                  _resolve_key(environ=environ, run=run, tool=tool))
    return {"installed": installed, "authed": authed}


def main():
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
    sys.exit(main())
