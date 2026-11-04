# appSpector user manual

This manual is for a person who wants to launch a Charm++ job and watch it
live. It does not assume you will change appSpector's code; contributors
start from [ONBOARDING.md](../ONBOARDING.md).

## What appSpector is

appSpector has two halves. The laptop runs the appSpector shell and the
viewer window. The cluster runs your Charm++ program, started with the
option `++server`, which makes the program listen for requests on a TCP
port. The laptop reaches that port through an ssh port forward over the
cluster's login node, which appSpector sets up for you.

CCS (Converse Client-Server) is the request and reply protocol a Charm++
program speaks once it runs with `++server`. The viewer uses it to ask
for the program's image, the load on each PE, and to send clicks and
button presses back to the program.

`++server-auth FILE` makes the program accept only requests signed with
the key in FILE. appSpector creates a fresh key for every job and gives
it to the viewer, so other users on the cluster cannot query or steer
your job; the traffic itself is not encrypted.

The laptop needs no Charm++ build. It talks CCS through `ccsio`, a client
written in plain Python.

## Installing on the laptop

You need Python 3.9 or newer with tkinter. The python.org installer on
macOS includes tkinter; on Linux install the `python3-tk` package. No
other packages are needed. Pillow is optional and is used only to save
images and to decode JPEG images in the viewer (`--jpeg`).

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
python3 -m unittest discover -s tests        # unit tests against a fake CCS server; no Charm++ needed
```

Nothing is built on the laptop for cluster work.

### Optional: a local demo

To run Charm++ programs on the laptop itself, build Charm++ beside the
repository. This needs a C++ toolchain, cmake, git and libjpeg. On macOS
with MacPorts:

```
sudo port install cmake jpeg
bash tests/setup-laptop.sh      # clones and builds Charm++ into ./charm-wt (10 to 15 minutes), examples, pfield
./demo_local.sh                 # pfield on 4 PEs plus the viewer
```

`tests/setup-laptop.sh` builds Charm++ branch `recharm` with tracing and
liveViz into `charm-wt/<arch>`. It reads the variables `BRANCH`,
`CHARM_WT`, `ARCH` and `JOBS` if you want other values.

`./demo_local.sh [app] [PEs] [port]` starts a program on the laptop and
opens the viewer on it; closing the viewer window ends the program. The
app is one of:

- `pfield` (the default): appSpector's demonstration program.
- `wave2d`: an 800x800 wave field on 16x16 = 256 chares.
- `wave2d-small`: the same on 4x4 = 16 chares, a few chares per PE.
- `mol2d`: Molecular2D particles. Its image shows only the patch grid;
  the particle pixels do not come through yet.
- a path to any other Charm++ program built against the same Charm++.

The defaults are 4 PEs and port 1234.

## Reaching a cluster

appSpector runs `ssh` with no prompts, so the ssh alias for the cluster
must work without asking for a password. Set up only the cluster you
will use.

### Delta

Delta asks for Duo on every login. Use an ssh control master: you log in
once from a real terminal, and every later `ssh delta ...` reuses that
connection. Add to `~/.ssh/config` on the laptop, with your NCSA username:

```
Host delta
    HostName login.delta.ncsa.illinois.edu
    User <your-ncsa-username>
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 12h
```

Open the master from a terminal window and answer Duo. Leave that window
open.

```
ssh delta
```

Check whether the master is up, close it, and reopen it:

```
ssh -O check delta     # is the master up?
ssh -O exit delta      # close it (also clears a stale master)
ssh delta              # reopen it, with Duo
```

Delta sometimes drops the master after a couple of hours; reopen it with
`ssh delta`.

You need an account on a Delta allocation. Its short name is the `X` in
the Slurm account `X-delta-cpu`.

### Anvil

Anvil uses an ssh key and needs no control master:

```
Host anvil
    HostName anvil.rcac.purdue.edu
    User <your-anvil-username>
    IdentityFile ~/.ssh/<your key>
```

`ssh anvil true` must return without a prompt. appSpector then starts
and stops its port forwards as background ssh processes.

### Windows

OpenSSH on Windows has no control master. Use WSL for the laptop side.

## Setting up a cluster

Do this once, on the one cluster you use. Log in to it (`ssh delta` or
`ssh anvil`), clone the repository a second time on the login node, and
run the setup script with the cluster's name and your allocation:

```
git clone https://github.com/charmplusplus/appSpector.git
cd appSpector
bash cluster/setup.sh delta <allocation>     # Delta: the X in your Slurm account X-delta-cpu
bash cluster/setup.sh anvil <allocation>     # Anvil: the Slurm account itself
```

It takes about 10 minutes. `cluster/<site>.env` holds each cluster's
modules and Slurm defaults. The script:

1. clones Charm++ branch `recharm` into `<work dir>/charm`;
2. builds it as `reconverse-linux-x86_64` with `--with-production
   --enable-tracing` (about 6 minutes), then the liveViz library
   (`cmake -DTARGET=LIBS`);
3. builds the example programs: the Converse `ccstest` server, and
   Charm++'s `wave2d` as `wave2d-demo` (liveViz, `-tracemode
   utilization`, runs until stopped);
4. builds `apps/pfield` in the repository checkout;
5. writes `env.sh` (modules, `CBUILD` set to the Charm++ build,
   `LD_LIBRARY_PATH`), batch scripts `ccs.sbatch`, `wave2d.sbatch` and
   `pfield.sbatch` (for `appspector.launch`; the shell writes its own),
   and `site.ini`, the site file for the laptop shell.

Build logs go to `<work dir>/charm-build.log`, `libs-build.log`,
`wave2d-build.log` and `pfield-build.log`. Running the script again skips
the clone and the Charm++ build and rebuilds the rest.

The default work directory is `/work/hdd/<allocation>/<your user>/appspector`
on Delta and `/anvil/projects/x-<allocation>/<your user>/software/appspector`
on Anvil. The Anvil project space has a shared file quota of one million
files and a Charm++ tree is a few hundred thousand files, so check
`myquota` first, or use scratch with
`APPSPECTOR_WORK=/anvil/scratch/<your user>/appspector` (scratch is purged
periodically).

Optional environment variables, prefixed so they do not collide with the
cluster's own (Anvil sets `$WORK` itself):

| Variable | Meaning |
|---|---|
| `APPSPECTOR_WORK` | work directory |
| `APPSPECTOR_BRANCH` | Charm++ branch (default `recharm`) |
| `APPSPECTOR_PARTITION`, `APPSPECTOR_ACCOUNT`, `APPSPECTOR_MEM` | Slurm partition, account, memory per job |
| `APPSPECTOR_PORT` | CCS port (default 1234) |
| `APPSPECTOR_JOBS` | parallel make jobs (default 16) |
| `APPSPECTOR_CHARM` | use an existing Charm++ build (next section) |

The last lines of the script's output are the commands to run next on
the laptop. The first one copies the site file:

```
python3 -m appspector
appspector> site fetch delta delta:<work dir>/site.ini      # once per cluster
```

### For instructors: one shared build for a class

With `APPSPECTOR_CHARM` set to an existing Charm++ build directory, the
script builds no Charm++. It copies the `ccstest` and `wave2d` example
sources into `<work dir>/examples` and builds them and pfield there, in
about a minute. The shared build must include liveViz.

To prepare a class: run `cluster/setup.sh` once under your account, make
the work directory group-readable (`chmod -R g+rX`), and give students the
path of `<work dir>/charm/reconverse-linux-x86_64`. Each student then runs,
on the cluster:

```
APPSPECTOR_CHARM=<the shared build dir> bash cluster/setup.sh delta <allocation>
```

Each student still needs an account on an allocation, the ssh control
master on their laptop, and a few minutes to run the script. Nothing else
is shared or needs coordination, since every job listens on its own
compute node.

## The shell

The shell is for firing jobs: choose a site, a program and a size, run
it, and open the viewer when it is up. Interaction with the running
program (clicks, Balance, the load views) is in the viewer, except
`steer`, which calls functions a charm4py program exposes.

```
python3 -m appspector
appspector> site delta
appspector> program pfield -k 16 -n 400        # a program from the site, then its own arguments
appspector> pes 16                              # and, for clusters: nodes N, ppn N, walltime HH:MM:SS
appspector> run                                 # writes the batch script, submits, returns at once
  ... a line appears when the job's CCS server is up ...
appspector> view                                # opens the viewer window on the job
appspector> status                              # or: jobs, log, stop
appspector> quit                                # the job keeps running; 'stop' cancels it
```

### Commands

| Command | What it does |
|---|---|
| `sites` | list the known sites |
| `site NAME` | select a site; with no name, show the current one |
| `site fetch NAME SSH:PATH` | copy a site file written by a cluster's setup script, then select it |
| `programs` | the site's programs and their command lines |
| `program NAME [ARGS...]` | run a program from the site; the rest of the line is its arguments |
| `program /path/to/exe [ARGS...]` | run an executable by path, as `./exe ARGS +pe {pes} ++server ++server-port {port}` |
| `program add NAME DIR \| CMD [\| VIEWER OPTIONS]` | remember a program in your site file |
| `command DIR \| CMD` | run any command line once (`{pes}`, `{port}` are filled in) |
| `pes N` | total PEs |
| `nodes N` | nodes (cluster sites) |
| `ppn N` | processes per node (cluster sites) |
| `walltime HH:MM:SS` | wall time; the default is 10 minutes |
| `port N` | the job's CCS port (default 1234) |
| `show` | the job spec with the site's defaults filled in, and the command it will run |
| `script` | print the batch script the spec would submit, without submitting |
| `run [--no-auth]` | submit or start the job; a line appears when its CCS server is up |
| `jobs [all]` | live jobs (queued, running, up, or stuck completing), re-checked with the scheduler; `jobs all` adds the last 15 that ended |
| `status [ID]` | refresh and show a job's state |
| `log [ID]` | the last lines of the job's output |
| `attach ID` | make a recorded job current, and wait for it if it is not up yet |
| `view [ID] [-- VIEWER-ARGS]` | open the viewer on the job (registers the port forward first) |
| `steer [list]`, `steer NAME [ARGS] [K=V]`, `steer eval SOURCE` | call a function a charm4py job exposes (see [Steering a charm4py program](#steering-a-charm4py-program)) |
| `stop [ID]` | cancel the job and its forward |
| `quit` | leave the shell; running jobs keep running |

`help COMMAND` explains any command. Commands that take `[ID]` use the
current job when the id is left out.

Every PE count must give each process at least one PE: `pes` must be at
least `nodes` times `ppn`. A batch job asks Slurm only for the cores its
PEs use, not a whole node, because a whole-node request on a shared
partition can wait in the queue for a long time.

`run` returns at once. Queue waits range from seconds to hours; `status`
shows the queue state meanwhile and `log` the job output. You can `quit`
and come back later with `attach ID`, because every job is recorded in
`~/.appspector/jobs.json` (see [Files on the laptop](#files-on-the-laptop)).

### Authentication

Every job starts with `++server-auth` and its own key, with nothing for
you to do. `run` draws a 32-digit key, writes it on the cluster as
`<work dir>/jobs/<program>-<stamp>.key` (mode 600, before the job is
submitted), appends `++server-auth <that file>` to the command, and keeps
the key in the job record. `view` passes it to the viewer as `-k`. The
key is decimal digits because the server reads the key string as decimal
digit pairs.

To turn it off: `auth = no` in the site file, or `run --no-auth` for one
job. For a job someone started by hand with their own key file, pass the
key yourself: `view -- -k KEY`.

### Viewer options from the shell

`view -- VIEWER-ARGS` passes everything after `--` to the viewer, for
example `view -- --inject myHandler --no-image`. To apply options every
time, put them in the program's entry as a third field (see
[Connecting your own program](#connecting-your-own-program)).

### One-shot forms

The same commands work without the interactive shell:

```
python3 -m appspector run --site delta --program pfield --pes 16 --args "-k 16"
python3 -m appspector view ID
python3 -m appspector status ID
python3 -m appspector stop ID
python3 -m appspector jobs            # or: jobs all
python3 -m appspector sites
python3 -m appspector script --site delta --program pfield --pes 16
python3 -m appspector steer ID set_rate 0.5     # or: steer ID list, steer ID eval SOURCE
```

`run` submits, waits for the server (up to 6 hours, `--wait SECONDS`),
and opens the viewer. It also takes `--nodes`, `--ppn`, `--port`,
`--walltime`, `--no-view` (do not open the viewer) and `--no-auth`.

### The programs a site comes with

A site file written by `cluster/setup.sh` lists three programs, built in
your own work directory (they are not shared binaries):

- `pfield`, appSpector's demonstration program
  ([apps/pfield/README.md](../apps/pfield/README.md) explains the model,
  the arguments and the CCS handlers). Particles live in a K x K array of
  cells and move under a forcing field or by a random walk. Birth and
  death follow a hot spot that circles the box. Rates are per wall-clock
  second, so the behaviour is the same at any step rate: a particle lives
  about 50 seconds, and an injected blob stays visible and decays at that
  rate. A click in the image injects a Gaussian blob of particles; the
  Balance button runs one load-balancing step.
- `wave2d`, Charm++'s wave2d example linked with the utilization trace,
  which also feeds the "over time, by entry method" view.
- `ccstest`, the Converse CCS test server.

pfield and wave2d are good code to read: wave2d for a stencil-style chare
array with liveViz, pfield for the CCS handlers and AtSync load
balancing. The built-in `local` site (`appspector/sites/local.ini`) lists
the same programs, plus `wave2d-small`, for the laptop build.

### Running a batch script you wrote yourself

`appspector.launch` runs a batch script that you wrote, outside the shell:

```
python3 -m appspector.launch run --site delta --sbatch <path on the cluster>.sbatch
python3 -m appspector.launch attach --site delta --job ID --out <path of the job output>
python3 -m appspector.launch watch --site delta --out <path of the job output>
python3 -m appspector.launch stop --site delta --job ID
```

`run` submits the script, waits for the `ccs: Server IP` line in the job
output, registers the port forward and starts the viewer. On exit it
cancels the forward and the job; `--keep` leaves the job running, and
`--check` prints the PE layout instead of opening the viewer. `attach`
joins a running job it did not start, `watch` tails the newest output,
and `stop` cancels. The script must start the program with `++server
++server-port N`.

## The viewer

The shell's `view` starts the viewer for you. It can also run on its own
against any job whose CCS port you can reach:

```
python3 -m appspector.viewer HOST PORT [-k KEY] [options]
```

The window has an image pane on top, a bottom pane with the load views, a
row of controls between them, and a status line at the bottom.

### The image pane

The program's own liveViz image, requested at most every 200 ms
(`--image-ms`) at the size of the pane. Pillow is not needed; Tk reads
the raw image bytes directly.

The viewer never has more than one image request out, and it does not
flood a slow job or link: after each request it waits until the
interval is up, and at least as long as requests have been taking
lately (a running average), but never more than 5 s. A request that
takes 2 s is followed by about 2 s of quiet, so for requests under 5 s
the job and the link are kept busy at most half the time; when requests
get fast again the viewer is back at the full rate after a few of them.
The load and utilization requests are not slowed down this way: they
stay at `--perf-ms`, because each one collects the next second of
utilization the job has stored, and their replies are small.
`--fixed-rate` turns the image backoff off. Clicks and the Balance
button go out on their own connection at once; they never wait for an
image.

A raw image is 3 bytes per pixel, about 1.3 MB for an 1100x400 pane:
several MB/s at 200 ms, and seconds per request over an ssh forward to a
cluster. `--jpeg` (quality 75, or `--jpeg 50` for another,
1 to 100) asks the program for JPEG images instead, a small fraction of
that size; the viewer decodes them with Pillow. This needs the program's
Charm++ built with libjpeg (see the table below). A JPEG request that
gets no JPEG back is followed by a raw one for that frame. Until the first
JPEG image arrives the viewer waits only 2 s for one, or three times as
long as the last raw image took if that is longer (not `--timeout`), so
a job that holds JPEG requests cannot stall every frame while a slow
link still gets its JPEG images. After three
misses in a row (or at once if Pillow is missing) the viewer
says so on the status line and requests raw images from then on. Once a JPEG image has
arrived, a failed request is reported like any other.

A click in the image sends an inject request to the program: the click's
x and y as fractions of the image, a blob width (`--inject-sigma`, 0.03
of the image) and a count (`--inject-count`, 2000 particles), to the
handler `pfieldInject` unless `--inject` names another. The label "click
in the image adds 2000 particles" beside the controls shows the count.

### The bottom panes

Radio buttons after "Load view:" choose one of three views. Both data
sources are requested every second (`--perf-ms`), so flipping between
views is immediate.

- **by PE, last second, stacked by chare** (the default, `--pane objects`):
  one bar per PE whose height is that PE's utilization over the last
  interval, stacked by the time each chare ran. Every chare has its own
  color, the same on every PE, so a chare that migrates keeps its color.
  The data comes from the load-balancing database, which every recent
  Charm++ program has; the first request turns its instrumentation on. A
  chare that did not run in the last interval is not shown.
- **over time, by entry method** (`--pane ep`): one stacked column per
  second of utilization by entry method, scrolling left. It needs the
  program linked with `-tracemode utilization`.
- **PE grid, utilization** (`--pane grid`): every PE as a square in a
  square-ish layout, colored from blue (idle) to red (busy) by its
  utilization over the last interval. The **per process** checkbox shows
  one square per process instead, averaged over its PEs.

The **Balance** button sends a request to the handler `pfieldBalance`
unless `--balance` names another. In pfield it runs one load-balancing
step at the end of the current iteration.

Watching these views while a program misbehaves (one PE busy and the rest
idle, or a chare that stops showing up) is a cheap debugging aid. `log`
in the shell shows the job output alongside.

### What each feature needs from the program

| Feature | What the program needs |
|---|---|
| Image pane | linked `-module liveViz` with a liveViz callback |
| JPEG images (`--jpeg`) | a Charm++ whose configure found libjpeg's headers and library (`CMK_USE_LIBJPEG 1` in `<build>/include/conv-autoconfig.h`, `-ljpeg` in `<build>/lib/libmoduleliveViz.dep`); without it the program answers a JPEG request with nothing and prints `Ignoring liveViz client's unrecognized compressionType 1` in its output. The Delta build from `cluster/setup.sh` has it (`cluster/delta.env` points the build at Spack's libjpeg-turbo; a Delta build made before that does not, rebuild it); laptop builds made after `port install jpeg` do |
| By-PE and PE-grid panes | linked `-tracemode utilization` (handler `CkPerfObjLoads`, from the trace events, unaffected by `+LBOff` or `LBTurnInstrumentOff`); without it, any Charm++ built from branch `recharm` after 2026-10-23 (handler `LBObjLoads`, which reports the load-balancing database and is empty while that instrumentation is off) |
| Over-time pane | linked `-tracemode utilization` (Charm++ built `--enable-tracing`); a greyed-out button means the handler is missing and the status line says so |
| All three load panes, charm4py | `from charm4py import appspector` at the top of the program and `appspector.serve()` once in `main` (see [Load data from charm4py programs](#load-data-from-charm4py-programs)) |
| Inject click | a CCS handler like pfield's `pfieldInject`; other programs need their own, named with `--inject` |
| Balance button | a balancer linked and selected with `+balancer`, plus a CCS handler that starts an LB step, named with `--balance` |

The CCS handlers behind these are `lvConfig` and `lvImage` (liveViz),
`CkPerfObjLoads` or `LBObjLoads` (per-object loads), and `CkPerfSumDetail
compressed` and `CkPerfSumDetail sts` (the utilization trace; the second
returns the entry-method names).

### Load data from charm4py programs

A charm4py program feeds all three bottom panes from its own handlers once
it opts in (charm4py branch `ccs-loads`, module `charm4py.appspector`):

```python
from charm4py import charm, appspector   # at top level, so every process registers it

def main(args):
    appspector.serve()     # once; returns when every PE is measuring
    ...

charm.start(main)
```

Run it with `++server ++server-port N` as usual. The viewer asks for
`CkPerfSumDetail sts` first; when the job has no such handler it asks for
`charm4py SumDetail sts`, and if that answers (the status line says
`charm4py loads`) it uses `charm4py ObjLoads` and `charm4py SumDetail` for
the rest of the session. Both use the Charm++ reply layouts, so the panes
read them unchanged:

- **by PE** and **PE grid**: the time each chare spent in Python entry
  methods over the last interval, per PE. Array elements keep their color
  across migration; group members and the mainchare (and charm4py's own
  internal group, which runs future and reduction callbacks) appear as
  chares too. Busy time is time inside entry methods, message unpickling
  included; the rest of the wall time counts as idle.
- **over time**: one column per poll (`--perf-ms`), the mean over PEs of
  each Python entry method's share, named `Class.method`. Code a coroutine
  runs after it resumes from a future or channel is charged to the entry
  method it started in.

The numbers are measured by charm4py around each entry method
(`time.perf_counter()`), not by the Charm++ trace, so no tracing build is
needed. Nothing is collected or sent until the viewer asks: each request
is one broadcast and one gather over the PEs. A charm4py program that does
not call `serve()` has no over-time pane, and its by-PE and grid panes come
from `LBObjLoads` (the C++ load-balancing database), which in a plain
charm4py program (no `useAtSync` array, instrumentation off) answers with
PEs but no chares, so the bars stay empty.

### The status line

| Message | Meaning |
|---|---|
| `connected: N PE(s) on M node(s); liveViz color, push; K entry names` | the viewer reached the job; it lists what it found |
| `error: ...` | the first connection failed: wrong host or port, the forward is not up, or a wrong or missing key |
| `frame N  WxH  T ms/request, every P ms` | images are arriving; T is the time the last image request took, P the time from one request to the next (`--image-ms`, or more while requests are slow) |
| `frame ...  JPEG qQ S KB` | the same with `--jpeg`: quality Q, S KB for the last image |
| `frame ...  raw (JPEG try K of 3 failed)` | with `--jpeg`, the last JPEG request got no JPEG back, so this frame is raw; a hiccup of the forward, or the start of the case below |
| `JPEG off: the job's liveViz cannot send JPEG ...` (held a few seconds), then `frame ...  raw (job has no JPEG)` | `--jpeg` was given but three JPEG requests in a row got none: the program's Charm++ has no libjpeg; images are raw |
| `JPEG off: 3 JPEG requests in a row got no reply within T s ...`, then `frame ...  raw (JPEG timed out)` | `--jpeg` was given but no JPEG image came back in time: a stuck job or forward, or a link much slower for JPEG than for raw images. Start the viewer again to retry `--jpeg` |
| `frame ...  raw (no Pillow for JPEG)`, after `...; JPEG off: Pillow is not installed, raw images` | `--jpeg` was given but Pillow is not installed on the laptop (`pip install Pillow`) |
| `image: the job is gone (...)` or `perf: the job is gone (...)` | the connection was refused, closed or lost: the program ended or was stopped |
| `image: ...` or `perf: ...` with another error | a request failed for another reason, shown in full |
| `'over time' pane off: the program has no CkPerfSumDetail handler (link it with -tracemode utilization; charm4py: call charm4py.appspector.serve())` | the over-time button is greyed out |
| `connected: ...; charm4py loads; K entry names` | a charm4py program serving its own loads (`charm4py.appspector.serve()`): all three panes come from it |
| `'by PE' and 'PE grid' panes off: the program has neither CkPerfObjLoads (-tracemode utilization) nor LBObjLoads (older Charm++)` | those buttons are greyed out; when several panes go off at once, their messages share one line, separated by `;` |
| `inject at (x, y): sent, waiting for the reply ...` | the click was sent; if nothing replaces it, the program has not answered (yet) |
| `inject at (x, y): REPLY` | the program's reply to a click |
| `inject at (x, y): no reply (job has no pfieldInject handler)` | the program has no handler by that name |
| `balance: REPLY`, `balance: no reply (job has no pfieldBalance handler)` | the same for the Balance button |
| `inject ... failed: ...`, `balance failed: ...`, `balance: not connected` | the request could not be sent |

The frame line is rewritten with every image, five times a second, so
anything else would vanish before it could be read. The replies to a
click or to Balance (and their `sent`, `failed` and `not connected`
lines) and the pane-off messages therefore hold the status line for 4.5
seconds; frames keep arriving meanwhile, and the frame line comes back
after that. An `image: ...` or `perf: ...` error is shown at once, even
over a held message.

The caption inside the bottom pane gives the PE and chare counts, the
interval and the busiest PE.

### Command-line options

| Option | Default | Meaning |
|---|---|---|
| `HOST PORT` | | where the job's CCS port is reachable |
| `-k`, `--key KEY` | none | the `++server-auth` key |
| `--size WxH` | 600x400 | initial image pane size |
| `--image-ms N` | 200 | shortest image request interval; longer while requests are slow |
| `--jpeg [Q]` | off (raw) | request JPEG images at quality Q, 1 to 100 (75 if Q is left out); needs Pillow and a Charm++ with libjpeg, else raw images. Put it after `HOST PORT` |
| `--perf-ms N` | 1000 | load and utilization request interval |
| `--fixed-rate` | | keep to `--image-ms` even when image requests are slow |
| `--pane objects\|ep\|grid` | objects | initial bottom view |
| `--sts FILE` | | the job's `.util.sts` file, for entry-method names; without it the names come over CCS (the viewer still asks the job, to tell a charm4py job that serves its own loads, whose handlers it then uses, from a Charm++ one) |
| `--no-image` | | do not request images (a program without liveViz) |
| `--no-perf` | | do not request loads or utilization |
| `--timeout S` | 10 | seconds before a request fails |
| `--inject HANDLER` | pfieldInject | the CCS handler a click sends to |
| `--inject-count N` | 2000 | particles per click |
| `--inject-sigma F` | 0.03 | blob width as a fraction of the image |
| `--balance HANDLER` | pfieldBalance | the CCS handler the Balance button sends to |
| `--steer` | off | add a "Steer:" line for a charm4py program that uses `charm4py.steer`: it lists the exposed calls, and a line typed there (`NAME ARGS`, `list`, `eval SOURCE`) is sent on Enter, the reply going to the status line |

The `.util.sts` file is written next to the program's binary, not in the
working directory.

All CCS requests run on worker threads, so a slow job does not freeze the
window.

## Connecting your own program

appSpector does not know what the program is. Any Charm++ program that
runs with `++server ++server-port N` connects as it is. The running
example here is the particle program from the Charm++ exercises; another
example such as `examples/charm++/leanmd` works the same way.

### 1. Build it against the right Charm++

Use the Charm++ build that `cluster/setup.sh` made (or a shared one from
your instructor, see
[For instructors](#for-instructors-one-shared-build-for-a-class)), so the
program has liveViz and the per-object load handler. On the cluster:

```
source <work dir>/env.sh
make CHARMC=$CBUILD/bin/charmc        # the exercises' Makefiles take CHARMC=...
```

On the laptop, after `tests/setup-laptop.sh`, the compiler is
`charm-wt/<arch>/bin/charmc`.

With that build:

- The by-PE and PE-grid views show your chares' loads with no code
  changes.
- For the image, link `-module liveViz` and implement its callback; if you
  did the liveViz exercise, the image pane shows your picture. pfield and
  wave2d show how. Without liveViz, run the viewer with `--no-image`.
- For the over-time view, link `-tracemode utilization`.

### 2. Point the shell at it

Quickest, by path, with the program's own arguments after it:

```
appspector> program <dir>/particle 10000 16
appspector> pes 4
appspector> run
appspector> view
```

A path runs as `./particle 10000 16 +pe {pes} ++server ++server-port
{port}`. To keep it, add it to your site file:

```
appspector> program add particle <dir> | ./particle {args} +pe {pes} ++server ++server-port {port}
appspector> program particle 10000 16
```

The entry has the form `NAME DIR | CMD [| VIEWER OPTIONS]`. `{args}`,
`{pes}` and `{port}` are filled in when the job runs. The optional third
field holds viewer options that apply every time the program is viewed,
for example `| --no-image` or `| --balance myBalance`. `program add`
writes to `~/.appspector/sites/<site>.ini`; adding to the built-in `local`
site first copies it there. `command DIR | CMD` runs a command line once
without saving it.

On the laptop the same works with `site local`. Or start the program
yourself with `++server ++server-port 1234` and run
`python3 -m appspector.viewer 127.0.0.1 1234`; `./demo_local.sh
<path to program>` does both.

### 3. Add handlers for clicks and Balance

Any interaction with the running program is a CCS handler. Register it
with `CcsRegisterHandler`, decode the request with `PUP_toNetwork_unpack`,
and answer with `CcsSendReply`. Handler names are at most 32 bytes.

- **Balance.** If your program has a balancer (`-module CommonLBs`,
  `AtSync`, selected at run time with `+balancer`), the Balance button
  needs a handler that starts a load-balancing step. Copy the twelve lines
  of `pfieldBalance` from `apps/pfield/pfield.C`.
- **Clicks.** A click sends x, y and sigma as network-order doubles
  (fractions of the image) and a count as a network-order 32-bit integer.
  `pfieldInject` in `apps/pfield/pfield.C` decodes this.

Give the viewer your handler names in the program entry's third field
(`| --balance myBalance --inject myInject`) or on the command line
(`view -- --balance myBalance`).

## charm4py programs

appSpector talks CCS, so a charm4py program (Python on Charm++) works too,
with a few differences. Measured on Delta in November 2026 against Charm++
recharm 5e3f7e4 (reconverse) and charm4py main; see
[apps/c4p_demo/README.md](../apps/c4p_demo/README.md) for the numbers.

**Setting up.** After `cluster/setup.sh`, run on the login node

```
bash cluster/charm4py.sh delta mzu
```

It makes `$WORK/charm4py`: a venv on the cluster's Python module
(`PYTHON_MODULE` in `cluster/<site>.env`), a Charm++ clone built for the
`charm4py` target (reconverse, tracing; 10 to 20 minutes the first time),
charm4py itself, and `bin/c4p-python`, the venv's interpreter with the
modules loaded, which batch jobs run. It adds two programs to the site
file's `[programs]` section, so fetch it again on the laptop (`site fetch delta ...`):

```
c4p_demo    = {appspector}/apps/c4p_demo | /work/.../charm4py/bin/c4p-python c4p_demo.py {args} +traceoff +pe {pes} ++server ++server-port {port} | --inject c4pInject | procs=pes
c4p_liveviz = /work/.../charm4py/src/examples/liveviz | /work/.../charm4py/bin/c4p-python liveviz.py {args} +traceoff +pe {pes} ++server ++server-port {port} | | procs=pes
```

Each entry it writes has a comment line `# added by cluster/charm4py.sh ...`
above it; a rerun replaces those entries and keeps one you wrote or edited
(no comment line above it: delete the comment to keep your edits). Running
it again also checks out `C4P_REF` and `C4P_CHARM_REF` again, so a changed
ref takes effect (a different Charm++ ref needs a rebuild: remove
`$WORK/charm4py/charm/reconverse-linux-x86_64-charm4py`). With
`C4P_CHECKOUT=/path/to/charm4py` it installs your checkout as it is: it
does not apply the liveViz fix there (see Images), only says whether the
checkout needs it.

Then `program c4p_demo`, `pes 4`, `run`, `view` as for any program.

**One PE per process.** A charm4py process is one Python interpreter and
runs one PE; several PEs in one process crash at startup. The fourth field
of a program entry holds job options, and `procs=pes` makes the processes
per node follow the PEs per node (so `pes 8` on one node runs 8
processes with one core each). The PEs must split evenly over the nodes
(`pes 6` with `nodes 4` is refused, with the nearest values that work),
and an explicit `ppn` that does not give one process per PE is refused
too (`ppn 0` goes back to the default); leave `ppn` unset for these
programs. For your own script:
`program add mine /path/to/dir | /work/.../charm4py/bin/c4p-python mine.py {args} +pe {pes} ++server ++server-port {port} | | procs=pes`.

**What works.** CCS itself, `++server-auth`, `num_pes`/`num_nodes` (the
viewer's PE layout), liveViz images (`lvConfig`, `lvImage`), and CCS
handlers the program registers with `charm.CcsRegisterHandler(name, fn)`
and answers with `charm.CcsSendReply(bytes)`, so clicks work when the
program has an inject handler (c4p_demo's `c4pInject`). There is no
Balance handler. The load panes need the program to opt in (see
[Load data from charm4py programs](#load-data-from-charm4py-programs));
without it the charm4py target, which has no utilization trace module,
leaves the "over time" view empty and the per-PE bars without load.

**Images.** Stock charm4py main cannot make an image at all (a TypeError
in `liveviz.py` aborts the job at the first request); `cluster/charm4py.sh`
applies a one-line fix to its own clone (and prints whether it applied it,
found it applied, or found it not needed), which still assembles the image pixel by pixel in
Python on PE 0: a 1100x400 frame costs 1.2 to 1.7 s on Delta (pfield about
0.3 s). charm4py branch `liveviz-numpy-v2` (until it is merged upstream)
assembles with NumPy, parses liveViz version 2 requests and answers JPEG
through Pillow: 0.15 to 0.2 s per raw 1100x400 frame on Delta, 0.09 s and
about 130 KB with `--jpeg 75`. That liveViz answers image requests
strictly in order, one deposit per request, so a program must not drop a
request it has been handed: c4p_demo serves one per step, oldest first.
With the appSpector viewer, which keeps one image request outstanding,
there is never more than one waiting, so the same program works with the
patched stock liveViz and the fixed one.

**Tracing writes files.** The tracing build writes projections logs
(`<script>.N.log.gz`, several MB a minute per PE) into the program's
directory. `+traceoff` on the command line (the entries above have it)
keeps them to a few KB.

### Steering a charm4py program

A charm4py program can expose Python functions that you call by name
while it runs, from the shell (`steer`) or the viewer (`--steer`). This
needs charm4py with the `charm4py.steer` module (branch `ccs-steer` of
charm4py until it is merged). In the program:

```python
from charm4py import charm, Chare, Array, steer

@steer.expose
def set_rate(rate: float):
    "Set the diffusion rate on every chare."
    cells.set_rate(rate, awaitable=True).get()   # broadcast, wait for every chare
    return rate

def main(args):
    global cells
    cells = Array(Cell, 16)
    steer.init()                 # registers the CCS handler c4pSteer on PE 0
    ...
charm.start(main)
```

Import `steer` at the top of the program (before `charm.start`), expose at
module level or from `main`, and call `steer.init()` once in `main`. A
function may block on futures (`awaitable=True`, `ret=True`,
`charm.sleep`): each call runs in its own coroutine on PE 0 and the reply
waits for it, while PE 0 keeps serving other requests (images, other
calls). If it returns a charm4py Future, the reply carries the future's
value. A function that computes for a long time without yielding holds
PE 0 like any entry method.

From the shell, for the current job (it uses the job's key, and the
viewer's port forward if one is open). There is one port forward at a
time, so a `steer` that needs a forward of its own (no viewer of this job
open) would cut off an open viewer of another job; it refuses then and
says so: close that viewer first, or steer from a viewer of this job
(`view ID -- --steer`). Errors start with `steer: `, and the one-shot form
(`python3 -m appspector steer ID ...`) then exits with status 1.

```
appspector> steer
  set_rate(rate: float)    Set the diffusion rate on every chare.
  eval: off
appspector> steer set_rate 0.5
0.5
appspector> steer set_rate -1
steer: ValueError: rate must be positive
Traceback (most recent call last): ...
```

Arguments are words as in a shell; each is a JSON value if it parses
(`0.5`, `true`, `null`, `[1,2]`), else a string, and `NAME=VALUE` gives a
keyword argument. For the string `"3"` quote the JSON quotes:
`steer f '"3"'`. Results print as JSON. In scripts, `ccsio.steer` does the
same: `steer.list(server)`, `steer.call(server, "set_rate", 0.5)`,
`steer.eval(server, source)`; a failed call raises `steer.SteerError` with
the job's error and traceback.

**Wire format** (CCS handler `c4pSteer`, PE 0). The request is UTF-8 JSON
`{"call": NAME, "args": [...], "kwargs": {...}}`; the reply is UTF-8 JSON,
one per request: `{"ok": true, "result": VALUE}` or `{"ok": false,
"error": "Type: message", "traceback": "..."}`. `list` and `eval` are
built in, so a function the program exposes as `list` or `eval` cannot be
called: `list` answers `{"calls": [{"name", "signature", "doc"}, ...],
"eval": true|false}`, and `eval` takes one argument, Python source, and
answers the value of an expression or of a trailing expression statement
(empty source is refused before anything is sent).
NumPy values come back as numbers and lists, anything else JSON cannot
hold as its `repr`.

**Security.** `++server-auth` (on by default for jobs `run` starts)
authenticates every request: only someone with the job's key can call
anything, and the replies prove the job has the key too. It does not
encrypt: arguments and results cross the network in the clear, so keep
the CCS port behind the ssh forward (which encrypts the laptop to login
node leg) and on the cluster's internal network. Without
`++server-auth`, anyone who can reach the port can call every exposed
function. Expose only what a key holder may do; the key file stays mode
600.

`eval` runs arbitrary Python in the job with your account's rights:
anyone with the key can do anything you can on the cluster. It is off
unless the program asks for it, `steer.init(allow_eval=True)`, AND the
job runs with `++server-auth`; with `allow_eval=True` and no auth the
program prints a warning and eval stays off. `steer` (list) says whether
it is on. Every eval is printed in the job's output.

## Troubleshooting

- **`run` fails with ssh error 255, or hangs.** The Delta control master
  is closed or stale. Run `ssh -O exit delta`, then `ssh delta` in a
  terminal and answer Duo.
- **A Delta job is RUNNING but `log` stays empty for over a minute.** A
  node-level file-system hang on Delta. `stop` the job and `run` again.
- **`run` is refused with `QOSMaxSubmitJobPerUserLimit`.** Old jobs stuck
  in COMPLETING count against the per-user limit. `jobs` lists them
  (they show as completing); `stop ID` each one.
- **A pane button is greyed out.** The program lacks the handler for that
  view; the status line names it. See
  [What each feature needs from the program](#what-each-feature-needs-from-the-program).
- **The viewer shows "the job is gone" right after a few frames.** The
  program finished. Give it enough steps to watch, or a long step count.
- **Clicks do nothing.** The program has no inject handler; the status
  line says "no reply (job has no pfieldInject handler)". Add one, or name
  yours with `--inject`.
- **"frame … ms/request" keeps climbing.** The forward, the network or
  the job is slow; "every P ms" shows the viewer already asking less
  often. Try `--jpeg` if the program's Charm++ has libjpeg (far fewer
  bytes per frame), make the image pane smaller, or raise `--image-ms`
  to ask less often still.
- **`run` says "cannot ssh to ... non-interactively".** Open the control
  master (`ssh delta`) or set up key authentication, then retry.
- **"spec incomplete" or a complaint about PEs and processes.** `pes` is
  smaller than `nodes` times `ppn`; raise `pes` or lower `nodes`/`ppn`.
- **A chare is missing from the by-PE bars.** Per-chare loads are the time
  each chare's entry methods ran in the last second; a chare that did not
  run is not shown.
- **The ssh control master does not work on Windows.** See
  [Windows](#windows).
- **The program has no image.** It is not linked with liveViz; run the
  viewer with `--no-image` (as a third field in the program entry).

## Files on the laptop

- `~/.appspector/sites/<name>.ini`: site files, written by `site fetch`
  or `program add`. They win over the built-in sites in
  `appspector/sites/` (the `local` site). The `[site]` section has these
  keys:

  | Key | Meaning |
  |---|---|
  | `scheduler` | `slurm` or `local` |
  | `ssh` | the ssh alias (slurm) |
  | `work` | the work directory on the cluster: `env.sh`, `jobs/`, outputs |
  | `appspector` | the repository checkout there |
  | `env` | sourced by every batch script (default `{work}/env.sh`) |
  | `account`, `partition` | Slurm account and partition |
  | `cores_per_node` | cores per node |
  | `default_nodes`, `default_procs_per_node`, `default_pes` | the defaults for `nodes`, `ppn`, `pes` |
  | `walltime` | default wall time (00:10:00) |
  | `mem` | memory per job |
  | `launcher` | the launch command, such as `srun -n {procs} -c {cores_per_proc}` |
  | `port` | the CCS port (1234) |
  | `auth` | `yes` (default) for a fresh `++server-auth` key per job |

  The `[programs]` section has one line per program:
  `name = directory | command line [| viewer options]`. Values may use
  `{work}`, `{appspector}`, `{home}` and, in commands, `{args}`, `{pes}`,
  `{port}`, `{procs}`, `{cores_per_proc}`.
- `~/.appspector/jobs.json`: the record of the last 50 jobs (site, job id,
  node, port, state, output file and key), so a later shell can `attach`
  and `view`. It holds the job keys, so it is mode 600.
- `~/.appspector-forward`: the port forward currently registered, so the
  next `view` or `stop` can remove it.
- `runs/` in the repository: output (`<program>-<stamp>.out`) and key
  files of jobs on the `local` site.

## Files on the cluster

- `<work dir>/jobs/<program>-<stamp>.sbatch`: the batch script `run`
  generated.
- `<work dir>/jobs/<program>-<stamp>.key`: the job's `++server-auth` key,
  mode 600.
- `<work dir>/jobs/<program>-<job id>.out`: the job's output, which `log`
  shows.
- `<work dir>/site.ini`: the site file for `site fetch`.
- `<work dir>/env.sh`: modules and `CBUILD`, sourced by every batch script
  and by you before building a program.
- `<work dir>/charm/reconverse-linux-x86_64`: the Charm++ build (`$CBUILD`),
  unless `APPSPECTOR_CHARM` pointed at a shared one.
