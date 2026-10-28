"""End-to-end check of the pfield demo through the viewer's own code paths,
headless: start pfield (or point at a running one), wait for load
intervals, inject blobs where the viewer would on clicks, run Balance,
and report loads and chare placement before and after.

    python3 tests/pfield_check.py [HOST PORT]      # default: starts ./apps/pfield/pfield on 4 PEs
"""
import argparse
import faulthandler
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
faulthandler.dump_traceback_later(240, exit=True)

import tkinter as tk
from appspector import viewer as V

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
job = None
if len(sys.argv) >= 3:
    host, port = sys.argv[1], int(sys.argv[2])
else:
    host, port = "127.0.0.1", 31399
    exe = os.path.join(REPO, "apps", "pfield", "pfield")
    job = subprocess.Popen([exe, "+pe", "4", "++server", "++server-port", str(port), "+balancer", "GreedyRefineLB"],
                           cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(2)
try:
    args = argparse.Namespace(host=host, port=port, key=None, size=(600, 600), image_ms=200, perf_ms=1000,
                              sts=None, no_image=False, no_perf=False, timeout=20.0, pane="objects",
                              inject="pfieldInject", inject_count=3000, inject_sigma=0.03, balance="pfieldBalance")
    root = tk.Tk()
    root.withdraw()
    v = V.Viewer(root, args)

    def spin_until(cond, limit):
        t0 = time.time()
        while time.time() - t0 < limit and not cond():
            root.update()
            time.sleep(0.02)
        return cond()

    def util():
        return {pe: "%3.0f%%" % (100 * p.utilization()) for pe, p in sorted(v.interval.pes.items())}

    def where():
        return {k: pe for pe, p in v.prev_snapshot.pes.items() for k in p.objs}

    ok = spin_until(lambda: v.intervals >= 3, 30)
    print("connected:", v.status.get() if not ok else "%d PEs, %d chares" % (v.prev_snapshot.num_pes, v.prev_snapshot.num_objs))
    assert ok, "no load intervals arrived"
    print("load before     :", util())
    class Ev:
        pass
    for x, y in ((120, 120), (150, 100), (100, 160)):
        e = Ev(); e.x, e.y = x, y
        v.on_image_click(e)
    n0 = v.intervals
    spin_until(lambda: v.intervals >= n0 + 4, 30)
    print("after 3 clicks  :", util(), "|", v.status.get())
    before = where()
    v.request_balance()
    n0 = v.intervals
    spin_until(lambda: v.intervals >= n0 + 6, 40)
    after = where()
    moved = sum(1 for k in after if k in before and before[k] != after[k])
    print("after balance   :", util(), "| %d chares moved; per PE %s" % (moved, {pe: len(p.objs) for pe, p in sorted(v.prev_snapshot.pes.items())}))
    print("frames %d, intervals %d, canvas items %d" % (v.frames, v.intervals, len(v.perf_canvas.find_all())))
    v.close()
    print("PASS" if moved > 0 and v.frames > 10 else "CHECK: no migration or no frames")
finally:
    if job is not None:
        job.kill()
        job.wait()
