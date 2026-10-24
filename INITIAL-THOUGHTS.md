# appSpector (application inspector): initial thoughts

Written 2026-10-20 from Kale's description at the end of a recharm session, plus
what that session learned driving liveViz from a laptop against a Delta job.
This folder is the seed of a separate project; nothing here is implemented.

## The idea (Kale, 2026-10-20)

A GUI on the laptop from which one can launch a Charm++ job on a cluster, a
supercomputer, or a cloud cluster (AWS or others), and watch it live. Split
screen:

- **Top**: the application's own live visualization, as liveViz gives for
  wave2d today (the program's image handler answers CCS "lvImage" requests).
- **Bottom**: runtime performance data, updating dynamically. One view we had
  before: a bar per PE, a colored rectangle per object on it, rectangle
  height proportional to the time that object took in the current interval.
  Other views can follow.

Minimize friction for the user. The ssh master connection is friction, but
the GUI can tell the user exactly what to do. On machines like Frontier the
ssh route may not work, but they allow some form of external connection for
parallel jobs; find out which.

## What already exists (verified 2026-10-20)

- **Transport**: CCS. Reconverse has no charmrun relay; PE 0 of the job
  listens on its compute node (`++server ++server-port N`, the job output
  prints `ccs: Server IP = ..., Server port = N`). From a laptop, forward
  the port through the login node: `ssh -O forward -L N:<node>:N delta`
  on an open ssh master (not `ssh -f -N -L`, which leaves a stale listener
  in the master). Verified on NCSA Delta: text CCS client and the liveViz
  Java client both got answers from a 2-process, 4-PE job on a
  cpu-interactive node. Recipe and lesson in
  ~/software/charm-notes/machines/delta.md.
- **Prototype driver**: ~/software/recharm/lv-delta.sh does the whole cycle
  from one laptop terminal: sbatch over ssh, poll for the server line,
  register the forward, start the client, cancel forward and job on exit.
  `--ccs` is a no-GUI self-check (about 40 s end to end), `--watch` tails
  the job output, `--stop` cleans up. This is the skeleton appSpector's
  launcher replaces with a GUI.
- **Client code**: UIUC-PPL/ccs_tools (Java, 2004 vintage), cloned at
  ~/software/ccs_tools; charm/ccs has the CCS client classes, charm/liveViz
  the image viewer, charm/debug CharmDebug's panels. Built by hand into
  bin/liveViz.jar (no ant on this Mac; the jar needs charm/liveViz/toolbar.jpg
  or the client blocks on a 2001 URL). A modern appSpector would likely not
  be Java; the CCS wire protocol is small enough to reimplement (header:
  length, PE, 32-byte handler name; reply: length + bytes).
- **Server-side gap found and fixed**: liveViz image requests crashed every
  reconverse build because the `[local]` entry-method path evaluated an
  uninitialized tracing Cpv; charm PR #4065 (2026-10-20). Until it merges,
  the Delta tree at /work/hdd/mzu/lkale/bump-charm is patched by hand.
- **Charm++ side for the bottom pane**: nothing live today. Candidates to
  look at: the CCS handlers Projections once used for live data
  (ck-perf trace-projections has CCS hooks for "live" summary data), the
  LB database (object times per interval are exactly what the load
  balancers collect), and CharmDebug's CCS introspection handlers
  (debug-conv++.C, kept through the classic deletion). The old "bar per PE,
  rectangle per object" view: find which tool drew it (Projections live
  mode or a liveViz-based demo) before designing the new one.

## Open questions

- Frontier/OLCF: can a login node reach a compute node's TCP port for a
  user's own job (then ssh forwarding works as on Delta), or is a
  reverse connection from the job to the laptop needed (job connects out
  through the login node's proxy)? Design the transport so either direction
  works: a relay process the job starts on the login node under the user's
  account is the fallback, and it is small.
- Cloud: with AWS the "login node" is whatever the user has; a reverse
  connection to the laptop is awkward behind NAT, so a tiny relay on a
  reachable instance is likely the uniform answer.
- Launch: Slurm today (sbatch over ssh). Keep the launcher pluggable
  (Slurm, PBS, cloud API) and keep the job-side contract minimal: print the
  CCS address line, nothing else.
- Performance data rate: a per-interval per-object summary is small; the
  bottom pane should pull it on a timer through CCS, not stream it.
- Authentication: `++server-auth <file>` exists; the GUI should set it up by
  default rather than leave the port open to anyone on the login node.

## Next step when the project starts

Open a new Claude session in this folder, read this file, and begin with the
bottom pane's data source on the Charm++ side (what CCS handler returns
per-PE, per-object time for the last interval), since the transport and the
top pane already work.

## Decisions (Kale, 2026-10-21 morning)

- **Python CCS client first.** It is orthogonal to everything else and can
  start now: the wire protocol is small (see charm/ccs/CcsServer.java in
  ccs_tools and src/ccs/ccs-client.cpp in reconverse for the framing and the
  handshake), and it replaces the 2004 Java client entirely.
- **Bottom pane shows Projections-style data, not LB-database data.** The
  load balancer's per-object times are collected per LB interval, which is
  too coarse for a live view; the pane needs entry-method level events as
  Projections records them. Needs thought: a tracing build
  (CMK_TRACE_ENABLED, -tracemode) is then required for appSpector runs, and
  the live path has to summarize on the PE (per interval, per object or per
  entry method) and serve that over CCS rather than stream raw log records.
  Check what classic trace-summary and trace-projections already offered
  over CCS (both had CCS-based "live" hooks at some point) before designing
  a new handler.
