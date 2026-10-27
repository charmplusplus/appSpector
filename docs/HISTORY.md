# appSpector history

A dated log of verification runs and status notes, moved here from README.md and kept unchanged for reference; the current documentation is in [README.md](../README.md).

## Clusters verified

- **Delta** (Duo, ssh control master): 2 processes x 2 PEs and 4 x 4 PEs
  pfield and wave2d jobs through the launcher and the shell; images in
  about 120 ms per frame through the login-node forward.
- **Anvil** (ssh key, no master; forwards are background ssh processes),
  2026-10-24: `cluster/setup.sh` built the stack in
  `/anvil/projects/x-<allocation>/<user>/software/appspector`; an 8-PE pfield
  job on the `shared` partition started once the request was trimmed to
  the cores the PEs use (a whole-node request sat in the queue for 30
  minutes), and the forward, image (273 ms) and LBObjLoads (144 chares on
  8 PEs) all answered. Observation to look into: utilization read 11 to
  13 percent per PE there, far below the laptop's and Delta's; pfield's
  lock-step reduction every step may be latency-bound across the two
  processes on Anvil.

## Charm++ side: PRs #4068, #4069 (merged 2026-10-22), #4071 (open)

- #4068 `trace-utilization-production-fixes`: the two trace-utilization
  fixes below. Squash-merged into recharm as afa464a79 on 2026-10-22
  (16:58 CDT, by the recharm session after Ritvik's approval).
- #4069 `trace-utilization-sts-handler`: a CCS handler `CkPerfSumDetail
  sts` that returns the sts text, so the client maps entry indices to
  names over CCS (`perf.fetch_sts`); the viewer uses it when no `--sts`
  file is given. It was merged into #4068's branch first, so the #4068
  squash carries it: GitHub lists #4069 as merged into that branch, and
  the recharm commit title names only #4068. Both branches are deleted.
- #4071 `lbmanager-objloads-ccs` (rebased onto the new recharm tip, one
  commit, mergeable): CCS handler `LBObjLoads` in LBManager,
  one record per PE with every object's cumulative wall time from the LB
  database (`ccsio.objload`: `fetch`, `diff`). Registered through the
  Converse-level table because the CkCallback form broadcasts to the
  callback group, which does not exist yet when LBManager is built.

## macOS: a Python crash makes every later Tk window hang

Found 2026-10-21: after a Python.app process using Tk aborts (here:
`Tcl_AsyncDelete` panic when a Tk object was garbage-collected on a worker
thread), macOS shows a modal "reopen windows?" alert for every later
Python Tk window, inside `tk.Tk()`, so headless tests and the viewer hang
until someone clicks it. `defaults write org.python.python
ApplePersistenceIgnoreState -bool YES` stops the prompt (done on this
Mac). The viewer now keeps its Tk root reachable until interpreter
shutdown and joins its poller threads on close, so the abort itself no
longer happens.

## Reconverse: verified 2026-10-21 (evening)

Worktree `charm-wt` (detached from recharm `06593cd56`, the #4061 merge,
local branch `appspector-local`), built `./build charm++
reconverse-darwin-arm8 --with-production --enable-tracing -j8`, then
`cmake -DTARGET=LIBS . && make` in the build dir for liveViz. Examples
built by `tests/build_reconverse_examples.sh` (needs `-L/opt/local/lib`
for libjpeg: `libmoduleliveViz.dep` says `-ljpeg` with no MacPorts path).

- ccstest: `tests/integration_reconverse.sh`, 10 checks, including
  multicast and auth.
- wave2d (liveViz, color, push): `lvConfig` and `lvImage` answer, 800x800
  RGB in about 11 ms per request on the laptop; the saved image is the
  wave field with the chare grid. Note the untraced binary also worked:
  with tracing compiled in, the #4065 `[local]` crash does not trigger.
- wave2d linked `-tracemode utilization`: `perf.fetch` returns 1000 bins
  for 4 PEs, 81 percent in `recvGhosts`, after two fixes to
  `src/ck-perf/trace-utilization.C` that live only in the worktree commit
  (since merged as charm PR #4068):
  1. the reducer read the bin count of messages 1..n inside `CkAssert`,
     which production builds do not evaluate, so every production build
     segfaulted in `mergeCompressedBin` on the first collected second;
  2. array delivery traces begin/endExecute nested (ck.C inside
     cklocation.C); the module took the inner end as the outer and
     printed `WARNING: epIdx=-2` once per message. It now counts depth
     like trace-summary.
- The viewer, run headless against the traced job: 29 image frames and 5
  utilization columns in 6 s.
- The `.util.sts` file is written next to the binary (`traceroot` is
  argv[0]), not in the working directory; pass it with `--sts`.

## Status (2026-10-21)

- Done: ccsio core, liveViz and utilization payloads, CLI, tkinter viewer,
  unit tests, classic and reconverse integration tests, all verified on
  this laptop against real jobs.
- Delta, 2026-10-22: `launch run` submitted job 23109890, which queued
  for 12 hours (drained partition, then a Slurm controller timeout; the
  launcher now retries transient failures), then `launch attach --check`
  registered the forward and the CCS self-check answered through it from
  a 2-process, 4-PE job on cn078. The traced build collected utilization
  on that multi-process job without crashing. The stock wave2d ended after
  23 s, before image checks. A second Delta build (branch
  `appspector-delta` = #4068 + #4069 + #4071, long-running wave2d-demo,
  4 min) and job 23112212 (12 min in the queue this time) completed the
  check through the forward with `tests/remote_check.py`: 800x800 color
  image in 256 ms (105 ms at 400x400), 182 entry names over CCS, the
  utilization stream (recvGhosts 61 percent), LBObjLoads (256 objects,
  87-88 percent per PE), and the viewer with both bottom views: 39 frames
  in 8 s at 121 ms per request through the login-node forward.
- Not yet done: the per-object view's absolute
  axis, horizontal layout and BG/idle toggles from the old demo; a Balance
  button (needs a CCS handler that starts an LB step); a synthetic
  particle-motion application like the demo's.

## Verification notes from the former README sections

Integration tests (from the former README "Tests" section):

`tests/integration_classic.sh` builds `examples/converse/ccstest/server.C`
from a classic Charm++ tree, runs it with `++server-port` with and without
`++server-auth`, and drives it with the CLI. Verified 2026-10-21 on the
classic netlrts-darwin-arm8-smp build: single PE, broadcast and
authenticated requests all answer. A CCS multicast to a proper subset of
PEs makes the classic job segfault (the PE list is handed to CmiListReduce
in network byte order in middle-ccs.C); the same request against the
reconverse server answers correctly, so this is a classic-only bug.

`tests/integration_reconverse.sh` does the same against the reconverse
ccstest server built by `tests/build_reconverse_examples.sh` in the
worktree `charm-wt` (recharm tip, built `--with-production
--enable-tracing`, then reconfigured `-DTARGET=LIBS` for liveViz).
Verified 2026-10-21: 10 checks pass, including multicast and auth.

pfield (from the former README "apps/pfield" section): `tests/pfield_check.py`
is the automated end-to-end check (start, clicks, Balance, migration
count); on 2026-10-23 three clicks took one PE to 91 percent while the
others waited at 42 to 50, and Balance moved 5 chares.

The old Charmworks demo (from the former README viewer section; a
screenshot is kept outside the repository: a synthetic particle-motion
application on the left, horizontal per-PE "CPU Load" bars stacked by
chare on the right, with Show Chare Loads / BG Load / Idle toggles and a
Balance button) is the reference for the viewer; its code is lost.

`appspector.launch` (from the former README launcher section) is the
Python version of an earlier shell script, `lv-delta.sh`, kept outside
the repository.
