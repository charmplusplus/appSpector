# appSpector: getting started

appSpector watches a running Charm++ job from a laptop: the application's
own live image (liveViz) on top, the load on every PE below, one bar per
PE stacked by chare. It launches the job on a cluster, forwards the job's
CCS port through the login node, and talks to the job with a small pure
Python client. Nothing in it is specific to one person or machine: all
paths come from where you check it out and from the variables below.

## What you need

- **Laptop:** Python 3.9 or newer with tkinter (the python.org installer
  on macOS has it; on Linux install `python3-tk`). No other packages;
  Pillow is optional and only used to save images.
- **For local demos** (optional): a C++ toolchain, cmake, git, and
  libjpeg, to build Charm++ beside the repo. On macOS with MacPorts:
  `sudo port install cmake jpeg`. Skip this if you only drive cluster jobs.
- **Delta:** an NCSA Delta account on an allocation (you need its short
  name, the `X` in the Slurm account `X-delta-cpu`).

## 1. Get the code

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
python3 -m unittest discover -s tests        # 29 tests against a fake CCS server, no Charm++ needed
```

## 2. Delta: ssh control master

Delta needs a Duo push on every new connection, so everything runs over
one ssh connection that you open once. Add to `~/.ssh/config` on the
laptop, with your NCSA username:

```
Host delta
    HostName login.delta.ncsa.illinois.edu
    User <your-ncsa-username>
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 12h
```

Then, in a terminal, `ssh delta` and answer Duo. Leave that window; every
later `ssh delta ...` reuses the connection without a prompt. `ssh -O check
delta` tells you whether the master is up; if Delta drops it (it did,
about two hours in, twice), just `ssh delta` again.

## 3. Delta: build the server side (once, about 10 minutes)

On a Delta login node, from a checkout of this repository:

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
ALLOC=<your allocation> bash delta/setup-delta.sh
```

This clones Charm++ (branch `appspector-delta` until PR #4071 is merged
into `recharm`, then `BRANCH=recharm`), builds it with tracing and
liveViz, builds the example programs and `apps/pfield`, and writes
`env.sh` and three batch scripts into the work directory, by default
`/work/hdd/<alloc>/<you>/appspector` (override with `WORK=`). The batch
scripts use partition `cpu-interactive` and account `<alloc>-delta-cpu`
(`PARTITION=`, `ACCOUNT=`). The last lines of its output are the exact
laptop command to run next.

## 4. Run a job from the laptop and watch it

With the ssh master open, from the laptop checkout:

```
python3 -m appspector.launch run --site delta --sbatch /work/hdd/<alloc>/<you>/appspector/pfield.sbatch
```

Two applications are set up: `pfield.sbatch` runs appSpector's own demo
(`apps/pfield`, read its README first: cells, pinned particles, click to
inject, Balance), and `wave2d.sbatch` runs Charm++'s wave2d example
linked with the utilization trace, which also feeds the "over time, by
entry method" view. Both are good code to read: wave2d for a classic
stencil-style chare array with liveViz, pfield for the CCS handlers and
AtSync load balancing.

It submits the job, polls until the job prints its CCS address (queue
waits on cpu-interactive have ranged from 12 minutes to 12 hours),
registers a port forward inside the ssh master, and opens the viewer.
Closing the viewer cancels the forward and the job. Useful variants:

- `--check --keep`: no window; print the PE layout and leave the job
  running. Then `ssh -O forward -L 1234:<node>:1234 delta` and
  `python3 tests/remote_check.py 127.0.0.1 1234 out.png` exercises every
  handler headlessly, and `python3 -m appspector.launch stop --site delta
  --job <id>` cleans up.
- `attach --job <id> --out <file>`: join a job that is already queued or
  running. `watch` tails the newest job output; `stop` cancels.

In the viewer: a click in the image drops a Gaussian blob of particles
there (pfield only); the Balance button runs one load-balancing step;
the radio buttons flip the bottom pane between "by PE, last second,
stacked by chare" and "over time, by entry method" (the latter needs a
job linked with `-tracemode utilization`, such as the wave2d demo).

## 5. Local demo on the laptop (optional)

```
bash tests/setup-laptop.sh      # clones and builds Charm++ into ./charm-wt (10 to 15 minutes), examples, pfield
./demo_local.sh                 # pfield on 4 PEs plus the viewer; also: ./demo_local.sh wave2d-small
```

`python3 -m ccsio HOST PORT HANDLER [-d DATA] [-x]` is a command-line CCS
client for poking at any job by hand.

## Where things are

| Path | What |
|---|---|
| `ccsio/` | CCS client: `protocol.py` wire format and auth, `client.py` Server, `liveviz.py`, `perf.py` utilization stream, `objload.py` per-object loads |
| `appspector/viewer.py` | the tkinter viewer |
| `appspector/launch.py` | the launcher (ssh, sbatch, forward) |
| `apps/pfield/` | the demo application (its README explains the model and the CCS handlers) |
| `tests/` | unit tests, fake CCS server, integration scripts, `remote_check.py`, setup scripts |
| `delta/setup-delta.sh` | the Delta build |
| `README.md`, `INITIAL-THOUGHTS.md` | status and history, design notes |

Charm++ side: the handlers the viewer relies on are `lvConfig`/`lvImage`
(liveViz), `CkPerfSumDetail compressed` and `CkPerfSumDetail sts`
(trace-utilization, merged in charm PR #4068), and `LBObjLoads`
(LBManager, PR #4071). The CCS protocol itself is documented at the top
of `ccsio/protocol.py`.

## Connecting your own program

appSpector does not know what the application is; any Charm++ program
that runs with `++server ++server-port N` works. To watch one of yours,
or another example such as `examples/charm++/leanmd`:

1. Build it against the Charm++ build `setup-delta.sh` (or
   `setup-laptop.sh`) made, so it has liveViz and the `LBObjLoads`
   handler: `CHARM_HOME=$CBUILD`, or `$CBUILD/bin/charmc` directly.
   Per-PE loads by chare then work with no code changes. For the image,
   link `-module liveViz` and implement its callback (pfield and wave2d
   show how); without it, run the viewer with `--no-image`. For the
   Balance button and clicks, register CCS handlers as pfield does and
   pass their names with `--balance` and `--inject`.
2. On Delta, copy a batch script and change the program and directory:
   `cp $WORK/pfield.sbatch $WORK/mine.sbatch`, edit the `cd` and the
   `srun ... ./program +pe 4 ++server ++server-port 1234` line, then
   `python3 -m appspector.launch run --site delta --sbatch $WORK/mine.sbatch`.
3. On the laptop, start it yourself with `++server ++server-port 1234`
   and run `python3 -m appspector.viewer 127.0.0.1 1234`, or
   `./demo_local.sh /path/to/program` which does both.

`docs/DESIGN.md` describes the contract, the transport and the plans to
generalize to other schedulers and clouds.

## Open items (good first tasks)

- Per-PE view refinements from the old demo: an absolute time axis,
  horizontal bars, Show BG Load / Show Idle toggles.
- A side-by-side layout option.
- `++server-auth` on by default in the launcher (the client supports it).
- Frontier and cloud transport (see INITIAL-THOUGHTS.md).
