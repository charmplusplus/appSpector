# appSpector

appSpector launches a Charm++ job on a cluster (Delta, Anvil) or on the
laptop and watches it live from the laptop: the program's own liveViz
image on top, the load on every PE below, one bar per PE stacked by
chare. The laptop side is plain Python: a command shell
(`python3 -m appspector`) that fires jobs, a tkinter viewer
(`appspector/viewer.py`), and `ccsio`, a CCS client; the laptop needs no
Charm++ build.

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): the user manual. Installing, reaching
  and setting up a cluster, the shell, the viewer, connecting your own
  program, troubleshooting.
- [ONBOARDING.md](ONBOARDING.md): for contributors. Repository layout,
  tests, a path into the code, open items.
- [docs/DESIGN.md](docs/DESIGN.md): the design and the long-term plan
  (other schedulers, relays for sites and clouds, ccsio as its own
  package).
- [docs/HISTORY.md](docs/HISTORY.md): a dated log of verification runs
  and status notes.

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
```

A `Server` may be shared between threads. With a key, the CCS server keeps
one request counter per authenticated client and rejects a request whose
hash used the wrong counter value, so requests from one identity must
arrive in order; over an ssh forward two threads' requests overtake each
other within a second (found 2026-10-27: the Delta viewer froze with "the
job is gone" while the job ran on). ccsio therefore gives each thread its
own identity on its first request, and `request()` re-authenticates and
retries once when the server drops a connection before any reply byte.

```python

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

## Repository layout

- `ccsio/`: the CCS client library described above.
- `appspector/`: the shell, the viewer, sites, jobs and the launcher.
- `apps/pfield/`: the demonstration program.
- `cluster/`: the cluster setup script and one env file per cluster.
- `tests/`: unit tests, the fake CCS server, integration and setup scripts.
- `docs/`: the manual, the design, the history.
