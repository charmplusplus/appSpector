import os
import struct
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from fake_server import FakeCcsServer
from ccsio import perf

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:
    HAVE_TK = False


def perf_reply(n_bins=1000):
    buf = struct.pack("<ii", n_bins, 2)
    for b in range(n_bins):
        buf += struct.pack("<h", 2) + struct.pack("<hB", 3, 150) + struct.pack("<hB", 10000, 25)
    return buf


class ColumnTests(unittest.TestCase):
    def test_column(self):
        from appspector.viewer import column_from_sumdetail
        by_ep, total = column_from_sumdetail(perf.decode_sumdetail(perf_reply(10)))
        self.assertEqual(by_ep, {3: 60.0, 10000: 10.0})
        self.assertEqual(total, 70.0)


class StatusLineTests(unittest.TestCase):
    """Notices (replies to a click or to Balance) hold the line against the
    frame counter for a while; alerts (polling errors) show at once."""

    class Var:
        def set(self, text):
            self.text = text

    def setUp(self):
        from appspector.viewer import StatusLine
        self.now = 100.0
        self.var = self.Var()
        self.line = StatusLine(self.var, hold=4.0, clock=lambda: self.now)

    def test_routine_without_notice(self):
        self.line.routine("frame 1")
        self.line.routine("frame 2")
        self.assertEqual(self.var.text, "frame 2")

    def test_notice_holds_then_expires(self):
        self.line.routine("frame 1")
        self.line.notice("inject at (0.13, 0.25): injected 2000 into 15 cells")
        self.now += 3.9
        self.line.routine("frame 20")
        self.assertEqual(self.var.text, "inject at (0.13, 0.25): injected 2000 into 15 cells")
        self.now += 0.2
        self.line.routine("frame 21")
        self.assertEqual(self.var.text, "frame 21")

    def test_new_notice_restarts_hold(self):
        self.line.notice("inject at (0.50, 0.50): sent, waiting for the reply ...")
        self.now += 3.0
        self.line.notice("inject at (0.50, 0.50): no reply (job has no pfieldInject handler)")
        self.now += 3.0
        self.line.routine("frame 30")
        self.assertIn("no reply", self.var.text)

    def test_alert_shows_at_once_and_ends_notice(self):
        self.line.notice("balance: done")
        self.line.alert("image: the job is gone (connection refused)")
        self.assertEqual(self.var.text, "image: the job is gone (connection refused)")
        self.line.routine("frame 5")           # not held: the next frame replaces it
        self.assertEqual(self.var.text, "frame 5")



class PacerTests(unittest.TestCase):
    def test_fast_requests_keep_the_interval(self):
        from appspector.viewer import Pacer
        p = Pacer(0.2)
        for _ in range(20):
            self.assertAlmostEqual(p.wait(0.02), 0.18)

    def test_slow_requests_back_off_to_the_latency(self):
        from appspector.viewer import Pacer
        p = Pacer(0.2)
        self.assertAlmostEqual(p.wait(2.0), 2.0)        # first sample seeds the average
        for _ in range(20):
            w = p.wait(2.0)
        self.assertAlmostEqual(w, 2.0)                  # idle as long as busy, not back to back

    def test_backoff_is_capped(self):
        from appspector.viewer import Pacer
        p = Pacer(0.2, max_wait=5.0)
        self.assertEqual(p.wait(30.0), 5.0)
        self.assertEqual(Pacer(10.0, max_wait=5.0).wait(0.0), 10.0)   # the interval is never cut

    def test_recovers_when_requests_speed_up(self):
        from appspector.viewer import Pacer
        p = Pacer(0.2)
        for _ in range(10):
            p.wait(2.0)
        waits = [p.wait(0.02) for _ in range(15)]
        self.assertGreater(waits[0], 1.0)               # smoothed: one fast request is not enough
        self.assertTrue(all(a >= b for a, b in zip(waits, waits[1:])))
        self.assertAlmostEqual(waits[-1], 0.18)

    def test_fixed_rate(self):
        from appspector.viewer import Pacer
        p = Pacer(0.2, adaptive=False)
        self.assertEqual(p.wait(2.0), 0.0)
        self.assertAlmostEqual(p.wait(0.05), 0.15)

    def test_poller_one_request_outstanding(self):
        import queue
        import threading
        from appspector.viewer import Poller
        lock = threading.Lock()
        state = {"now": 0, "max": 0}

        def fn():
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.03)
            with lock:
                state["now"] -= 1
            return 1
        out = queue.Queue()
        p = Poller(fn, 0.001, out)
        p.start()
        for _ in range(5):
            out.get(timeout=5)
        p.stop.set()
        p.join(timeout=2)
        self.assertEqual(state["max"], 1)
        self.assertGreaterEqual(p.period, 0.05)         # 30 ms request, then at least ~30 ms quiet

@unittest.skipUnless(HAVE_TK, "no Tk display")
class ViewerSmokeTest(unittest.TestCase):
    def test_polls_both_panes(self):
        from appspector import viewer as V
        srv = FakeCcsServer(node_sizes=(2,))
        srv.register("lvConfig", lambda pe, d: struct.pack("!iiii", 1, 1, 1, 0))

        def image(pe, d):
            v, code, w, h = struct.unpack("!iiii", d[:16])
            return bytes([200, 30, 30]) * (w * h)
        srv.register("lvImage", image)
        srv.register(perf.HANDLER, lambda pe, d: perf_reply())
        srv.register("LBObjLoads", lambda pe, d: struct.pack("<i", 0))
        try:
            args = V.main.__globals__["argparse"].Namespace(
                host="127.0.0.1", port=srv.port, key=None, size=(120, 80), image_ms=50,
                perf_ms=50, sts=None, no_image=False, no_perf=False, timeout=5.0, pane="ep",
                inject="pfieldInject", inject_count=2000, inject_sigma=0.03, balance="pfieldBalance", fixed_rate=False)
            root = tk.Tk()
            root.withdraw()
            v = V.Viewer(root, args)
            deadline = time.time() + 5
            while time.time() < deadline and (v.frames < 2 or len(v.columns) < 2):
                root.update()
                time.sleep(0.02)
            self.assertGreaterEqual(v.frames, 2, v.status.get())
            self.assertGreaterEqual(len(v.columns), 2)
            self.assertEqual(v.columns[-1][0], {3: 60.0, 10000: 10.0})
            self.assertIn("frame", v.status.get())
            v.close()
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_TK, "no Tk display")
class ObjectsPaneTest(unittest.TestCase):
    def test_objects_pane(self):
        from appspector import viewer as V
        from ccsio import objload
        srv = FakeCcsServer(node_sizes=(2,))
        state = {"t": 0.0}

        def loads(pe, d):
            state["t"] += 0.5
            t = state["t"]
            out = struct.pack("<i", 2)
            for p in (0, 1):
                out += struct.pack("<idddi", p, t, t, 0.1 * t, 3)
                for k in range(3):
                    out += struct.pack("<QidB", 100 + 10 * p + k, 9, (0.2 + 0.05 * k) * t, 1)
            return out
        srv.register(objload.HANDLER, loads)
        try:
            args = V.main.__globals__["argparse"].Namespace(
                host="127.0.0.1", port=srv.port, key=None, size=(120, 80), image_ms=50,
                perf_ms=50, sts=None, no_image=True, no_perf=False, timeout=5.0, pane="objects",
                inject="pfieldInject", inject_count=2000, inject_sigma=0.03, balance="pfieldBalance", fixed_rate=False)
            root = tk.Tk()
            root.withdraw()
            v = V.Viewer(root, args)
            deadline = time.time() + 5
            while time.time() < deadline and v.intervals < 3:
                root.update()
                time.sleep(0.02)
            self.assertGreaterEqual(v.intervals, 3)
            iv = v.interval
            self.assertEqual(sorted(iv.pes), [0, 1])
            self.assertAlmostEqual(iv.pes[1].seconds, 0.5)
            self.assertAlmostEqual(iv.pes[1].utilization(), (0.2 + 0.25 + 0.3), places=6)
            self.assertEqual(len(V.color_for_object((9, 100))), 7)
            # a job without the ep stream: that view is disabled, the flip stays on objects
            self.assertEqual(str(v.view_buttons["ep"].cget("state")), "disabled")
            self.assertEqual(v.view.get(), "objects")
            v.view.set("objects"); v.redraw_bottom()
            self.assertGreater(len(v.perf_canvas.find_all()), 5)
            v.view.set("grid"); v.redraw_bottom()
            items = len(v.perf_canvas.find_all())
            self.assertGreaterEqual(items, 2 + 1)          # two PE squares (+ labels) + caption
            v.per_process.set(True); v.redraw_bottom()
            self.assertLess(len(v.perf_canvas.find_all()), items)   # one process square instead of two
            self.assertEqual(V.utilization_color(0.0), "#2800ff")
            self.assertEqual(V.utilization_color(1.0), "#ff0028")
            self.assertNotEqual(V.color_for_object((9, 100)), V.color_for_object((9, 101)))
            v.close()
        finally:
            srv.close()


@unittest.skipUnless(HAVE_TK, "no Tk display")
class InteractionTest(unittest.TestCase):
    def test_click_and_balance(self):
        from appspector import viewer as V
        from ccsio import objload
        seen = []
        # like reconverse: unknown handlers (here the sts and ep stream) close the connection
        srv = FakeCcsServer(node_sizes=(1,), close_on_unknown=True)
        srv.register("lvConfig", lambda pe, d: struct.pack("!iiii", 1, 1, 1, 0))
        srv.register("lvImage", lambda pe, d: bytes(3 * struct.unpack("!iiii", d[:16])[2] * struct.unpack("!iiii", d[:16])[3]))
        srv.register(objload.HANDLER, lambda pe, d: struct.pack("<i", 0))
        srv.register("pfieldInject", lambda pe, d: (seen.append(("inject", struct.unpack("!dddi", d))), b"injected 7")[1])
        srv.register("pfieldBalance", lambda pe, d: (seen.append(("balance", d)), b"balancing")[1])
        try:
            args = V.main.__globals__["argparse"].Namespace(
                host="127.0.0.1", port=srv.port, key=None, size=(200, 100), image_ms=50,
                perf_ms=50, sts=None, no_image=False, no_perf=False, timeout=5.0, pane="objects",
                inject="pfieldInject", inject_count=7, inject_sigma=0.05, balance="pfieldBalance", fixed_rate=False)
            root = tk.Tk()
            root.withdraw()
            v = V.Viewer(root, args)
            v.status_line.hold = 60.0      # longer than the test, however slow the box
            deadline = time.time() + 5
            while time.time() < deadline and v.server is None:
                root.update()
                time.sleep(0.02)
            # let the missing ep stream switch its pane off first: that is a notice too
            deadline = time.time() + 5
            while time.time() < deadline and str(v.view_buttons["ep"].cget("state")) != "disabled":
                root.update()
                time.sleep(0.02)
            class Ev: x, y = 50, 25
            v.on_image_click(Ev())
            self.assertEqual(v.status.get(), "inject at (0.25, 0.25): sent, waiting for the reply ...")
            deadline = time.time() + 5
            while time.time() < deadline and "injected" not in v.status.get():
                root.update()
                time.sleep(0.02)
            # the reply stays on the status line while frames keep arriving
            frames = v.frames
            deadline = time.time() + 5
            while time.time() < deadline and v.frames < frames + 3:
                root.update()
                time.sleep(0.02)
            self.assertGreaterEqual(v.frames, frames + 3)
            self.assertEqual(v.status.get(), "inject at (0.25, 0.25): injected 7")
            v.request_balance()
            deadline = time.time() + 5
            while time.time() < deadline and len(seen) < 2:
                root.update()
                time.sleep(0.02)
            kinds = {k for k, _ in seen}
            self.assertEqual(kinds, {"inject", "balance"})
            self.assertFalse(v.has_ep_stream)       # probed, found missing, bars kept working
            self.assertTrue(v.has_objects)
            inj = [d for k, d in seen if k == "inject"][0]
            self.assertAlmostEqual(inj[0], 0.25); self.assertAlmostEqual(inj[1], 0.25)
            self.assertAlmostEqual(inj[2], 0.05); self.assertEqual(inj[3], 7)
            v.close()
        finally:
            srv.close()
