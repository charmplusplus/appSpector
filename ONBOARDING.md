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

The shell is the front door. With the ssh master open, from the laptop
checkout:

```
python3 -m appspector
appspector> site fetch delta delta:/work/hdd/<alloc>/<you>/appspector/site.ini   # once; the setup script printed this line
appspector> site delta
appspector> program pfield -k 16 -n 400        # a program from the site, then its own arguments
appspector> pes 16                              # and, for clusters: nodes N, ppn N, walltime HH:MM:SS
appspector> run                                 # generates the batch script, submits, returns at once
```

`run` prints the job id and the shell keeps working; a line appears when
the job's CCS server is up (queue waits on cpu-interactive have ranged
from seconds to 12 hours). Then:

```
appspector> view          # opens the viewer window on the job (forward registered for you)
appspector> status        # or: jobs, log, stop
appspector> quit          # the job keeps running; 'stop' cancels it
```

Every job is recorded in `~/.appspector/jobs.json`, so a later shell can
`attach <id>` and `view` it again. The same commands work in one shot:
`python3 -m appspector run --site delta --program pfield --pes 16 --args
"-k 16"` submits, waits, and opens the viewer; `python3 -m appspector
view <id>`, `status <id>`, `stop <id>`, `jobs`, `sites`, and `script`
(prints the batch script a spec would submit without submitting).

Two programs are set up by `setup-delta.sh`: `pfield`, appSpector's own
demo (`apps/pfield`, read its README first: cells, pinned particles,
click to inject, Balance), and `wave2d`, Charm++'s wave2d example linked
with the utilization trace, which also feeds the "over time, by entry
method" view. Both are good code to read: wave2d for a classic
stencil-style chare array with liveViz, pfield for the CCS handlers and
AtSync load balancing. `command DIR | CMD` runs anything else.

In the viewer: a click in the image drops a Gaussian blob of particles
there (pfield only); the Balance button runs one load-balancing step;
the radio buttons flip the bottom pane between "by PE, last second,
stacked by chare" and "over time, by entry method".

The older `appspector.launch` still works for a batch script you wrote
yourself: `python3 -m appspector.launch run --site delta --sbatch
/path/file.sbatch`, and `attach --job <id> --out <file>` for a job it
did not start.

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
| `appspector/shell.py`, `__main__.py` | the command shell and its one-shot forms |
| `appspector/sites.py`, `jobs.py` | site descriptions, job specs, batch generation, records, connections |
| `appspector/viewer.py` | the tkinter viewer |
| `appspector/launch.py` | the ssh, sbatch and port-forward primitives (also a standalone launcher for hand-written batch scripts) |
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
2. Add it to the site file (`~/.appspector/sites/delta.ini`, section
   `[programs]`): `mine = /path/to/dir | ./mine {args} +pe {pes} ++server
   ++server-port {port}`. Then `program mine`, `pes 32`, `run` in the
   shell. Or, without editing anything, `command /path/to/dir | ./mine
   +pe {pes} ++server ++server-port {port}`.
3. On the laptop the same works with `site local` (its programs are in
   `appspector/sites/local.ini`), or start the program yourself with
   `++server ++server-port 1234` and run `python3 -m appspector.viewer
   127.0.0.1 1234`; `./demo_local.sh /path/to/program` does both.

`docs/DESIGN.md` describes the contract, the transport and the plans to
generalize to other schedulers and clouds.

## Open items (good first tasks)

- Per-PE view refinements from the old demo: an absolute time axis,
  horizontal bars, Show BG Load / Show Idle toggles.
- A side-by-side layout option.
- `++server-auth` on by default in the launcher (the client supports it).
- Frontier and cloud transport (see INITIAL-THOUGHTS.md).
