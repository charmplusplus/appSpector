# appSpector: getting started

Users who want to launch a Charm++ job and watch it read the
[user manual](docs/MANUAL.md). This file is for contributors who will
change appSpector's code. A contributor first follows the manual's
chapters [Installing on the laptop](docs/MANUAL.md#installing-on-the-laptop),
[Reaching a cluster](docs/MANUAL.md#reaching-a-cluster) and
[Setting up a cluster](docs/MANUAL.md#setting-up-a-cluster), and the
optional local demo in the first of them. The design and the plan are in
[docs/DESIGN.md](docs/DESIGN.md); dated verification notes are in
[docs/HISTORY.md](docs/HISTORY.md).

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
| `README.md`, `docs/MANUAL.md`, `docs/DESIGN.md`, `docs/HISTORY.md`, `INITIAL-THOUGHTS.md` | front door, user manual, design and plan, dated log, original idea |

The CCS protocol itself is documented at the top of `ccsio/protocol.py`.
The Charm++ handlers the viewer relies on are listed in the manual under
[What each feature needs from the program](docs/MANUAL.md#what-each-feature-needs-from-the-program).

## Tests

- `python3 -m unittest discover -s tests`: the unit tests, against an
  in-process fake CCS server (`tests/fake_server.py`, written from
  ccs-server.C), including the authenticated handshake and a check that
  hashlib's SHA-1 equals the hand-written SHA-1 in ccs-auth.C. No Charm++
  needed.
- `tests/integration_classic.sh`: builds `examples/converse/ccstest/server.C`
  from a classic Charm++ tree, runs it with `++server-port` with and
  without `++server-auth`, and drives it with the `ccsio` command line.
- `tests/integration_reconverse.sh`: the same against the reconverse
  ccstest server built by `tests/build_reconverse_examples.sh` in
  `charm-wt`.
- `tests/remote_check.py HOST PORT [PNG] [-k KEY]`: a headless check of
  everything appSpector reads from a running job through a forward:
  liveViz config and image, the utilization stream and its names, the
  LBObjLoads snapshot, and the viewer with its bottom views.
- `tests/pfield_check.py [HOST PORT]`: an end-to-end check of pfield
  through the viewer's own code paths, headless: start, clicks, Balance,
  migration count.

## A path for a new contributor

1. Run the demos: `./demo_local.sh` on the laptop (after
   `tests/setup-laptop.sh`), then pfield and wave2d on Delta through the
   shell. Click, balance, flip the views, read `apps/pfield/README.md`
   and skim `pfield.C` and `appspector/viewer.py` while they run.
2. Connect a program of your own. A particle code from the Charm++
   exercises is ideal: follow the manual's
   [Connecting your own program](docs/MANUAL.md#connecting-your-own-program),
   run it, and see it in the viewer with no changes (per-chare loads come
   free). Then add liveViz for an image and, if you like, a CCS handler
   for a button, following pfield.
3. Pick something from the open items below, or whatever the demos made
   you want to change. The repository is charmplusplus/appSpector;
   branch, pull request, review.

When you change what a user sees (a shell command, a viewer option, a
status message, a setup step), update its one place in
[docs/MANUAL.md](docs/MANUAL.md); other documents link there.

## Open items (good first tasks)

- Per-PE view refinements from the old demo: an absolute time axis,
  horizontal bars, Show BG Load / Show Idle toggles.
- A side-by-side layout option.
- A reconverse fix so `++server-auth` reads hexadecimal keys as the Charm++
  manual says (the key files are decimal digits today for that reason).
- Frontier and cloud transport (see INITIAL-THOUGHTS.md).
