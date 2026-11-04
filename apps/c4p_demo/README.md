# c4p_demo: a charm4py program for appSpector

A K x K chare array (charm4py) covers the unit square; each chare owns an
n x n patch of a field: two travelling waves plus a hot spot that circles
the square. A driver chare on PE 0 runs the steps in lock step (broadcast
`step`, the reduction calls `stepped`, which starts the next), until killed.
Each step a chare smooths its patch up to `-hot` extra times, more the
closer the hot spot is, so the load is uneven and moves around; the
image's green tint shows each chare's load.

- **Image**: liveViz through `charm4py.liveviz`. An `lvImage` request is
  carried by the next step: every chare paints its share of the requested
  width x height from its patch and deposits it, so the image always fills
  the viewer's pane.
- **Clicks**: `c4pInject` takes the viewer's click payload (x, y, sigma as
  network-order doubles, an int32 count) and adds a second hot spot there
  for `-bump` seconds. The site entry passes `--inject c4pInject`.
- No Balance handler, no utilization trace (see docs/MANUAL.md, "charm4py
  programs").

Arguments: `-k` chares per side (8), `-n` cells per chare side (32),
`-hot` extra smoothing passes at the hot spot (40), `-period` seconds per
orbit (30), `-bump` seconds a click lasts (20), `-steps` (0: until killed).

Run one PE per process (`procs=pes` in the site entry does this):

    srun --mpi=pmix -n 4 c4p-python c4p_demo.py +traceoff +pe 4 ++server ++server-port 1234
    python -m charmrun.start +p4 c4p_demo.py +traceoff ++server ++server-port 1234     # laptop

Two charm4py (main, 2026-11) pitfalls this program avoids, worth knowing
when writing your own:

- A `Future` used as a reduction target carries its id in a 16-bit
  Charm++ callback field, so the 65536th one arrives without it and the
  job aborts (`_future_deposit_result() missing ... 'fid'`). A loop of
  `f = Future(); cells.step(f); f.get()` dies after about 65000 steps;
  reduce to an entry method instead.
- A liveViz deposit is a reduction on the array. Deposit at the same point
  of every element's sequence of reductions (here: inside `step`), not from
  a separately broadcast request while steps are reducing.

Stock charm4py main's `liveviz.py` aborts at the first image request (a
TypeError in `ByteImage.from_contributions`); run with a charm4py that has
that fixed.
