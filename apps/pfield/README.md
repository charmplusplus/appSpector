# pfield: appSpector's demonstration program

Particles in cells under a forcing field. A K x K chare array of cells
covers a square box; each cell owns a vector of particles that move
inside the cell, either by a random walk (`-mode walk`) or under a
time-varying forcing field sampled on a small local mesh and
interpolated bilinearly (`-mode field`, the default; a proxy for the
particle-mesh step of a PIC or PPPM code, after Intel PRK's PIC kernel by
Evangelos Georganas). A move that would leave the cell is dropped, so a
particle never changes chare: a chare's cost is its particle count times
the per-particle work, and there is no neighbour communication at all.

Load drifts by itself: particles die at a small rate per step and are
born at a rate that follows a hot spot circling the box (the red shading
in the image). Load can be made by hand over CCS:

- `pfieldInject`: request data `x y sigma` as fractions of the box
  (network-order doubles) and an int32 `count`; drops a Gaussian blob of
  particles. The appSpector viewer sends one per mouse click in the image.
- `pfieldBalance`: runs one load-balancing step (AtSync, GreedyRefineLB)
  at the end of the current iteration. The viewer's Balance button.

Every step ends in a reduction to the main chare, so the run is in lock
step and an overloaded PE shows as idle time on all the others, which is
what the viewer's per-PE bars display.

Build: `make` (CHARM_HOME defaults to the appSpector worktree build; needs
liveViz and CommonLBs). Run: `./pfield +pe 4 ++server ++server-port 1234
+balancer GreedyRefineLB`, then `python -m appspector.viewer 127.0.0.1
1234` from the appSpector directory, or just `./demo_local.sh` there.

Arguments: `-k` cells per side (8), `-n` initial particles per cell (300),
`-mode walk|field`, `-w` extra field terms per particle (16), `-death`
per-particle death probability per step (0.002), `-birth` birth rate
relative to `-n` per step (defaults to the death rate), `-hot` hot-spot
amplitude (3.0), `-period` seconds per hot-spot orbit (120), `-lb`
automatic AtSync period in steps (0: only on request), `-steps` (0:
until killed), `-box` box size (100).

This is not a solution to the Charm++ particle exercises on
charmplusplus.org: there is no particle migration between chares.
