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
images.

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
it, and open the viewer when it is up. All interaction with the running
program (clicks, Balance, the load views) is in the viewer.

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
The load and utilization requests follow the same rule with their own
interval. `--fixed-rate` turns the backoff off. Clicks and the Balance
button go out on their own connection at once; they never wait for an
image.

A click in the image sends an inject request to the program: the click's
x and y as fractions of the image, a blob width (`--inject-sigma`, 0.03
of the image) and a count (`--inject-count`, 2000 particles), to the
handler `pfieldInject` unless `--inject` names another. The label "click
in the image adds 2000 particles" beside the controls shows the count.

### The bottom panes

Radio buttons after "Load view:" choose one of three views. Both data
sources are requested every second (`--perf-ms`, slower while requests
are slow, as for the image), so flipping between views is immediate.

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
| By-PE and PE-grid panes | linked `-tracemode utilization` (handler `CkPerfObjLoads`, from the trace events, unaffected by `+LBOff` or `LBTurnInstrumentOff`); without it, any Charm++ built from branch `recharm` after 2026-10-23 (handler `LBObjLoads`, which reports the load-balancing database and is empty while that instrumentation is off) |
| Over-time pane | linked `-tracemode utilization` (Charm++ built `--enable-tracing`); a greyed-out button means the handler is missing and the status line says so |
| Inject click | a CCS handler like pfield's `pfieldInject`; other programs need their own, named with `--inject` |
| Balance button | a balancer linked and selected with `+balancer`, plus a CCS handler that starts an LB step, named with `--balance` |

The CCS handlers behind these are `lvConfig` and `lvImage` (liveViz),
`CkPerfObjLoads` or `LBObjLoads` (per-object loads), and `CkPerfSumDetail
compressed` and `CkPerfSumDetail sts` (the utilization trace; the second
returns the entry-method names).

### The status line

| Message | Meaning |
|---|---|
| `connected: N PE(s) on M node(s); liveViz color, push; K entry names` | the viewer reached the job; it lists what it found |
| `error: ...` | the first connection failed: wrong host or port, the forward is not up, or a wrong or missing key |
| `frame N  WxH  T ms/request, every P ms` | images are arriving; T is the time the last image request took, P the time from one request to the next (`--image-ms`, or more while requests are slow) |
| `image: the job is gone (...)` or `perf: the job is gone (...)` | the connection was refused, closed or lost: the program ended or was stopped |
| `image: ...` or `perf: ...` with another error | a request failed for another reason, shown in full |
| `'over time' pane off: the program has no CkPerfSumDetail handler (link it with -tracemode utilization)` | the over-time button is greyed out |
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
| `--perf-ms N` | 1000 | shortest load and utilization request interval; longer while requests are slow |
| `--fixed-rate` | | keep to `--image-ms` and `--perf-ms` even when requests are slow |
| `--pane objects\|ep\|grid` | objects | initial bottom view |
| `--sts FILE` | | the job's `.util.sts` file, for entry-method names; without it the names come over CCS |
| `--no-image` | | do not request images (a program without liveViz) |
| `--no-perf` | | do not request loads or utilization |
| `--timeout S` | 10 | seconds before a request fails |
| `--inject HANDLER` | pfieldInject | the CCS handler a click sends to |
| `--inject-count N` | 2000 | particles per click |
| `--inject-sigma F` | 0.03 | blob width as a fraction of the image |
| `--balance HANDLER` | pfieldBalance | the CCS handler the Balance button sends to |

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
  often. Make the image pane smaller (fewer bytes per frame), or raise
  `--image-ms` to ask less often still.
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
