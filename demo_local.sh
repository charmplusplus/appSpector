#!/bin/bash
# Run the whole appSpector chain on this laptop: a liveViz job from the
# worktree build with the viewer attached. Close the viewer window to end
# the job.
#   ./demo_local.sh [app] [PEs] [port]
# app: wave2d        800x800 wave field, 16x16 = 256 chares
#      wave2d-small  same, 4x4 = 16 chares (a few per PE, like the old demo)
#      mol2d         Molecular2D particles, 25 patches + 125 computes
#      pfield        appSpector's own demo: particles in cells under a
#                    forcing field, click to inject, Balance button (default)
APP=${1:-pfield}
PES=${2:-4}
PORT=${3:-1234}
ROOT=$(cd "$(dirname "$0")" && pwd)
EX=$ROOT/charm-wt/examples/charm++
case "$APP" in
  wave2d)       DIR=$EX/wave2d;      BIN=wave2d-demo ;;
  wave2d-small) DIR=$EX/wave2d;      BIN=wave2d-small ;;
  mol2d)        DIR=$EX/Molecular2D; BIN=mol2d ;;
  pfield)       DIR=$ROOT/apps/pfield; BIN=pfield; EXTRA="+balancer GreedyRefineLB" ;;
  *) echo "unknown app '$APP' (wave2d, wave2d-small, mol2d)"; exit 1 ;;
esac
[ -x "$DIR/$BIN" ] || { echo "no $DIR/$BIN; run tests/build_reconverse_examples.sh (or make in apps/pfield) first"; exit 1; }
cd "$DIR" || exit 1
./$BIN +pe $PES ++server ++server-port $PORT ${EXTRA:-} > "$DIR/$BIN.log" 2>&1 &
JOB=$!
trap 'kill -9 $JOB 2>/dev/null; echo "job $JOB stopped"' EXIT
for i in $(seq 1 20); do grep -q 'ccs: Server' "$DIR/$BIN.log" && break; sleep 1; done
grep 'ccs: Server' "$DIR/$BIN.log" || { echo "job did not start:"; cat "$DIR/$BIN.log"; exit 1; }
cd "$ROOT" && python3 -m appspector.viewer 127.0.0.1 $PORT
