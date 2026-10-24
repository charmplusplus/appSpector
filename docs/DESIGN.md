# appSpector design notes

Where the tool is going and how its parts fit, so that new programs,
new machines and new front ends can be connected without reworking it.
Status and history are in README.md; the original idea is in
INITIAL-THOUGHTS.md.

## The shape

Three parts, each replaceable on its own:

1. **The job-side contract** is deliberately minimal: a Charm++ program
   that runs with `++server ++server-port N` and prints the line
   `ccs: Server IP = ..., Server port = N`. Everything else is optional
   and discovered at run time by probing CCS handlers: `lvConfig` and
   `lvImage` (liveViz) for the image, `LBObjLoads` (LBManager) for
   per-object loads, `CkPerfSumDetail compressed` and `CkPerfSumDetail
   sts` (trace-utilization) for utilization by entry method, and any
   application handlers the viewer is told about (`--inject`,
   `--balance`). A program that has none of them still connects and shows
   its PE layout. Nothing in the viewer knows what the application is.
2. **The transport** is CCS over one TCP connection per request. Today the
   laptop reaches the job's PE 0 through an ssh port forward registered
   in an ssh control master on the login node (`ssh -O forward`), because
   on the clusters we use a login node can open TCP connections to a
   compute node. `ccsio` is a pure-Python implementation of the wire
   protocol (header, authentication handshake, broadcast and multicast),
   so the laptop needs no Charm++ build.
3. **The launcher** turns "run this program on that machine" into a job
   and a connection: submit, poll for the server line, connect the
   transport, start the viewer, clean up. It is written against Slurm
   over ssh, with the site as an ssh alias and every path as an argument.

## Generalizing to other installations and clouds (long-term plan)

The design keeps the three parts separate so that each can grow a second
implementation:

- **Schedulers.** `appspector.launch` has Slurm specifics in two places:
  the `sbatch --parsable` submission and the `squeue` state poll. A site
  description (scheduler kind, submit and poll commands, how the output
  file is named) turns these into a table; PBS and a plain `ssh host
  ./program` for a workstation are the first additions. Site
  descriptions should live in a small config file, not in code, so a
  user adds an installation without editing Python.
- **Transport direction.** Not every site lets a login node reach a
  compute node (Frontier is the open question). The fallback is a relay
  the job starts on the login node under the user's account, or a
  reverse connection from the job out to a reachable endpoint. CCS's
  request-reply shape works in either direction; the client just needs
  an address to connect to. The same relay is the uniform answer for
  clouds: a tiny relay on a reachable instance, the laptop connects to
  it, the job connects to it, and the cloud "login node" is whatever the
  user has (an AWS instance started by the launcher, for example).
- **Authentication.** `++server-auth` with a key file exists on the job
  side and `ccsio` implements the client side; the launcher should
  generate a key per run and pass it to both ends by default rather than
  leave the port open to anyone on the login node.
- **Several jobs and several viewers.** Nothing requires one job per
  viewer; the Server object is per connection and the viewer could hold
  tabs. A persistent session file (job id, node, port, key) lets a
  viewer re-attach after the laptop sleeps.

## ccsio as a library of its own

`ccsio` has no dependency on the rest of appSpector and uses beyond it:
CharmArray and charm4py users today drive jobs through the ctypes-based
PyCCS, which needs a shared-library Charm++ build on the client machine;
`ccsio` needs nothing. It stays in this repository for now and should
become its own package (and likely a pure-Python backend inside PyCCS)
once its API has settled. Keep it free of viewer or launcher imports.

## Connecting a new program

The contract above is all a program needs. In practice:

- Link with `-module liveViz` and implement the image callback if you
  want the top pane (see `apps/pfield` and `examples/charm++/wave2d`);
  otherwise run the viewer with `--no-image`.
- Per-object loads come free from the LB database (charm branch with
  PR #4071) and need no code; the first request turns instrumentation
  on. Link `-module CommonLBs` and use `AtSync` if you want the Balance
  button to do something, and register a handler for it (pfield's
  `pfieldBalance` is twelve lines).
- Any interaction with the running program is a CCS handler: register it
  with `CcsRegisterHandler`, decode the request with
  `PUP_toNetwork_unpack`, answer with `CcsSendReply` or a delayed reply.
  Tell the viewer its name (`--inject NAME`) or add a button. Handler
  names are at most 32 bytes.
- For a deeper integration, such as a front end that generates code and
  runs it (the charmnumerics idea: a Python-like front end on the laptop,
  generated Charm++ on the machine), the launcher is the piece to build
  on: it already knows how to put a program on a machine, bring up its
  CCS endpoint and connect; the front end would call `appspector.launch`
  as a library and use `ccsio.Server` for its own request-reply traffic,
  with the viewer attached to the same job for the image and loads.

## Step-by-step plan: the laptop drives everything (2026-10-23)

Today the job's shape is baked into batch scripts that `setup-delta.sh`
writes (2 processes x 2 PEs on one node, `+pe 4`, which is why the Delta
demo shows four PEs), and the viewer is opened by the launcher after the
job is up. The direction Kale set: appSpector on the laptop starts first
and the user says, in it, what to run and how big. Steps, each useful on
its own:

1. **Job spec instead of batch files.** `appspector.launch run` takes the
   program, its arguments, the PE count and the node and process layout
   (`--program pfield --args "-k 16 -n 400" --pes 16 --nodes 1
   --procs-per-node 2`), fills a per-site batch template (account,
   partition, srun flags, environment file) and submits it over ssh; the
   setup script only installs the template and the environment. The
   same spec runs locally (`+pe N`, no Slurm). The generated script is
   kept next to the job output for the record.
2. **A command interpreter, for firing the job.** `python3 -m appspector`
   opens a small shell (Python's `cmd` module) whose business is the
   launch: `site delta`, `program pfield -k 16`, `pes 16`, `run`,
   `attach 23143979`, `status`, `stop`, and `view`, which opens the
   viewer window on the job (the images start there). Interaction with
   the running program, injecting, balancing, flipping the load view,
   stays in the GUI's buttons and clicks; the shell does not duplicate
   it. Every shell command is also a one-line non-interactive
   invocation, so scripts and the launch pane call the same functions.
   This is the cheap, scriptable form of the front end and the one to
   build first.
3. **A launch pane in the viewer window.** The same fields as a form:
   site, program (from a list the site reports, plus a free text field),
   arguments, PEs, nodes, a Run button, the job state and a log tail
   while it queues, then the panes fill in when the job is up. The
   viewer starts without a job and can hold several.
4. **Site descriptions as data.** A small file per installation:
   scheduler (Slurm, PBS, none), submit and poll commands, the batch
   template, how output files are named, how the transport is set up
   (ssh forward through the login node, or a relay). Delta and the
   laptop are the first two entries; a workstation over plain ssh is the
   third; PBS and a cloud instance follow.
5. **Transport alternatives.** The relay process for sites where the login
   node cannot reach a compute node and for clouds, and `++server-auth`
   keys generated per run.

Steps 1 and 2 remove the need for anyone to edit batch scripts; 3 gives
the demo its intended shape; 4 and 5 are the generalization proper.

Status 2026-10-23: steps 1 and 2 are in (`appspector/sites.py`,
`jobs.py`, `shell.py`); step 4 is half there, since sites are already INI
files with a scheduler field, only `slurm` and `local` are implemented.
The job record (`~/.appspector/jobs.json`) is the seed of the long-term
idea of starting a long ChaNGa or NAMD run, leaving, and re-attaching
from the laptop or another machine later: the record holds the site, job
id, node and port, and `attach`/`view` rebuild the connection; sharing
it between machines (or a phone) means moving that record to a small
service, which is step 6 when it comes.
