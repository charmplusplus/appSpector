#!/bin/bash
# Set up the laptop side of appSpector for local runs: a Charm++
# (reconverse) build with tracing and liveViz next to this repository, the
# example programs, and the pfield demo. Only needed for ./demo_local.sh;
# running the viewer against a cluster job needs just Python 3.
#
#   bash tests/setup-laptop.sh            # clones into ../appSpector/charm-wt
#
# Variables: BRANCH (default recharm),
# CHARM_WT (default <repo>/charm-wt), ARCH (default by OS: reconverse-darwin-arm8
# on macOS arm64, reconverse-linux-x86_64 on Linux), JOBS (default 8).
# macOS: Xcode command line tools, cmake, and libjpeg (MacPorts or Homebrew)
# are required; the Makefiles add the MacPorts library path when present.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
CHARM_WT=${CHARM_WT:-$REPO/charm-wt}
BRANCH=${BRANCH:-recharm}
JOBS=${JOBS:-8}
if [ -z "${ARCH:-}" ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) ARCH=reconverse-darwin-arm8 ;;
    Linux-x86_64) ARCH=reconverse-linux-x86_64 ;;
    Linux-aarch64) ARCH=reconverse-linux-arm8 ;;
    *) echo "set ARCH for $(uname -s)-$(uname -m)"; exit 1 ;;
  esac
fi
B=$CHARM_WT/$ARCH
step() { echo "== $(date +%H:%M:%S) $*"; }

step "charm clone ($BRANCH) in $CHARM_WT"
[ -d "$CHARM_WT" ] || git clone -q --recurse-submodules -b "$BRANCH" https://github.com/charmplusplus/charm.git "$CHARM_WT"
cd "$CHARM_WT" && git log -1 --oneline
step "charm build ($ARCH, tracing on)"
[ -x "$B/bin/charmc" ] || ./build charm++ "$ARCH" --with-production --enable-tracing -j$JOBS > "$CHARM_WT/build-tracing.log" 2>&1 \
  || { tail -5 "$CHARM_WT/build-tracing.log"; exit 1; }
step "ck-libs (liveViz)"
(cd "$B" && cmake -DTARGET=LIBS . > "$CHARM_WT/libs-build.log" 2>&1 && make -j$JOBS >> "$CHARM_WT/libs-build.log" 2>&1) \
  || { tail -5 "$CHARM_WT/libs-build.log"; exit 1; }
step "examples and pfield"
WT=$CHARM_WT bash "$REPO/tests/build_reconverse_examples.sh"
echo "done: run ./demo_local.sh from $REPO"
