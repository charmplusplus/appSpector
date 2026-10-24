# appSpector

A laptop GUI for launching a Charm++ job on a cluster and watching it live:
the application's own liveViz image on top, the load on every PE below,
one bar per PE stacked by chare. New here? Read ONBOARDING.md: it has the
setup for a laptop and for NCSA Delta with no personal paths baked in
(`cluster/setup.sh` with `cluster/delta.env` and `cluster/anvil.env`,
`tests/setup-laptop.sh`). Background and plan:
INITIAL-THOUGHTS.md; the design and the long-term direction (other
schedulers, relays for sites and clouds, ccsio as its own package):
docs/DESIGN.md.

## ccsio: a pure-Python CCS client

`ccsio/` talks CCS (Converse Client-Server, the TCP request/reply protocol
a Charm++ job opens with `++server`) using only the Python standard library.
It replaces the Java client in UIUC-PPL/ccs_tools for appSpector's purposes
and differs from charmplusplus/PyCCS, which is a ctypes wrapper that needs
a shared-library Charm++ build on the client machine. ccsio needs no
Charm++ at all on the laptop.

```python
import ccsio
s = ccsio.Server("127.0.0.1", 1234)              # or Server.from_output(job_log)
s.num_pes, s.node_sizes                          # from ccs_getinfo
s.request("ping", 0, b"bob")                     # one PE
s.request("ping", ccsio.BROADCAST, b"x")         # every PE, merged by the handler's merge fn
s.request("ping", [1, 3], b"x")                  # multicast
s.send("fire", 2, b"")  .close()                 # one-way, no reply wanted

s = ccsio.Server(host, port, key="0102...")      # job started with ++server-auth

from ccsio import liveviz, perf
cfg = liveviz.get_config(s)                      # lvConfig
img = liveviz.get_image(s, 400, 300, config=cfg) # lvImage; img.to_pil() needs Pillow
sd = perf.fetch(s)                               # "CkPerfSumDetail compressed", needs
                                                 # a job linked -tracemode utilization
```

Command line: `python -m ccsio HOST PORT HANDLER [-p PE | -b | -m 1,3]
[-d TEXT | -D FILE] [-k KEY] [-x | -o FILE]`, or `python -m ccsio --from-log
job.out HANDLER ...` to take the address from the job's
`ccs: Server IP = ..., Server port = ...` line.

Modules:

- `protocol.py`: header layout, SHA-1 authentication hash, key-string
  parsing (reproduces the server's decimal-pair quirk, see the docstring),
  the server line and `ccs_getinfo` parsers.
- `client.py`: `Server`, `Pending`, `CcsError`. One TCP connection per
  request, as the C client does.
- `liveviz.py`: the `lvConfig` and `lvImage` payloads, 2d and 3d.
- `perf.py`: decoder for the live utilization stream of
  `trace-utilization.C` and the `.util.sts` entry-method names.

## appspector.viewer: the split-screen viewer

`python -m appspector.viewer HOST PORT [-k KEY] [--pane objects|ep]`
opens a tkinter window: the liveViz image on top, polled every 200 ms,
and below it, by default, a snapshot that changes once a second: one bar
per PE whose height is that PE's utilization over the last interval,
stacked from the time each chare ran, every chare in its own color
(stable across PEs, so a migrating chare keeps its color). The data is the
`LBObjLoads` handler (PR #4071), which every Charm++ program has; the
first request turns the LB instrumentation on. `--pane ep` shows the
older view instead: one stacked column per second of utilization by entry
method, scrolling left, from the `-tracemode utilization` stream. Two
worker threads do the CCS requests; the UI thread only draws. No Pillow
needed: Tk reads the raw PPM/PGM bytes directly. `--no-image` /
`--no-perf` for jobs that lack one of the handlers.

Radio buttons above the bottom pane flip between the two views at run
time; both data sources are polled each second, and the over-time view is
disabled when the job has no utilization stream.

`./demo_local.sh [wave2d|wave2d-small|mol2d] [PEs] [port]` runs the whole
thing on this laptop: the 256-chare wave2d, a 16-chare wave2d (a few
chares per PE, like the old demo), or Molecular2D (particles; its liveViz
image currently shows only the patch grid, the particle pixels do not
come through yet).

The old Charmworks demo (a screenshot is kept outside the repository: a synthetic
particle-motion application on the left, horizontal per-PE "CPU Load"
bars stacked by chare on the right, with Show Chare Loads / BG Load /
Idle toggles and a Balance button) is the reference; its code is lost.

## apps/pfield: the demonstration program

`apps/pfield/` is appSpector's own demo application (see its README):
particles pinned to a K x K array of cells, moving under a forcing field
or a random walk, with slow birth and death that follows a circling hot
spot, a CCS handler that injects a Gaussian blob of particles where you
click in the image, and one that runs a load-balancing step (the Balance
button). Rates are per wall-clock second so the behaviour is the same at any
step rate; particles bounce off the cell walls and circulate in a per-cell
vortex with thermal jitter, so an injected blob stays visible and decays
with the death rate (about 50 s). `tests/pfield_check.py` is the
automated end-to-end check (start, clicks, Balance, migration count);
on 2026-10-23 three clicks took one PE to 91 percent while the others
waited at 42 to 50, and Balance moved 5 chares. `./demo_local.sh` runs it
by default.

## Clusters verified

- **Delta** (Duo, ssh control master): 2 processes x 2 PEs and 4 x 4 PEs
  pfield and wave2d jobs through the launcher and the shell; images in
  about 120 ms per frame through the login-node forward.
- **Anvil** (ssh key, no master; forwards are background ssh processes),
  2026-10-24: `cluster/setup.sh` built the stack in
  `/anvil/projects/x-asc050025/<user>/software/appspector`; an 8-PE pfield
  job on the `shared` partition started once the request was trimmed to
  the cores the PEs use (a whole-node request sat in the queue for 30
  minutes), and the forward, image (273 ms) and LBObjLoads (144 chares on
  8 PEs) all answered. Observation to look into: utilization read 11 to
  13 percent per PE there, far below the laptop's and Delta's; pfield's
  lock-step reduction every step may be latency-bound across the two
  processes on Anvil.

## python3 -m appspector: the shell

The front door since 2026-10-23: `site delta`, `program pfield -k 16`,
`pes 16`, `run`, then `view` when the shell reports the job up. Sites are
INI files (`appspector/sites/local.ini` built in, cluster files in
`~/.appspector/sites/`, written by the cluster's setup script and fetched
with `site fetch`); a job spec (program, arguments, PEs, nodes, processes
per node, wall time) is rendered into a batch script from the site's
template and submitted over ssh, or started as a local process. Jobs are
recorded in `~/.appspector/jobs.json` for `attach`, `view`, `status`,
`stop` from any later shell. One-shot forms: `python3 -m appspector run
--site delta --program pfield --pes 16 ...`, `view ID`, `status ID`,
`stop ID`, `jobs`, `sites`, `script`. Interaction with the running
program stays in the viewer.

## appspector.launch: the launcher primitives

`python -m appspector.launch run --site delta --sbatch /remote/wave2d.sbatch`
submits the script over the site's open ssh control master, polls the job
output for the `ccs: Server IP` line, registers a port forward in the
master (`ssh -O forward`), starts the viewer on `127.0.0.1:<port>`, and on
exit cancels the forward and the job (`--keep` leaves it running,
`--check` only prints the PE layout instead of opening the viewer).
`attach --job ID --out FILE` joins a running job, `watch` tails the newest
output, `stop` cancels. It is the Python version of
~/software/recharm/lv-delta.sh; the human still opens the master once
(`ssh delta`, Duo).

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

## Tests

`python3 -m unittest discover -s tests` runs 20 unit tests against an
in-process fake CCS server (`tests/fake_server.py`, written from
ccs-server.C), including the authenticated handshake and a check that
hashlib's SHA-1 equals the hand-written SHA-1 in ccs-auth.C.

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
