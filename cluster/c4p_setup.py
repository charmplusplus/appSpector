"""Helpers for cluster/charm4py.sh (run with the venv's python on the login node).

    python cluster/c4p_setup.py programs SITE_INI C4P_DIR CHARM4PY_SRC
        add the c4p_demo and c4p_liveviz entries to the site file's [programs]
    python cluster/c4p_setup.py liveviz CHARM4PY_SRC [--check]
        fix stock charm4py's liveviz.py image assembly (--check: report only,
        for a checkout that is not ours to edit)

Both edit text, not a configparser round trip, which would drop the file's
comments. Each prints what it did.
"""

import re
import sys

MARK = "# added by cluster/charm4py.sh (it replaces this entry when run again; remove this line to keep your edits)"


def program_entries(c4p, src):
    py = c4p + "/bin/c4p-python"
    return [
        ("c4p_demo", "c4p_demo = {appspector}/apps/c4p_demo | %s c4p_demo.py {args} +traceoff +pe {pes} "
                     "++server ++server-port {port} | --inject c4pInject | procs=pes" % py),
        ("c4p_liveviz", "c4p_liveviz = %s/examples/liveviz | %s liveviz.py {args} +traceoff +pe {pes} "
                        "++server ++server-port {port} | | procs=pes" % (src, py)),
    ]


def add_programs(text, entries):
    """``text`` with ``entries`` [(name, line)] in its [programs] section.
    An entry this script wrote before (the MARK comment line above it) is
    replaced; one without the mark is the user's and stays as it is. New
    entries go at the end of the section, which is created at the end of
    the file only when the file has none. Returns (text, messages)."""
    lines = text.splitlines()
    msgs = []
    header = next((i for i, l in enumerate(lines) if l.strip().lower() == "[programs]"), None)
    if header is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "[programs]"]
        header = len(lines) - 1
    for name, entry in entries:
        end = next((i for i in range(header + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        pat = re.compile(r"\s*%s\s*[=:]" % re.escape(name))
        at = next((i for i in range(header + 1, end) if pat.match(lines[i])), None)
        if at is None:
            while end > header + 1 and not lines[end - 1].strip():
                end -= 1                        # before the blank lines that end the section
            lines[end:end] = [MARK, entry]
            msgs.append("added %s" % name)
            continue
        # a value can go on over indented continuation lines
        last = at
        while last + 1 < end and lines[last + 1][:1] in (" ", "\t") and lines[last + 1].strip():
            last += 1
        if at > 0 and lines[at - 1].strip() == MARK:
            if lines[at:last + 1] == [entry]:
                msgs.append("%s is up to date" % name)
            else:
                lines[at:last + 1] = [entry]
                msgs.append("updated %s" % name)
        else:
            msgs.append("kept your own %s entry (no '%s' line above it); the one this script would write:\n  %s"
                        % (name, MARK[:30] + "...", entry))
    return "\n".join(lines) + "\n", msgs


# charm4py main (2026-11) aborts at the first liveViz image: ByteImage.from_contributions does
# (bytearray + bytes) % 256, which is bytes formatting (TypeError). Same per-pixel sum, done per byte.
LV_OLD = "= (buffer[dst_pos:dst_pos + bytes_per_pixel] + data[src_pos:src_pos + bytes_per_pixel]) % 256"
LV_NEW = ("= bytes((a + b) % 256 for a, b in zip(buffer[dst_pos:dst_pos + bytes_per_pixel], "
          "data[src_pos:src_pos + bytes_per_pixel]))")


def liveviz_state(text):
    """'needs-patch', 'patched' (our fix is in), 'not-needed' (no per-byte
    % 256 sum at all, e.g. the NumPy liveviz of branch liveviz-numpy-v2),
    or 'unknown' (a % 256 sum this script does not recognise)."""
    if LV_OLD in text:
        return "needs-patch"
    if LV_NEW in text:
        return "patched"
    if "% 256" not in text:
        return "not-needed"
    return "unknown"


def patch_liveviz(path, check_only=False):
    """Apply (or with check_only, report) the liveviz fix. Returns (state, message)."""
    with open(path) as f:
        text = f.read()
    state = liveviz_state(text)
    if state == "needs-patch" and not check_only:
        with open(path, "w") as f:
            f.write(text.replace(LV_OLD, LV_NEW))
        return "applied", "liveviz fix: applied to %s" % path
    if state == "needs-patch":
        return state, ("liveviz fix: NOT applied: %s is your checkout, and it has the line that aborts at the "
                       "first image. Replace\n    %s\n  with\n    %s\n  or use charm4py branch liveviz-numpy-v2."
                       % (path, LV_OLD, LV_NEW))
    if state == "patched":
        return state, "liveviz fix: already applied in %s" % path
    if state == "not-needed":
        return state, "liveviz fix: not needed (%s has no per-byte %% 256 sum; NumPy liveviz?)" % path
    return state, ("liveviz fix: NOT applied: %s has a %% 256 expression this script does not recognise; "
                   "check ByteImage.from_contributions by hand (images may abort the job)" % path)


def main(argv):
    if argv[:1] == ["programs"] and len(argv) == 4:
        path, c4p, src = argv[1:]
        with open(path) as f:
            text, msgs = add_programs(f.read(), program_entries(c4p, src))
        with open(path, "w") as f:
            f.write(text)
        for m in msgs:
            print("%s: %s" % (path, m))
        return 0
    if argv[:1] == ["liveviz"] and len(argv) in (2, 3):
        state, msg = patch_liveviz(argv[1] + "/charm4py/liveviz.py", check_only=argv[2:] == ["--check"])
        print(msg)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
