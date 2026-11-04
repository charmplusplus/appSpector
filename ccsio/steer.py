"""Steering a charm4py program: call the Python functions it exposes with
``charm4py.steer`` (CCS handler "c4pSteer", on PE 0).

    import ccsio
    from ccsio import steer
    s = ccsio.Server("127.0.0.1", 1404, key=KEY)
    steer.list(s)                   # {"calls": [{"name", "signature", "doc"}], "eval": bool}
    steer.call(s, "set_rate", 0.5)  # the function's return value, or SteerError
    steer.eval(s, "x + 1")          # only if the program enabled eval and runs with ++server-auth

Wire format: the request is UTF-8 JSON {"call": NAME, "args": [...],
"kwargs": {...}}; the reply is UTF-8 JSON {"ok": true, "result": ...} or
{"ok": false, "error": "Type: message", "traceback": "..."}.
"""

import builtins
import json
import shlex

from .client import CcsError, CcsNoReply

HANDLER = "c4pSteer"
PE = 0                  # the handler is registered on PE 0 only


class SteerError(CcsError):
    """The call failed in the job (``error``, ``traceback`` from its reply),
    or the job does not serve steering requests."""

    def __init__(self, error, traceback=""):
        super().__init__(error)
        self.error = error
        self.traceback = traceback


def encode_request(name, args=(), kwargs=None):
    return json.dumps({"call": name, "args": builtins.list(args),
                       "kwargs": dict(kwargs or {})}).encode("utf-8")


def decode_reply(data):
    """Reply bytes -> the reply dict; SteerError if they are not a steering reply."""
    text = data.decode("utf-8", "replace").rstrip("\0")
    if not text:
        raise SteerError("empty reply: the job has no %s handler (a charm4py program that calls "
                         "charm4py.steer.init())" % HANDLER)
    try:
        reply = json.loads(text)
    except ValueError:
        raise SteerError("not a steering reply: %r" % text[:200])
    if not isinstance(reply, dict) or "ok" not in reply:
        raise SteerError("not a steering reply: %r" % text[:200])
    return reply


def request(server, name, args=(), kwargs=None, timeout=None):
    """Send one steering request; return the reply dict (ok or not)."""
    try:
        data = server.request(HANDLER, PE, encode_request(name, args, kwargs), timeout=timeout)
    except CcsNoReply:
        if getattr(server, "key", None) is None:
            raise SteerError("no reply: the job has no %s handler, or it runs with ++server-auth and "
                             "no key was given" % HANDLER)
        raise SteerError("no reply: the job has no %s handler (a charm4py program that calls "
                         "charm4py.steer.init())" % HANDLER)
    return decode_reply(data)


def _result(reply):
    if not reply.get("ok"):
        raise SteerError(reply.get("error", "failed"), reply.get("traceback", ""))
    return reply.get("result")


def call(server, name, /, *args, timeout=None, **kwargs):
    """Call the exposed function ``name`` with these arguments (JSON values);
    returns its result, or raises SteerError with the job's error."""
    return _result(request(server, name, args, kwargs, timeout=timeout))


def list(server, timeout=None):
    """What the job exposes: {"calls": [{"name", "signature", "doc"}, ...], "eval": bool}."""
    return _result(request(server, "list", timeout=timeout))


def eval(server, source, timeout=None):
    """Run Python source on the job's PE 0 (if the job allows it); returns
    the value of an expression, or of a trailing expression statement."""
    return _result(request(server, "eval", [source], timeout=timeout))


# -- command-line form (the shell's and the viewer's 'steer' line) -------------

def parse_value(word):
    """A command-line word as a JSON value when it parses as one (0.5, true,
    [1,2], "text", null), else as the string itself."""
    try:
        return json.loads(word)
    except ValueError:
        return word


def parse_command(line):
    """'NAME ARG ... KEY=VALUE ...' -> (name, args, kwargs). Words are split
    as by a shell; each value is JSON if it parses, else a string. 'eval
    SOURCE' keeps the rest of the line as one source string. An empty line,
    'list' or '?' mean list."""
    line = line.strip()
    if not line or line in ("list", "?"):
        return "list", [], {}
    head, _, rest = line.partition(" ")
    if head == "eval":
        return "eval", [rest.strip()], {}
    words = shlex.split(line)
    name, args, kwargs = words[0], [], {}
    for w in words[1:]:
        key, eq, value = w.partition("=")
        if eq and key.isidentifier():
            kwargs[key] = parse_value(value)
        elif kwargs:
            raise ValueError("positional argument %r after keyword arguments" % w)
        else:
            args.append(parse_value(w))
    return name, args, kwargs


def format_listing(listing):
    """The 'list' result as lines of text."""
    calls = listing.get("calls", [])
    lines = []
    for c in calls:
        doc = (c.get("doc") or "").strip().splitlines()
        lines.append("  %s%s%s" % (c["name"], c.get("signature", ""), ("    " + doc[0]) if doc else ""))
    if not calls:
        lines.append("  (the job exposes no calls)")
    lines.append("  eval: %s" % ("on (Python on PE 0: 'steer eval SOURCE')" if listing.get("eval")
                                 else "off"))
    return "\n".join(lines)


def format_result(result):
    if isinstance(result, str):
        return result
    return json.dumps(result)


def run_command(server, line, timeout=None):
    """One command line -> the text to show (raises SteerError, CcsError, ValueError)."""
    name, args, kwargs = parse_command(line)
    if name == "list":
        return format_listing(list(server, timeout=timeout))
    return format_result(_result(request(server, name, args, kwargs, timeout=timeout)))
