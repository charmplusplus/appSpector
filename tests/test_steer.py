"""ccsio.steer, the shell's steer command and the viewer's steer line,
against fake_server.steer_handler (the c4pSteer protocol of charm4py.steer)."""

import argparse
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import ccsio
from ccsio import steer
from appspector import jobs as J
from appspector import launch as L
from fake_server import FakeCcsServer, steer_handler

KEY = "0 12345678901234567890123456789012".split()[1]

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_TK = True
except Exception:
    HAVE_TK = False


def make_calls(state):
    def set_rate(rate: float, clamp=True):
        """Set the diffusion rate.

        Every chare gets it."""
        if rate < 0:
            raise ValueError("rate must be positive")
        state["rate"] = min(rate, 1.0) if clamp else rate
        return state["rate"]

    def status():
        "Steps done and the rate."
        return {"steps": 12, "rate": state.get("rate")}

    def slow(secs=0.5):
        time.sleep(secs)
        return "slept"
    return {"set_rate": set_rate, "status": status, "slow": slow}


class SteerClientTests(unittest.TestCase):
    def setUp(self):
        self.state, self.seen = {}, []
        self.srv = FakeCcsServer(node_sizes=(2,), key=None)
        self.srv.register(steer.HANDLER, steer_handler(make_calls(self.state), seen=self.seen))
        self.s = ccsio.Server("127.0.0.1", self.srv.port)

    def tearDown(self):
        self.srv.close()

    def test_list(self):
        listing = steer.list(self.s)
        self.assertFalse(listing["eval"])
        self.assertEqual([c["name"] for c in listing["calls"]], ["set_rate", "slow", "status"])
        self.assertEqual(listing["calls"][0]["signature"], "(rate: float, clamp=True)")
        text = steer.format_listing(listing)
        self.assertIn("  set_rate(rate: float, clamp=True)    Set the diffusion rate.", text)
        self.assertTrue(text.endswith("eval: off"))
        self.assertEqual(self.srv.requests[-1][:2], (steer.HANDLER, 0))     # PE 0

    def test_call(self):
        self.assertEqual(steer.call(self.s, "set_rate", 0.25), 0.25)
        self.assertEqual(steer.call(self.s, "set_rate", 3, clamp=False), 3)
        self.assertEqual(self.seen[-1], {"call": "set_rate", "args": [3], "kwargs": {"clamp": False}})
        self.assertEqual(steer.call(self.s, "status"), {"steps": 12, "rate": 3})

    def test_errors(self):
        with self.assertRaises(steer.SteerError) as cm:
            steer.call(self.s, "set_rate", -1)
        self.assertEqual(cm.exception.error, "ValueError: rate must be positive")
        self.assertIn("Traceback", cm.exception.traceback)
        with self.assertRaises(steer.SteerError) as cm:
            steer.call(self.s, "nope")
        self.assertIn("no steering call 'nope'", cm.exception.error)
        with self.assertRaises(steer.SteerError) as cm:
            steer.eval(self.s, "1+1")
        self.assertIn("eval is off", cm.exception.error)
        self.assertIsInstance(cm.exception, ccsio.CcsError)

    def test_job_without_handler(self):
        self.srv.handlers.pop(steer.HANDLER)          # classic: 0-byte reply
        with self.assertRaises(steer.SteerError) as cm:
            steer.list(self.s)
        self.assertIn("no c4pSteer handler", str(cm.exception))
        self.srv.close_on_unknown = True              # reconverse: closes
        with self.assertRaises(steer.SteerError) as cm:
            steer.call(self.s, "x")
        self.assertIn("no c4pSteer handler", str(cm.exception))
        self.srv.register(steer.HANDLER, lambda pe, d: b"hello")
        with self.assertRaises(steer.SteerError) as cm:
            steer.list(self.s)
        self.assertIn("not a steering reply", str(cm.exception))

    def test_slow_call_does_not_hold_other_requests(self):
        """A steering call in flight on one thread; another thread's
        requests still go through (each thread has its own connection)."""
        got = {}
        t = threading.Thread(target=lambda: got.update(r=steer.call(self.s, "slow", 0.6)))
        t0 = time.monotonic()
        t.start()
        time.sleep(0.05)
        self.assertEqual(steer.call(self.s, "status")["steps"], 12)
        self.assertLess(time.monotonic() - t0, 0.5)
        t.join()
        self.assertEqual(got["r"], "slept")


class SteerAuthTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeCcsServer(node_sizes=(1,), key=ccsio.parse_key(KEY))
        self.srv.register(steer.HANDLER, steer_handler(make_calls({}), eval_namespace={"x": 41}))

    def tearDown(self):
        self.srv.close()

    def test_with_key(self):
        s = ccsio.Server("127.0.0.1", self.srv.port, key=KEY)
        self.assertTrue(steer.list(s)["eval"])
        self.assertEqual(steer.eval(s, "x + 1"), 42)
        self.assertEqual(steer.call(s, "set_rate", 0.5), 0.5)

    def test_wrong_or_no_key(self):
        with self.assertRaises(ccsio.CcsError) as cm:
            ccsio.Server("127.0.0.1", self.srv.port, key="9" * 32)
        self.assertIn("does not accept our key", str(cm.exception))
        s = ccsio.Server("127.0.0.1", self.srv.port, connect=False)     # no key at all
        with self.assertRaises(steer.SteerError) as cm:
            steer.call(s, "set_rate", 0.5)
        self.assertIn("++server-auth and no key was given", str(cm.exception))
        self.assertFalse(any(r[0] == steer.HANDLER for r in self.srv.requests))


class ParseTests(unittest.TestCase):
    def test_parse_command(self):
        p = steer.parse_command
        self.assertEqual(p(""), ("list", [], {}))
        self.assertEqual(p("list"), ("list", [], {}))
        self.assertEqual(p("set_rate 0.5"), ("set_rate", [0.5], {}))
        self.assertEqual(p("f -2 true null [1,2] word 'two words' clamp=false"),
                         ("f", [-2, True, None, [1, 2], "word", "two words"], {"clamp": False}))
        self.assertEqual(p('g "3"'), ("g", [3], {}))          # the shell's quotes go ...
        self.assertEqual(p("g '\"3\"'"), ("g", ["3"], {}))     # ... JSON's quotes make a string
        self.assertEqual(p("eval  y = [x for x in range(3)]; y "), ("eval", ["y = [x for x in range(3)]; y"], {}))
        with self.assertRaises(ValueError):
            p("f a=1 2")
        self.assertEqual(steer.format_result("text"), "text")
        self.assertEqual(steer.format_result({"a": [1]}), '{"a": [1]}')


class ShellSteerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (J.JOBS_FILE, J.connect, J._port_free)
        J.JOBS_FILE = os.path.join(self.tmp, "jobs.json")
        self.state = {}
        self.srv = FakeCcsServer(node_sizes=(1,), key=ccsio.parse_key(KEY))
        self.srv.register(steer.HANDLER, steer_handler(make_calls(self.state)))
        self.connects = []

        def connect(site, job, local_port=None):
            self.connects.append(job.id)
            job.forward = "%d:cn001:1304" % self.srv.port
            return "127.0.0.1", self.srv.port
        J.connect = connect
        from appspector.shell import Shell
        self.sh = Shell("local")
        self.out = []
        self.sh.say = self.out.append
        self.job = J.Job(id="777", site="local", program="demo", args="", pes=2, port=1304, out="",
                         submitted=0.0, state="up", node="cn001", key=KEY)
        J.record(self.job)
        self.sh.current = self.job

    def tearDown(self):
        J.JOBS_FILE, J.connect, J._port_free = self.saved
        self.srv.close()

    def test_steer_commands(self):
        self.sh.do_steer("")
        self.assertIn("set_rate(rate: float, clamp=True)", self.out[-1])
        self.sh.do_steer("set_rate 0.5")
        self.assertEqual(self.out[-1], "0.5")
        self.assertEqual(self.state["rate"], 0.5)
        self.sh.do_steer("status")
        self.assertEqual(self.out[-1], '{"steps": 12, "rate": 0.5}')
        self.sh.do_steer("set_rate -1")
        self.assertEqual(self.out[-2], "steer: ValueError: rate must be positive")
        self.assertIn("Traceback", self.out[-1])
        self.sh.do_steer("f a=1 2")
        self.assertIn("after keyword", self.out[-1])
        self.assertEqual(self.connects, ["777"])          # one connection, kept

    def test_reuses_an_open_forward(self):
        """A slurm job whose forward (the viewer's) is listening: steer uses
        it rather than registering a new forward, which would replace it."""
        from appspector import sites as S
        site = S.Site(name="cluster", path="", scheduler="slurm")
        self.job.forward = "%d:cn001:1304" % self.srv.port
        J._port_free = lambda port: port != self.srv.port
        self.sh._site_of = lambda job: site
        self.sh.do_steer("set_rate 0.25")
        self.assertEqual(self.out[-1], "0.25")
        self.assertEqual(self.connects, [])
        # no forward in place: connect() makes one
        self.sh._steer_servers.clear()
        J._port_free = lambda port: True
        self.sh.do_steer("status")
        self.assertEqual(self.connects, ["777"])

    def test_wrong_key_and_not_up(self):
        self.job.key = "1" * 32
        self.sh.do_steer("status")
        self.assertIn("steer: server does not accept our key", self.out[-1])
        self.assertNotIn("777", self.sh._steer_servers)
        self.job.state = "running"
        self.sh.do_steer("status")
        self.assertEqual(self.out[-1], "job 777 is running, not up")
        self.sh.current = None
        self.sh.do_steer("")
        self.assertIn("no current job", self.out[-1])

    def test_one_shot(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from appspector import shell
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = shell.main(["steer", "777", "set_rate", "0.75"])
        self.assertEqual((rc, buf.getvalue()), (0, "0.75\n"))
        with redirect_stdout(buf):
            rc = shell.main(["steer", "777", "nope"])
        self.assertEqual(rc, 1)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(shell.main(["steer", "999"]), 1)


@unittest.skipUnless(HAVE_TK, "no Tk display")
class ViewerSteerTest(unittest.TestCase):
    def test_steer_line(self):
        from appspector import viewer as V
        state = {}
        srv = FakeCcsServer(node_sizes=(1,), close_on_unknown=True)
        srv.register(steer.HANDLER, steer_handler(make_calls(state)))
        try:
            args = argparse.Namespace(
                host="127.0.0.1", port=srv.port, key=None, size=(120, 80), image_ms=50,
                perf_ms=50, fixed_rate=False, sts=None, no_image=True, no_perf=True, timeout=5.0, pane="objects",
                inject="pfieldInject", inject_count=2000, inject_sigma=0.03, balance="pfieldBalance", steer=True)
            root = tk.Tk()
            root.withdraw()
            v = V.Viewer(root, args)
            v.status_line.hold = 60.0
            deadline = time.time() + 5
            while time.time() < deadline and not v.steer_calls.get().startswith("calls:"):
                root.update()
                time.sleep(0.02)
            self.assertEqual(v.steer_calls.get(), "calls: set_rate(rate: float, clamp=True), slow(secs=0.5), status()")
            v.request_steer("set_rate 0.4")
            self.assertIn("sent", v.status.get())
            deadline = time.time() + 5
            while time.time() < deadline and "sent" in v.status.get():
                root.update()
                time.sleep(0.02)
            self.assertEqual(v.status.get(), "steer set_rate 0.4: 0.4")
            self.assertEqual(state["rate"], 0.4)
            v.request_steer("nope")
            deadline = time.time() + 5
            while time.time() < deadline and "sent" in v.status.get():
                root.update()
                time.sleep(0.02)
            self.assertIn("steer nope: failed: KeyError", v.status.get())
            v.close()
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
