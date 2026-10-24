"""Headless check of everything appSpector reads from a running job, through
a forward on HOST:PORT: liveViz config and image (saved as PNG), the
utilization stream and its names, the LBObjLoads snapshot, and the viewer
with both bottom views. Usage: python3 tests/remote_check.py HOST PORT [PNG]"""
import faulthandler
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

faulthandler.dump_traceback_later(180, exit=True)
import ccsio
from ccsio import liveviz, objload, perf

host, port = sys.argv[1], int(sys.argv[2])
png = sys.argv[3] if len(sys.argv) > 3 else None
s = ccsio.Server(host, port, timeout=30)
print("job:", s)
cfg = liveviz.get_config(s)
print("liveViz config:", cfg)
t0 = time.time()
img = liveviz.get_image(s, 800, 800, config=cfg)
print("image 800x800: %d bytes in %.0f ms" % (len(img.pixels), 1000 * (time.time() - t0)))
if png:
    img.to_pil().save(png)
    print("saved", png)
t0 = time.time()
for _ in range(5):
    liveviz.get_image(s, 400, 400, config=cfg)
print("5 x 400x400: %.0f ms each" % (200 * (time.time() - t0)))
# a job without a handler answers with 0 bytes (classic) or closes the
# connection (reconverse); both mean "not there"
try:
    names = perf.fetch_sts(s)
    print("entry names over CCS:", len(names))
    sd = None
    for _ in range(6):
        sd = perf.fetch(s)
        if sd:
            break
        time.sleep(1)
    print("utilization stream:", "none" if sd is None else "%d bins, %d procs, top %s" % (
        sd.num_bins, sd.num_procs,
        [(perf.ep_name(names, ep), round(u)) for ep, u in sorted(sd.by_ep().items(), key=lambda kv: -kv[1])[:3]]))
except (ValueError, ccsio.CcsError):
    print("utilization stream: not in this program (no -tracemode utilization)")
try:
    a = objload.fetch(s)
    time.sleep(1)
    d = objload.diff(a, objload.fetch(s))
    print("LBObjLoads: %d PEs, %d objects; utilization per PE %s" % (
        a.num_pes, a.num_objs, {pe: "%.0f%%" % (100 * p.utilization()) for pe, p in sorted(d.pes.items())}))
except (ValueError, ccsio.CcsError) as e:
    print("LBObjLoads: not in this build:", e)
import argparse
import tkinter as tk
from appspector import viewer as V
args = argparse.Namespace(host=host, port=port, key=None, size=(400, 300), image_ms=200, perf_ms=1000,
                          sts=None, no_image=False, no_perf=False, timeout=30.0, pane="objects")
root = tk.Tk()
root.withdraw()
v = V.Viewer(root, args)
t0 = time.time()
while time.time() - t0 < 8:
    root.update()
    time.sleep(0.02)
n_obj = len(v.perf_canvas.find_all())
v.view.set("ep")
v.redraw_bottom()
root.update()
print("viewer: %d frames, %d intervals, %d ep columns; canvas items objects=%d ep=%d; status: %s" % (
    v.frames, v.intervals, len(v.columns), n_obj, len(v.perf_canvas.find_all()), v.status.get()))
v.close()
print("exit clean")
