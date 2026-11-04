"""c4p_demo: a small charm4py program for appSpector.

A K x K chare array covers the unit square; each chare owns an n x n patch
of a field (two travelling waves plus a hot spot that circles the square).
A driver chare on PE 0 runs the program in lock step: it broadcasts
``step``, and the step's reduction starts the next one, forever (or
``-steps`` steps). Every step a chare
does work proportional to how close the hot spot is to it (repeated
smoothing of its patch), so the load is uneven and moves around.

Images: liveViz (charm4py.liveviz). A viewer's lvImage request is handed
to the driver, and the next ``step`` carries it: each chare paints its
share of the requested width x height image from its patch and deposits
it, then contributes to the step's reduction. The image therefore fits the
viewer's pane and shows the latest step. Each step serves one request,
the oldest waiting: liveViz answers requests in the order they came, one
deposit per request, so none may be skipped (with the appSpector viewer,
which keeps one request outstanding, at most one waits anyway).

Why not deposit straight from the request (the library's example
broadcasts the request to the array)? charm4py's deposit is a reduction
over the array, and so is the step. If the request's broadcast reaches
some chares before their step and others after, the two reductions are
contributed in different orders and get mixed up. Deposits must sit at the same point of every chare's
sequence of reductions. (The library's poll mode, which deposits every
step, queues every image until a viewer asks; that grows without bound
when nobody looks, so this demo does not use it either.)

Clicks: the CCS handler ``c4pInject`` takes the appSpector viewer's click
payload (x, y, sigma as network-order doubles, int32 count) and adds a
second, fixed hot spot there for ``-bump`` seconds.

Run (one PE per process; appSpector's site entry does this):
    srun -n 4 python -u c4p_demo.py +pe 4 ++server ++server-port 1234
    python -m charmrun.start +p4 c4p_demo.py ++server ++server-port 1234   (laptop)
Options: -k chares per side (8), -n cells per chare side (32), -hot extra
smoothing passes at the hot spot (40), -period seconds per orbit (30),
-bump seconds a click lasts (20), -steps (0: until killed).
"""

import math
import struct
import sys
import time

import numpy as np
from charm4py import charm, Chare, Array, liveviz


def opt(args, name, default, cast=int):
    if name in args:
        return cast(args[args.index(name) + 1])
    return default


def colorize(u, load):
    """u in [-1, 1] -> RGB uint8 (blue..white..red), load in [0, 1] tints green."""
    a = np.clip((u + 1.0) * 0.5, 0.0, 1.0)
    r = (255 * a).astype(np.uint8)
    b = (255 * (1.0 - a)).astype(np.uint8)
    g = np.full_like(r, int(40 + 180 * load))
    return np.dstack((r, g, b))


class Cell(Chare):

    def __init__(self, K, n, hot, period):
        self.K, self.n, self.hot, self.period = K, n, hot, period
        i, j = self.thisIndex
        c = (np.arange(n) + 0.5) / (K * n)
        self.X, self.Y = np.meshgrid(c + j / K, c + i / K)   # row i is y, column j is x
        self.cx, self.cy = (j + 0.5) / K, (i + 0.5) / K
        self.u = np.zeros((n, n))
        self.load = 0.0
        self.bumps = []          # (x, y, sigma, until)

    def add_bump(self, x, y, sigma, until):
        self.bumps.append((x, y, sigma, until))

    def step(self, t, done, request=None):
        w = 2 * math.pi * t / self.period
        hx, hy = 0.5 + 0.32 * math.cos(w), 0.5 + 0.32 * math.sin(w)
        u = 0.6 * np.sin(8 * self.X - 3 * t) * np.cos(6 * self.Y + 2 * t)
        u += np.exp(-((self.X - hx) ** 2 + (self.Y - hy) ** 2) / 0.01)
        heat = math.exp(-((self.cx - hx) ** 2 + (self.cy - hy) ** 2) / 0.02)
        now = time.time()
        self.bumps = [b for b in self.bumps if b[3] > now]
        for bx, by, s, _ in self.bumps:
            u += np.exp(-((self.X - bx) ** 2 + (self.Y - by) ** 2) / (2 * s * s))
            heat = max(heat, math.exp(-((self.cx - bx) ** 2 + (self.cy - by) ** 2) / (2 * max(s, 0.05) ** 2)))
        passes = int(self.hot * heat)
        for _ in range(passes):                      # the uneven work
            u[1:-1, 1:-1] = 0.2 * (u[1:-1, 1:-1] + u[:-2, 1:-1] + u[2:, 1:-1] + u[1:-1, :-2] + u[1:-1, 2:])
        self.u = np.clip(u, -1.0, 1.0)
        self.load = passes / max(1, self.hot)
        if request is not None:
            self.render(request)
        self.reduce(done)

    def render(self, request):
        W, H, K = request.width, request.height, self.K
        i, j = self.thisIndex
        x0, x1 = j * W // K, (j + 1) * W // K
        y0, y1 = i * H // K, (i + 1) * H // K
        w, h = x1 - x0, y1 - y0
        if w > 0 and h > 0:
            rows = (np.arange(h) * self.n // h)
            cols = (np.arange(w) * self.n // w)
            rgb = colorize(self.u[np.ix_(rows, cols)], self.load)
            data = rgb.tobytes()
        else:
            data = b""
        # deposit(buffer, elem, x, y, height, width, total height, total width)
        liveviz.LiveViz.deposit(data, self, x0, y0, h, w, H, W)


PENDING = []      # lvImage requests waiting for the next step (PE 0, where liveViz and main live)


def image_requested(request):
    """liveViz's callback, called on PE 0 for each lvImage request."""
    PENDING.append(request)


class Driver(Chare):
    """Runs the steps on PE 0: broadcast ``step``, the array's reduction
    calls ``stepped``, which starts the next one. No Future per step on
    purpose: charm4py carries a Future's id in a 16-bit Charm++ callback
    reference number, so the 65536th Future used as a reduction target
    arrives without its id and the job aborts ("_future_deposit_result()
    missing 1 required positional argument: 'fid'")."""

    def __init__(self, cells, steps):
        self.cells, self.steps = cells, steps
        self.t0 = self.last = time.time()
        self.k = self.done_at = 0

    def go(self):
        # one request per step, oldest first, none dropped: charm4py's liveViz (the fixed one of
        # branch liveviz-numpy-v2) answers requests strictly in order, one deposit each, so a
        # skipped request would pair every later reply with the wrong request. The appSpector
        # viewer has at most one image request outstanding, so the queue is one long at most.
        request = PENDING.pop(0) if PENDING else None
        self.cells.step(time.time() - self.t0, self.thisProxy.stepped, request)

    def stepped(self, result=None):
        self.k += 1
        now = time.time()
        if now - self.last >= 10:
            print("c4p_demo: step %d, %.1f steps/s" % (self.k, (self.k - self.done_at) / (now - self.last)))
            self.last, self.done_at = now, self.k
        if self.steps and self.k >= self.steps:
            charm.exit()
        else:
            self.go()


def main(args):
    K, n = opt(args, "-k", 8), opt(args, "-n", 32)
    hot, period = opt(args, "-hot", 40), opt(args, "-period", 30.0, float)
    bump, steps = opt(args, "-bump", 20.0, float), opt(args, "-steps", 0)
    cells = Array(Cell, (K, K), args=[K, n, hot, period])
    liveviz.LiveViz.init(liveviz.Config(), image_requested)

    def inject(msg):
        try:
            x, y, s, count = struct.unpack("!dddi", bytes(msg[:28]))
        except struct.error:
            charm.CcsSendReply(b"c4pInject: want x y sigma (doubles) and count (int32)")
            return
        cells.add_bump(x, y, s, time.time() + bump)
        charm.CcsSendReply(("hot spot at (%.2f, %.2f) for %.0f s" % (x, y, bump)).encode())

    charm.CcsRegisterHandler("c4pInject", inject)
    print("c4p_demo: %dx%d chares of %dx%d cells on %d PEs; CCS handlers lvImage, lvConfig, c4pInject"
          % (K, K, n, n, charm.numPes()))
    driver = Chare(Driver, args=[cells, steps], onPE=0)
    driver.go()


if __name__ == "__main__":
    charm.start(main)
