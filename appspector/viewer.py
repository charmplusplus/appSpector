"""A first split-screen viewer, tkinter only.

    python -m appspector.viewer HOST PORT [-k KEY] [--size WxH]
                               [--image-ms 200] [--perf-ms 1000] [--fixed-rate]
                               [--sts prog.util.sts] [--no-image] [--no-perf]
                               [--inject HANDLER] [--balance HANDLER]
                               [--jpeg [QUALITY]]

Top pane: the job's liveViz image (handlers lvConfig / lvImage), polled on a
timer that backs off while requests are slow (see Pacer), raw pixels
unless --jpeg asks for JPEG (needs Pillow, and a Charm++ built with
libjpeg; the viewer falls back to raw if either is missing). Bottom pane
(default, --pane objects): a snapshot that changes once a second, one
bar per PE whose height is the PE's utilization in the last interval,
stacked from the time each chare ran, every chare in its own
color (handler "LBObjLoads", any Charm++ program). --pane ep instead
shows one stacked column per second of utilization by entry method,
scrolling left (handler "CkPerfSumDetail compressed", needs -tracemode
utilization). --pane grid shows every PE (or every process) as a square
in a square-ish layout, colored from blue (idle) to red (100 percent
busy) by its utilization over the last interval. A click in the image pane sends an inject request to the job (handler
"pfieldInject" by default: x, y, sigma as fractions of the image, and a
count, network order) and the Balance button sends "pfieldBalance"; both
are no-ops on jobs without those handlers. All CCS traffic runs on worker
threads; the UI thread only draws.
"""

import argparse
import collections
import math
import queue
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk

import ccsio
import colorsys

from ccsio import liveviz, objload, perf

PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
           "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#aec7e8",
           "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5"]
PANE_MISSING = {        # why a bottom-pane button is greyed out
    "ep": "'over time' pane off: the program has no CkPerfSumDetail handler (link it with -tracemode utilization)",
    "objects": "'by PE' pane off: the program has neither CkPerfObjLoads (-tracemode utilization) nor LBObjLoads (older Charm++)",
    "grid": "'PE grid' pane off: the program has neither CkPerfObjLoads (-tracemode utilization) nor LBObjLoads (older Charm++)",
    "objects+grid": "'by PE' and 'PE grid' panes off: the program has neither CkPerfObjLoads (-tracemode utilization) nor LBObjLoads (older Charm++)",
}

NOTICE_SECONDS = 4.5   # how long a notice holds the status line against routine updates
JPEG_TRIES = 3          # JPEG requests in a row with no JPEG back before raw for good
OTHER_COLOR = "#999999"
IDLE_COLOR = "#f0f0f0"


_obj_colors = {}
# Tk objects must never be finalized on a worker thread (Tcl panics with
# Tcl_AsyncDelete and the process aborts); keeping every root reachable
# until interpreter shutdown makes sure the main thread does it.
_keep_alive = []


def color_for_object(key):
    """A stable, well-separated color per chare: the hue walks the circle
    in golden-ratio steps indexed by the object id, so neighbours in id
    space (neighbouring array elements) get clearly different hues."""
    c = _obj_colors.get(key)
    if c is None:
        om, oid = key
        n = (oid * 0x9E3779B97F4A7C15 + om * 0x632BE59BD9B4E019) & 0xFFFFFFFFFFFFFFFF
        h = (n / 2.0 ** 64)
        sat = 0.55 + 0.35 * (((n >> 20) & 0xFF) / 255.0)
        val = 0.70 + 0.25 * (((n >> 28) & 0xFF) / 255.0)
        r, g, b = colorsys.hsv_to_rgb(h, sat, val)
        c = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
        _obj_colors[key] = c
    return c


def utilization_color(u):
    """Blue (idle) to red (busy), mixed in proportion; the middle passes
    through purple so a half-loaded PE reads as neither."""
    u = min(1.0, max(0.0, u))
    r = int(40 + 215 * u)
    g = int(40 * (1 - abs(2 * u - 1)))
    b = int(255 - 215 * u)
    return "#%02x%02x%02x" % (r, g, b)


def canvas_size(c):
    """Current size, or the requested size while the window is not mapped
    (headless runs and the first draw)."""
    w, h = c.winfo_width(), c.winfo_height()
    if w <= 1 or h <= 1:
        w, h = c.winfo_reqwidth(), c.winfo_reqheight()
    return w, h


def column_from_sumdetail(sd):
    """Mean utilization per entry method over one reply, as {ep: percent},
    plus the mean total. One reply is one second of 1 ms bins."""
    by_ep = sd.by_ep()
    return by_ep, sum(by_ep.values())


def tk_photo_from_image(img, master=None):
    """A tk.PhotoImage from a liveviz.Image without Pillow: Tk reads binary
    PPM (RGB) and PGM (grey) natively. master pins the image to one Tk
    root (several roots exist in the tests)."""
    magic = b"P6" if img.channels == 3 else b"P5"
    data = magic + b"\n%d %d\n255\n" % (img.width, img.height) + img.pixels
    return tk.PhotoImage(master=master, data=data, format="PPM")


class StatusLine:
    """The one status line, written three ways. routine() is the frame
    counter, set on every image (5 times a second): it would wipe anything
    else before anyone could read it, so it is dropped while a notice
    holds the line. notice() is a message the user must get to read (the
    reply to a click or to Balance, a pane switched off): it shows at once
    and holds the line for hold seconds. alert() is a polling error (the
    job is gone, a request failed) or the connect message: it shows at
    once and ends any notice, since a dead job matters more than an older
    reply and no frames will follow to replace it anyway; it is not held,
    so a one-off timeout gives way to the next frame as before. var is
    anything with set(text), a tk.StringVar in the viewer; clock is for
    the tests."""

    def __init__(self, var, hold=NOTICE_SECONDS, clock=time.monotonic):
        self.var, self.hold, self.clock = var, hold, clock
        self.until = None          # clock() time the current notice expires

    def routine(self, text):
        if self.until is None or self.clock() >= self.until:
            self.until = None
            self.var.set(text)

    def notice(self, text):
        self.until = self.clock() + self.hold
        self.var.set(text)

    def alert(self, text):
        self.until = None
        self.var.set(text)


class Pacer:
    """When a poller asks next, given how long its last request took.

    The rule: wait max(interval - latency, smoothed latency), at most
    max_wait. interval (--image-ms, --perf-ms) is the fastest the viewer
    asks. The smoothed latency (an EWMA, weight alpha on the newest
    request, seeded with the first) is the backoff: after each request the
    viewer stays quiet for at least as long as requests have been taking,
    so for requests under max_wait it keeps a slow job or link busy at most
    half the time instead of back to back. Fast requests leave the plain
    fixed rate; when they speed up again the smoothed latency falls within
    a few requests and the rate recovers. max_wait keeps a very slow pane
    refreshing. adaptive=False (--fixed-rate) is the plain
    interval - latency.

    Only the image poller is paced. Each utilization request takes the
    oldest one-second result from a queue in the runtime that grows by one
    every second, so the perf poller must keep up with --perf-ms; its
    replies are a few KB and were never the load problem."""

    def __init__(self, interval, adaptive=True, alpha=0.3, max_wait=5.0):
        self.interval, self.adaptive = interval, adaptive
        self.alpha, self.max_wait = alpha, max(max_wait, interval)
        self.smoothed = None

    def wait(self, latency):
        if self.smoothed is None:
            self.smoothed = latency
        else:
            self.smoothed += self.alpha * (latency - self.smoothed)
        w = max(0.0, self.interval - latency)
        if self.adaptive:
            w = min(max(w, self.smoothed), self.max_wait)
        return w


class Poller(threading.Thread):
    """Calls fn() over and over on one thread, so one request of its kind
    is outstanding at a time, waiting between calls as Pacer says, and
    queues (result or exception)."""

    def __init__(self, fn, interval, out, adaptive=True):
        super().__init__(daemon=True)
        self.fn, self.interval, self.out = fn, interval, out
        self.pacer = Pacer(interval, adaptive)
        self.stop = threading.Event()
        self.latency = 0.0
        self.period = interval          # last request plus the wait after it

    def run(self):
        while not self.stop.is_set():
            t0 = time.monotonic()
            try:
                r = self.fn()
            except Exception as e:          # report, keep polling
                r = e
            self.latency = time.monotonic() - t0
            wait = self.pacer.wait(self.latency)
            self.period = self.latency + wait
            self.out.put(r)
            self.stop.wait(wait)


class Viewer:
    def __init__(self, root, args):
        _keep_alive.append((root, self))
        self.root = root
        self.args = args
        root.title("appSpector  %s:%s" % (args.host, args.port))
        self.status = tk.StringVar(value="connecting to %s:%s ..." % (args.host, args.port))
        self.status_line = StatusLine(self.status)
        self.width, self.height = args.size

        pane = ttk.PanedWindow(root, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(pane)
        self.image_canvas = tk.Canvas(top, width=self.width, height=self.height, bg="black",
                                      highlightthickness=0)
        self.image_canvas.pack(fill=tk.BOTH, expand=True)
        self.image_size = (self.width, self.height)   # read by the worker thread
        self.image_canvas.bind("<Configure>", lambda e: setattr(self, "image_size", (e.width, e.height)))
        pane.add(top, weight=3)
        bottom = ttk.Frame(pane)
        controls = ttk.Frame(bottom)
        controls.pack(fill=tk.X)
        self.view = tk.StringVar(value=args.pane)
        ttk.Label(controls, text="Load view:").pack(side=tk.LEFT, padx=(6, 2))
        self.view_buttons = {}
        for value, label in (("objects", "by PE, last second, stacked by chare"),
                             ("ep", "over time, by entry method"),
                             ("grid", "PE grid, utilization")):
            b = ttk.Radiobutton(controls, text=label, value=value, variable=self.view,
                                command=self.redraw_bottom)
            b.pack(side=tk.LEFT, padx=6)
            self.view_buttons[value] = b
        self.per_process = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="per process", variable=self.per_process,
                        command=self.redraw_bottom).pack(side=tk.LEFT, padx=2)
        self.balance_button = ttk.Button(controls, text="Balance", command=self.request_balance)
        self.balance_button.pack(side=tk.RIGHT, padx=6)
        ttk.Label(controls, text="click in the image adds %d particles" % args.inject_count).pack(side=tk.RIGHT, padx=6)
        self.image_canvas.bind("<Button-1>", self.on_image_click)
        self.perf_canvas = tk.Canvas(bottom, height=220, bg="white", highlightthickness=0)
        self.perf_canvas.pack(fill=tk.BOTH, expand=True)
        self.perf_canvas.bind("<Configure>", lambda e: self.redraw_bottom())
        pane.add(bottom, weight=1)
        ttk.Label(root, textvariable=self.status, anchor="w").pack(fill=tk.X)

        self.photo = None
        self.columns = collections.deque(maxlen=300)   # (by_ep, total), ep pane
        self.prev_snapshot = None                       # objects pane
        self.interval = None                            # objload.Interval
        self.intervals = 0
        self.has_ep_stream = False
        self.has_objects = True
        self.objload_handler = None     # settled by the first successful fetch (objload.fetch_any)
        self.ep_colors = {}
        self.names = perf.read_sts_entries(args.sts) if args.sts else {}
        self.image_q, self.perf_q = queue.Queue(), queue.Queue()
        self.msg_q = queue.Queue()      # (status_line method, text) from worker threads
        self.image_poller = self.perf_poller = None
        self.server = self.config = None
        self.frames = 0
        self.empty_perf = 0
        self.jpeg = getattr(args, "jpeg", None)     # JPEG quality, None for raw pixels
        self.jpeg_ok = False                        # a JPEG frame has arrived
        self.jpeg_misses = 0                        # JPEG requests in a row that got no JPEG
        self.image_note = ""                        # end of the frame status line
        threading.Thread(target=self.connect, daemon=True).start()
        self.drain_id = root.after(50, self.drain)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # -- connection and pollers (worker threads) ---------------------------

    def connect(self):
        try:
            self.server = ccsio.Server(self.args.host, self.args.port, key=self.args.key,
                                       timeout=self.args.timeout)
            msg = "connected: %d PE(s) on %d node(s)" % (self.server.num_pes, self.server.num_nodes)
            if not self.args.no_image:
                self.config = liveviz.get_config(self.server)
                msg += "; liveViz %s%s" % ("color" if self.config.is_color else "grey",
                                           ", push" if self.config.is_push else "")
                if self.jpeg is not None and not pillow_available():
                    self.jpeg = None
                    self.image_note = "  raw (no Pillow for JPEG)"
                    msg += "; JPEG off: Pillow is not installed, raw images"
                self.image_poller = Poller(self.fetch_image, self.args.image_ms / 1000.0, self.image_q,
                                           adaptive=not self.args.fixed_rate)
                self.image_poller.start()
            if not self.args.no_perf:
                if not self.names:
                    try:
                        self.names = perf.fetch_sts(self.server)
                    except ccsio.CcsError:        # job has no sts handler
                        self.names = {}
                self.has_ep_stream = True
                msg += "; %d entry names" % len(self.names)
                self.perf_poller = Poller(self.fetch_loads, self.args.perf_ms / 1000.0, self.perf_q,
                                          adaptive=False)    # see Pacer: never paced
                self.perf_poller.start()
            self.msg_q.put((self.status_line.alert, msg))
        except Exception as e:
            self.msg_q.put((self.status_line.alert, "error: %s" % e))

    # -- interaction with the application ---------------------------------

    def _oneway(self, handler, data, what):
        """A request on its own short thread; "sent" and then the reply go to
        the status line as notices, so a click that gets no answer reads
        differently from a click that never happened. Its own thread means
        its own CCS identity and connection, so it does not wait for an
        image or perf request in flight, nor for a poller's pause."""
        def run():
            try:
                reply = self.server.request(handler, 0, data, timeout=self.args.timeout)
                text = reply.decode("utf-8", "replace").rstrip("\0") or "no reply (job has no %s handler)" % handler
                self.msg_q.put((self.status_line.notice, "%s: %s" % (what, text)))
            except Exception as e:
                self.msg_q.put((self.status_line.notice, "%s failed: %s" % (what, e)))
        if self.server is None:
            self.status_line.notice("%s: not connected" % what)
            return
        self.status_line.notice("%s: sent, waiting for the reply ..." % what)
        threading.Thread(target=run, daemon=True).start()

    def on_image_click(self, event):
        w, h = (max(1, v) for v in self.image_size)
        fx, fy = event.x / w, event.y / h
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            return
        payload = struct.pack("!dddi", fx, fy, self.args.inject_sigma, self.args.inject_count)
        self._oneway(self.args.inject, payload, "inject at (%.2f, %.2f)" % (fx, fy))

    def request_balance(self):
        self._oneway(self.args.balance, b"", "balance")

    def fetch_loads(self):
        """One tick of the bottom pane: the LBObjLoads snapshot, and the
        entry-method second if the job streams it (-tracemode utilization).
        A job without that handler answers with 0 bytes: give up on it."""
        # A job without a handler answers with 0 bytes (classic) or closes the
        # connection (reconverse): either way that source is not there.
        snap = None
        if self.has_objects:
            try:
                snap, self.objload_handler = objload.fetch_any(self.server, self.objload_handler,
                                                               timeout=self.args.timeout)
            except (ValueError, ccsio.CcsError):
                self.has_objects = False
        sd = None
        if self.has_ep_stream:
            try:
                sd = perf.fetch(self.server, timeout=self.args.timeout)
            except (ValueError, ccsio.CcsError):
                self.has_ep_stream = False
        return (snap, sd)

    def fetch_image(self):
        w, h = (max(1, v) for v in self.image_size)   # no Tk calls off the UI thread
        if self.jpeg is not None:
            try:
                img = liveviz.get_image(self.server, w, h, config=self.config, timeout=self.args.timeout,
                                        compression=liveviz.COMPRESS_JPEG, quality=self.jpeg)
                self.jpeg_ok, self.jpeg_misses = True, 0
                self.image_note = "  JPEG q%d %.0f KB" % (self.jpeg, img.wire_bytes / 1024.0)
                return img
            except (ValueError, ccsio.CcsNoReply) as e:
                # A liveViz without libjpeg answers 0 bytes (classic) or closes
                # the connection before any reply byte (reconverse). One such
                # miss may be a hiccup of the forward, so this frame comes raw
                # and JPEG is given up for good only after JPEG_TRIES in a row.
                # Once JPEG has worked the job has it: misses are reported as
                # usual, as are timeouts and refused connections.
                if self.jpeg_ok:
                    raise
                self.jpeg_misses += 1
                if self.jpeg_misses < JPEG_TRIES:
                    self.image_note = "  raw (JPEG try %d of %d failed)" % (self.jpeg_misses, JPEG_TRIES)
                else:
                    self.jpeg = None
                    self.image_note = "  raw (job has no JPEG)"
                    self.msg_q.put((self.status_line.notice,
                                    "JPEG off: the job's liveViz cannot send JPEG (Charm++ built without "
                                    "libjpeg?), raw images from now on (%s)" % e))
        return liveviz.get_image(self.server, w, h, config=self.config, timeout=self.args.timeout)

    # -- UI thread ---------------------------------------------------------

    def drain(self):
        try:
            while True:
                show, text = self.msg_q.get_nowait()
                show(text)
        except queue.Empty:
            pass
        try:
            while True:
                self.show_image(self.image_q.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                self.add_perf(self.perf_q.get_nowait())
        except queue.Empty:
            pass
        self.drain_id = self.root.after(50, self.drain)

    def describe(self, what, e):
        if "refused" in str(e) or "closed" in str(e) or "lost" in str(e):
            return "%s: the job is gone (%s)" % (what, e)
        return "%s: %s" % (what, e)

    def show_image(self, r):
        if isinstance(r, Exception):
            self.status_line.alert(self.describe("image", r))
            return
        self.frames += 1
        self.photo = tk_photo_from_image(r, master=self.root)
        self.image_canvas.delete("all")
        self.image_canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.status_line.routine("frame %d  %dx%d  %.0f ms/request, every %.0f ms%s" % (
            self.frames, r.width, r.height, 1000 * self.image_poller.latency,
            1000 * self.image_poller.period, self.image_note))

    def add_perf(self, r):
        if isinstance(r, Exception):
            self.status_line.alert(self.describe("perf", r))
            return
        if isinstance(r, tuple):
            snap, sd = r
        elif isinstance(r, objload.Snapshot):
            snap, sd = r, None
        else:
            snap, sd = None, r
        if snap is not None:
            self.interval = objload.diff(self.prev_snapshot, snap)
            self.prev_snapshot = snap
            self.intervals += 1
        if sd is not None:
            self.columns.append(column_from_sumdetail(sd))
        elif snap is None:
            self.empty_perf += 1
        off = []
        for name, ok in (("ep", self.has_ep_stream), ("objects", self.has_objects), ("grid", self.has_objects)):
            if not ok and str(self.view_buttons[name].cget("state")) != "disabled":
                self.view_buttons[name].configure(state="disabled")
                off.append(name)
                if self.view.get() == name:
                    self.view.set("objects" if name == "ep" else "ep")
        if off:             # one notice: a second one would replace the first at once
            if "objects" in off and "grid" in off:
                off = [n for n in off if n not in ("objects", "grid")] + ["objects+grid"]
            self.status_line.notice("; ".join(PANE_MISSING[n] for n in off))
        self.redraw_bottom()

    def redraw_bottom(self):
        if self.view.get() == "ep":
            self.draw_perf()
        elif self.intervals >= 2:          # the first difference has no time span
            if self.view.get() == "grid":
                self.draw_grid()
            else:
                self.draw_objects()

    def color_for(self, ep):
        if ep == perf.OTHER_EP:
            return OTHER_COLOR
        if ep not in self.ep_colors:
            self.ep_colors[ep] = PALETTE[len(self.ep_colors) % len(PALETTE)]
        return self.ep_colors[ep]

    def draw_objects(self):
        """One bar per PE: height = utilization over the last interval,
        stacked from the time each chare ran, idle shown light."""
        c = self.perf_canvas
        c.delete("all")
        W, H = canvas_size(c)
        iv = self.interval
        if iv is None or W < 40 or H < 40:
            return
        pes = sorted(iv.pes)
        left, right, top, bottom = 36, W - 10, 8, H - 22
        plot_w = right - left
        n = len(pes)
        slot = plot_w / max(1, n)
        bar_w = max(1.0, slot * 0.8)
        scale = (bottom - top)
        for i, pe in enumerate(pes):
            p = iv.pes[pe]
            x0 = left + i * slot + (slot - bar_w) / 2
            x1 = x0 + bar_w
            c.create_rectangle(x0, top, x1, bottom, fill=IDLE_COLOR, outline="")
            if p.seconds <= 0:
                continue
            y = bottom
            # biggest first, so a dominant chare sits at the bottom of the bar
            for key, dt in sorted(p.objs.items(), key=lambda kv: -kv[1]):
                hgt = min(1.0, dt / p.seconds) * scale
                if hgt < 0.5:
                    continue
                c.create_rectangle(x0, y - hgt, x1, y, fill=color_for_object(key),
                                   outline="white" if bar_w > 6 and hgt > 2 else "")
                y -= hgt
                if y <= top:
                    break
            if n <= 64 or i % max(1, n // 32) == 0:
                c.create_text((x0 + x1) / 2, bottom + 3, text=str(pe), anchor="n", font=("", 8))
        for pct in (0, 25, 50, 75, 100):
            yy = bottom - pct / 100.0 * scale
            c.create_line(left, yy, right, yy, fill="#cccccc", dash=(2, 4))
            c.create_text(left - 4, yy, text="%d%%" % pct, anchor="e", font=("", 8))
        busiest = max((p.utilization() for p in iv.pes.values()), default=0.0)
        c.create_text(left, H - 2, anchor="sw", font=("", 9),
                      text="%d PEs, %d chares, last %.1f s: busiest PE %.0f%%, one color per chare"
                      % (n, sum(len(p.objs) for p in iv.pes.values()),
                         max((p.seconds for p in iv.pes.values()), default=0.0), 100 * busiest))

    def draw_grid(self):
        """Every PE (or process) as a square, blue when idle, red when fully
        busy, in a square-ish layout with the gap in the last row."""
        c = self.perf_canvas
        c.delete("all")
        W, H = canvas_size(c)
        iv = self.interval
        if iv is None or W < 40 or H < 40:
            return
        # utilization per PE over the interval: 1 - idle/seconds when the LB
        # database gave idle time, else the chares' share
        util = {}
        for pe, p in iv.pes.items():
            if p.seconds <= 0:
                continue
            util[pe] = min(1.0, max(0.0, 1.0 - p.idle / p.seconds)) if p.idle > 0 or p.busy == 0 else min(1.0, p.utilization())
        if not util:
            return
        if self.per_process.get() and self.server is not None and self.server.node_sizes:
            groups, first = {}, 0
            for proc, size in enumerate(self.server.node_sizes):
                members = [util[pe] for pe in range(first, first + size) if pe in util]
                if members:
                    groups[proc] = sum(members) / len(members)
                first += size
            items, kind = sorted(groups.items()), "process"
        else:
            items, kind = sorted(util.items()), "PE"
        n = len(items)
        cols = int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))
        top, bottom, left, right = 6, H - 18, 6, W - 6
        side = max(3, min((right - left) / cols, (bottom - top) / rows) * 0.92)
        gap = side * 0.08 / 0.92
        x_off = left + ((right - left) - cols * (side + gap)) / 2
        for i, (idx, u) in enumerate(items):
            r, col = divmod(i, cols)
            x0 = x_off + col * (side + gap)
            y0 = top + r * (side + gap)
            c.create_rectangle(x0, y0, x0 + side, y0 + side, fill=utilization_color(u), outline="#444444")
            if side >= 26:
                c.create_text(x0 + side / 2, y0 + side / 2, text="%d\n%.0f%%" % (idx, 100 * u),
                              font=("", 9 if side < 48 else 11), fill="white" if 0.25 < u < 0.8 else "black",
                              justify="center")
            elif side >= 14:
                c.create_text(x0 + side / 2, y0 + side / 2, text=str(idx), font=("", 7),
                              fill="white" if 0.25 < u < 0.8 else "black")
        mean = sum(u for _, u in items) / n
        c.create_text(left, H - 2, anchor="sw", font=("", 9),
                      text="%d %ss, last %.1f s: mean utilization %.0f%%, busiest %.0f%%, idlest %.0f%%  (blue idle, red busy)"
                      % (n, kind, max(p.seconds for p in iv.pes.values()), 100 * mean,
                         100 * max(u for _, u in items), 100 * min(u for _, u in items)))

    def draw_perf(self):
        c = self.perf_canvas
        c.delete("all")
        W, H = canvas_size(c)
        legend_w = 170
        plot_w, top, bottom = W - legend_w - 10, 8, H - 18
        if plot_w < 20 or bottom <= top:
            return
        col_w = max(2, min(12, plot_w // max(1, len(self.columns))))
        n = min(len(self.columns), plot_w // col_w)
        x = plot_w - n * col_w + 5
        scale = (bottom - top) / 100.0
        for by_ep, total in list(self.columns)[-n:]:
            c.create_rectangle(x, top, x + col_w, bottom, fill=IDLE_COLOR, outline="")
            y = bottom
            for ep, u in sorted(by_ep.items(), key=lambda kv: -kv[1]):
                hgt = u * scale
                c.create_rectangle(x, y - hgt, x + col_w, y, fill=self.color_for(ep), outline="")
                y -= hgt
            x += col_w
        for pct in (0, 50, 100):
            yy = bottom - pct * scale
            c.create_line(5, yy, plot_w + 5, yy, fill="#cccccc", dash=(2, 4))
            c.create_text(plot_w + 8, yy, text="%d%%" % pct, anchor="w", font=("", 9))
        c.create_text(5, H - 4, anchor="sw", font=("", 9),
                      text="utilization, mean over PEs, one column per second (%d s)" % len(self.columns))
        # legend: most recent column's entry methods, biggest first
        lx, ly = W - legend_w + 4, 8
        if self.columns:
            for ep, u in sorted(self.columns[-1][0].items(), key=lambda kv: -kv[1])[:10]:
                c.create_rectangle(lx, ly, lx + 10, ly + 10, fill=self.color_for(ep), outline="")
                c.create_text(lx + 14, ly + 5, anchor="w", font=("", 9),
                              text="%-18.18s %4.0f%%" % (perf.ep_name(self.names, ep), u))
                ly += 14

    def close(self):
        for p in (self.image_poller, self.perf_poller):
            if p is not None:
                p.stop.set()
        for p in (self.image_poller, self.perf_poller):
            if p is not None:
                p.fn = None
                p.join(timeout=2.0)
        self.root.after_cancel(self.drain_id)     # else Tcl complains about a dead drain at exit
        self.root.destroy()


def pillow_available():
    try:
        import PIL.Image            # noqa: F401  (decodes JPEG frames)
        return True
    except ImportError:
        return False


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def jpeg_quality(s):
    q = int(s)
    if not 1 <= q <= 100:
        raise argparse.ArgumentTypeError("JPEG quality must be 1..100, not %d" % q)
    return q


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m appspector.viewer", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("-k", "--key")
    ap.add_argument("--size", type=parse_size, default=(600, 400), help="initial image pane size, WxH")
    ap.add_argument("--image-ms", type=int, default=200, help="shortest image poll interval")
    ap.add_argument("--jpeg", type=jpeg_quality, nargs="?", const=75, metavar="QUALITY",
                    help="request JPEG images at this quality, 1..100 (75 if not given) instead of raw "
                         "pixels; needs Pillow and a Charm++ built with libjpeg, else raw")
    ap.add_argument("--perf-ms", type=int, default=1000, help="shortest utilization poll interval")
    ap.add_argument("--fixed-rate", action="store_true",
                    help="poll images at --image-ms even when requests are slow (no backoff)")
    ap.add_argument("--pane", choices=["objects", "ep", "grid"], default="objects",
                    help="initial bottom view: per-PE bars stacked by chare (default) or utilization by entry "
                         "method over time; radio buttons in the window flip between them")
    ap.add_argument("--sts", help="the job's .util.sts file, for entry-method names (ep pane)")
    ap.add_argument("--no-image", action="store_true")
    ap.add_argument("--no-perf", action="store_true")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--inject", default="pfieldInject", help="CCS handler a click in the image sends to")
    ap.add_argument("--inject-count", type=int, default=2000, help="particles per click")
    ap.add_argument("--inject-sigma", type=float, default=0.03, help="blob width as a fraction of the image")
    ap.add_argument("--balance", default="pfieldBalance", help="CCS handler the Balance button sends to")
    args = ap.parse_args(argv)
    root = tk.Tk()
    Viewer(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
