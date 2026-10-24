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
                inject="pfieldInject", inject_count=2000, inject_sigma=0.03, balance="pfieldBalance")
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
                inject="pfieldInject", inject_count=2000, inject_sigma=0.03, balance="pfieldBalance")
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
                inject="pfieldInject", inject_count=7, inject_sigma=0.05, balance="pfieldBalance")
            root = tk.Tk()
            root.withdraw()
            v = V.Viewer(root, args)
            deadline = time.time() + 5
            while time.time() < deadline and v.server is None:
                root.update()
                time.sleep(0.02)
            class Ev: x, y = 50, 25
            v.on_image_click(Ev())
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
