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

## 1. Get the code, on the laptop

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
python3 -m unittest discover -s tests        # 36 tests against a fake CCS server, no Charm++ needed
```

The laptop side is pure Python; nothing is built here.

## 2. Reaching a cluster from the laptop

Still on the laptop. appSpector talks to a cluster over ssh with no
prompts, so the alias must work non-interactively. Set up the cluster you
will use; you do not need both.

**Delta (Duo on every login):** use an ssh control master that you open
once. Add to `~/.ssh/config` on the laptop, with your NCSA username:

```
Host delta
    HostName login.delta.ncsa.illinois.edu
    User <your-ncsa-username>
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 12h
```

Then, in a terminal, `ssh delta` and answer Duo. Leave that window; every
later `ssh delta ...` reuses the connection. `ssh -O check delta` tells
you whether the master is up; if Delta drops it (it did, about two hours
in, twice), just `ssh delta` again.

**Anvil (ssh key, no Duo):** an alias with your key is enough:

```
Host anvil
    HostName anvil.rcac.purdue.edu
    User <your-anvil-username>
    IdentityFile ~/.ssh/<your key>
```

`ssh anvil true` must return without a prompt. Port forwards are then
background ssh processes that appSpector starts and stops itself.

## 3. Build the server side, on the cluster (once, about 10 minutes)

Now log in to the cluster (`ssh delta` or `ssh anvil`). On its login
node, clone this repository a second time and run the setup script with
two arguments: the cluster's name, and your allocation.

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
bash cluster/setup.sh delta <allocation>     # on Delta: the X in your Slurm account X-delta-cpu
```

On Anvil the second argument is the Slurm account itself:
`bash cluster/setup.sh anvil asc050025`. Do this on the one cluster you
use, not on both.

`cluster/<site>.env` holds each cluster's modules and Slurm defaults; the
script clones Charm++ (branch `recharm`), builds it with tracing and
liveViz, builds the example programs and `apps/pfield`, and writes
`env.sh`, batch scripts and a site file into the work directory: by
default `/work/hdd/<alloc>/<you>/appspector` on Delta and
`/anvil/projects/x-<account>/<you>/software/appspector` on Anvil (that
space has a shared file quota; `APPSPECTOR_WORK=/anvil/scratch/<you>/appspector`
uses scratch instead, which is purged periodically). Override with `APPSPECTOR_WORK=`, `APPSPECTOR_PARTITION=`,
`APPSPECTOR_ACCOUNT=` (prefixed so they cannot collide with the
cluster's own variables; Anvil sets `$WORK` itself). The last
lines of its output are the exact laptop commands to run next.

## 4. Run a job from the laptop and watch it

Back on the laptop. The shell is the front door. With the ssh master
open, from the laptop checkout:

```
python3 -m appspector
appspector> site fetch delta delta:/work/hdd/<alloc>/<you>/appspector/site.ini   # once per cluster; the setup script printed this line
appspector> site delta
appspector> program pfield -k 16 -n 400        # a program from the site, then its own arguments
appspector> pes 16                              # and, for clusters: nodes N, ppn N, walltime HH:MM:SS
appspector> run                                 # generates the batch script, submits, returns at once
```

`run` prints the job id and the shell keeps working; a line appears when
the job's CCS server is up (queue waits on cpu-interactive have ranged
from seconds to 12 hours; jobs get 10 minutes of wall time by default,
`walltime 00:30:00` for more). Then:

```
appspector> view          # opens the viewer window on the job (forward registered for you)
appspector> status        # or: jobs, log, stop
appspector> quit          # the job keeps running; 'stop' cancels it
```

Every job is recorded in `~/.appspector/jobs.json`, so a later shell can
`attach <id>` and `view` it again. Every job also starts with
`++server-auth` and a key made for it: nobody else on the cluster can
query or steer your job, and there is nothing to do for it, because `run`
puts the key on the cluster and `view` hands it to the viewer. The same
commands work in one shot:
`python3 -m appspector run --site delta --program pfield --pes 16 --args
"-k 16"` submits, waits, and opens the viewer; `python3 -m appspector
view <id>`, `status <id>`, `stop <id>`, `jobs` (live jobs; `jobs all`
includes ended ones), `sites`, and `script` (prints the batch script a
spec would submit without submitting).

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
| `cluster/setup.sh`, `cluster/*.env` | the cluster build (Delta, Anvil; add a cluster by adding an env file) |
| `README.md`, `INITIAL-THOUGHTS.md` | status and history, design notes |

Charm++ side: the handlers the viewer relies on are `lvConfig`/`lvImage`
(liveViz), `CkPerfSumDetail compressed` and `CkPerfSumDetail sts`
(trace-utilization, merged in charm PR #4068), and `LBObjLoads`
(LBManager, merged in charm PR #4071). The CCS protocol itself is documented at the top
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
2. Point the shell at it. Quickest: `program /path/to/dir/mine -s 10`
   (a path runs as `./mine -s 10 +pe {pes} ++server ++server-port
   {port}`). To keep it: `program add mine /path/to/dir | ./mine {args}
   +pe {pes} ++server ++server-port {port}`, which writes it into your
   site file (`~/.appspector/sites/delta.ini`), and from then on
   `program mine -s 10`. `command DIR | CMD` runs any command line once.
   The three programs a fresh site file lists (pfield, wave2d, ccstest)
   are the ones `setup-delta.sh` built in your own work directory; they
   are not shared binaries.
3. On the laptop the same works with `site local` (its programs are in
   `appspector/sites/local.ini`), or start the program yourself with
   `++server ++server-port 1234` and run `python3 -m appspector.viewer
   127.0.0.1 1234`; `./demo_local.sh /path/to/program` does both.

`docs/DESIGN.md` describes the contract, the transport and the plans to
generalize to other schedulers and clouds.

## For students: connecting your exercise program

The particle program from the Charm++ exercises connects as it is. Any
Charm++ program accepts `++server ++server-port N`; with that, appSpector
shows your chares' loads per PE with no code changes, and if you did the
liveViz exercise the image pane shows your picture too. Steps:

1. Get a Charm++ build that has liveViz and the per-object load handler.
   If your instructor set one up (a shared build on the cluster), run the
   setup script pointing at it, which takes about a minute and builds
   only the examples and the demo in your own space (on the cluster):
   `APPSPECTOR_CHARM=<the shared build dir> bash cluster/setup.sh delta
   <allocation>`. Otherwise `bash cluster/setup.sh delta <allocation>`
   builds your own in ten minutes. Then `source <work dir>/env.sh` and build your
   program with `$CBUILD/bin/charmc`; the exercises' Makefiles take
   `CHARMC=...`. On a laptop, `charm-wt/<arch>/bin/charmc` after
   `tests/setup-laptop.sh`.
2. In the shell: `program /path/to/your/particle 10000 16` (its own
   arguments after the path), `pes 4`, `run`, `view`. To keep it:
   `program add particle /path/to/dir | ./particle {args} +pe {pes}
   ++server ++server-port {port}`.
3. If your program has a balancer (`-module CommonLBs`, `AtSync`), the
   viewer's Balance button needs a CCS handler to trigger it; copy the
   twelve lines of `pfieldBalance` from `apps/pfield/pfield.C`. Your own
   handler names go in the program entry's third field (`| --balance
   myBalance`) or on `view -- --balance myBalance`.

For an instructor preparing a class: run `cluster/setup.sh` once under
your account, make the work directory group-readable (`chmod -R g+rX`),
and give students the path of `<work dir>/charm/reconverse-linux-x86_64`
for `APPSPECTOR_CHARM`. Each student still needs an account on an
allocation, the ssh control master on their laptop, and ten minutes to
run the script; nothing else is shared or needs coordination, since every
job listens on its own compute node.

Things that trip people up:

- A program that finishes in seconds shows a few frames and then "the
  job is gone": give it enough steps to watch, or a long step count.
- The clicks send `pfieldInject`; on a program without that handler the
  status line says so and nothing else happens.
- Windows: OpenSSH on Windows has no ssh control master; use WSL for
  the laptop side.
- Per-chare loads are the time each chare's entry methods ran in the
  last second, from the load-balancing database; a chare that never
  runs is not shown. Watching this while a program misbehaves (one PE
  busy, the rest idle; a chare that stops showing up) is a cheap
  debugging aid; `log` in the shell tails the job output.

## A path for a new contributor

1. Run the demos: `./demo_local.sh` on the laptop (after
   `tests/setup-laptop.sh`), then pfield and wave2d on Delta through the
   shell. Click, balance, flip the views, read `apps/pfield/README.md`
   and skim `pfield.C` and `appspector/viewer.py` while they run.
2. Connect a program of your own. A particle code from the Charm++
   exercises is ideal: build it against the Delta build (`$CBUILD`),
   `program add` it in the shell, run it, and see it in the viewer with
   no changes (per-chare loads come free). Then add liveViz for an image
   and, if you like, a CCS handler for a button, following pfield.
3. Pick something from the open items below, or whatever the demos made
   you want to change. The repository is charmplusplus/appSpector;
   branch, pull request, review.

## Open items (good first tasks)

- Per-PE view refinements from the old demo: an absolute time axis,
  horizontal bars, Show BG Load / Show Idle toggles.
- A side-by-side layout option.
- A reconverse fix so `++server-auth` reads hexadecimal keys as the
  manual says (the key files are decimal digits today for that reason).
- Frontier and cloud transport (see INITIAL-THOUGHTS.md).
